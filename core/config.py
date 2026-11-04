"""
core/config.py - 统一配置管理

从 .env 加载所有配置项，供各模块引用。
支持本地 SQLite3 数据库、多 LLM 供应商、网络代理与自动化 RSS 参数。
"""
import os
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()


class Settings:
    """应用配置 - 所有配置项优先从环境变量读取"""

    # --- 本地 SQLite3 数据库 ---
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", "yahoonews.db")

    # --- 阿里云 DashScope / Qwen / DeepSeek ---
    QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # --- OpenRouter (Nemotron 等海外模型) ---
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # --- 默认模型配置 ---
    DEFAULT_LLM: str = os.getenv("DEFAULT_LLM", "qwen3.5-flash")
    EVALUATION_MODEL: str = os.getenv("EVALUATION_MODEL", "deepseek-v4-flash")
    SUMMARIZATION_MODEL: str = os.getenv("SUMMARIZATION_MODEL", "deepseek-v4-flash")
    DAILY_SUMMARY_MODEL: str = os.getenv("DAILY_SUMMARY_MODEL", "nvda-nemotron-120b")

    # --- 代理设置 ---
    HTTP_PROXY: str = os.getenv("HTTP_PROXY", "")
    SOCKS5_PROXY: str = os.getenv("SOCKS5_PROXY", "")

    @property
    def http_proxies(self) -> dict | None:
        """返回 requests / curl_cffi 格式的代理字典"""
        if self.HTTP_PROXY:
            return {"http": self.HTTP_PROXY, "https": self.HTTP_PROXY}
        return None

    # --- RSS 输出路径与保留策略 ---
    RSS_NEWS_PATH: str = os.getenv("RSS_NEWS_PATH", "yahoonews_rss.xml")
    RSS_SUMMARY_PATH: str = os.getenv("RSS_SUMMARY_PATH", "summary_rss.xml")
    RSS_RETENTION_DAYS: int = int(os.getenv("RSS_RETENTION_DAYS", "2"))

    # --- 抓取与并发参数 ---
    SCRAPE_MAX_THREADS: int = int(os.getenv("SCRAPE_MAX_THREADS", "4"))
    SCRAPE_INTERVAL_MINUTES: int = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "3"))

    # --- 自选股池（用于 RSS 模式 B 二次筛选的兜底名单） ---
    DEFAULT_WATCHLIST: str = os.getenv("DEFAULT_WATCHLIST", "SPY,QQQ,AAPL,NVDA,MSFT,TSLA,AMZN,GOOGL,META")

    @property
    def default_watchlist_set(self) -> set[str]:
        return {s.strip().upper() for s in self.DEFAULT_WATCHLIST.split(",") if s.strip()}


settings = Settings()
