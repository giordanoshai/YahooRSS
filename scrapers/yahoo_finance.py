"""
scrapers/yahoo_finance.py - Yahoo Finance 抓取器

从 Yahoo Finance latest-news 页面采集高频财经新闻。
支持动态 stream-items 新闻流容器、备用数据选择器与全局文章锚点兜底，
内置媒体黑名单与合作伙伴字段提取，物理阻断引流软文。
"""
import json
import re
from urllib.parse import unquote
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from core.logger import logger


class YahooFinanceScraper(BaseScraper):
    """Yahoo Finance 新闻抓取器（专注于 latest-news 页面）"""

    SOURCE_NAME = "yahoo_finance"
    URL = "https://finance.yahoo.com/topic/latest-news/"
    
    # 媒体黑名单：直接在抓取 HTML 时彻底排除这些投顾/个人理财推广/自媒体源
    MEDIA_BLACKLIST = {
        "stockstory", 
        "motley fool", 
        "the motley fool",
        "fool.com",
        "zacks", 
        "simply wall st", 
        "simply wall.st", 
        "simply wall pst",
        "investorplace",
        "gurufocus",
        "24/7 wall st",
        "24/7 wall street",
        "247 wall st",
        "marketbeat",
        "smartasset",
        "gobankingrates",
        "tipranks",
        "benzinga",
        "coincodex",
        "finbold",
        "investing.com",
    }

    def _extract_partner(self, link_tag) -> str | None:
        """从 a 标签的 data-yga / data-ylk 属性或父级元素文本中提取 Yahoo 内容合作伙伴名称"""
        yga_str = link_tag.get("data-yga")
        if yga_str:
            try:
                yga_data = json.loads(yga_str)
                partner = yga_data.get("yDestinationContentPartner") or yga_data.get("yContentPartner")
                if partner:
                    return partner.strip()
            except Exception:
                pass

        ylk_str = link_tag.get("data-ylk")
        if ylk_str:
            match = re.search(r'destpartner:([^;]+)', ylk_str)
            if match:
                return unquote(match.group(1)).strip()

        # 检查祖先容器中的 publishing / byline / provider 文本
        parent = link_tag.parent
        for _ in range(4):
            if parent:
                publishing = parent.find(class_=lambda c: c and any(k in str(c).lower() for k in ["publishing", "source", "provider", "byline"]))
                if publishing:
                    txt = publishing.get_text().strip()
                    if txt:
                        return txt.split("•")[0].strip()
                parent = parent.parent

        return None

    def _is_blacklisted_partner(self, partner: str | None) -> bool:
        """检查合作伙伴是否在黑名单中"""
        if not partner:
            return False
        p_lower = partner.lower()
        return any(bm in p_lower for bm in self.MEDIA_BLACKLIST)

    def _parse_html_titles(self, html: str) -> list[dict]:
        """解析 HTML 页面提取新闻标题与链接"""
        soup = BeautifulSoup(html, "html.parser")
        news_items = []
        seen_urls = set()

        # 策略 1: 优先查找 stream-items 容器（Yahoo Finance 当前主流动态新闻流容器）
        stream_uls = soup.find_all("ul", class_=lambda c: c and "stream-items" in c)
        for u in stream_uls:
            for li in u.find_all("li"):
                h = li.find(["h3", "h2"])
                title = h.get_text().strip() if h else None
                link_tag = None
                for a in li.find_all("a"):
                    href = a.get("href", "")
                    if ".html" in href:
                        link_tag = a
                        if not title and len(a.get_text().strip()) > 10:
                            title = a.get_text().strip()
                        break

                if link_tag and title:
                    href = link_tag.get("href", "")
                    if href.startswith("/"):
                        href = "https://finance.yahoo.com" + href

                    partner = self._extract_partner(link_tag)
                    if self._is_blacklisted_partner(partner):
                        continue

                    if any(bm in title.lower() for bm in ["motley fool", "zacks", "simply wall", "gurufocus", "24/7 wall", "marketbeat", "smartasset", "gobankingrates"]):
                        continue

                    if href not in seen_urls:
                        seen_urls.add(href)
                        news_items.append({
                            "title": title,
                            "url": href,
                            "source": self.SOURCE_NAME,
                            "partner": partner,
                        })

        if len(news_items) >= 5:
            return news_items

        # 策略 2: 备用容器定位（按 data-testid 或 role 寻找）
        candidate_containers = soup.find_all("ul", attrs={"data-testid": "list-ds"})
        candidate_containers += soup.find_all("ul", class_=re.compile(r".*(yf-12gc3ad|list).*"), role="list")

        for container in candidate_containers:
            for link in container.find_all("a"):
                title = link.get_text().strip()
                href = link.get("href")
                if href:
                    if href.startswith("/"):
                        href = "https://finance.yahoo.com" + href

                    if href.startswith("http") and href.endswith(".html") and title and len(title) > 10:
                        partner = self._extract_partner(link)
                        if self._is_blacklisted_partner(partner):
                            continue

                        if any(bm in title.lower() for bm in ["motley fool", "zacks", "simply wall", "gurufocus", "24/7 wall", "marketbeat", "smartasset", "gobankingrates"]):
                            continue

                        if href not in seen_urls:
                            seen_urls.add(href)
                            news_items.append({
                                "title": title,
                                "url": href,
                                "source": self.SOURCE_NAME,
                                "partner": partner,
                            })

        if len(news_items) >= 5:
            return news_items

        # 策略 3: 全局文章锚点兜底（匹配形如 /articles/...html 或 /news/...html）
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not (".html" in href and ("articles" in href or "/news/" in href)):
                continue
            title = a.get_text().strip()
            h = a.find(["h2", "h3"]) or (a.parent and a.parent.name in ["h2", "h3"])
            if h:
                title = h.get_text().strip()
            if not title or len(title) < 15:
                continue
            if href.startswith("/"):
                href = "https://finance.yahoo.com" + href
            partner = self._extract_partner(a)
            if self._is_blacklisted_partner(partner):
                continue
            if any(bm in title.lower() for bm in ["motley fool", "zacks", "simply wall", "gurufocus", "24/7 wall", "marketbeat", "smartasset", "gobankingrates"]):
                continue
            if href not in seen_urls:
                seen_urls.add(href)
                news_items.append({
                    "title": title,
                    "url": href,
                    "source": self.SOURCE_NAME,
                    "partner": partner,
                })

        return news_items

    def fetch_titles(self) -> list[dict]:
        """抓取 Yahoo Finance 最新新闻列表的新闻标题和链接"""
        html = self._request_page(self.URL)
        if not html:
            logger.error(f"抓取页面失败: {self.URL}")
            return []

        items = self._parse_html_titles(html)
        if items:
            logger.info(f"从 {self.URL} 成功获取到 {len(items)} 条标题")
            return items

        logger.warning(f"未能从 {self.URL} 解析出有效新闻标题")
        return []
