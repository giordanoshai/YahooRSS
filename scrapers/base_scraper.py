"""
scrapers/base_scraper.py - 新闻抓取器抽象基类

定义抓取器标准接口规范。
内置 curl_cffi 模拟真实 Chrome 浏览器 TLS/JA3 指纹，结合 trafilatura 自动化正文抽取，
支持指数退避重试与多线程批量并发采集。
"""
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
import random
import time
from curl_cffi import requests
import trafilatura

from core.config import settings
from core.logger import logger


class BaseScraper(ABC):
    """新闻抓取器基类"""

    SOURCE_NAME: str = "unknown"
    URL: str = ""

    def __init__(self, proxies: dict | None = None, max_threads: int = 4, max_retries: int = 3):
        self.proxies = proxies or settings.http_proxies
        self.max_threads = max_threads
        self.max_retries = max_retries

    @abstractmethod
    def fetch_titles(self) -> list[dict]:
        """
        抓取新闻标题和链接列表。

        Returns:
            [{"title": str, "url": str, "source": str, ...}]
        """
        ...

    def fetch_content(self, url: str) -> str | None:
        """
        通用正文提取（使用 curl_cffi + trafilatura）。

        Args:
            url: 新闻文章链接

        Returns:
            清洗后的正文文本，失败返回 None
        """
        try:
            response = requests.get(
                url,
                impersonate="chrome",
                proxies=self.proxies,
                timeout=30,
            )
            if response.status_code != 200:
                if response.status_code in (401, 403):
                    logger.warning(f"页面受限或需付费订阅 {url}, 状态码: {response.status_code}")
                else:
                    logger.error(f"正文请求失败 {url}, 状态码: {response.status_code}")
                return None

            content = trafilatura.extract(response.text)
            return content.strip() if content and content.strip() else None

        except requests.errors.RequestsError as e:
            logger.error(f"[网络错误] {url} - {e}")
        except Exception as e:
            logger.error(f"[提取错误] {url} - {e}")
        return None

    def fetch_all_contents(self, urls: list[str]) -> dict[str, str | None]:
        """
        多线程批量并发抓取文章正文。

        Args:
            urls: URL 列表

        Returns:
            {url: content_or_None}
        """
        results = {}

        def _process(url: str):
            content = self.fetch_content(url)
            results[url] = content
            if content:
                logger.debug(f"正文抓取成功: {url}")
            else:
                logger.warning(f"正文抓取为空或失败: {url}")

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            executor.map(_process, urls)

        return results

    def _request_page(self, url: str) -> str | None:
        """
        通用页面请求（带 Chrome 指纹伪装 + 指数退避重试）。

        Returns:
            页面 HTML 文本，失败返回 None
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    impersonate="chrome",
                    proxies=self.proxies,
                    timeout=30,
                )
                if response.status_code == 200:
                    return response.text
                if response.status_code == 404:
                    logger.warning(f"页面不存在 (404)，跳过重试: {url}")
                    return None
                logger.warning(f"请求页面失败 (第 {attempt} 次), 状态码: {response.status_code}")
            except requests.errors.RequestsError as e:
                logger.warning(f"网络连接异常 (第 {attempt} 次): {e}")
            except Exception as e:
                logger.error(f"页面加载发生错误: {e}")
                return None

            if attempt < self.max_retries:
                delay = random.uniform(2 ** (attempt - 1), 2 ** attempt)
                logger.debug(f"等待 {delay:.1f}s 后执行重试...")
                time.sleep(delay)

        logger.error(f"页面请求失败，已重试 {self.max_retries} 次: {url}")
        return None
