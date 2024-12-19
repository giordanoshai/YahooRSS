from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import fake_useragent

from selenium.common.exceptions import TimeoutException

def web_driver():
    try:
        user_agent = fake_useragent.UserAgent().random
        proxy = 'socks5://127.0.0.1:1080'
        chrome_options = Options()
        # chrome_options.add_argument('--headless')
        # chrome_options.add_argument('--disable-gpu')
        # chrome_options.add_argument('--no-sandbox')
        # chrome_options.add_argument('--disable-dev-shm-usage')
        # chrome_options.add_argument('--enable-unsafe-swiftshader')
        chrome_options.add_argument(f'--proxy-server={proxy}')
        chrome_options.add_argument('--ignore-certificate-errors')
        # chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        chrome_options.add_argument(f'--user-agent={user_agent}')
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error creating WebDriver: {e}")
        raise

driver = web_driver()
driver.get('https://finance.yahoo.com/')

def test_fun():
    try:
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='hero-right']")))
        print('页面加载完成')
        return True
    except TimeoutException as e:
        print(f"Timeout while waiting for element: {e}")
        return None

test_fun()