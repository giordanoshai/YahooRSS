"""
core/logger.py - 日志模块

提供按日轮转的 Logger 工厂函数与全局默认 logger 实例。
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

# 日志目录（项目根目录下的 logs/）
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


def get_logger(name: str = "yahoorss") -> logging.Logger:
    """
    获取按日轮转的 Logger。

    Args:
        name: Logger 名称，不同名称对应不同日志文件

    Returns:
        配置好的 Logger 实例
    """
    _logger = logging.getLogger(name)

    # 防止重复添加 handler
    if _logger.hasHandlers():
        return _logger

    _logger.setLevel(logging.DEBUG)

    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)

    # 按日轮转的文件 handler
    log_file = os.path.join(LOG_DIR, name)
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d.log"

    # 格式
    formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s")
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)

    return _logger


# 默认全局 logger
logger = get_logger("yahoorss")
