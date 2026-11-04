"""
core/llm_client.py - 多 LLM 适配器与调用引擎

基于 OpenAI 兼容协议工厂模式，支持 DashScope / 阿里云通义千问、DeepSeek、
OpenRouter (Nemotron 120B / 免费模型) 等多模型无缝切换。
自动处理网络代理、请求重试与 JSON 格式清洗。
"""
import os
import re
import time
import random
import httpx
from openai import OpenAI
from core.config import settings
from core.logger import logger

# ============================================================
# 模型注册表
# ============================================================
MODELS: dict[str, dict] = {
    # 阿里云 / DashScope 系列
    "qwen3.5-flash": {
        "api_key": settings.QWEN_API_KEY,
        "base_url": settings.QWEN_BASE_URL,
        "model": "qwen3.5-flash",
        "extra_body": {"enable_thinking": False},
        "use_proxy": False,
    },
    "qwen-flash": {
        "api_key": settings.QWEN_API_KEY,
        "base_url": settings.QWEN_BASE_URL,
        "model": "qwen-flash",
        "extra_body": {"enable_thinking": False},
        "use_proxy": False,
    },
    "qwen3-max": {
        "api_key": settings.QWEN_API_KEY,
        "base_url": settings.QWEN_BASE_URL,
        "model": "qwen-max",
        "extra_body": {"enable_thinking": True},
        "use_proxy": False,
    },
    "deepseek-v4-flash": {
        "api_key": settings.QWEN_API_KEY,
        "base_url": settings.QWEN_BASE_URL,
        "model": "deepseek-v4-flash-0731",
        "extra_body": {"enable_thinking": False},
        "use_proxy": False,
    },
    # OpenRouter 系列（每日总结买方策略推荐）
    "nvda-nemotron-120b": {
        "api_key": settings.OPENROUTER_API_KEY,
        "base_url": settings.OPENROUTER_BASE_URL,
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "extra_body": {},
        "use_proxy": True,
    },
    "nemotron-3.5-lightning": {
        "api_key": settings.OPENROUTER_API_KEY,
        "base_url": settings.OPENROUTER_BASE_URL,
        "model": "nvidia/nemotron-3.5-lightning:free",
        "extra_body": {},
        "use_proxy": True,
    },
}

# 客户端连接池缓存
_clients: dict[str, OpenAI] = {}


def _build_client(config: dict) -> OpenAI:
    """根据配置创建 OpenAI 客户端（支持可选网络代理）"""
    api_key = config.get("api_key") or "dummy"
    base_url = config.get("base_url")

    http_client = None
    if config.get("use_proxy") and settings.HTTP_PROXY:
        try:
            http_client = httpx.Client(
                proxy=settings.HTTP_PROXY,
                timeout=60.0,
            )
        except Exception as e:
            logger.warning(f"创建代理 HTTP 客户端失败: {e}，将使用直连")

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=60,
    )


def _get_client(model_name: str) -> tuple[OpenAI, dict]:
    """获取或初始化指定模型的 OpenAI 客户端"""
    if model_name not in MODELS:
        # 如果未显式在字典中注册，尝试以默认配置构建通用客户端
        logger.debug(f"模型 {model_name} 未在固定映射表中，使用通用 OpenRouter/Qwen 配置")
        config = {
            "api_key": settings.OPENROUTER_API_KEY or settings.QWEN_API_KEY,
            "base_url": settings.OPENROUTER_BASE_URL if settings.OPENROUTER_API_KEY else settings.QWEN_BASE_URL,
            "model": model_name,
            "extra_body": {},
            "use_proxy": bool(settings.HTTP_PROXY),
        }
        MODELS[model_name] = config

    config = MODELS[model_name]

    if model_name not in _clients:
        _clients[model_name] = _build_client(config)

    return _clients[model_name], config


def chat(
    messages: list[dict],
    model_name: str | None = None,
    temperature: float = 0.5,
    top_p: float = 0.9,
    timeout: int = 45,
    max_retries: int = 3,
) -> str:
    """
    统一大模型调用接口。

    Args:
        messages: 遵循 OpenAI 格式的消息列表
        model_name: 模型别名或标准 ID，None 时使用 DEFAULT_LLM
        temperature: 采样温度
        top_p: 核采样比例
        timeout: 超时阈值（秒）
        max_retries: 失败重试次数

    Returns:
        AI 生成的文本内容
    """
    model_name = model_name or settings.DEFAULT_LLM
    client, config = _get_client(model_name)

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=messages,
                extra_body=config.get("extra_body", {}),
                temperature=temperature,
                top_p=top_p,
                timeout=timeout,
            )
            content = response.choices[0].message.content or ""
            return content.strip()

        except Exception as e:
            last_err = e
            logger.warning(f"LLM [{model_name}] 调用失败 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                time.sleep(random.uniform(1.5, 3.5))

    logger.error(f"LLM [{model_name}] 达到最大重试次数仍失败: {last_err}")
    raise last_err
