"""
main.py - YahooRSS 统一调度主入口

使用 APScheduler 管理所有自动化定时任务：
1. 新闻高频抓取 + 初筛去重 + AI分流评分翻译 + RSS 2.0 生成（每 3 分钟带随机扰动）；
2. 盘前宏观买方总结（美东 08:45，自动校验 XNYS 美股交易日）；
3. 盘后宏观买方总结（美东 21:00，自动校验 XNYS 美股交易日）。

运行方式：
    python main.py             # 启动全自动守护进程
    python main.py --once      # 立即执行单次抓取与推送
    python main.py --premarket # 单独手动运行盘前总结
    python main.py --postmarket# 单独手动运行盘后总结
"""
import sys
import json
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.config import settings
from core.logger import logger
from core.database import (
    init_db,
    insert_news,
    get_urls_without_content,
    update_content,
    get_recent_news,
)
from scrapers.yahoo_finance import YahooFinanceScraper
from services.news_filter import filter_raw_titles
from services.translator import run_translation
from services.daily_summary import generate_summary
from services.rss_generator import generate_news_rss, generate_summary_rss

# 美东时区与交易日历
ET = ZoneInfo("America/New_York")
XNYS = xcals.get_calendar("XNYS")

# 幂等状态记录文件
STATE_FILE = "run_state.json"
_state = {"done": set()}

# 抓取器单例
scraper = YahooFinanceScraper(max_threads=settings.SCRAPE_MAX_THREADS)


# ============================================================
# 幂等状态管理
# ============================================================

def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _state["done"] = set(data.get("done", []))
    except (FileNotFoundError, json.JSONDecodeError):
        _state["done"] = set()


def _save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"done": sorted(_state["done"])}, f, ensure_ascii=False, indent=2)


def _state_key(d: date, kind: str) -> str:
    return f"{d.isoformat()}-{kind}"


def _already_done(d: date, kind: str) -> bool:
    return _state_key(d, kind) in _state["done"]


def _mark_done(d: date, kind: str):
    _state["done"].add(_state_key(d, kind))
    _save_state()


def is_us_trading_day(d: date) -> bool:
    """检查是否为美股正规交易日（自动排除周末及法定节假日）"""
    return XNYS.is_session(pd.Timestamp(d))


# ============================================================
# 调度任务
# ============================================================

def scrape_task():
    """
    新闻全链路主流水线：
    1. 抓取最新新闻标题
    2. 入库前初筛：17+ 正则拦截套路软文 + 24小时罕见词事件去重
    3. 批量持久化到数据库
    4. 抓取正文内容
    5. 执行 AI 评级打分与分流翻译
    6. 二次过滤并生成 RSS 2.0 源（带过期修剪）
    """
    logger.info("=== [流水线启动] 开始执行新闻采集与处理任务 ===")
    try:
        # 1. 抓取最新标题
        titles = scraper.fetch_titles()
        if not titles:
            logger.debug("未获取到新标题，跳过后续步骤")
            return

        # 2. 初筛与去重
        recent_news = get_recent_news(hours=24)
        pending_titles = filter_raw_titles(titles, recent_news=recent_news)

        # 3. 存入数据库
        inserted = insert_news(pending_titles)

        # 4. 抓取缺失的正文
        pending_contents = get_urls_without_content(limit=30)
        if pending_contents:
            logger.info(f"开始抓取 {len(pending_contents)} 篇新闻正文...")
            urls = [item["url"] for item in pending_contents]
            id_map = {item["url"]: item["id"] for item in pending_contents}

            results = scraper.fetch_all_contents(urls)
            for url, content in results.items():
                if content:
                    update_content(id_map[url], content)
                else:
                    update_content(id_map[url], "[Fetch Failed]")
            logger.info("正文抓取完成")

        # 5. 执行智能评级、分流与翻译
        run_translation()

        # 6. 生成新闻 RSS 源（实施模式 B 自选股筛选与旧条目修剪）
        generate_news_rss()

        logger.info("=== [流水线完成] 本轮任务处理完毕 ===")

    except Exception as e:
        logger.error(f"抓取流水线发生未捕获异常: {e}", exc_info=True)


