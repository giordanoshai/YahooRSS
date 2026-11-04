"""
services/rss_generator.py - RSS 2.0 生成与自动化维护引擎

负责将结构化新闻和每日宏观研报生成为符合国际标准的 RSS 2.0 XML 源。
特性：
1. 严格符合 RFC 2822 时间标准（带 +0000 偏移），兼容全平台 RSS 阅读器；
2. format_content 语义化 HTML 转换引擎（自动高亮 Markdown 标题、列表、金融逻辑链 '→'）；
3. 自动化过期清理与时区修正，有效控制 XML 文件体积。
"""
import os
import re
import time
from email.utils import format_datetime
from xml.etree.ElementTree import Element, SubElement, ElementTree, ParseError
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser

from core.config import settings
from core.database import (
    get_unrss_news,
    get_unrss_summaries,
    mark_news_rss,
    mark_summary_rss,
)
from core.logger import logger


# ============================================================
# RSS 根节点与时间规范化
# ============================================================

def _create_rss_root(title: str = "雅虎财经新闻", link: str = "", description: str = "Yahoo finance news") -> Element:
    """创建全新 RSS 2.0 根结构"""
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "link").text = link
    SubElement(channel, "description").text = description
    return rss


def _format_pubdate(dt: datetime) -> str:
    """
    按 RSS 规范要求的 RFC 2822 写出时间，如 Mon, 07 Sep 2026 11:41:22 +0000。
    使用 email.utils 消除时区缩写歧义与本地化语言干扰。
    """
    return format_datetime(dt.astimezone(timezone.utc))


def _convert_time_to_rss(iso_time: str) -> str:
    """ISO 时间字符串转换为 RFC 2822 标准格式"""
    try:
        dt = dateutil_parser.parse(iso_time)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _format_pubdate(dt)
    except Exception:
        return _format_pubdate(datetime.now(timezone.utc))


# ============================================================
# 内容格式化（Markdown/中文结构 → 语义化 HTML）
# ============================================================

def _close_ul_if_needed(formatted: list, in_ul: bool) -> bool:
    if in_ul:
        formatted.append("</ul>")
    return False


def _process_sentences(text: str, container: list):
    """按中文句号拆分为自然段落"""
    sentences = re.split(r"(?<=[。！？])(?!→)", text)
    for s in filter(None, [s.strip() for s in sentences]):
        container.append(f"<p>{s}</p>")


def format_content(content: str) -> str:
    """将 AI 生成的 Markdown/中文内容转为语义化 HTML（注入 RSS description）"""
    if not content:
        return "<p>内容未翻译或正在处理中</p>"

    formatted = []
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    in_ul = False

    for para in paragraphs:
        # Markdown 标题 (# Title)
        md_title = re.match(r"^(#{1,6})\s*\*\*?(.+?)\*\*?$", para)
        if md_title:
            in_ul = _close_ul_if_needed(formatted, in_ul)
            level = len(md_title.group(1))
            title_text = md_title.group(2).replace("**", "")
            formatted.append(f"<h{level}>{title_text}</h{level}>")
            continue

        # 【】章节标题
        if re.match(r"^【.*?】$", para):
            in_ul = _close_ul_if_needed(formatted, in_ul)
            formatted.append(f"<h3>{para}</h3>")
            continue

        # 日期标题
        if re.match(r"^\d{1,2}月\d{1,2}日（周[一二三四五六日]）", para):
            in_ul = _close_ul_if_needed(formatted, in_ul)
            formatted.append(f"<h4>{para}</h4>")
            continue

        # 列表条目
        if re.match(r"^[-\u3000—*]+\s", para):
            if not in_ul:
                formatted.append("<ul>")
                in_ul = True
            item_text = re.sub(r"^[-\u3000—*]+\s*", "", para)
            formatted.append(f"<li>{item_text}</li>")
            continue

        # 数字编号 (1. xxx)
        if re.match(r"^(\d+[\.．])\s+", para):
            in_ul = _close_ul_if_needed(formatted, in_ul)
            parts = re.split(r"\s+", para, maxsplit=1)
            number = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            formatted.append(f"<p><strong>{number}</strong> {rest}</p>")
            continue

        # 逻辑推理链 (A → B → C)
        if "→" in para:
            in_ul = _close_ul_if_needed(formatted, in_ul)
            formatted.append(f"<p class='logic-chain'>{para}</p>")
            continue

        # 普通段落
        in_ul = _close_ul_if_needed(formatted, in_ul)
        _process_sentences(para, formatted)

    if in_ul:
        formatted.append("</ul>")

    return "".join(formatted)


