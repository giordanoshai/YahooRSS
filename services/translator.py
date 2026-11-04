"""
services/translator.py - 新闻智能评分、分流精简与摘要翻译服务

采用双阶段大模型管道：
1. 阶段一（初评）：基于 deepseek-v4-flash 快速评定新闻重要度 (High/Medium/Low)、
   情绪评分 (-1.0~1.0) 与受影响股票代码。
2. 阶段二（分流）：Low 级别新闻自动略过二次调用，拼接结构化轻量模板落库，立省 50%+ Token；
   Medium / High 级别新闻放行执行专业标题翻译与 150 字以内核心事实摘要提取。
"""
import json
import time
import random
import threading

from core import llm_client
from core.database import get_untranslated_news, update_translation
from core.logger import logger
from core.config import settings

# 并发线程控制
MAX_CONCURRENT = 5

FETCH_FAILED_MARK = "[Fetch Failed]"
NO_CONTENT_HINT = "(Article body unavailable. Judge from the title alone.)"


def _clean_tickers(relate_tickers: list) -> tuple[list[str], str]:
    """从关联股票对象列表中提取标准代码并生成人类可读详情字符串"""
    if not relate_tickers or not isinstance(relate_tickers, list):
        return [], "无"
    
    clean_list = []
    details = []
    for item in relate_tickers:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker", "").strip().upper()
        reason = item.get("reason", "").strip()
        if ticker:
            clean_list.append(ticker)
            details.append(f"{ticker} : {reason}" if reason else ticker)
    
    return clean_list, "\n".join(details) if details else "无"


def _usable_content(content: str | None) -> str:
    """过滤占位符，返回有效正文"""
    text = (content or "").strip()
    if not text or text == FETCH_FAILED_MARK:
        return ""
    return text


def evaluate_importance_and_sentiment(title: str, content: str, model_name: str | None = None) -> dict:
    """
    阶段一：快速评估新闻重要性（High/Medium/Low）、市场情绪与关联个股。
    即使是 Low/Medium 评级，也能在此步骤以零额外成本获取个股归属与情绪值。
    """
    model_name = model_name or settings.EVALUATION_MODEL

    messages = [
        {
            "role": "system",
            "content": (
                """
                Please analyze the following financial news. Provide:
                1. importance: Whether this is important news (high/medium/low) for the stock market, with reasoning in Chinese. High = directly impacts market-wide sentiment, Fed policy, or major sector; Medium = sector-specific; Low = minor impact.
                2. sentiment: Sentiment analysis for the stock market. Provide "label" (positive/negative/neutral), "score" (a numeric value between -1.0 and 1.0, where -1.0 is extremely bearish, 1.0 is extremely bullish, and 0 is neutral), and brief "reasoning" in Chinese.
                3. relate_tickers: Related stocks/tickers that may be affected. If the article mentions a company name without a ticker, fill in the standard ticker. Return as an array of objects with "ticker" and "reason" (brief, in Chinese) keys. Return an empty array if no specific company is involved.

                Output ONLY a valid JSON object. Do NOT use Markdown code blocks. Do NOT output any preamble or explanation.

                Output Format:
                {
                  "importance": { "level": "", "reasoning": "" },
                  "sentiment": { "label": "", "score": 0.0, "reasoning": "" },
                  "relate_tickers": [{ "ticker": "", "reason": "" }]
                }
                """
            ),
        },
        {"role": "user", "content": f"Title: {title}\n\nContent: {content[:3000] or NO_CONTENT_HINT}"},
    ]
    raw = llm_client.chat(messages, model_name=model_name, timeout=45)
    try:
        # 清除代码块标记
        if raw.strip().startswith("```"):
            lines = raw.strip().split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Response is not a JSON object")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"解析 evaluate_importance_and_sentiment JSON 失败: {e}, Raw: {raw[:200]}")
        return {
            "importance": {"level": "low", "reasoning": "评估解析失败"},
            "sentiment": {"label": "neutral", "score": 0.0, "reasoning": "评估解析失败"},
            "relate_tickers": []
        }


def summarize_and_translate_content(title: str, content: str, model_name: str | None = None) -> dict:
    """
    阶段二：深度生成中文专业标题与核心事实摘要（<=150字），提炼高阶关联个股。
    复合 Prompt 单次调用消减网络 RTT 延迟。
    """
    model_name = model_name or settings.SUMMARIZATION_MODEL

    messages = [
        {
            "role": "system",
            "content": (
                """
                Please analyze the following financial news title and article. Provide:
                1. title_cn: An accurate and professional Chinese translation of the original title. Do NOT include any explanations.
                2. summary: A concise summary in Chinese (2-3 sentences, 150 chars max), strictly based on the original article, no inference.
                3. relate_tickers: Related stocks/tickers that may be affected. List tickers with brief reason. If the article mentions a company name without a ticker, fill in the standard ticker. Return as an array of objects with "ticker" and "reason" keys.

                Output ONLY a valid JSON object. Do NOT use Markdown code blocks. Do NOT output any preamble or explanation.

                Output Format:
                {
                  "title_cn": "",
                  "summary": "",
                  "relate_tickers": [{ "ticker": "", "reason": "" }]
                }
                """
            ),
        },
        {"role": "user", "content": f"Original Title: {title}\n\nArticle Content: {content or NO_CONTENT_HINT}"},
    ]
    raw = llm_client.chat(messages, model_name=model_name, timeout=60)
    try:
        if raw.strip().startswith("```"):
            lines = raw.strip().split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Response is not a JSON object")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"解析 summarize_and_translate_content JSON 失败: {e}, Raw: {raw[:200]}")
        return {
            "title_cn": f"[翻译失败] {title}",
            "summary": raw[:300],
            "relate_tickers": []
        }


