import time
import sqlite3
from bs4 import BeautifulSoup
from datetime import datetime
from fake_useragent import UserAgent
import random
from dailylogger import DailyLogger
import requests
import re




# 初始化日志记录
daily_logger = DailyLogger()
logger = daily_logger.get_logger()
proxies = {
    "http": "http://127.0.0.1:1081",
    "https": "http://127.0.0.1:1081"
}


def get_title():
    # 定义全局变量 table_name
    global table_name
    current_date = datetime.now().strftime('%Y_%m_%d')
    table_name = f'news_{current_date}'
    
    logger.info('开始获取新闻标题和链接...')
    
    try:
        # 使用 fake_useragent 设置随机 User-Agent
        ua = UserAgent()
        headers = {'User-Agent': ua.random}
        
        # 请求 Yahoo 财经页面
        url = 'https://finance.yahoo.com/'
        response = requests.get(url, headers=headers,proxies=proxies)
        
        # 检查请求是否成功
        if response.status_code != 200:
            logger.error(f"请求失败，状态码: {response.status_code}")
            return None
        
        # 解析页面 HTML
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # 查找包含 'hero-lead' 或相关类名的 div 元素
        hero_divs = soup.find_all('div', class_=re.compile('.*(hero-lead|hero-second-col|hero-latest-news).*'))

        # 提取新闻标题和链接
        news_items = []
        for div in hero_divs:
            links = div.find_all('a')
            for link in links:
                title = link.get_text().strip()
                href = link.get('href')
                if href and (href.startswith('http') or href.startswith('https')) and title:
                    news_items.append({'title': title, 'link': href, 'date': int(time.time())})
        logger.info(news_items)
        logger.info(f"成功获取 {len(news_items)} 条新闻")
        return news_items

    except Exception as e:
        logger.error(f"获取新闻时发生错误: {e}")
        return None


def try_login():
    url = "https://finance.yahoo.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
        "Referer": "https://finance.yahoo.com/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    login_url = "https://login.yahoo.com/"
    session = requests.Session()
    session.headers.update(headers)
    session.post(login_url, data={"username": "giordanoshai", "password": "pass"})