# ============================================================
# 清理过期条目
# ============================================================

def _clear_old_items(channel: Element, retention_days: int = 2):
    """清理超过保留天数的旧 RSS 条目，并规范化时区"""
    cutoff = time.time() - retention_days * 24 * 60 * 60
    items_to_remove = []

    for item in channel.findall("item"):
        pub_date_node = item.find("pubDate")
        if pub_date_node is None or not pub_date_node.text:
            continue
        try:
            dt = dateutil_parser.parse(pub_date_node.text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.timestamp() < cutoff:
                items_to_remove.append(item)
                continue
            # 顺便规范化历史遗留时区写法
            normalized = _format_pubdate(dt)
            if pub_date_node.text != normalized:
                pub_date_node.text = normalized
        except Exception as e:
            logger.warning(f"解析 pubDate 异常: {e}")

    for item in items_to_remove:
        channel.remove(item)

    if items_to_remove:
        logger.debug(f"修剪移除 {len(items_to_remove)} 条过期 RSS 条目")


# ============================================================
# 通用 XML 写入逻辑
# ============================================================

def _write_items_to_rss(
    rows: list[dict],
    rss_path: str,
    title_key: str,
    content_key: str,
    url_key: str,
    time_key: str,
    feed_title: str = "雅虎财经新闻",
    feed_description: str = "Yahoo finance news",
) -> list[int]:
    """通用 RSS 写入逻辑"""
    if not rss_path:
        logger.error("RSS 输出文件路径未配置")
        return []

    if os.path.exists(rss_path) and os.path.getsize(rss_path) > 0:
        try:
            tree = ElementTree(file=rss_path)
            root = tree.getroot()
            channel = root.find("channel")
        except ParseError:
            logger.error(f"RSS 文件损坏，重新建立 XML 骨架: {rss_path}")
            root = _create_rss_root(feed_title, description=feed_description)
            channel = root.find("channel")
            tree = ElementTree(root)
    else:
        root = _create_rss_root(feed_title, description=feed_description)
        channel = root.find("channel")
        tree = ElementTree(root)

    # 清理过期旧条目
    _clear_old_items(channel, settings.RSS_RETENTION_DAYS)

    added_ids = []
    for row in rows:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = row.get(title_key, "")
        SubElement(item, "description").text = format_content(row.get(content_key, ""))
        url = row.get(url_key, "")
        SubElement(item, "link").text = url
        SubElement(item, "guid").text = url
        SubElement(item, "pubDate").text = _convert_time_to_rss(row.get(time_key, ""))
        added_ids.append(row["id"])

    # 持久化 XML 文件
    tree.write(rss_path, encoding="utf-8", xml_declaration=True)
    return added_ids


# ============================================================
# 公开对外接口
# ============================================================

def generate_news_rss():
    """生成财经新闻 RSS 源（含模式 B 二次自选股筛选）"""
    rows = get_unrss_news()
    if not rows:
        return

    rss_path = settings.RSS_NEWS_PATH
    added_ids = _write_items_to_rss(
        rows, 
        rss_path,
        title_key="title_cn",
        content_key="summary_cn",
        url_key="url",
        time_key="published_at",
    )
    if added_ids:
        mark_news_rss(added_ids)
        logger.info(f"新闻 RSS 写入完成: {len(added_ids)} 篇 -> {rss_path}")


def generate_summary_rss():
    """生成每日盘前/盘后大盘宏观总结 RSS 源"""
    rows = get_unrss_summaries()
    if not rows:
        return

    rss_path = settings.RSS_SUMMARY_PATH
    added_ids = _write_items_to_rss(
        rows, 
        rss_path,
        title_key="title",
        content_key="summary_content",
        url_key="url",
        time_key="created_at",
        feed_title="雅虎财经每日宏观总结",
        feed_description="Yahoo finance daily macro summary",
    )
    if added_ids:
        mark_summary_rss(added_ids)
        logger.info(f"大盘总结 RSS 写入完成: {len(added_ids)} 篇 -> {rss_path}")
