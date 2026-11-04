"""
services/daily_summary.py - 每日盘前/盘后大盘宏观总结服务

根据美东交易时钟生成盘前/盘后买方策略综述研报。
核心流程：
1. 精准根据美东开盘/收盘时间窗口计算 UTC 查询范围；
2. 严格筛选 High 级别重大新闻；
3. 调用旗舰大模型（nvda-nemotron-120b）执行宏观逻辑链归纳；
4. 幂等落库并广播至总结 RSS。
"""
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from core import llm_client
from core.database import get_news_by_time_range, save_daily_summary
from core.logger import logger
from core.config import settings
from services.prompts import get_daily_summary_prompts

ET = ZoneInfo("America/New_York")
FALLBACK_PREFIX = "翻译服务暂时不可用，原文内容："


def get_current_session(now_et: datetime | None = None) -> str:
    """根据美东时间判断当前是盘前还是盘后（以 14:00 为分界）"""
    if now_et is None:
        now_et = datetime.now(ET)

    minutes = now_et.hour * 60 + now_et.minute
    return "premarket" if minutes < 14 * 60 else "postmarket"


def _get_time_range_utc(session: str) -> tuple[datetime, datetime, datetime]:
    """
    根据 session 类型计算 UTC 时间范围与对应归属交易日。

    Returns:
        (start_utc, end_utc, target_date)
    """
    now_et = datetime.now(ET)

    if session == "premarket":
        # 盘前总结：统计从上一交易日收盘（周末往前推 3 天，平时 1 天）到今日开盘前
        target_date = now_et
        days_back = 3 if target_date.weekday() == 0 else 1
        
        start_et = (target_date - timedelta(days=days_back)).replace(hour=20, minute=45, second=0, microsecond=0)
        end_et = target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        
    elif session == "postmarket":
        # 盘后总结：统计目标日交易时段的新闻
        if now_et.hour < 20 or (now_et.hour == 20 and now_et.minute < 45):
            days_back = 3 if now_et.weekday() == 0 else 1
            target_date = now_et - timedelta(days=days_back)
        else:
            target_date = now_et

        start_et = target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        end_et = target_date.replace(hour=20, minute=45, second=0, microsecond=0)
    else:
        raise ValueError(f"无效的 session 类型: {session}")

    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)

    logger.info(
        f"总结时间窗口: {session} | 归属交易日: {target_date.strftime('%Y-%m-%d')} | "
        f"美东 {start_et.strftime('%m-%d %H:%M')} → {end_et.strftime('%m-%d %H:%M')} | "
        f"UTC {start_utc.strftime('%m-%d %H:%M')} → {end_utc.strftime('%m-%d %H:%M')}"
    )

    return start_utc, end_utc, target_date


def _build_news_json(news_list: list[dict]) -> str:
    """将重点新闻列表格式化为 JSON 字符串投喂给大模型"""
    items = []
    for n in news_list:
        content = n.get("summary_cn", "")
        if content and not content.startswith(FALLBACK_PREFIX):
            items.append({
                "id": n["id"],
                "time": n.get("published_at", ""),
                "content_cn": content.strip(),
            })
    return json.dumps(items, ensure_ascii=False, indent=2)


def generate_summary(session: str | None = None) -> dict:
    """
    生成每日盘前/盘后大盘宏观总结。

    Args:
        session: "premarket" 或 "postmarket"，None 时自动判断

    Returns:
        {"ok": bool, "saved": bool, "title": str, ...}
    """
    if session is None:
        session = get_current_session()

    session_cn = "盘前" if session == "premarket" else "盘后"
    start_utc, end_utc, target_date = _get_time_range_utc(session)
    date_str = target_date.strftime("%Y-%m-%d")
    summary_date = date_str

    logger.info(f"开始生成 {date_str} {session_cn} 总结...")

    news_list = get_news_by_time_range(start_utc, end_utc)
    # 严格仅保留 High 级别的核心全局新闻，防止杂讯污染大盘综述
    news_list = [n for n in news_list if str(n.get("significant")).strip().lower() == "high"]
    news_count = len(news_list)

    if not news_list:
        logger.warning(f"时间范围内无 High 级别重大新闻: {date_str} {session}")
        return {"ok": True, "saved": False, "skipped": "no_news"}

    content_json = _build_news_json(news_list)
    prompt = get_daily_summary_prompts(session, content_json)

    et_date_str = target_date.strftime("%Y_%m_%d")
    url = f"https://finance.yahoo.com/market-summary/{date_str}_{session}"
    title = f"美东时间 {et_date_str} {session_cn} 核心研报 (精选样本 {news_count} 条)"

    # 调用旗舰模型
    try:
        messages = [{"role": "system", "content": prompt}]
        summary_text = llm_client.chat(messages, model_name=settings.DAILY_SUMMARY_MODEL, timeout=120)
        logger.info(f"大盘总结 AI 成功生成，字数: {len(summary_text)}")
    except Exception as e:
        logger.error(f"大盘总结模型调用失败: {e}")
        return {"ok": False, "saved": False, "error": str(e), "title": title}

    # 保存至数据库
    db_session = "pre_market" if session == "premarket" else "post_market"
    try:
        saved = save_daily_summary(
            summary_date=summary_date,
            market_session=db_session,
            title=title,
            summary_content=summary_text,
            url=url,
            news_count=news_count,
        )
        if saved:
            logger.info(f"{date_str} {session_cn} 总结成功保存入库")
        return {"ok": True, "saved": saved, "skipped": None if saved else "exists", "title": title}
    except Exception as e:
        logger.error(f"保存每日总结失败: {e}")
        return {"ok": False, "saved": False, "error": str(e), "title": title}
