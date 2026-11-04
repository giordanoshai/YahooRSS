"""
services/news_filter.py — 新闻入库前的初筛与事件去重

只做两件事，都发生在新闻写进数据库之前：

1. **套路文过滤**：剔除退休理财、房贷、荐股列表这类对交易没用的内容，直接丢弃不入库。
2. **事件去重**：识别出「同一件事的第 N 篇报道」并打上标记。重复的新闻**照样入库**，
   只是带着标记，后续不抓正文、不做 AI 分析、不推 RSS。这样既不会重复消耗算力，
   万一判错了也能在数据库中翻出来核对。

去重的判据是「罕见词」——一个词在最近 24 小时的新闻标题里出现得越少，它越能代表一件
具体的事。Fed、Earnings、Stock 这类天天出现的词几乎不算数；Hugging、OPEC 这类罕见词
才算「事件特征」。两条标题共享 2 个以上罕见词，就认为它们在说同一件事。

关键之处在于词频只统计「首发新闻」（is_duplicate = false）：一件事不管被报道多少次，
它的特征词在库里始终只出现一两次，永远是罕见词——所以第 20 篇跟踪报道照样能拦住。
"""

from __future__ import annotations

import re
from collections import defaultdict

from core.logger import logger

# ============================================================
# 去重参数
# ============================================================

# 一个词在「首发新闻」库里出现不超过这么多次，才算罕见词（事件特征词）
RARE_DF_MAX = 2

# 两条标题共享这么多个罕见词，就判定为同一事件
RARE_HIT_MIN = 2

# 首发库小于这么多条时跳过事件去重：样本太少时所有词看着都罕见，容易误杀
MIN_CORPUS_SIZE = 30

# 标题有效词少于这么多个时不参与去重：信息量不足，判不准
MIN_TOKENS = 3


# ============================================================
# 套路文过滤规则
# ============================================================

