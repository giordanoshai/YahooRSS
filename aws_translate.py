import boto3
import sqlite3
from datetime import datetime
import threading
import time

aws_access_key_id = 'AKIAYXWBN2CTI64ZBVRA'
aws_secret_access_key ='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'
region = 'us-east-1'



current_date = datetime.now().strftime('%Y_%m_%d')
# table_name = f'news_{current_date}'
table_name = 'news_2024_12_05'

translate = boto3.client(
    service_name='translate',
    region_name=region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

s3_client = boto3.client('s3')
s3_bucket_name =  'tt-translate-s3'


def get_ids_to_process():
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    SELECT id, title, content FROM {table_name} WHERE content IS NOT NULL AND title_cn IS NULL AND content_cn IS NULL
    """
    cursor.execute(query)
    ids = cursor.fetchall()
    conn.close()
    return ids


def translate_batch(texts):
    translated_texts = []
    for text in texts:
        try:
            response = translate.translate_text(
                Text=text,
                SourceLanguageCode='en',
                TargetLanguageCode='zh',
            )
            translated_texts.append(response['TranslatedText'])
        except Exception as e:
            print(f"Error in translation: {e}")
            translated_texts.append("")  # 失败时返回空字符串
        time.sleep(5)  # 为了避免请求过快，适当延时
    return translated_texts


def save_translate_result(ids, title_cn, content_cn):
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    UPDATE {table_name} SET title_cn = ?, content_cn = ? WHERE id = ?
    """
    cursor.execute(query, (title_cn, content_cn, ids))
    conn.commit()
    conn.close()


def translation_task(ids, title, content):
    translated_texts = translate_batch([title, content])

    if translated_texts:
        title_cn, content_cn = translated_texts[0], translated_texts[1]
        # 保存翻译结果到数据库
        save_translate_result(ids, title_cn, content_cn)
        print(f"Successfully translated and stored for URL: {ids}")
    else:
        print(f"Failed to translate for URL: {ids}")



def main():
    urls_to_process = get_ids_to_process()
    threads = []

    # 启动线程处理每个 URL
    for id, title, content in urls_to_process:
        thread = threading.Thread(target=translation_task, args=(id, title, content))
        threads.append(thread)
        thread.start()

    # 等待所有线程完成
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()