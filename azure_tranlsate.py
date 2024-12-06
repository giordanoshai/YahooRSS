import requests, uuid, json
import sqlite3
from datetime import datetime
import time
import threading

# Add your key and endpoint
key = "6zpizYwFrlpALBqF0GWL8v8HWZOJDXF7NW40XBL5chQvgIF9PH1VJQQJ99ALACYeBjFXJ3w3AAAbACOGRD01"
constructed_url = 'https://api.cognitive.microsofttranslator.com/translate'
params = {
    "api-version": '3.0',
    "from": 'en',
    'to': ['zh']
}

headers = {
    'Ocp-Apim-Subscription-Key': key,
    'Ocp-Apim-Subscription-Region': 'eastus',
    'Content-type': 'application/json',
    'X-ClientTraceId': str(uuid.uuid4())
}

current_date = datetime.now().strftime('%Y_%m_%d')
# table_name = f'news_{current_date}'
table_name = 'news_2024_12_05'

def get_ids_to_process():
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

def save_translate_result(ids, title_cn, content_cn):
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
                print(f"Error parsing response as JSON: {e}")
                return None
        else:
            print(f"Request failed with status code {request.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Error during request: {e}")
        return None

def translation_task(ids, title, content):
    translated_texts = azure_translate(title, content)
    
    if translated_texts:
        try:
            # 确保 translated_texts 结构正确
            title_cn = translated_texts[0]['translations'][0]['text']
            content_cn = translated_texts[1]['translations'][0]['text']
            
            # 调用保存函数（假设该函数已经定义）
            save_translate_result(ids, title_cn, content_cn)
            print(f"Successfully translated and stored for ID : {ids}")
        except (IndexError, KeyError) as e:
            print(f"Error processing translated data for ID {ids}: {e}")
    else:
        print(f"Failed to translate for ID: {ids}")

def main():
    ids_to_process = get_ids_to_process()
    threads = []

    for id, title, content in ids_to_process:
        time.sleep(5)
        thread = threading.Thread(target=translation_task, args=(id, title, content))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()
        

if __name__ == "__main__":
    main()