# 垃圾新闻套路正则表达式
EXCLUDE_REGEX: list[re.Pattern] = [
    # 1. 股票精选、个股推荐列表套路（如 "3 of the best stocks", "10 dividend stocks", "5 stocks to watch"）
    re.compile(r'\b\d+\s+(?:of\s+)?(?:the\s+)?(?:best\s+)?(?:stocks|things|ways|etfs|dividend|reasons|mistakes|rules|rebound|cryptocurrenc|options|picks|cryptos)\b', re.IGNORECASE),

    # 2. “是否应该买入/卖出” 提问套路（如 "should you buy/sell/invest"）
    re.compile(r'\bshould\s+(?:you|investors|we|people|anyone)\s+(?:buy|sell|hold|invest|avoid|worry|be\s+worrying)\b', re.IGNORECASE),

    # 3. "$1,000 investment..." 噱头财富套路
    re.compile(r'\$[0-9,]+\s+investment\b', re.IGNORECASE),

    # 4. “值不值得买” 投顾噱头词 (better buy, worth buying, worth owning, growth stocks to buy, smartest buy, no-brainer)
    re.compile(r'\b(?:millionaire-maker|better buy|worth buying|worth owning|growth stocks to buy|smartest buy|no-brainer)\b', re.IGNORECASE),

    # 5. 横评对比选股套路 "X vs Y: Which is the..." 或 "X vs the rest"
    re.compile(r'\bvs\.?\s+(?:the\s+rest|each\s+other|each)\b', re.IGNORECASE),
    re.compile(r'\b[a-zA-Z0-9\s]+vs\.?\s+[a-zA-Z0-9\s]+:\s+which\s+is\s+the\b', re.IGNORECASE),

    # 6. “是不是到了买入时间” 或 “某股票是否值得买入” 噱头句式
    re.compile(r'\bis\s+it\s+time\s+to\b', re.IGNORECASE),
    re.compile(r'\bis\s+[A-Za-z0-9\s]+stock\s+(?:a\s+)?(?:buy|sell|rebound|ripe|safe)\b', re.IGNORECASE),

    # 7. "X stocks to (buy/avoid/sell) instead"
    re.compile(r'\band\s+\d+\s+stocks?\s+to\s+(?:buy|sell|avoid|hold)\s+instead\b', re.IGNORECASE),

    # 8. "These are the only \d+" 吸睛句式
    re.compile(r'\bthese\s+are\s+the\s+only\s+\d+\b', re.IGNORECASE),

    # 9. 虚空设问式标题 "Is there anything [company] can do to..."
    re.compile(r'\bis\s+there\s+anything\s+[A-Za-z0-9\s]+\s+can\s+do\s+to\b', re.IGNORECASE),

    # 10. StockStory 标志性套路一 (e.g. "1 Profitable Stock ... and 2 We Ignore/Avoid/Question")
    re.compile(r"\b\d+\s+(?:of\s+)?(?:.+?)\s+stocks?\s+.*and\s+\d+\s+(?:we|we'll)\s+(?:question|ignore|avoid|dislike|skip)\b", re.IGNORECASE),

    # 11. StockStory 标志性套路二 (e.g. "3 Growth Stocks We Approach with Caution / That Concern Us")
    re.compile(r"\b\d+\s+(?:.+?)\s+stocks?\s+(?:we|we'll|that|to)\s+(?:approach|think\s+twice|keep\s+off|concern|ignore|avoid|worry|interest|research|question)\b", re.IGNORECASE),

    # 12. StockStory 标志性套路三 (e.g. "5 Potential Buyers of Roku That Actually Make Sense")
    re.compile(r"\b\d+\s+potential\s+(?:buyers|sellers)\s+of\s+(?:.+?)\s+that\s+actually\s+make\s+sense\b", re.IGNORECASE),

    # 13. 跑赢/跑输大盘或板块对比 (Barchart/Zacks 批量模板)
    re.compile(r'\bis\s+[A-Za-z0-9\s\.\,\'\-]+?\s+stock\s+(?:outperforming|underperforming)\b', re.IGNORECASE),
    re.compile(r'\bhow\s+is\s+[A-Za-z0-9\s\.\,\'\-]+?\s+stock\s+performance\s+compared\b', re.IGNORECASE),
    re.compile(r'\b(?:underperforming|outperforming)\s+the\s+[A-Za-z0-9\s]+(?:sector|market|s&p|nasdaq|dow)\b', re.IGNORECASE),

    # 14. 股息/分红股评测、对比与引流 (GuruFocus / 24/7 Wall St / Seeking Alpha)
    re.compile(r"['’]s\s+dividend\s+analysis\b", re.IGNORECASE),
    re.compile(r'\bdividend\s+aristocrat(?:s)?\b', re.IGNORECASE),
    re.compile(r'\bdividend\s+king(?:s)?\b', re.IGNORECASE),
    re.compile(r'\bwhich\s+dividend\s+is\s+safer\b', re.IGNORECASE),
    re.compile(r'\b(?:one|1)\s+of\s+these\s+\d+\s+(?:bdcs|stocks|dividend|funds|etfs)\b', re.IGNORECASE),
    re.compile(r'\bhow\s+much\s+to\s+invest\s+in\s+[A-Za-z0-9\s\.\,\'\-]+?\s+to\s+earn\s+\$[\d\.\,]+\b', re.IGNORECASE),
    re.compile(r'\bhow\s+much\s+do\s+you\s+(?:really\s+)?need\s+invested\b', re.IGNORECASE),
    re.compile(r'\b(?:monthly\s+dividend|paying\s+\d+\s+to\s+\d+\s+percent)\b', re.IGNORECASE),
    re.compile(r'\bwe\s+ranked\s+all\s+(?:four|three|five|\d+)\b', re.IGNORECASE),
    re.compile(r'\bhere(?:’|\')?s\s+which\s+belongs\s+in\s+your\s+(?:roth\s+ira|401k|portfolio)\b', re.IGNORECASE),
    re.compile(r'\bthese\s+\w+\s+funds\s+get\s+a\s+raise\b', re.IGNORECASE),
    re.compile(r'\bwhich\s+[A-Za-z0-9\s\-]+?\s+(?:etf|stock|fund)\s+pays\s+you\s+more\b', re.IGNORECASE),
    re.compile(r'\bcovered-call\s+etf\b', re.IGNORECASE),

    # 15. 投顾噱头喊单、炒作与荐股评级
    re.compile(r'\bwhy\s+it(?:’|\')?s\s+time\s+to\s+(?:load\s+up\s+on|buy|dump|sell|accumulate)\b', re.IGNORECASE),
    re.compile(r'\breasons?\s+to\s+buy\b', re.IGNORECASE),
    re.compile(r'\b\$\d+.*reason\s+(?:to\s+buy|why\s+[A-Za-z0-9]+\s+stock)\b', re.IGNORECASE),
    re.compile(r'\bthis\s+analyst\s+just\s+upgraded\b', re.IGNORECASE),
    re.compile(r'\bjust\s+scored\s+an\s+upgrade\b', re.IGNORECASE),
    re.compile(r'\bdouble-upgrades?\b', re.IGNORECASE),
    re.compile(r'\bturned\s+(?:bearish|bullish)\s+on\b', re.IGNORECASE),
    re.compile(r'\bturning\s+point\s+for\s+(?:the\s+)?beaten-down\s+stock\b', re.IGNORECASE),
    re.compile(r'\bjust\s+dropped\s+huge\s+news\s+for\s+this\b', re.IGNORECASE),
    re.compile(r'\bhow\s+to\s+play\s+[A-Za-z0-9]+\s+stock\b', re.IGNORECASE),
    re.compile(r'\bhere\s+are\s+\d+\s+stocks\s+we\s+like\s+better\b', re.IGNORECASE),
    re.compile(r'\bbacking\s+up\s+the\s+truck\s+on\b', re.IGNORECASE),

    # 16. 加密货币算命与AI虚假设问
    re.compile(r'\b(?:price\s+prediction|price\s+forecast)\b', re.IGNORECASE),
    re.compile(r'\bhow\s+much\s+[A-Za-z0-9]+\s+do\s+you\s+need\s+to\s+be\s+in\s+the\s+top\b', re.IGNORECASE),
    re.compile(r'\bwe\s+asked\s+(?:grok|chatgpt|copilot|ai)\s+if\b', re.IGNORECASE),

    # 17. 个人理财/继承/买房养老与鸡汤故事
    re.compile(r'\bwhich\s+account\s+goes\s+first\b', re.IGNORECASE),
    re.compile(r'\b(?:inheritance|inherited)\b.*\b(?:irs|timeshare|rent-free|florida|tax|brother|heir)\b', re.IGNORECASE),
    re.compile(r'\bi(?:’|\')?m\s+\d+\s+and\s+want\s+to\s+spend\b', re.IGNORECASE),
    re.compile(r'\bi(?:’|\')?m\s+\d+\s+with\s+\$[\d\.\,]+\b', re.IGNORECASE),
    re.compile(r'\bthey\s+bought\s+[A-Za-z0-9\s]+stock\s+in\s+the\s+(?:\'|\b)?\d+s\b', re.IGNORECASE),
    re.compile(r'\bwithout\s+financial\s+advisors?\b', re.IGNORECASE),
    re.compile(r'\bthe\s+smartest\s+money\s+moves\b', re.IGNORECASE),
    re.compile(r'\bwhat\s+happens\s+if\s+you\s+never\s+buy\s+a\s+house\b', re.IGNORECASE),
    re.compile(r'\bput\s+his\s+daughter(?:’|\')?s\s+name\s+on\b', re.IGNORECASE),
    re.compile(r'\bmedicaid\s+didn(?:’|\')?t\s+care\b', re.IGNORECASE),
    re.compile(r'\bwhere\s+gen\s+z\s+can\s+afford\s+to\s+buy\s+homes\b', re.IGNORECASE),
    re.compile(r'\bto\s+cash\s+out\s+for\s+\$\d+k\s+or\s+get\s+\$\d+\s+per\s+month\b', re.IGNORECASE),
    re.compile(r'\bsole\s+heir\s+to\s+\$[\d\.\,]+m\b', re.IGNORECASE),
    re.compile(r'\badult\s+kid\s+live\s+at\s+home\b', re.IGNORECASE),
    re.compile(r'\bwealth-building\s+tips\b', re.IGNORECASE),
    re.compile(r'\bmoving\s+billions\s+to\s+the\s+next\s+generation\b', re.IGNORECASE),
    re.compile(r'\bowns\s+the\s+same\s+\w+\s+stocks\s+twice\b', re.IGNORECASE),
    re.compile(r'\b(?:best|worst)\s+week\s+of\s+the\s+year\s+to\s+buy\s+a\s+house\b', re.IGNORECASE),
]

