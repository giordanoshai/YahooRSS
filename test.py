import sqlite3
from datetime import datetime

current_date = datetime.now().strftime('%Y_%m_%d')
table_name = f'news_{current_date}'

def set_content_null():
    # 连接到数据库
    conn = sqlite3.connect('yahoonews.db')
    cursor = conn.cursor()

    # 更新 content 长度小于 1 的数据为 NULL
    cursor.execute(f"""
    UPDATE {table_name}
    SET content = NULL
    WHERE LENGTH(content) < 4
    """)

    # 提交更改并关闭连接
    conn.commit()
    conn.close()



# 调用函数
set_content_null()
