# -*- coding: UTF-8 -*-
"""
大麦app抢票 V3 - 独立版
"""

import argparse, json, os, sys, time, signal, subprocess, atexit
import urllib.request
from pathlib import Path
from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# --- 硬编码配置（机器相关）---
ADB_DIR = r"C:\Users\wangqian\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe"
APPIUM_CMD = r"C:\Users\wangqian\AppData\Roaming\npm\appium.cmd"
APPIUM_URL = "http://127.0.0.1:4723"
STARTUP_TIMEOUT = 30


# --- Config 类 ---
class Config:
    def __init__(self, server_url, keyword, users, city, date, price, price_index, if_commit_order,
                 enable_refresh=True, max_refresh_attempts=0, refresh_interval=0.2):
        self.server_url = server_url
        self.keyword = keyword
        self.users = users
        self.city = city
        self.date = date
        self.price = price
        self.price_index = price_index
        self.if_commit_order = if_commit_order
        self.enable_refresh = enable_refresh
        self.max_refresh_attempts = max_refresh_attempts
        self.refresh_interval = refresh_interval

    @staticmethod
    def load_config():
        config_path = Path(__file__).parent / "config.jsonc"
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
        return Config(config['server_url'],
                      config['keyword'],
                      config['users'],
                      config['city'],
                      config['date'],
                      config['price'],
                      config['price_index'],
                      config['if_commit_order'],
                      enable_refresh=config.get('enable_refresh', True),
                      max_refresh_attempts=config.get('max_refresh_attempts', 0),
                      refresh_interval=config.get('refresh_interval', 0.2))