# 媒体黑名单（入库前初筛兜底）
MEDIA_BLACKLIST: set[str] = {
    "stockstory", "motley fool", "the motley fool", "fool.com", "zacks",
    "simply wall st", "simply wall.st", "simply wall pst", "investorplace",
    "gurufocus", "24/7 wall st", "247 wall st", "24/7 wall street", "marketbeat",
    "smartasset", "gobankingrates", "tipranks", "benzinga",
    "coincodex", "finbold", "investing.com"
}

# 命中任意一个词 → 强制过滤（垃圾新闻）
KEYWORD_EXCLUDE: list[str] = [
    # 彻底屏蔽：社保、房地产、退休金、日常储蓄/房贷理财
    "retirement", "retirees", "retire", "401(k)", "401k", "social security",
    "housing market", "home price", "home prices", "mortgage rates", "mortgage rate", "mortgage",
    "save money", "tax tip", "tax tips", "annuities", "annuity",
    "savings interest rates", "savings rate", "savings rates", "high-yield savings",
    "mortgage and refinance", "refinance interest", "cd rates", "cd rate", "heloc",
    "home equity loan", "home equity loans", "timeshare", "medicare", "medicaid",
    "roth ira", "traditional ira",

    # 值不值得买/如何买相关
    "reasons to buy", "reasons to sell", "reasons to avoid", "reasons to like",
    "stock to buy instead", "stocks to buy instead", "buy instead", "is it time to buy",
    "could double", "millionaire-maker", "what that means for investors", "facing headwinds",
    "penny stock", "penny stocks", "dividend stock", "dividend stocks", "passive income",
    "how to invest in", "how safe is", "buying opportunity or a warning", "buying opportunity or warning",
    "load up on", "dividend aristocrat", "dividend king", "dividend kings", "price prediction",
    "suze orman", "dave ramsey", "living off the dividends",

    # 大众股票精选/推荐词
    "under $10", "under $5", "under-the-radar", "hidden gem", "hidden gems",

    # 原先的排除词
    "russell 2000 stocks to", "walk a fine line", "facing challenges", "brush off",
    "crypto scam", "rug pull", "celebrity",
]


