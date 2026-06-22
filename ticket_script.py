# coding: utf-8
import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from time import sleep, time
from pickle import dump, load
from selenium import webdriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
COOKIE_PATH = PROJECT_ROOT / "cookies.pkl"
PRE_SALE_KEYWORDS = ("即将开抢", "即将开售", "暂未开售", "未开售", "开售提醒", "预约", "预售")
SOLD_OUT_KEYWORDS = ("缺货", "售罄", "已售罄", "无票", "票已售完", "提交缺货登记")
PRE_SALE_REFRESH_SECONDS = 0.6
SOLD_OUT_REFRESH_SECONDS = 1.2
WAIT_LOG_EVERY = 20
PAYMENT_HOLD_SECONDS = 15 * 60


def compact_text(text, limit=120):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def contains_any(text, keywords):
    return any(keyword in (text or "") for keyword in keywords)


def notify_user(title, message):
    print(f"###{title}：{message}###", flush=True)
    if platform.system().lower() != "darwin":
        return

    script = (
        f"display notification {json.dumps(message, ensure_ascii=False)} "
        f"with title {json.dumps(title, ensure_ascii=False)} sound name \"Glass\""
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def start_keep_awake():
    if platform.system().lower() != "darwin" or not shutil.which("caffeinate"):
        return None

    try:
        process = subprocess.Popen(
            ["caffeinate", "-dimsu", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as error:
        print(f"###macOS 防睡眠启动失败: {error}###")
        return None

    print(u"###已启用 macOS 防睡眠：脚本运行期间请保持电脑接电、不要合盖###", flush=True)
    return process


def _usable_executable(path):
    path = Path(path)
    if not path.is_file():
        return False
    return os.name == "nt" or os.access(str(path), os.X_OK)


def _resolve_existing_path(raw_path):
    if not raw_path:
        return None

    path = Path(raw_path).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([Path.cwd() / path, PROJECT_ROOT / path])

    for candidate in candidates:
        if _usable_executable(candidate):
            return str(candidate)

    found = shutil.which(str(raw_path))
    if found and _usable_executable(found):
        return found
    return None


def resolve_driver_path(configured_path=""):
    env_driver = os.environ.get("CHROMEDRIVER") or os.environ.get("CHROMEWEBDRIVER")
    driver_path = _resolve_existing_path(env_driver) or _resolve_existing_path(configured_path)
    if driver_path:
        return driver_path

    system = platform.system().lower()
    candidates = [shutil.which("chromedriver")]

    if system == "darwin":
        candidates.extend([
            "/opt/homebrew/bin/chromedriver",
            "/usr/local/bin/chromedriver",
            PROJECT_ROOT / "chromedriver",
        ])
    elif system == "windows":
        candidates.extend([
            PROJECT_ROOT / "chromedriver.exe",
            "chromedriver.exe",
        ])
    else:
        candidates.extend([
            "/usr/bin/chromedriver",
            "/usr/local/bin/chromedriver",
            PROJECT_ROOT / "chromedriver",
        ])

    for candidate in candidates:
        if candidate and _usable_executable(candidate):
            return str(candidate)

    hint = (
        "未找到可用的 ChromeDriver。\n"
        "macOS 可先执行: brew install chromedriver\n"
        "然后可通过 config/config.json 的 driver_path 或 CHROMEDRIVER 环境变量指定路径。"
    )
    if configured_path:
        hint += f"\n当前配置的 driver_path 为: {configured_path}"
    raise FileNotFoundError(hint)


def resolve_config_path(config_path=None):
    if config_path:
        path = Path(config_path).expanduser()
        candidates = [path] if path.is_absolute() else [Path.cwd() / path, PROJECT_ROOT / path]
    else:
        candidates = [DEFAULT_CONFIG_PATH]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"未找到配置文件，已查找:\n{searched}")


def load_config(config_path=None):
    path = resolve_config_path(config_path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class Concert(object):
    def __init__(self, date, session, price, ticket_num, viewer_person, damai_url, target_url, driver_path):
        self.date = date  # 日期序号
        self.session = session  # 场次序号优先级
        self.price = price  # 票价序号优先级
        self.status = 0  # 状态标记
        self.time_start = 0  # 开始时间
        self.time_end = 0  # 结束时间
        self.num = 0  # 尝试次数
        self.ticket_num = ticket_num  # 购买票数
        self.viewer_person = viewer_person  # 观影人序号优先级
        self.damai_url = damai_url  # 大麦网官网网址
        self.target_url = target_url  # 目标购票网址
        self.driver_path = resolve_driver_path(driver_path)  # 浏览器驱动地址
        self.driver = None
        self.last_wait_reason = ""

    def create_driver(self, options=None):
        service = Service(executable_path=self.driver_path)
        if options is None:
            return webdriver.Chrome(service=service)
        return webdriver.Chrome(service=service, options=options)

    def isClassPresent(self, item, name, ret=False):
        try:
            result = item.find_element(by=By.CLASS_NAME, value=name)
            if ret:
                return result
            else:
                return True
        except:
            return False

    # 获取账号的cookie信息
    def get_cookie(self):
        self.driver.get(self.damai_url)
        print(u"###请点击登录###")
        self.driver.find_element(by=By.CLASS_NAME, value='login-user').click()
        while self.driver.title.find('大麦网-全球演出赛事官方购票平台') != -1:  # 等待网页加载完成
            sleep(1)
        print(u"###请扫码登录###")
        while self.driver.title == '大麦登录':  # 等待扫码完成
            sleep(1)
        dump(self.driver.get_cookies(), open(COOKIE_PATH, "wb"))
        print(u"###Cookie保存成功###")

    def login_only(self):
        print(u"###登录测试：只打开大麦并保存 Cookie，不进入购票流程###")
        print(f"###ChromeDriver: {self.driver_path}###")
        self.driver = self.create_driver()
        try:
            self.get_cookie()
        finally:
            self.driver.quit()
        print(u"###登录测试完成，浏览器已关闭###")

    def open_target_only(self, hold_seconds=20):
        print(u"###演出页测试：打开目标页面，不点击购买按钮###")
        print(f"###ChromeDriver: {self.driver_path}###")
        self.driver = self.create_driver()
        try:
            self.driver.get(self.damai_url)
            if COOKIE_PATH.exists():
                self.set_cookie()
            else:
                print(u"###未找到 cookies.pkl；如需登录状态，请先运行登录测试###")
            self.driver.get(self.target_url)
            sleep(3)
            print(f"###页面标题: {self.driver.title}###")
            print(f"###当前链接: {self.driver.current_url}###")
            print(f"###页面将停留 {hold_seconds} 秒供人工查看，不会自动点击购买###")
            sleep(hold_seconds)
        finally:
            self.driver.quit()
        print(u"###演出页测试完成，浏览器已关闭###")

    def set_cookie(self):
        try:
            cookies = load(open(COOKIE_PATH, "rb"))  # 载入cookie
            for cookie in cookies:
                cookie_dict = {
                    'domain': '.damai.cn',  # 必须有，不然就是假登录
                    'name': cookie.get('name'),
                    'value': cookie.get('value'),
                    "expires": "",
                    'path': '/',
                    'httpOnly': False,
                    'HostOnly': False,
                    'Secure': False}
                self.driver.add_cookie(cookie_dict)
            print(u'###载入Cookie###')
        except Exception as e:
            print(e)

    def login(self):
        print(u'###开始登录###')
        self.driver.get(self.target_url)
        WebDriverWait(self.driver, 10, 0.1).until(EC.title_contains('商品详情'))
        self.set_cookie()

    def enter_concert(self):
        print(u'###打开浏览器，进入大麦网###')
        print(f"###ChromeDriver: {self.driver_path}###")
        if not COOKIE_PATH.exists():   # 如果不存在cookie.pkl,就获取一下
            self.driver = self.create_driver()
            self.get_cookie()
            print(u'###成功获取Cookie，重启浏览器###')
            self.driver.quit()

        options = webdriver.ChromeOptions()
        # 禁止图片、js、css加载
        prefs = {"profile.managed_default_content_settings.images": 2,
                 "profile.managed_default_content_settings.javascript": 1,
                 'permissions.default.stylesheet': 2}
        mobile_emulation = {"deviceName": "Nexus 6"}
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("mobileEmulation", mobile_emulation)
        # 就是这一行告诉chrome去掉了webdriver痕迹，令navigator.webdriver=false，极其关键
        options.add_argument("--disable-blink-features=AutomationControlled")

        # 更换等待策略为不等待浏览器加载完全就进行下一步操作
        # normal, eager, none
        options.set_capability("pageLoadStrategy", "eager")
        self.driver = self.create_driver(options=options)
        # 登录到具体抢购页面
        self.login()
        self.driver.refresh()
        self.status = 1
        self.time_start = time()
        print(u"###已进入目标页面；如未开售，将持续等待并刷新###")

    def click_util(self, btn, locator):
        while True:
            btn.click()
            try:
                return WebDriverWait(self.driver, 1, 0.1).until(EC.presence_of_element_located(locator))
            except:
                continue

    def wait_and_refresh(self, reason, button_text="", interval=PRE_SALE_REFRESH_SECONDS):
        detail = compact_text(button_text, limit=60)
        if self.num == 1 or self.num % WAIT_LOG_EVERY == 0 or self.last_wait_reason != reason:
            if detail:
                print(f"###{reason}：当前按钮「{detail}」，第 {self.num} 次检查，继续等待###", flush=True)
            else:
                print(f"###{reason}：第 {self.num} 次检查，继续等待###", flush=True)
        self.last_wait_reason = reason
        sleep(interval)
        try:
            self.driver.refresh()
        except Exception:
            self.driver.get(self.target_url)

    # 实现购买函数

    def choose_ticket(self):
        print(u"###进入抢票界面###")
        # 如果跳转到了确认界面就算这步成功了，否则继续执行此步
        while self.driver.title.find('订单确认') == -1:
            self.num += 1  # 尝试次数加1

            if self.driver.current_url.find("buy.damai.cn") != -1:
                self.status = 4
                break

            # 确认页面刷新成功
            try:
                box = WebDriverWait(self.driver, 3, 0.1).until(
                    EC.presence_of_element_located((By.ID, 'app')))
            except:
                raise Exception(u"***Error: 页面刷新出错***")

            try:
                realname_popup = box.find_elements(
                    by=By.XPATH, value="//div[@class='realname-popup']")  # 寻找实名身份遮罩
                if len(realname_popup) != 0:
                    known_button = realname_popup[0].find_element(
                        by=By.XPATH, value="//div[@class='operate']//div[@class='button']")
                    known_button[0].click()
            except:
                raise Exception(u"***Error: 实名制遮罩关闭失败***")

            try:
                buybutton = box.find_element(by=By.CLASS_NAME, value='buy__button')
                sleep(0.5)
                buybutton_text: str = buybutton.text
            except Exception as e:
                raise Exception(f"***Error: buybutton 位置找不到***: {e}")

            if contains_any(buybutton_text, PRE_SALE_KEYWORDS):
                self.status = 2
                self.wait_and_refresh("尚未开售，开售前持续等待", buybutton_text, PRE_SALE_REFRESH_SECONDS)
                continue

            if contains_any(buybutton_text, SOLD_OUT_KEYWORDS):
                self.status = 7
                self.wait_and_refresh("当前缺货/售罄，持续捡漏", buybutton_text, SOLD_OUT_REFRESH_SECONDS)
                continue

            sleep(0.1)
            buybutton.click()
            try:
                box = WebDriverWait(self.driver, 2, 0.1).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.sku-pop-wrapper')))
            except Exception as e:
                if contains_any(buybutton_text, PRE_SALE_KEYWORDS):
                    self.wait_and_refresh("尚未开售，票档面板暂未出现", buybutton_text, PRE_SALE_REFRESH_SECONDS)
                    continue
                raise Exception(f"***Error: 票档面板未出现***: {e}")

            try:
                # 日期选择
                toBeClicks = []
                try:
                    date = WebDriverWait(self.driver, 2, 0.1).until(
                        EC.presence_of_element_located((By.CLASS_NAME, 'bui-dm-sku-calendar')))
                except Exception as e:
                    date = None
                if date is not None:
                    date_list = date.find_elements(
                        by=By.CLASS_NAME, value='bui-calendar-day-box')
                    for i in self.date:
                        j: WebElement = date_list[i-1]
                        toBeClicks.append(j)
                        break
                    for i in toBeClicks:
                        i.click()
                        sleep(0.05)

                # 选定场次
                session = WebDriverWait(self.driver, 2, 0.1).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'sku-times-card')))    # 日期、场次和票档进行定位
                session_list = session.find_elements(
                    by=By.CLASS_NAME, value='bui-dm-sku-card-item')

                toBeClicks = []
                for i in self.session:  # 根据优先级选择一个可行场次
                    if i > len(session_list):
                        i = len(session_list)
                    j: WebElement = session_list[i-1]
                    # TODO 不确定已满的场次带的是什么Tag
                    
                    k = self.isClassPresent(j, 'item-tag', True)
                    if k:  # 如果找到了带presell的类
                        if k.text == '无票':
                            continue
                        elif k.text == '预售':
                            toBeClicks.append(j)
                            break
                        elif k.text == '惠':
                            toBeClicks.append(j)
                            break
                    else:
                        toBeClicks.append(j)
                        break
                
                # 多场次的场要先选择场次才会出现票档
                for i in toBeClicks:
                    i.click()
                    sleep(0.05)

                # 选定票档
                toBeClicks = []
                price = WebDriverWait(self.driver, 2, 0.1).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'sku-tickets-card')))  # 日期、场次和票档进行定位

                price_list = price.find_elements(
                    by=By.CLASS_NAME, value='bui-dm-sku-card-item')  # 选定票档
                # print('可选票档数量为：{}'.format(len(price_list)))
                for i in self.price:
                    if i > len(price_list):
                        i = len(price_list)
                    j = price_list[i-1]
                    # k = j.find_element(by=By.CLASS_NAME, value='item-tag')
                    k = self.isClassPresent(j, 'item-tag', True)
                    if k:  # 存在notticket代表存在缺货登记，跳过
                        continue
                    else:
                        toBeClicks.append(j)
                        break

                for i in toBeClicks:
                    i.click()
                    sleep(0.1)

                buybutton = box.find_element(
                    by=By.CLASS_NAME, value='sku-footer-buy-button')
                sleep(1.0)
                buybutton_text = buybutton.text
                if buybutton_text == "":
                    raise Exception(u"***Error: 提交票档按钮文字获取为空,适当调整 sleep 时间***")

                if contains_any(buybutton_text, PRE_SALE_KEYWORDS):
                    self.wait_and_refresh("尚未开售，票档面板等待中", buybutton_text, PRE_SALE_REFRESH_SECONDS)
                    continue

                if contains_any(buybutton_text, SOLD_OUT_KEYWORDS):
                    self.wait_and_refresh("当前票档缺货/售罄，持续捡漏", buybutton_text, SOLD_OUT_REFRESH_SECONDS)
                    continue


                try:
                    WebDriverWait(self.driver, 2, 0.1).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'bui-dm-sku-counter')))
                except:
                    raise Exception(u"***购票按钮未开始***")

            except Exception as e:
                raise Exception(f"***Error: 选择日期or场次or票档不成功***: {e}")

            try:
                ticket_num_up = box.find_element(
                    by=By.CLASS_NAME, value='plus-enable')
            except:
                if buybutton_text == "选座购买":  # 选座购买没有增减票数键
                    buybutton.click()
                    self.status = 5
                    print(u"###请自行选择位置和票价###")
                    break
                elif contains_any(buybutton_text, SOLD_OUT_KEYWORDS):
                    self.wait_and_refresh("当前票档缺货/售罄，持续捡漏", buybutton_text, SOLD_OUT_REFRESH_SECONDS)
                    continue
                else:
                    raise Exception(u"***Error: ticket_num_up 位置找不到***")

            if buybutton_text == "立即预订" or buybutton_text == "立即购买" or buybutton_text == '确定':
                for i in range(self.ticket_num-1):  # 设置增加票数
                    ticket_num_up.click()
                buybutton.click()
                self.status = 4
                WebDriverWait(self.driver, 3, 0.1).until(
                    EC.title_contains("确认"))
                break
            else:
                raise Exception(f"未定义按钮：{buybutton_text}")

    def check_order(self):
        if self.status in [3, 4, 5]:
            # 选择观影人
            toBeClicks = []
            WebDriverWait(self.driver, 5, 0.1).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="dmViewerBlock_DmViewerBlock"]/div[2]/div/div')))
            people = self.driver.find_elements(
                By.XPATH, '//*[@id="dmViewerBlock_DmViewerBlock"]/div[2]/div/div')
            sleep(0.2)

            for i in self.viewer_person:
                if i > len(people):
                    break
                j = people[i-1]
                j.click()
                sleep(0.05)

            WebDriverWait(self.driver, 5, 0.1).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="dmOrderSubmitBlock_DmOrderSubmitBlock"]/div[2]/div/div[2]/div[3]/div[2]')))
            comfirmBtn = self.driver.find_element(
                By.XPATH, '//*[@id="dmOrderSubmitBlock_DmOrderSubmitBlock"]/div[2]/div/div[2]/div[3]/div[2]')
            sleep(0.5)
            comfirmBtn.click()
            self.status = 6
            self.time_end = time()
            notify_user("大麦订单已提交", "请尽快打开浏览器完成付款，脚本会保留页面等待。")
            print(u'###成功提交订单，请手动完成付款###')
            print(f"###浏览器将保留 {PAYMENT_HOLD_SECONDS // 60} 分钟，方便你接手支付###")
            sleep(PAYMENT_HOLD_SECONDS)


