from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 启动 WebDriver
chrome_options = Options()
proxy = 'socks5://127.0.0.1:1080'
chrome_options.add_argument(f'--proxy-server={proxy}')
driver = webdriver.Chrome(options=chrome_options)

# 打开目标页面
url = "https://www.yahoo.com/news/house-may-vote-temporary-fix-142146044.html"  # 或者 "https://www.yahoo.com"
driver.get(url)

try:
    # 获取当前页面的URL前缀
    current_url = driver.current_url

    if current_url.startswith("https://finance.yahoo.com"):
        # 如果 URL 前缀为 finance.yahoo.com，抓取 body-wrap 下的 p 元素
        print("当前为 finance.yahoo.com，开始抓取 body-wrap 中的 p 元素...")
        elements = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class, 'body-wrap')]//p"))
        )
        for element in elements:
            print("抓取到的文本:", element.text)

    elif current_url.startswith("https://www.yahoo.com"):
        # 如果 URL 前缀为 www.yahoo.com，抓取 grid grid-cols-article-mobile 等类名的 div 元素
        print("当前为 www.yahoo.com，开始抓取动态 grid 元素...")
        elements = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//div[contains(@class, 'grid') and contains(@class, 'grid-cols-article-mobile') and contains(@class, 'md:max-w-[750px]') and contains(@class, 'md:grid-cols-article')]")
            )
        )
        for element in elements:
            print("抓取到的文本:", element.text)

    else:
        print("未匹配到任何已知 URL 前缀，跳过抓取操作。")

except Exception as e:
    print("抓取过程中出错:", e)

finally:
    # 关闭浏览器
    driver.quit()
