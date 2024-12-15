import sqlite3
from datetime import datetime

table_name = None


def get_table_name():
    global table_name
    current_date = datetime.now().strftime('%Y_%m_%d')
    table_name = f'news_{current_date}'
    return table_name



def test_table_name():
    get_table_name()
    print(table_name)


test_table_name()