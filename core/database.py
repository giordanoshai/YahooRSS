"""
core/database.py - 本地 SQLite3 数据库交互模块

提供新闻全生命周期 CRUD 操作，包括入库排重、正文回写、AI分析结果持久化、
自选股联动二次筛选（模式 B）以及每日宏观研报读写。
支持开箱即用自动建表、WAL 并发模式与多线程写安全锁。
"""
import os
import json
import time
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

from core.config import settings
from core.logger import logger

# 多线程写互斥锁，保证多线程同时写 SQLite 绝对不报 database is locked
_db_write_lock = threading.Lock()

# 线程局部存储，确保每个线程拥有独立的 SQLite 连接
_local = threading.local()

# 自选股轻量内存缓存
_watchlist_cache = {"tickers": set(), "expire_at": 0.0}

# 数据库自动初始化标记
_is_initialized = False
_init_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """获取当前线程的 SQLite3 数据库连接（启用 WAL 模式与行字典工厂）"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        db_path = settings.SQLITE_DB_PATH
        # 若指定了父目录且不存在，则自动创建
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # 优化 SQLite 运行性能与并发度
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 15000;")
        _local.conn = conn

    return conn


def init_db():
    """自动初始化数据库表结构与自选股数据（开箱即用）"""
    global _is_initialized
    if _is_initialized:
        return

    with _init_lock:
        if _is_initialized:
            return

        with _db_write_lock:
            conn = get_connection()
            with conn:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    published_at TEXT NOT NULL,
                    content TEXT,
                    title_cn TEXT,
                    summary_cn TEXT,
                    related_tickers TEXT,
                    significant TEXT DEFAULT 'Low',
                    significant_reason TEXT,
                    sentiment_label TEXT DEFAULT 'Neutral',
                    sentiment_score REAL DEFAULT 0.0,
                    is_duplicate INTEGER NOT NULL DEFAULT 0,
                    dup_of INTEGER REFERENCES news(id),
                    is_rss INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'yahoo_finance',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_news_dup ON news(is_duplicate, published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_news_is_rss ON news(is_rss);
                CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);

                CREATE TABLE IF NOT EXISTS news_daily_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_date TEXT NOT NULL,
                    market_session TEXT NOT NULL CHECK (market_session IN ('pre_market', 'post_market', 'daily')),
                    title TEXT NOT NULL,
                    summary_content TEXT NOT NULL,
                    url TEXT,
                    news_count INTEGER DEFAULT 0,
                    is_rss INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_summary_date_session
                    ON news_daily_summary(summary_date, market_session);

                CREATE TABLE IF NOT EXISTS user_watchlist (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO user_watchlist (ticker, company_name)
                VALUES 
                    ('SPY', 'SPDR S&P 500 ETF Trust'),
                    ('QQQ', 'Invesco QQQ Trust'),
                    ('NVDA', 'NVIDIA Corporation'),
                    ('AAPL', 'Apple Inc.'),
                    ('MSFT', 'Microsoft Corporation'),
                    ('TSLA', 'Tesla Inc.'),
                    ('AMZN', 'Amazon.com Inc.'),
                    ('GOOGL', 'Alphabet Inc.'),
                    ('META', 'Meta Platforms Inc.');
                """)
            _is_initialized = True
            logger.info("SQLite3 数据库结构与初始自选股池校验完成")


# 模块加载时执行自初始化
init_db()


# ============================================================
# 自选股查询 (支持模式 B 二次筛选)
# ============================================================

def get_user_watchlist_tickers() -> set[str]:
    """获取用户自选股列表 Tickers 集合（带 5 分钟轻量内存缓存，若无表则退回配置项）"""
    now = time.time()
    if _watchlist_cache["tickers"] and now < _watchlist_cache["expire_at"]:
        return _watchlist_cache["tickers"]

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM user_watchlist")
        rows = cursor.fetchall()
        tickers = {row["ticker"].strip().upper() for row in rows if row["ticker"]}
        if not tickers:
            tickers = settings.default_watchlist_set
        _watchlist_cache["tickers"] = tickers
        _watchlist_cache["expire_at"] = now + 300  # 5分钟缓存
        return tickers
    except Exception as e:
        logger.warning(f"获取 user_watchlist 数据表异常，回退使用默认自选池配置: {e}")
        fallback = settings.default_watchlist_set
        _watchlist_cache["tickers"] = fallback
        _watchlist_cache["expire_at"] = now + 300
        return fallback


# ============================================================
# 新闻表 (news) CRUD
# ============================================================