def parse_args():
    parser = argparse.ArgumentParser(description="DamaiHelper ticket script")
    parser.add_argument(
        "--config",
        default=None,
        help="配置文件路径，默认读取 config/config.json。",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="只检查配置文件和 ChromeDriver 路径，不启动浏览器。",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="只打开大麦登录并保存 Cookie，不进入购票流程。",
    )
    parser.add_argument(
        "--open-target-only",
        action="store_true",
        help="只打开配置中的目标演出页面，不点击购买按钮。",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=20,
        help="测试模式打开页面后停留的秒数，默认 20 秒。",
    )
    return parser.parse_args()


def main(config_path=None, check_env=False, login_only=False, open_target_only=False, hold_seconds=20):
    keep_awake_process = None
    try:
        config = load_config(config_path)
        if check_env:
            print(f"配置文件: {resolve_config_path(config_path)}")
            driver_path = resolve_driver_path(config.get('driver_path', ''))
            print(f"ChromeDriver: {driver_path}")
            print("环境检查通过。")
            return

        con = Concert(config['date'], config['sess'], config['price'], config['ticket_num'],
                      config['viewer_person'], config['damai_url'], config['target_url'], config.get('driver_path', ''))
        if login_only:
            con.login_only()
            return
        if open_target_only:
            con.open_target_only(max(1, hold_seconds))
            return
        keep_awake_process = start_keep_awake()
        con.enter_concert()  # 进入到具体抢购页面
    except Exception as e:
        print(e)
        if keep_awake_process:
            keep_awake_process.terminate()
        exit(1)

    try:
        while True:
            try:
                con.choose_ticket()
                con.check_order()
            except Exception as e:
                con.driver.get(con.target_url)
                print(e)
                continue

            if con.status == 6:
                print(u"###经过%d轮奋斗，共耗时%.1f秒，抢票成功！请确认订单信息###" %
                      (con.num, round(con.time_end-con.time_start, 3)))
                break
    finally:
        if keep_awake_process:
            keep_awake_process.terminate()


if __name__ == '__main__':
    args = parse_args()
    main(
        args.config,
        args.check_env,
        args.login_only,
        args.open_target_only,
        args.hold_seconds,
    )