def _matches_exclude(text: str) -> bool:
    """标题是否命中套路文规则"""
    for reg in EXCLUDE_REGEX:
        if reg.search(text):
            return True
    lower = text.lower()
    return any(kw in lower for kw in KEYWORD_EXCLUDE)


# ============================================================
# 标题分词
# ============================================================

STORY_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "with", "is", "are",
    "was", "were", "has", "have", "had", "been", "be", "by", "after", "amid",
    "as", "from", "its", "it", "says", "said", "say", "report", "reports",
    "reported", "could", "would", "will", "may", "about", "into", "over",
    "under", "more", "than", "and", "or", "but", "not", "no", "up", "down",
    "heres", "here", "why", "what", "how", "who", "which", "when", "where",
    "out", "new", "first", "just", "now", "today", "day", "market", "stocks",
    "stock", "shares", "share", "top", "investors", "analysts", "analyst",
    "view", "look", "closer", "ahead", "following", "amidst", "know", "need",
    "alphacheck", "check",
}


def _depluralize(word: str) -> str:
    """粗略去复数：rates → rate，但 business / press 这类不动"""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def extract_tokens(title: str) -> set[str]:
    """把标题拆成用于比对的词集合，过滤停用词与纯数字"""
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9]+", title.lower()):
        if len(raw) <= 1 or raw.isdigit() or raw in STORY_STOP_WORDS:
            continue
        word = _depluralize(raw)
        if word in STORY_STOP_WORDS:
            continue
        tokens.add(word)
    return tokens


def _title_key(title: str) -> str:
    """标题归一化指纹，用于识别一字不差的转载"""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


# ============================================================
# 事件索引
# ============================================================