def insert_news(news_list: list[dict]) -> int:
    """
    批量插入新闻，使用 INSERT OR IGNORE（url 为唯一键）去重。
    重复报道也会入库，带着 is_duplicate 标记，后续不抓正文、不做 AI 分析、不推 RSS。

    Args:
        news_list: [{"title", "url", "source", "is_duplicate", "dup_of", ...}]

    Returns:
        实际插入条数
    """
    if not news_list:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0

    with _db_write_lock:
        conn = get_connection()
        try:
            with conn:
                for item in news_list:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO news 
                        (title, url, published_at, source, is_duplicate, dup_of)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        item["title"],
                        item["url"],
                        now,
                        item.get("source", "yahoo_finance"),
                        1 if item.get("is_duplicate") else 0,
                        item.get("dup_of"),
                    ))
                    if cursor.rowcount > 0:
                        inserted += 1

            logger.info(f"插入新闻: 提交 {len(news_list)} 条, 实际写入 {inserted} 条")
            return inserted
        except Exception as e:
            logger.error(f"插入新闻失败: {e}")
            return 0


def get_urls_without_content(limit: int = 50) -> list[dict]:
    """获取缺失正文且非重复的新闻条目"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, url 
            FROM news 
            WHERE content IS NULL AND is_duplicate = 0 
            ORDER BY published_at DESC 
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [{"id": row["id"], "url": row["url"]} for row in rows]
    except Exception as e:
        logger.error(f"查询待抓取正文新闻失败: {e}")
        return []


def update_content(news_id: int, content: str):
    """更新新闻正文"""
    with _db_write_lock:
        try:
            conn = get_connection()
            with conn:
                conn.execute("UPDATE news SET content = ? WHERE id = ?", (content, news_id))
        except Exception as e:
            logger.error(f"更新正文失败 ID {news_id}: {e}")


def get_untranslated_news(limit: int = 30) -> list[dict]:
    """获取有正文但尚未完成 AI 分析的新闻（排除重复报道）"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, content 
            FROM news 
            WHERE content IS NOT NULL 
              AND title_cn IS NULL 
              AND summary_cn IS NULL 
              AND is_duplicate = 0 
            ORDER BY published_at DESC 
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [{"id": row["id"], "title": row["title"], "content": row["content"]} for row in rows]
    except Exception as e:
        logger.error(f"查询待翻译分析新闻失败: {e}")
        return []


def update_translation(
    news_id: int, 
    title_cn: str, 
    summary_cn: str, 
    related_tickers: list[str] | None = None,
    significant: str = "Low",
    significant_reason: str = "",
    sentiment_label: str = "Neutral",
    sentiment_score: float = 0.0
):
    """更新新闻的中文翻译、摘要、重要度与情绪分"""
    tickers_json = json.dumps(related_tickers, ensure_ascii=False) if related_tickers else None

    with _db_write_lock:
        try:
            conn = get_connection()
            with conn:
                conn.execute("""
                    UPDATE news SET
                        title_cn = ?,
                        summary_cn = ?,
                        related_tickers = ?,
                        significant = ?,
                        significant_reason = ?,
                        sentiment_label = ?,
                        sentiment_score = ?
                    WHERE id = ?
                """, (
                    title_cn,
                    summary_cn,
                    tickers_json,
                    significant,
                    significant_reason,
                    sentiment_label,
                    sentiment_score,
                    news_id
                ))
        except Exception as e:
            logger.error(f"更新翻译分析结果失败 ID {news_id}: {e}")


