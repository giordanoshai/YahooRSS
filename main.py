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
import logging
import concurrent.futures

logging.basicConfig(level=logging.INFO)



current_date = datetime.now().strftime('%Y_%m_%d')
table_name = f'news_{current_date}'



def web_driver():
    user_agent = fake_useragent.UserAgent().random
    proxy = 'http://127.0.0.1:1081'
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--enable-unsafe-swiftshader')
    chrome_options.add_argument(f'--proxy-server={proxy}')
    chrome_options.add_argument(f'--user-agent={user_agent}')
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def get_title():
    # 打开页面
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
        content_cn TEXT
    )
    ''')

    # 插入新闻数据到当天的表，url 添加唯一约束
    for item in news_items:
        try:
            cursor.execute(f'''
            INSERT INTO {table_name} (title, url, date) VALUES (?, ?, ?)
            ''', (item['title'], item['link'], item['date']))
        except sqlite3.IntegrityError:
            # 如果 URL 已经存在，跳过该条记录
            print(f"Duplicate URL skipped: {item['link']}")
    
    # 提交事务并关闭连接
    conn.commit()
    conn.close()
    
    print(f"News {len(news_items)}items successfully stored in the table {table_name}.")
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
    time.sleep(random.uniform(3, 15))  # Random delay to mimic human browsing
    elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'body-wrap')]//p")
    content = "\n".join([element.text for element in elements])
    return content

def process_url(url):
    driver = web_driver()
    try:
        content = fetch_content(url, driver)
        store_content(url, content)
    except Exception as e:
        print(f"Error fetching content for {url}: {e}")
    finally:
        driver.quit()

def main():
    try:
        # 获取标题，这里是一个阻塞操作，完成后才会继续执行
        get_title_result = get_title()
        
        if get_title_result:
            urls_to_fetch = get_urls_fromDB()
            
            # 限制同时最多运行 3 个线程
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                
                for url in urls_to_fetch:
                    # 提交 URL 处理任务给线程池
                    futures.append(executor.submit(process_url, url))
                    time.sleep(random.uniform(2, 5))  # 控制间隔时间
                
                # 等待所有线程完成
                for future in concurrent.futures.as_completed(futures):
                    future.result()  # 获取结果，抛出异常（如果有的话）

            logging.info("All URLs processed successfully.")
        else:
            logging.error("Failed to get the title.")
    
    except Exception as e:
        logging.error(f"Error in main function: {e}")

if __name__ == "__main__":
    main()

# get_title()