class StoryIndex:
    """
    最近一段时间「首发新闻」的标题索引，用来判断一条新标题是不是同一事件的重复报道。
    """

    def __init__(
        self,
        records: list[dict] | None = None,
        rare_df_max: int = RARE_DF_MAX,
        rare_hit_min: int = RARE_HIT_MIN,
        min_corpus: int = MIN_CORPUS_SIZE,
    ):
        self._rare_df_max = rare_df_max
        self._rare_hit_min = rare_hit_min
        self._min_corpus = min_corpus

        self._doc_count = 0
        self._doc_ids: dict[int, int | None] = {}
        self._df: dict[str, int] = defaultdict(int)
        self._postings: dict[str, set[int]] = defaultdict(set)
        self._exact: dict[str, int] = {}

        for rec in records or []:
            self.add(rec.get("title") or "", rec.get("id"))

    def __len__(self) -> int:
        return self._doc_count

    def add(self, title: str, news_id: int | None = None) -> None:
        """把一条首发标题加进索引"""
        if not title:
            return
        slot = self._doc_count
        self._doc_count += 1
        self._doc_ids[slot] = news_id

        key = _title_key(title)
        if key and key not in self._exact:
            self._exact[key] = slot

        for token in extract_tokens(title):
            self._df[token] += 1
            self._postings[token].add(slot)

    def find_duplicate(self, title: str) -> tuple[int | None, str]:
        """
        判断标题是不是已有事件的重复报道。

        Returns:
            (首发那条的新闻 id, 判定理由)。不是重复时返回 (None, "")。
        """
        if not title:
            return None, ""

        key = _title_key(title)
        if key and key in self._exact:
            return self._doc_ids[self._exact[key]], "标题完全相同"

        if self._doc_count < self._min_corpus:
            return None, ""

        tokens = extract_tokens(title)
        if len(tokens) < MIN_TOKENS:
            return None, ""

        rare = {t for t in tokens if 0 < self._df[t] <= self._rare_df_max}
        if len(rare) < self._rare_hit_min:
            return None, ""

        hits: dict[int, set[str]] = defaultdict(set)
        for token in rare:
            for slot in self._postings[token]:
                hits[slot].add(token)

        for slot, shared in hits.items():
            if len(shared) >= self._rare_hit_min:
                words = ", ".join(sorted(shared))
                return self._doc_ids[slot], f"共享罕见词 [{words}]"

        return None, ""


# ============================================================
# 入库前初筛主入口
# ============================================================

def filter_raw_titles(titles: list[dict], recent_news: list[dict] | None = None) -> list[dict]:
    """
    新闻抓取后、入库前的初筛。
    1. 已抓过网址跳过
    2. 套路文直接丢弃
    3. 事件去重打标 is_duplicate=True 照样入库
    """
    recent_news = recent_news or []
    known_urls = {r["url"] for r in recent_news if r.get("url")}
    origin_news = [r for r in recent_news if not r.get("is_duplicate")]

    index = StoryIndex(origin_news)

    pending: list[dict] = []
    skipped_known = 0
    dropped_junk = 0
    marked_dup = 0

    for item in titles:
        title_text = (item.get("title") or "").strip()
        if not title_text:
            continue

        url = item.get("url")
        if url and url in known_urls:
            skipped_known += 1
            continue

        partner = (item.get("partner") or "").lower()
        if partner and any(bm in partner for bm in MEDIA_BLACKLIST):
            dropped_junk += 1
            logger.debug(f"[媒体黑名单初筛] {title_text} -> partner: {partner}")
            continue

        if _matches_exclude(title_text):
            dropped_junk += 1
            continue

        dup_of, reason = index.find_duplicate(title_text)
        is_dup = bool(reason)

        row = dict(item)
        row["is_duplicate"] = is_dup
        row["dup_of"] = dup_of
        pending.append(row)

        if is_dup:
            marked_dup += 1
            logger.debug(f"[事件去重] {title_text} -> {reason}")
        else:
            index.add(title_text)

        if url:
            known_urls.add(url)

    if titles:
        logger.info(
            f"新闻初筛: 抓取 {len(titles)} 条, 已抓过跳过 {skipped_known} 条, "
            f"套路文丢弃 {dropped_junk} 条, 标记重复 {marked_dup} 条, "
            f"首发入库 {len(pending) - marked_dup} 条"
        )

    return pending