def get_recent_news(hours: int = 24, limit: int = 1000) -> list[dict]:
    """获取最近指定时间内的已入库新闻，供 StoryIndex 事件去重比对"""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, url, is_duplicate 
            FROM news 
            WHERE published_at >= ? 
            ORDER BY published_at DESC 
            LIMIT ?
        """, (cutoff, limit))
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "is_duplicate": bool(row["is_duplicate"])
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"查询最近新闻失败: {e}")
        return []


def get_unrss_news() -> list[dict]:
    """
    获取未写入 RSS 的新闻（实施模式 B 过滤）：
    1. High 级别：全局重磅，无条件推入 RSS
    2. Medium 级别：仅当关联标的命中 user_watchlist 自选股时才推入 RSS
    3. Low 级别及未命中的 Medium：不推入 RSS，但标记为已处理以避免堵塞队列
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, title_cn, summary_cn, url, published_at, is_rss, significant, related_tickers 
            FROM news 
            WHERE title_cn IS NOT NULL 
              AND summary_cn IS NOT NULL 
              AND is_rss = 0 
              AND is_duplicate = 0 
            ORDER BY published_at DESC 
            LIMIT 50
        """)
        rows = cursor.fetchall()

        all_news = []
        for row in rows:
            # 解析 related_tickers JSON
            raw_tickers = row["related_tickers"]
            tickers = []
            if raw_tickers:
                try:
                    tickers = json.loads(raw_tickers)
                    if not isinstance(tickers, list):
                        tickers = []
                except Exception:
                    tickers = []

            all_news.append({
                "id": row["id"],
                "title": row["title"],
                "title_cn": row["title_cn"],
                "summary_cn": row["summary_cn"],
                "url": row["url"],
                "published_at": row["published_at"],
                "is_rss": bool(row["is_rss"]),
                "significant": row["significant"],
                "related_tickers": tickers
            })

        watchlist = get_user_watchlist_tickers()

        unrss = []
        skip_ids = []

        for item in all_news:
            sig = str(item.get("significant") or "").strip().lower()
            news_id = item["id"]

            if sig == "high":
                unrss.append(item)
            elif sig == "medium":
                tickers = [t.upper() for t in (item.get("related_tickers") or [])]
                if set(tickers) & watchlist:
                    unrss.append(item)
                else:
                    skip_ids.append(news_id)
            else:
                skip_ids.append(news_id)

        # 闭环机制：将无需推入 RSS 的新闻打标已处理，避免堵塞未处理队列
        if skip_ids:
            mark_news_rss(skip_ids)
            logger.debug(f"RSS模式B: 过滤并标记已跳过 {len(skip_ids)} 条普通/无关新闻")

        return unrss
    except Exception as e:
        logger.error(f"查询未RSS新闻失败: {e}")
        return []


def mark_news_rss(ids: list[int]):
    """批量标记新闻为已写入 RSS"""
    if not ids:
        return
    with _db_write_lock:
        try:
            conn = get_connection()
            placeholders = ",".join("?" for _ in ids)
            with conn:
                conn.execute(f"UPDATE news SET is_rss = 1 WHERE id IN ({placeholders})", ids)
        except Exception as e:
            logger.error(f"标记新闻 RSS 状态失败: {e}")


# ============================================================
# 每日总结表 (news_daily_summary) CRUD
# ============================================================

def get_news_by_time_range(start_utc: datetime, end_utc: datetime) -> list[dict]:
    """按 UTC 时间范围查询已分析的新闻，供每日总结调用"""
    try:
        start_str = start_utc.isoformat()
        end_str = end_utc.isoformat()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, published_at, title_cn, summary_cn, significant, sentiment_label, sentiment_score, related_tickers 
            FROM news 
            WHERE summary_cn IS NOT NULL 
              AND is_duplicate = 0 
              AND published_at >= ? 
              AND published_at <= ? 
            ORDER BY published_at ASC
        """, (start_str, end_str))
        rows = cursor.fetchall()

        results = []
        for row in rows:
            raw_tickers = row["related_tickers"]
            tickers = []
            if raw_tickers:
                try:
                    tickers = json.loads(raw_tickers)
                    if not isinstance(tickers, list):
                        tickers = []
                except Exception:
                    tickers = []

            results.append({
                "id": row["id"],
                "published_at": row["published_at"],
                "title_cn": row["title_cn"],
                "summary_cn": row["summary_cn"],
                "significant": row["significant"],
                "sentiment_label": row["sentiment_label"],
                "sentiment_score": row["sentiment_score"],
                "related_tickers": tickers
            })
        return results
    except Exception as e:
        logger.error(f"按时间段查询新闻失败: {e}")
        return []


def save_daily_summary(
    summary_date: str,
    market_session: str,
    title: str,
    summary_content: str,
    url: str | None = None,
    news_count: int = 0,
) -> bool:
    """保存每日总结（幂等更新，基于 summary_date + market_session）"""
    with _db_write_lock:
        try:
            conn = get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO news_daily_summary 
                    (summary_date, market_session, title, summary_content, url, news_count, is_rss)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(summary_date, market_session) DO UPDATE SET
                        title = excluded.title,
                        summary_content = excluded.summary_content,
                        url = excluded.url,
                        news_count = excluded.news_count,
                        is_rss = 0
                """, (
                    summary_date,
                    market_session,
                    title,
                    summary_content,
                    url,
                    news_count
                ))
            return True
        except Exception as e:
            logger.error(f"保存每日总结失败: {e}")
            return False


def get_unrss_summaries() -> list[dict]:
    """获取未写入 RSS 的每日总结"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, summary_content, url, created_at, is_rss 
            FROM news_daily_summary 
            WHERE is_rss = 0 
            ORDER BY created_at DESC 
            LIMIT 10
        """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary_content": row["summary_content"],
                "url": row["url"],
                "created_at": row["created_at"],
                "is_rss": bool(row["is_rss"])
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"查询未写入 RSS 的每日总结失败: {e}")
        return []


def mark_summary_rss(ids: list[int]):
    """标记总结为已写入 RSS"""
    if not ids:
        return
    with _db_write_lock:
        try:
            conn = get_connection()
            placeholders = ",".join("?" for _ in ids)
            with conn:
                conn.execute(f"UPDATE news_daily_summary SET is_rss = 1 WHERE id IN ({placeholders})", ids)
        except Exception as e:
            logger.error(f"标记总结 RSS 状态失败: {e}")
