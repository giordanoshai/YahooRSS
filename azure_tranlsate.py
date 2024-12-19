import requests, uuid
import sqlite3
import time
import threading
from make_rss import make_rss
from dailylogger import DailyLogger
import settting as sts

daily_logger = DailyLogger()
logger = daily_logger.get_logger()


# Add your key and endpoint
key = "1GWQDhHEki1leSzVT6j4sN2bhI8hKWkqjvwfSckZltCrlcjMLjWPJQQJ99ALAC4f1cMXJ3w3AAAbACOGLMg0"
constructed_url = 'https://api.cognitive.microsofttranslator.com/translate'
params = {
    "api-version": '3.0',
    "from": 'en',
    'to': ['zh']
}

headers = {
    'Ocp-Apim-Subscription-Key': key,
    'Ocp-Apim-Subscription-Region': 'westus',
    'Content-type': 'application/json',
    'X-ClientTraceId': str(uuid.uuid4())
}

def get_ids_to_process(table_name):
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    SELECT id, title, content FROM {table_name} WHERE content IS NOT NULL AND title_cn IS NULL AND content_cn IS NULL
    """
    cursor.execute(query)
    ids = cursor.fetchall()
    conn.close()
    # print(ids)
    return ids

def save_translate_result(ids, title_cn, content_cn,table_name):
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    UPDATE {table_name} SET title_cn = ?, content_cn = ? WHERE id = ?
    """
    cursor.execute(query, (title_cn, content_cn, ids))
    conn.commit()
    conn.close()

def azure_translate(title, content):
    body = [
        {'text': title},
        {'text': content}
    ]
    
    try:
        # 发起 POST 请求，假设 constructed_url, params 和 headers 已经定义好
        request = requests.post(constructed_url, params=params, headers=headers, json=body)
        
        # 检查响应状态码是否为 200，表示请求成功
        if request.status_code == 200:
            try:
                response = request.json()  # 尝试解析 JSON 响应
                return response
            except ValueError as e:
                logger.error(f"Error parsing response as JSON: {e}")
                return None
        else:
            logger.error(f"Request failed with status code {request.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during request: {e}")
        return None

def translation_task(ids, title, content,table_name):
    translated_texts = azure_translate(title, content)
    
    if translated_texts:
        try:
            # 确保 translated_texts 结构正确
            title_cn = translated_texts[0]['translations'][0]['text']
            content_cn = translated_texts[1]['translations'][0]['text']
            
            # 调用保存函数（假设该函数已经定义）
            save_translate_result(ids, title_cn, content_cn,table_name)
        except (IndexError, KeyError) as e:
            logger.warning(f"Error processing translated data for ID {ids}: {e}")
    else:
        logger.warning(f"Failed to translate for ID: {ids}")

def azure_translate_main(table_name):
    ids_to_process = get_ids_to_process(table_name)
    threads = []

    for id, title, content in ids_to_process:
        time.sleep(5)
        thread = threading.Thread(target=translation_task, args=(id, title, content,table_name))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()
    logger.info(f'{len(ids_to_process)}条新闻被翻译')
    #生成rss源
    make_rss(table_name)
    sts.is_done = True
    



# azure_translate_main('news_2024_12_19')