import boto3
import sqlite3
import threading
import random
from datetime import datetime
import time


session = boto3.Session(
    aws_access_key_id = 'AKIAYXWBN2CTI64ZBVRA',
    aws_secret_access_key ='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',
    region_name = 'us-east-1'
    )

# 初始化 AWS 客户端
s3_client = session.client('s3')
translate_client = session.client(service_name='translate')

# 设置 S3 存储桶名称
S3_BUCKET_NAME = 'tt-translate-s3'

# 获取今天的日期
current_date = datetime.now().strftime('%Y_%m_%d')
# table_name = f'news_{current_date}'
table_name = 'news_2024_12_05'

# 获取需要翻译的 URL 内容
def get_ids_to_process():
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    SELECT id, title, content FROM {table_name} WHERE title_cn IS NULL AND content_cn IS NULL
    """
    cursor.execute(query)
    ids = cursor.fetchall()
    conn.close()
    return ids

# 上传文本到 S3
def upload_to_s3(text, file_name):
    try:
        # 将文本上传到 S3
        s3_key = f"new_list/2024_12_05/{file_name}"
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=s3_key, Body=text)
        print(f"Uploaded {s3_key} to S3")
        return f"s3://{S3_BUCKET_NAME}/{s3_key}"
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return None

# 批量翻译函数，通过 S3 上传的内容进行翻译
def start_translation_job(s3_folder_uri):
    try:
        data_access_role_arn = 'arn:aws:iam::600627335334:role/yahoonews_translate_role'
        response = translate_client.start_text_translation_job(
                InputDataConfig={
                    'S3Uri': s3_folder_uri,  # 确保这里是文件夹路径
                    'ContentType': 'text/plain'
                },
                OutputDataConfig={
                    'S3Uri': f's3://{S3_BUCKET_NAME}/translate_output/2024_12_05'
                },
                SourceLanguageCode='en',
                TargetLanguageCodes=['zh'],
                DataAccessRoleArn=data_access_role_arn,
                JobName=f'job{int(time.time())}',
            )
        job_id = response.get('JobId', None)
        if job_id:
            print(f"Started translation job with JobId: {job_id}")
            return job_id
        else:
            print("Failed to get job ID from response.")
            return None
    except Exception as e:
        print(f"Error starting translation job: {e}")
        return None

def check_translation_status(job_id):
    try:
        response = translate_client.describe_text_translation_job(JobId=job_id)
        status = response['TextTranslationJob']['JobStatus']
        print(f"Job status: {status}")
        return status
    except Exception as e:
        print(f"Error checking translation job status: {e}")
        return None

# 获取翻译结果
def get_translation_results(job_id):
    try:
        response = translate_client.describe_text_translation_job(JobId=job_id)
        status = response['TextTranslationJob']['JobStatus']
        
        if status == 'COMPLETED':
            s3_output_uri = response['TextTranslationJob']['OutputDataConfig']['S3Uri']
            print(f"Translation completed. Results stored at: {s3_output_uri}")
            return s3_output_uri
        elif status == 'FAILED':
            print(f"Translation job {job_id} failed.")
            return None
        else:
            print(f"Translation job {job_id} is still in progress.")
            return None
    except Exception as e:
        print(f"Error getting translation results: {e}")
        return None

# 从 S3 获取翻译后的内容
def get_s3_file_content(s3_uri):
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_uri.split('s3://')[1])
        return response['Body'].read().decode('utf-8')
    except Exception as e:
        print(f"Error reading from S3: {e}")
        return None


# 将翻译结果保存到数据库
def store_translated_content_in_db(ids, title_cn, content_cn):
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()
    query = f"""
    UPDATE {table_name} SET title_cn = ?, content_cn = ? WHERE id = ?
    """
    cursor.execute(query, (title_cn, content_cn, ids))
    conn.commit()
    conn.close()

# 处理翻译任务
def process_translation_task(id, title, content):
    # 将标题和内容上传到 S3
    upload_to_s3(title, f"{id}_title.txt")
    upload_to_s3(content, f"{id}_content.txt")

    # 指定包含这些文件的 S3 文件夹路径
    s3_folder_uri = 's3://tt-translate-s3/new_list/2024_12_05/'
    
    # 提交异步翻译作业
    job_id = start_translation_job(s3_folder_uri)
    
    # 检查作业状态并处理结果（保持原逻辑）
    if job_id:
        while True:
            status = check_translation_status(job_id)
            if status == 'COMPLETED':
                translation_results_uri = get_translation_results(job_id)
                if translation_results_uri:
                    # 假设翻译结果存放在 S3 上，可以从 S3 下载并处理
                    title_cn = get_s3_file_content(translation_results_uri + "title_translated.txt")
                    content_cn = get_s3_file_content(translation_results_uri + "content_translated.txt")
                    store_translated_content_in_db(id, title_cn, content_cn)
                break
            elif status == 'FAILED':
                print(f"Translation job {job_id} failed.")
                break
            else:
                print("Waiting for translation to complete...")
                time.sleep(30)  # 每30秒检查一次状态
# 主函数
def main():
    ids_to_process = get_ids_to_process()
    threads = []

    # 启动线程处理每个 URL
    for id, title, content in ids_to_process:
        thread = threading.Thread(target=process_translation_task, args=(id, title, content))
        threads.append(thread)
        thread.start()

    # 等待所有线程完成
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()