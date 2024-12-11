import re
import time
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from datetime import datetime
import fake_useragent
import random
from concurrent.futures import ThreadPoolExecutor
from azure_tranlsate import azure_translate_main
from dailylogger import DailyLogger
import settting as sts
import http.server
import socketserver
import threading



#github loggin key
#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
daily_logger = DailyLogger()
logger = daily_logger.get_logger()

current_date = datetime.now().strftime('%Y_%m_%d')
table_name = f'news_{current_date}'
MAX_THREADS = 4


def web_driver():
    user_agent = fake_useragent.UserAgent().random
    proxy = 'socks5://127.0.0.1:1080'
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--enable-unsafe-swiftshader')
    # chrome_options.add_argument(f'--proxy-server={proxy}')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    chrome_options.add_argument(f'--user-agent={user_agent}')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def set_content_null():
    # 连接到数据库
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()

    # 更新 content 长度小于 1 的数据为 NULL
    cursor.execute(f"""
    UPDATE {table_name}
    SET content = NULL
    WHERE LENGTH(content) < 3
    """)

    # 提交更改并关闭连接
    conn.commit()
    conn.close()

def get_title():
    # 打开页面
    logger.info('开始获取新闻标题和链接...')
    driver = web_driver()
    driver.get('https://finance.yahoo.com/')
    time.sleep(random.uniform(2, 5))

    # 获取页面的 HTML
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    # 使用正则表达式查找包含 'hero' 和 'lead' 的类名
    hero_divs = soup.find_all('div', class_=re.compile('.*(hero-lead|hero-second-col|hero-latest-news).*'))

    # 提取新闻标题和链接
    news_items = []
    for div in hero_divs:
        links = div.find_all('a')
        for link in links:
            title = link.get_text().strip()  # 获取新闻标题
            href = link.get('href')  # 获取链接

            if href and (href.startswith('http') or href.startswith('https')) and title != '':  # 只保留完整链接
                # 添加到新闻列表
                news_items.append({'title': title, 'link': href, 'date': int(time.time())})  # 当前时间戳

    # 关闭浏览器
    driver.quit()


    # 创建 SQLite 数据库连接
    db_file = 'yahoonews.db'
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # 创建当天的表（如果不存在），url 设置为主键
    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        date INTEGER NOT NULL,
        content TEXT,
        title_cn TEXT,
        content_cn TEXT,
        rss INTEGER DEFAULT 0
    )
    ''')

    # 插入新闻数据到当天的表，url 添加唯一约束
    inserted_count = 0
    for item in news_items:
        try:
            cursor.execute(f'''
            INSERT INTO {table_name} (title, url, date) VALUES (?, ?, ?)
            ''', (item['title'], item['link'], item['date']))
            inserted_count += 1
            logger.info(f"URL successfully stored: {item['link']}")
        except sqlite3.IntegrityError:
            # 如果 URL 已经存在，跳过该条记录
            pass
    
    # 提交事务并关闭连接
    conn.commit()
    conn.close()
    
    logger.info(f"{inserted_count}items successfully stored in the table {table_name}.")
    return True



def get_urls_fromDB():
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    SELECT url FROM {table_name} WHERE content IS NULL
    """
    cursor.execute(query)
    urls = cursor.fetchall()
    urls_to_fetch = [url[0] for url in urls]
    conn.close()
    return urls_to_fetch

def store_content(url, content):
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    UPDATE {table_name} SET content = ? WHERE url = ?
    """
    cursor.execute(query, (content, url))
    conn.commit()
    conn.close()

def fetch_content(url, driver):
    driver.get(url)
    time.sleep(random.uniform(3, 5))  # Random delay to mimic human browsing
    elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'body-wrap')]//p")
    content = "\n".join([element.text for element in elements])
    return content

def process_url(url):
    driver = web_driver()
    try:
        content = fetch_content(url, driver)
        store_content(url, content)
    except Exception as e:
        logger.error(f"Error fetching content for {url}: {e}")
    finally:
        driver.quit()

"""def main():
    try:
        # 获取标题，这里是一个阻塞操作，完成后才会继续执行
        get_title_result = get_title()
        
        if get_title_result:
            urls_to_fetch = get_urls_fromDB()
            threads = []
            active_threads = 0
            
            for url in urls_to_fetch:
                while active_threads >= MAX_THREADS:
                    # 等待一个线程完成
                    for thread in threads:
                        if not thread.is_alive():
                            active_threads -= 1
                            threads.remove(thread)
                    time.sleep(1)  # 等待并再次检查

                # 启动一个新线程处理 URL
                thread = threading.Thread(target=process_url, args=(url,))
                threads.append(thread)
                thread.start()
                active_threads += 1
                time.sleep(random.uniform(2, 5))  # 控制间隔时间

            # 等待所有线程完成
            for thread in threads:
                thread.join()

            logging.info("All URLs processed successfully.")
        else:
            logging.error("Failed to get the title.")
    
    except Exception as e:
        logging.error(f"Error in main function: {e}")"""

"""def main(): #有多少个任务就启动多少个进程
    try:
        # 获取标题，这里是一个阻塞操作，完成后才会继续执行
        get_title_result = get_title()
        
        if get_title_result:
            set_content_null()
            urls_to_fetch = get_urls_fromDB()
            threads = []
            
            for url in urls_to_fetch:
                time.sleep(random.uniform(2, 5))
                # 为每个 URL 启动一个线程进行处理
                thread = threading.Thread(target=process_url, args=(url,))
                threads.append(thread)
                thread.start()

            # 等待所有线程完成
            for thread in threads:
                thread.join()

            logging.info("All URLs processed successfully.")
        else:
            logging.error("Failed to get the title.")
    
    except Exception as e:
        logging.error(f"Error in main function: {e}")"""


def http_server():
    try:
        Handler = http.server.SimpleHTTPRequestHandler
        # 绑定到本地回环接口
        with socketserver.TCPServer(("192.168.100.39", 52491), Handler) as httpd:
            logger.info(f"Serving HTTP on port 52491 (http://localhost:52491/)")
            httpd.serve_forever()
    except OSError as e:
        logger.error(f"Failed to start server: {e}")
    except ConnectionAbortedError as e:
        logger.error(f"Connection was aborted: {e}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")


def main():
    
    try:
        get_title_reslut = get_title()
        if get_title_reslut:
            urls_to_fetch = get_urls_fromDB()
            with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                executor.map(process_url, urls_to_fetch)
            logger.info('ALL URLS processed successfully.')
            #翻译表中数据
            azure_translate_main(table_name)
        else:
            logger.error('Failed to get the title.')

    except Exception as e:
        logger.error(f'Error in main function: {e}')



def wait_random_time():
    random_min = random.randint(10,15)
    wait_time = random_min*60
    time.sleep(wait_time)

#检测
def execute_task():
    if sts.is_done:
        sts.is_done = False
        main()
    else:
        logger.warning('前序进程未结束，等待中...')

def start_task():
    # http_thread = threading.Thread(target=http_server)
    # http_thread.start()
    while True:
        wait_random_time()
        execute_task()
        


if __name__ == "__main__":
    start_task()




