from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import time


proxy = 'http://127.0.0.1:1081'
chrome_options = Options()
chrome_options.add_argument(f'--proxy-server={proxy}')

# 启动浏览器
driver = webdriver.Chrome(options=chrome_options)


driver.get("https://finance.yahoo.com/news/us-agencies-brief-senators-chinese-144658826.html")


# 获取动态加载的内容
elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'body-wrap')]//p")
for element in elements:
    print(element.text)

driver.quit()