# --- DamaiBot 类 ---
class DamaiBot:
    def __init__(self):
        self.config = Config.load_config()
        self.driver = None
        self.wait = None
        self._setup_driver()

    def _setup_driver(self):
        """初始化 Appium driver + 性能优化"""
        capabilities = {
            "platformName": "Android",
            "deviceName": "Android",
            "udid": "5df482ec",
            "appPackage": "cn.damai",
            "appActivity": ".launcher.splash.SplashMainActivity",
            "noReset": True,
            "newCommandTimeout": 6000,
            "automationName": "UiAutomator2",
            "skipServerInstallation": False,
            "mjpegServerFramerate": 1,
            "shouldTerminateApp": False,
            "adbExecTimeout": 20000,
        }

        device_app_info = AppiumOptions()
        device_app_info.load_capabilities(capabilities)
        self.driver = webdriver.Remote(self.config.server_url, options=device_app_info)

        self.driver.update_settings({
            "waitForIdleTimeout": 0,
            "actionAcknowledgmentTimeout": 0,
            "keyInjectionDelay": 0,
            "waitForSelectorTimeout": 300,
            "ignoreUnimportantViews": False,
            "allowInvisibleElements": True,
            "enableNotificationListener": False,
        })

        self.wait = WebDriverWait(self.driver, 2)

    def _swipe_down(self):
        """屏幕自适应下拉刷新"""
        try:
            size = self.driver.get_window_size()
            x = size['width'] // 2
            y_start = int(size['height'] * 0.25)
            y_end = int(size['height'] * 0.75)
            self.driver.swipe(x, y_start, x, y_end, 300)
        except Exception as e:
            print(f"下拉刷新失败: {e}")

    def _wait_for_tickets_open(self):
        """等开售：检测"立即购买"或可点击票档，不行就下拉刷新
        enable_refresh=False 时不做下拉刷新，直接继续。
        max_refresh_attempts=0 表示无限刷新直到开售。
        """
        if not getattr(self.config, 'enable_refresh', True):
            return

        max_attempts = getattr(self.config, 'max_refresh_attempts', 0)
        interval = getattr(self.config, 'refresh_interval', 0.2)
        attempts = 0

        while True:
            attempts += 1

            # A. 检测"立即购买"文本
            try:
                btn_elements = self.driver.find_elements(
                    By.ID, 'cn.damai:id/tv_left_main_text'
                )
                if btn_elements and '立即购买' in (btn_elements[0].text or ''):
                    print(f"检测到'立即购买'（刷新 {attempts - 1} 次）")
                    return
            except Exception:
                pass

            # B. 检测可点击票档
            try:
                container = self.driver.find_elements(
                    By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout'
                )
                if container:
                    clickable = container[0].find_elements(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiSelector().clickable(true)'
                    )
                    if clickable:
                        print(f"检测到可点击票档（刷新 {attempts - 1} 次）")
                        return
            except Exception:
                pass

            if max_attempts and attempts >= max_attempts:
                print(f"已刷新 {max_attempts} 次仍未开售，继续后续流程")
                return

            self._swipe_down()
            time.sleep(interval)

    def fast_click(self, by, value, timeout=1.5):
        """快速轮询点击"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                elements = self.driver.find_elements(by, value)
                if elements:
                    rect = elements[0].rect
                    x = rect['x'] + rect['width'] // 2
                    y = rect['y'] + rect['height'] // 2
                    self.driver.execute_script("mobile: clickGesture", {
                        "x": x, "y": y, "duration": 50
                    })
                    return True
            except Exception:
                pass
            time.sleep(0.12)
        return False

    def smart_click(self, by, value, backup_selectors=None, timeout=1.5):
        """多选择器兜底 + 坐标手势点击"""
        selectors = [(by, value)]
        if backup_selectors:
            selectors.extend(backup_selectors)

        for selector_by, selector_value in selectors:
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    elements = self.driver.find_elements(selector_by, selector_value)
                    if elements:
                        rect = elements[0].rect
                        x = rect['x'] + rect['width'] // 2
                        y = rect['y'] + rect['height'] // 2
                        self.driver.execute_script("mobile: clickGesture", {
                            "x": x, "y": y, "duration": 50
                        })
                        return True
                except Exception:
                    pass
                time.sleep(0.15)
        return False

    def _click_purchase_button(self):
        """多策略点击购票入口：选座购票 -> 立即购买 -> 容器兜底"""
        print("点击购票按钮...")

        # 策略1: 选座购票（4种选择器）
        seat_selectors = [
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("选座购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("选座购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("选座")'),
            (By.XPATH, '//*[contains(@text,"选座购票")]')
        ]
        if self.smart_click(*seat_selectors[0], seat_selectors[1:], timeout=1.2):
            print("已命中购票入口: 选座购票")
            return True

        # 策略2: 常规购买按钮（5种选择器）
        buy_selectors = [
            (By.ID, 'cn.damai:id/tv_left_main_text'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("特惠购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("立即购买")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("购买")'),
            (By.XPATH, '//*[contains(@text,"特惠购票") or contains(@text,"立即购买") or contains(@text,"购买")]')
        ]
        if self.smart_click(*buy_selectors[0], buy_selectors[1:], timeout=1.5):
            print("已命中购票入口: 常规购买按钮")
            return True

        # 策略3: 容器兜底
        if self.fast_click(
            By.XPATH,
            '//android.widget.FrameLayout[@resource-id="cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"]/android.widget.LinearLayout'
        ):
            print("已命中购票入口: 容器兜底点击")
            return True

        print("未命中任何购票入口")
        return False

    def _select_price(self):
        """按 price_index 选票档，失败则点击首个可选票档"""
        print("选择票价...")
        try:
            price_container = self.driver.find_element(
                By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout'
            )
            target_price = price_container.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().className("android.widget.FrameLayout").index({self.config.price_index}).clickable(true)'
            )
            self.driver.execute_script(
                'mobile: clickGesture', {'elementId': target_price.id}
            )
            return True
        except Exception as e:
            print(f"按索引选择票价失败: {e}")

        try:
            price_container = self.driver.find_element(
                By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout'
            )
            clickable_prices = price_container.find_elements(
                AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().clickable(true)'
            )
            if clickable_prices:
                self.driver.execute_script(
                    'mobile: clickGesture', {'elementId': clickable_prices[0].id}
                )
                return True
        except Exception as e:
            print(f"票档兜底点击失败: {e}")
        return False

    def _click_confirm(self):
        """点击确定/购买确认按钮"""
        print("确认购买...")
        return self.smart_click(
            By.ID, "btn_buy_view",
            backup_selectors=[
                (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*确定.*|.*购买.*")')
            ],
            timeout=1.5
        )

    def _click_submit(self):
        """点击提交订单按钮"""
        print("提交订单...")
        submit_selectors = [
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("立即提交")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*提交.*|.*确认.*")'),
            (By.XPATH, '//*[contains(@text,"提交")]')
        ]
        return self.smart_click(*submit_selectors[0], submit_selectors[1:])

    def run(self):
        """主流程：等开售 -> 点击购票 -> 选票档 -> 确认 -> 提交"""
        try:
            print("开始抢票流程...")
            start_time = time.time()

            # 1. 等待开售（下拉刷新）
            print("等待开售...")
            self._wait_for_tickets_open()

            # 2. 点击购票入口
            if not self._click_purchase_button():
                print("未找到购票入口，流程终止")
                return False

            # 3. 选择票档
            if not self._select_price():
                print("未能选择票档，流程终止")
                return False

            # 4. 确认购买
            self._click_confirm()

            # 5. 提交订单
            self._click_submit()

            end_time = time.time()
            print(f"抢票流程完成，耗时: {end_time - start_time:.2f}秒")
            return True

        except Exception as e:
            print(f"抢票过程发生错误: {e}")
            return False
        finally:
            time.sleep(1)
            self.driver.quit()


# --- Appium 生命周期 ---
def setup_android_env():
    """设置 ANDROID_HOME 和 ANDROID_SDK_ROOT 环境变量"""
    os.environ["ANDROID_HOME"] = ADB_DIR
    os.environ["ANDROID_SDK_ROOT"] = ADB_DIR
    platform_tools = os.path.join(ADB_DIR, "platform-tools")
    os.environ["PATH"] = platform_tools + os.pathsep + os.environ.get("PATH", "")


def start_appium():
    """启动 Appium Server 并等待就绪"""
    print("Starting Appium...")
    proc = subprocess.Popen(
        [APPIUM_CMD, "--address", "127.0.0.1", "--port", "4723"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(f"{APPIUM_URL}/status", timeout=2)
            if resp.status == 200:
                print("Appium ready!")
                return proc
        except Exception:
            pass
        time.sleep(0.5)

    proc.terminate()
    proc.wait(timeout=5)
    raise RuntimeError(f"Appium 启动超时（{STARTUP_TIMEOUT}s），请检查 Appium 是否安装正确")


def stop_appium(proc):
    """终止 Appium Server"""
    if proc and proc.poll() is None:
        print("Stopping Appium...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print("Appium stopped.")


# --- 入口 ---
def parse_args():
    parser = argparse.ArgumentParser(description="大麦抢票自动化脚本 V3")
    parser.add_argument("--debug-click", action="store_true",
                        help="调试模式：在指定坐标模拟点击后退出")
    parser.add_argument("--click-x", type=int, help="调试点击 X 坐标")
    parser.add_argument("--click-y", type=int, help="调试点击 Y 坐标")
    parser.add_argument("--click-count", type=int, default=1,
                        help="点击次数（默认 1）")
    parser.add_argument("--click-interval", type=float, default=0.5,
                        help="点击间隔秒数（默认 0.5）")
    parser.add_argument("--click-loop", action="store_true",
                        help="持续循环点击直到手动停止（此时 --click-count 无效）")
    parser.add_argument("--click-positions", type=str, default=None,
                        help='多点点击位置 JSON: \'[{"x":100,"y":200,"count":3}]\'')
    return parser.parse_args()


def run_debug_click(x=None, y=None, count=1, interval=0.5, loop=False,
                    positions=None):
    """调试模式：启动 Appium，执行点击手势，支持多次/循环/多位置点击"""
    # 统一转换为 positions 列表
    if positions is not None:
        # 多点模式：确保每个位置有 count 默认值
        for p in positions:
            p.setdefault("count", 1)
        pos_list = positions
    elif x is not None and y is not None:
        # 旧版单点模式：内部转为单元素列表
        pos_list = [{"x": x, "y": y, "count": count}]
        if loop:
            pos_list = [{"x": x, "y": y, "count": count}]
    else:
        raise ValueError("必须提供 positions 或 (x, y) 参数")

    setup_android_env()
    appium_proc = start_appium()
    try:
        bot = DamaiBot()
        i = 0
        while True:
            for pos in pos_list:
                for _ in range(pos["count"]):
                    i += 1
                    bot.driver.execute_script("mobile: clickGesture", {
                        "x": pos["x"], "y": pos["y"], "duration": 50
                    })
                    label = f"({i}{'' if loop else ''})"
                    print(f"调试点击 {label}: 坐标 ({pos['x']}, {pos['y']})")
                    time.sleep(interval)
            if not loop:
                break
        print(f"调试点击完成: 共 {i} 次")
    finally:
        bot.driver.quit()
        stop_appium(appium_proc)


def main():
    args = parse_args()

    if args.debug_click:
        if args.click_positions:
            try:
                pos_list = json.loads(args.click_positions)
            except json.JSONDecodeError as e:
                print(f"错误: --click-positions JSON 解析失败: {e}")
                sys.exit(1)
            if not isinstance(pos_list, list) or len(pos_list) == 0:
                print("错误: --click-positions 必须是非空 JSON 数组")
                sys.exit(1)
            for p in pos_list:
                if not isinstance(p, dict) or "x" not in p or "y" not in p:
                    print("错误: --click-positions 每个元素必须包含 x 和 y 字段")
                    sys.exit(1)
                p.setdefault("count", 1)
            run_debug_click(positions=pos_list, interval=args.click_interval)
        elif args.click_x is not None and args.click_y is not None:
            run_debug_click(x=args.click_x, y=args.click_y,
                            count=args.click_count, interval=args.click_interval,
                            loop=args.click_loop)
        else:
            print("错误: 需要 --click-x/--click-y 或 --click-positions")
            sys.exit(1)
        return

    # --- 正常抢票流程（原有逻辑不变）---
    # 1. 设置 Android 环境变量
    setup_android_env()

    # 2. 启动 Appium
    appium_proc = start_appium()

    # 3. 确保退出时清理 Appium
    def cleanup():
        stop_appium(appium_proc)

    atexit.register(cleanup)

    def signal_handler(sig, frame):
        print("\n收到中断信号，正在退出...")
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 4. 运行 V3 抢票脚本
    print("开始抢票流程...")
    bot = DamaiBot()
    bot.run()

    # 5. 正常退出清理
    cleanup()


if __name__ == "__main__":
    main()