def run_premarket():
    """盘前大盘买方策略研报任务（美东 08:45）"""
    today = datetime.now(ET).date()
    if not is_us_trading_day(today):
        logger.info("[PRE-MARKET] 今日非美股交易日，跳过盘前总结")
        return
    if _already_done(today, "PRE"):
        logger.info("[PRE-MARKET] 今日盘前总结已完成，无需重复生成")
        return

    logger.info("[PRE-MARKET] 开始生成盘前买方宏观综述...")
    res = generate_summary("premarket")

    if res and res.get("ok") and (res.get("saved") or res.get("skipped") == "exists"):
        _mark_done(today, "PRE")
        generate_summary_rss()
        logger.info("[PRE-MARKET] 盘前大盘总结生成成功并已推入 RSS")
    else:
        logger.warning(f"[PRE-MARKET] 未成功标记完成: {(res or {}).get('error')}")


def run_postmarket():
    """盘后大盘买方策略研报任务（美东 21:00）"""
    today = datetime.now(ET).date()
    if not is_us_trading_day(today):
        logger.info("[POST-MARKET] 今日非美股交易日，跳过盘后总结")
        return
    if _already_done(today, "POST"):
        logger.info("[POST-MARKET] 今日盘后总结已完成，无需重复生成")
        return

    logger.info("[POST-MARKET] 开始生成盘后买方宏观综述...")
    res = generate_summary("postmarket")

    if res and res.get("ok") and (res.get("saved") or res.get("skipped") == "exists"):
        _mark_done(today, "POST")
        generate_summary_rss()
        logger.info("[POST-MARKET] 盘后大盘总结生成成功并已推入 RSS")
    else:
        logger.warning(f"[POST-MARKET] 未成功标记完成: {(res or {}).get('error')}")


# ============================================================
# 程序主入口
# ============================================================

def main():
    """启动调度器守护服务"""
    logger.info("==========================================")
    logger.info("      YahooRSS 自动化服务系统已启动        ")
    logger.info("==========================================")
    _load_state()

    scheduler = BlockingScheduler(
        timezone=ET,
        job_defaults={"coalesce": True, "misfire_grace_time": 600},
    )

    # 1. 周期性抓取任务（基础间隔 + 120s 随机波动，有效防止被风控）
    interval = settings.SCRAPE_INTERVAL_MINUTES
    scheduler.add_job(
        scrape_task,
        IntervalTrigger(minutes=interval, jitter=120),
        id="scrape_job",
        name="高频新闻抓取处理流水线",
    )

    # 首次启动立即执行一轮初始采集
    scheduler.add_job(scrape_task, id="scrape_initial", name="启动初始采集")

    # 2. 美东 08:45 盘前大盘综述定时任务
    scheduler.add_job(
        run_premarket,
        CronTrigger(hour=8, minute=45, timezone=ET),
        id="premarket_job",
        name="美东 08:45 盘前大盘研报",
    )

    # 3. 美东 21:00 盘后大盘综述定时任务
    scheduler.add_job(
        run_postmarket,
        CronTrigger(hour=21, minute=0, timezone=ET),
        id="postmarket_job",
        name="美东 21:00 盘后大盘研报",
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("捕获退出信号，正在安全关闭调度器...")
        scheduler.shutdown()
        logger.info("调度服务已正常关闭。")


if __name__ == "__main__":
    init_db()
    args = sys.argv[1:]
    _load_state()

    if args and args[0] in ("--premarket", "-p"):
        run_premarket()
    elif args and args[0] in ("--postmarket", "-post"):
        run_postmarket()
    elif args and args[0] in ("--once", "-1"):
        scrape_task()
    else:
        main()
