import logging
import os
from logging.handlers import TimedRotatingFileHandler

class DailyLogger:
    def __init__(self, log_directory='logs', logger_name='daily_logger'):
        """
        初始化日志类，支持每天自动创建新的日志文件。
        :param log_directory: 日志文件存储的目录
        :param logger_name: 日志记录器的名称
        """
        self.log_directory = log_directory
        self.logger_name = logger_name
        self.logger = None
        self._setup_logger()

    def _setup_logger(self):
        """设置日志记录器"""
        # 确保日志目录存在
        if not os.path.exists(self.log_directory):
            os.makedirs(self.log_directory)

        # 日志文件路径（基础文件名）
        log_filename = os.path.join(self.log_directory, self.logger_name)

        # 创建日志记录器
        self.logger = logging.getLogger(self.logger_name)

        # 防止重复添加处理器（避免多次调用时重复写入）
        if not self.logger.hasHandlers():
            self.logger.setLevel(logging.DEBUG)

            # 创建按时间分割的处理器，每天午夜创建新文件
            handler = TimedRotatingFileHandler(log_filename, when='midnight', interval=1, backupCount=7,encoding='utf-8')
            handler.suffix = "%Y-%m-%d.log"  # 设置日志文件名后缀格式

            # 设置日志格式
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)

            # 将处理器添加到记录器中
            self.logger.addHandler(handler)

    def get_logger(self):
        """获取日志记录器实例"""
        return self.logger