import sqlite3


conn = sqlite3.connect('yahoonews.db')
cursor = conn.cursor()
quere = f"UPDATE news_2024_12_05 SET rss = 0 WHERE rss = 1"
cursor.execute(quere)
conn.commit()
conn.close()