def _process_single(record: dict, model_name: str | None = None):
    """处理单条新闻：先评级评分，Low 旁路跳过二次调用，Medium/High 完整翻译与摘要"""
    news_id = record["id"]
    title = record["title"]
    content = _usable_content(record.get("content"))
    if not content:
        logger.debug(f"ID {news_id} 正文缺失或抓取失败，仅依据标题分析")

    # 1. 快速重要度、情绪与关联个股评估
    try:
        eval_result = evaluate_importance_and_sentiment(title, content, model_name=model_name)
    except Exception as e:
        logger.warning(f"评估新闻重要度失败 ID {news_id}: {e}")
        eval_result = {
            "importance": {"level": "low", "reasoning": f"评估异常: {e}"},
            "sentiment": {"label": "neutral", "score": 0.0, "reasoning": f"评估异常: {e}"},
            "relate_tickers": []
        }

    importance = eval_result.get("importance") or {}
    sentiment = eval_result.get("sentiment") or {}
    eval_tickers_list, eval_tickers_detail = _clean_tickers(eval_result.get("relate_tickers"))

    imp_level = importance.get("level", "Low").capitalize()
    imp_reason = importance.get("reasoning", "").strip()
    sent_label = sentiment.get("label", "Neutral").capitalize()
    sent_score = sentiment.get("score", 0.0)
    sent_reason = sentiment.get("reasoning", "").strip()

    title_cn = None
    summary_cn = None
    relate_tickers_list = eval_tickers_list

    # 2. 核心分流控制门
    if imp_level.lower() == "low":
        # Low 级别新闻直接保留原英文标题，拼接精简模板，节省第二次 API 调用的巨大 Token
        title_cn = title
        summary_cn = (
            f"1. 【新闻摘要】\n低重要度新闻，略过详细摘要。\n\n"
            f"2. 【市场情绪】\n{sent_label} ({sent_score}) - {sent_reason}\n\n"
            f"3. 【相关股票】\n{eval_tickers_detail}\n\n"
            f"4. 【重要程度】\n{imp_level} - {imp_reason}\n"
        )
        logger.info(f"ID {news_id} 评级为 LOW，略过标题翻译与正文总结（已旁路落库） | Tickers: {relate_tickers_list}")
    else:
        # Medium 或 High：执行深度翻译 + 摘要提取
        try:
            result = summarize_and_translate_content(title, content, model_name=model_name)
            title_cn = result.get("title_cn", "").strip() or f"[翻译失败] {title}"
            summary = result.get("summary", "").strip()
            relate_tickers_list, tickers_detail = _clean_tickers(result.get("relate_tickers"))
            if not relate_tickers_list:
                relate_tickers_list, tickers_detail = eval_tickers_list, eval_tickers_detail

            summary_cn = (
                f"1. 【新闻摘要】\n{summary}\n\n"
                f"2. 【市场情绪】\n{sent_label} ({sent_score}) - {sent_reason}\n\n"
                f"3. 【相关股票】\n{tickers_detail}\n\n"
                f"4. 【重要程度】\n{imp_level} - {imp_reason}\n"
            )
            logger.debug(f"ID {news_id} 深度分析完成 | Tickers: {relate_tickers_list}")
        except Exception as e:
            logger.warning(f"内容摘要与翻译合并调用失败 ID {news_id}: {e}")
            title_cn = f"[翻译失败] {title}"
            summary_cn = f"AI 分析服务暂时不可用。原文摘要：\n{content[:500]}..."

    # 3. 结果保存到数据库
    try:
        update_translation(
            news_id, 
            title_cn, 
            summary_cn, 
            related_tickers=relate_tickers_list or None,
            significant=imp_level,
            significant_reason=imp_reason,
            sentiment_label=sent_label,
            sentiment_score=sent_score
        )
        status = "成功" if "[翻译失败]" not in title_cn else "标题失败"
        logger.info(f"保存翻译分析 ID {news_id} | 状态: {status} | Level: {imp_level} | Tickers: {relate_tickers_list}")
    except Exception as e:
        logger.error(f"保存分析结果到数据库失败 ID {news_id}: {e}")


def run_translation(model_name: str | None = None):
    """
    主翻译与分析管道执行函数。
    读取待分析新闻，多线程受控并发处理。
    """
    records = get_untranslated_news()
    if not records:
        logger.debug("没有待翻译的新闻")
        return

    MAX_TRANSLATE_PER_RUN = 10
    if len(records) > MAX_TRANSLATE_PER_RUN:
        logger.info(f"待翻译新闻较多 ({len(records)} 条)，本次仅处理前 {MAX_TRANSLATE_PER_RUN} 条，其余留待下次轮询...")
        records = records[:MAX_TRANSLATE_PER_RUN]

    logger.debug(f"待处理分析: {len(records)} 条")
    active_threads = []

    for idx, record in enumerate(records, 1):
        while len(active_threads) >= MAX_CONCURRENT:
            time.sleep(1)
            active_threads = [t for t in active_threads if t.is_alive()]

        # 智能抖动延迟，防止突发流量触发 API Rate Limit
        if idx % 10 == 0:
            time.sleep(random.uniform(2, 4))
        else:
            time.sleep(random.uniform(0.5, 1.2))

        thread = threading.Thread(
            target=_process_single,
            args=(record, model_name),
        )
        thread.start()
        active_threads.append(thread)

    for thread in active_threads:
        thread.join()

    if records:
        logger.info(f"本轮处理完成: {len(records)} 条")
