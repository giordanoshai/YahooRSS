import sqlite3
import os
import time
from xml.etree.ElementTree import Element, SubElement, ElementTree,ParseError
from datetime import datetime
from pytz import timezone
from dateutil import parser
from dateutil.tz import gettz
from dailylogger import DailyLogger
import re



daily_logger = DailyLogger()
logger = daily_logger.get_logger()

xml_path = 'rss.xml'
db_path='yahoonews.db'
# table_name='news_2024_12_05'


def create_new_rss_root():
    """创建一个新的RSS结构，并返回根元素"""
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    
    title = SubElement(channel, "title")
    title.text = "雅虎财经新闻"
    link = SubElement(channel, "link")
    link.text = "http://box.ggwp.cn:52491/rss.xml"
    description = SubElement(channel, "description")
    description.text = "Yahoo finance news"
    
    return rss



def get_rows(table_name):
    """从数据库中获取未添加到RSS的条目"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, title_cn, content_cn, url, date FROM {table_name} WHERE rss = 0")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_rss_status(ids,table_name):
    """更新数据库中条目的rss状态为1"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executemany(f"UPDATE {table_name} SET rss = 1 WHERE id = ? AND title_cn IS NOT NULL", [(id,) for id in ids])
    conn.commit()
    conn.close()

def clear_rss(channel):
    current_time = time.time()
    seven_days_ago = current_time - 7 * 24 * 60 * 60  # 7 天前的时间戳

    # 定义时区映射
    tzinfos = {
        "EST": gettz("America/New_York"),
        "EDT": gettz("America/New_York"),
    }

    items_to_remove = []
    for item in channel.findall('item'):
        pub_date_node = item.find('pubDate')
        if pub_date_node is None or not pub_date_node.text:
            logger.warning("Missing or empty pubDate, skipping item.")
            continue
        try:
            # 使用 tzinfos 解析包含时区缩写的日期字符串
            pub_datetime = parser.parse(pub_date_node.text, tzinfos=tzinfos)
            pub_timestamp = pub_datetime.timestamp()  # 转换为时间戳
            if pub_timestamp < seven_days_ago:
                items_to_remove.append(item)
        except Exception as e:
            logger.error(f"Error parsing pubDate: {pub_date_node.text}, error: {e}")
            continue

    for item in items_to_remove:
        channel.remove(item)
    logger.info(f'{len(items_to_remove)}条rss被移除')


def format_content(content):
    # 使用正则表达式按句号、感叹号和问号分割文本
    sentences = re.split(r'(?<=[。！？])', content)
    # 去除空白并格式化为 HTML 段落
    html_paragraphs = [f"<p>{sentence.strip()}</p>" for sentence in sentences if sentence.strip()]
    # 将所有段落合并为一个字符串
    return ''.join(html_paragraphs)

def convert_to_new_york_time(timestamp):
    """将UTC时间戳转换为美国纽约时间（Eastern Time，自动处理EST和EDT）"""
    utc_time = datetime.utcfromtimestamp(timestamp)
    utc_time = utc_time.replace(tzinfo=timezone('UTC'))
    
    # 转换为纽约时间
    new_york_time = utc_time.astimezone(timezone('America/New_York'))
    
    # 格式化为所需的字符串格式
    return new_york_time.strftime("%a, %d %b %Y %H:%M:%S %Z")


def add_to_rss(rows,rss_path):
    """将条目添加到 RSS 文件"""
    if os.path.exists(rss_path) and os.path.getsize(rss_path) > 0:
        try:
            tree = ElementTree(file=xml_path)
            root = tree.getroot()
            channel = root.find('channel')
        except ParseError:
            logger.error(f"Error parsing {xml_path}. The file might be corrupted.")
            # 如果解析失败，可以选择重新创建 RSS 文件
            root = create_new_rss_root()
            channel = root.find('channel')
            tree = ElementTree(root) 
    else:
         root = create_new_rss_root()
         channel = root.find('channel')
         tree = ElementTree(root) 

    #清楚7天前的rss
    clear_rss(channel)
    
    
    # 用于记录成功添加的条目 ID
    added_ids = []
    
    for row in rows:
        id, title, content, url, pub_date_timestamp = row
        
        # 创建新的 <item> 元素
        item = SubElement(channel, "item")
        item_title = SubElement(item, "title")
        item_title.text = title
        item_description = SubElement(item, "description")
        item_description.text = format_content(content)
        item_link = SubElement(item, "link")
        item_link.text = url  # URL
        item_guid = SubElement(item, "guid")
        item_guid.text = url  # 使用 URL 作为 guid
        item_pubDate = SubElement(item, "pubDate")
        item_pubDate.text = convert_to_new_york_time(pub_date_timestamp)# 转换为日期格式
        
        # 添加成功后记录 ID
        added_ids.append(id)
    
    # 写入更新后的 RSS 文件
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return added_ids


# 主流程
def make_rss(table_name):
    rows = get_rows(table_name)
    if rows:
        added_ids = add_to_rss(rows,xml_path)
        if added_ids:
            update_rss_status(added_ids,table_name)
            logger.info(f'{len(added_ids)}条新闻被条件到RSS')