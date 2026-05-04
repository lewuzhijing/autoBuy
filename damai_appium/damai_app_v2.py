# -*- coding: UTF-8 -*-
"""
__Author__ = "BlueCestbon"
__Version__ = "2.0.0"
__Description__ = "大麦app抢票自动化 - 优化版"
__Created__ = 2025/09/13 19:27
"""

import argparse
import json
import sys
import time
from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from config import Config

DEBUG_LOG_PATH = r"E:\项目\ticket-purchase\debug-b39314.log"
DEBUG_SESSION_ID = "b39314"


class DamaiBot:
    def __init__(self):
        self.config = Config.load_config()
        self.driver = None
        self.wait = None
        self.debug_run_id = f"run-{int(time.time() * 1000)}"
        self.last_purchase_entry_result = {"success": False, "route": None}
        self._setup_driver()

    def _debug_log(self, hypothesis_id, location, message, data):
        payload = {
            "sessionId": DEBUG_SESSION_ID,
            "runId": self.debug_run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _probe_selector_count(self, selector_by, selector_value):
        try:
            elements = self.driver.find_elements(selector_by, selector_value)
            return {"count": len(elements), "error": None}
        except Exception as e:
            return {"count": -1, "error": str(e)}

    def _setup_driver(self):
        """初始化驱动配置"""
        capabilities = {
            "platformName": "Android",  # 操作系统
            "deviceName": "Android",  # 设备名称（通用）
            "udid": "5df482ec",  # 指定真机，避免连到模拟器
            "appPackage": "cn.damai",  # app 包名
            "appActivity": ".launcher.splash.SplashMainActivity",  # app 启动 Activity
            "noReset": True,  # 不重置 app
            "newCommandTimeout": 6000,  # 超时时间
            "automationName": "UiAutomator2",  # 使用 uiautomator2
            "skipServerInstallation": False,  # 首次调试允许自动安装服务
            # 优化性能配置
            "mjpegServerFramerate": 1,  # 降低截图帧率
            "shouldTerminateApp": False,
            "adbExecTimeout": 20000,
        }

        device_app_info = AppiumOptions()
        device_app_info.load_capabilities(capabilities)
        self.driver = webdriver.Remote(self.config.server_url, options=device_app_info)

        # 更激进的性能优化设置
        self.driver.update_settings({
            "waitForIdleTimeout": 0,  # 空闲时间，0 表示不等待，让 UIAutomator2 不等页面“空闲”再返回
            "actionAcknowledgmentTimeout": 0,  # 禁止等待动作确认
            "keyInjectionDelay": 0,  # 禁止输入延迟
            "waitForSelectorTimeout": 300,  # 从500减少到300ms
            "ignoreUnimportantViews": False,  # 保持false避免元素丢失
            "allowInvisibleElements": True,
            "enableNotificationListener": False,  # 禁用通知监听
        })

        # 极短的显式等待，抢票场景下速度优先
        self.wait = WebDriverWait(self.driver, 2)  # 从5秒减少到2秒

    def ultra_fast_click(self, by, value, timeout=1.5):
        """超快速点击 - 适合抢票场景"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                elements = self.driver.find_elements(by, value)
                if elements:
                    rect = elements[0].rect
                    x = rect['x'] + rect['width'] // 2
                    y = rect['y'] + rect['height'] // 2
                    self.driver.execute_script("mobile: clickGesture", {
                        "x": x,
                        "y": y,
                        "duration": 50
                    })
                    return True
            except Exception:
                pass
            time.sleep(0.12)
        return False

    def batch_click(self, elements_info, delay=0.1):
        """批量点击操作"""
        for by, value in elements_info:
            if self.ultra_fast_click(by, value):
                if delay > 0:
                    time.sleep(delay)
            else:
                print(f"点击失败: {value}")

    def ultra_batch_click(self, elements_info, timeout=2):
        """超快批量点击 - 带等待机制"""
        coordinates = []
        # 批量收集坐标，带超时等待
        for by, value in elements_info:
            try:
                # 等待元素出现
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                rect = el.rect
                x = rect['x'] + rect['width'] // 2
                y = rect['y'] + rect['height'] // 2
                coordinates.append((x, y, value))
            except TimeoutException:
                print(f"超时未找到用户: {value}")
            except Exception as e:
                print(f"查找用户失败 {value}: {e}")
        print(f"成功找到 {len(coordinates)} 个用户")
        # 快速连续点击
        for i, (x, y, value) in enumerate(coordinates):
            self.driver.execute_script("mobile: clickGesture", {
                "x": x,
                "y": y,
                "duration": 30
            })
            if i < len(coordinates) - 1:
                time.sleep(0.01)
            print(f"点击用户: {value}")

    def smart_wait_and_click(self, by, value, backup_selectors=None, timeout=1.5):
        """智能等待和点击 - 支持备用选择器"""
        selectors = [(by, value)]
        if backup_selectors:
            selectors.extend(backup_selectors)

        for selector_index, (selector_by, selector_value) in enumerate(selectors):
            # #region agent log
            self._debug_log(
                "H6",
                "damai_app_v2.py:smart_wait_and_click:selector_start",
                "selector_loop_start",
                {
                    "selector_index": selector_index,
                    "selector_by": str(selector_by),
                    "selector_value": selector_value,
                    "timeout": timeout,
                },
            )
            # #endregion
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    elements = self.driver.find_elements(selector_by, selector_value)
                    if elements:
                        rect = elements[0].rect
                        x = rect['x'] + rect['width'] // 2
                        y = rect['y'] + rect['height'] // 2
                        self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y, "duration": 50})
                        # #region agent log
                        self._debug_log(
                            "H6",
                            "damai_app_v2.py:smart_wait_and_click:click_success",
                            "selector_click_success",
                            {
                                "selector_index": selector_index,
                                "selector_by": str(selector_by),
                                "selector_value": selector_value,
                                "rect": rect,
                            },
                        )
                        # #endregion
                        return True
                except Exception as e:
                    # #region agent log
                    self._debug_log(
                        "H6",
                        "damai_app_v2.py:smart_wait_and_click:find_exception",
                        "find_elements_exception",
                        {
                            "selector_index": selector_index,
                            "selector_by": str(selector_by),
                            "selector_value": selector_value,
                            "error": str(e),
                        },
                    )
                    # #endregion
                    # 个别机型/页面会出现瞬时 socket hang up，短暂忽略继续重试
                    pass
                time.sleep(0.15)
            # #region agent log
            self._debug_log(
                "H6",
                "damai_app_v2.py:smart_wait_and_click:selector_timeout",
                "selector_timeout",
                {
                    "selector_index": selector_index,
                    "selector_by": str(selector_by),
                    "selector_value": selector_value,
                },
            )
            # #endregion
        # #region agent log
        self._debug_log(
            "H6",
            "damai_app_v2.py:smart_wait_and_click:return_false",
            "all_selectors_failed",
            {"selector_count": len(selectors)},
        )
        # #endregion
        return False

    def _pull_to_refresh(self):
        """模拟下拉刷新，按屏幕尺寸自适应坐标"""
        try:
            size = self.driver.get_window_size()
            x = size['width'] // 2
            y_start = int(size['height'] * 0.25)
            y_end = int(size['height'] * 0.75)
            self.driver.swipe(x, y_start, x, y_end, 300)
        except Exception as e:
            # 单次刷新失败不应中断整个等开售循环
            print(f"下拉刷新失败: {e}")

    def _wait_for_tickets_open(self, max_attempts=0, interval=0.2):
        """等开售循环：未检测到可下单则下拉刷新继续等待

        命中以下任一信号即视为已开售并返回 True：
          A. 购买按钮 tv_left_main_text 文本为"立即购买"
          B. 票价容器 project_detail_perform_price_flowlayout 下存在 clickable=true 的子元素

        max_attempts=0 表示无限刷新直到开售；>0 时达到上限后返回 False，主流程会继续往下走
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                btn_elements = self.driver.find_elements(By.ID, 'cn.damai:id/tv_left_main_text')
                if btn_elements and '立即购买' in (btn_elements[0].text or ''):
                    print(f"检测到'立即购买'，结束等待（共刷新 {attempts - 1} 次）")
                    return True
            except Exception:
                pass

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
                        print(f"检测到可点击票档，结束等待（共刷新 {attempts - 1} 次）")
                        return True
            except Exception:
                pass

            if max_attempts and attempts >= max_attempts:
                print(f"已刷新 {max_attempts} 次仍未开售，跳出等待并尝试后续流程")
                return False

            self._pull_to_refresh()
            time.sleep(interval)

    def _click_purchase_button(self):
        """开售后点击购票入口，支持多选择器兜底"""
        print("点击购票按钮...")
        current_activity = getattr(self.driver, "current_activity", "")
        current_package = getattr(self.driver, "current_package", "")
        self.last_purchase_entry_result = {
            "success": False,
            "route": None,
            "activity_before": current_activity,
            "package_before": current_package,
        }
        print(f"购票入口点击前页面: activity={current_activity}, package={current_package}")
        # #region agent log
        self._debug_log(
            "H1",
            "damai_app_v2.py:_click_purchase_button:entry",
            "purchase_step_context",
            {
                "current_activity": current_activity,
                "current_package": current_package,
                "window_size": self.driver.get_window_size(),
            },
        )
        # #endregion
        seat_selectors = [
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("选座购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("选座购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("选座")'),
            (By.XPATH, '//*[contains(@text,"选座购票")]')
        ]
        # #region agent log
        self._debug_log(
            "H2",
            "damai_app_v2.py:_click_purchase_button:seat_probe",
            "seat_selector_probe",
            {
                "probes": [
                    {"by": str(seat_selectors[0][0]), "value": seat_selectors[0][1], **self._probe_selector_count(*seat_selectors[0])},
                    {"by": str(seat_selectors[1][0]), "value": seat_selectors[1][1], **self._probe_selector_count(*seat_selectors[1])},
                    {"by": str(seat_selectors[2][0]), "value": seat_selectors[2][1], **self._probe_selector_count(*seat_selectors[2])},
                    {"by": str(seat_selectors[3][0]), "value": seat_selectors[3][1], **self._probe_selector_count(*seat_selectors[3])},
                ]
            },
        )
        # #endregion
        # #region agent log
        self._debug_log(
            "H7",
            "damai_app_v2.py:_click_purchase_button:desc_probe",
            "seat_content_desc_probe",
            {
                "probes": [
                    {
                        "by": str(AppiumBy.ANDROID_UIAUTOMATOR),
                        "value": 'new UiSelector().descriptionContains("选座")',
                        **self._probe_selector_count(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("选座")'),
                    },
                    {
                        "by": str(AppiumBy.ANDROID_UIAUTOMATOR),
                        "value": 'new UiSelector().descriptionContains("购票")',
                        **self._probe_selector_count(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("购票")'),
                    },
                ]
            },
        )
        # #endregion
        if self.smart_wait_and_click(*seat_selectors[0], seat_selectors[1:], timeout=1.2):
            print("已命中购票入口: 选座购票")
            self.last_purchase_entry_result["success"] = True
            self.last_purchase_entry_result["route"] = "seat_selectors"
            # #region agent log
            self._debug_log(
                "H2",
                "damai_app_v2.py:_click_purchase_button:seat_hit",
                "seat_selector_click_success",
                {"timeout": 1.2},
            )
            # #endregion
            return True

        buy_selectors = [
            (By.ID, 'cn.damai:id/tv_left_main_text'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("特惠购票")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("立即购买")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("购买")'),
            (By.XPATH, '//*[contains(@text,"特惠购票") or contains(@text,"立即购买") or contains(@text,"购买")]')
        ]
        # #region agent log
        self._debug_log(
            "H4",
            "damai_app_v2.py:_click_purchase_button:buy_probe",
            "buy_selector_probe",
            {
                "timeout": 1.5,
                "probes": [
                    {"by": str(buy_selectors[0][0]), "value": buy_selectors[0][1], **self._probe_selector_count(*buy_selectors[0])},
                    {"by": str(buy_selectors[1][0]), "value": buy_selectors[1][1], **self._probe_selector_count(*buy_selectors[1])},
                    {"by": str(buy_selectors[2][0]), "value": buy_selectors[2][1], **self._probe_selector_count(*buy_selectors[2])},
                    {"by": str(buy_selectors[3][0]), "value": buy_selectors[3][1], **self._probe_selector_count(*buy_selectors[3])},
                    {"by": str(buy_selectors[4][0]), "value": buy_selectors[4][1], **self._probe_selector_count(*buy_selectors[4])},
                ],
            },
        )
        # #endregion
        if self.smart_wait_and_click(*buy_selectors[0], buy_selectors[1:], timeout=1.5):
            print("已命中购票入口: 常规购买按钮")
            self.last_purchase_entry_result["success"] = True
            self.last_purchase_entry_result["route"] = "buy_selectors"
            # #region agent log
            self._debug_log(
                "H4",
                "damai_app_v2.py:_click_purchase_button:buy_hit",
                "buy_selector_click_success",
                {"timeout": 1.5},
            )
            # #endregion
            return True

        fallback_selector = (
            By.XPATH,
            '//android.widget.FrameLayout[@resource-id="cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"]/android.widget.LinearLayout'
        )
        # #region agent log
        self._debug_log(
            "H5",
            "damai_app_v2.py:_click_purchase_button:fallback_probe",
            "fallback_selector_probe",
            {
                "by": str(fallback_selector[0]),
                "value": fallback_selector[1],
                **self._probe_selector_count(*fallback_selector),
            },
        )
        # #endregion
        if self.ultra_fast_click(
            By.XPATH,
            '//android.widget.FrameLayout[@resource-id="cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"]/android.widget.LinearLayout'
        ):
            print("已命中购票入口: 容器兜底点击")
            self.last_purchase_entry_result["success"] = True
            self.last_purchase_entry_result["route"] = "fallback_container"
            # #region agent log
            self._debug_log(
                "H5",
                "damai_app_v2.py:_click_purchase_button:fallback_hit",
                "fallback_click_success",
                {},
            )
            # #endregion
            return True

        print("未命中任何购票入口")
        print(
            "购票入口点击失败上下文: "
            f"activity={getattr(self.driver, 'current_activity', '')}, "
            f"package={getattr(self.driver, 'current_package', '')}"
        )
        
        # #region agent log
        self._debug_log(
            "H3",
            "damai_app_v2.py:_click_purchase_button:all_miss",
            "no_purchase_selector_matched",
            {},
        )
        # #endregion
        return False

    def debug_enter_seat_purchase_detail(self, hold_seconds=20):
        """调试入口：仅点击购票入口并停留，方便人工观察页面状态。"""
        result = {
            "ok": False,
            "entry_route": None,
            "activity_before": getattr(self.driver, "current_activity", ""),
            "package_before": getattr(self.driver, "current_package", ""),
            "activity_after": "",
            "package_after": "",
            "hold_seconds": hold_seconds,
        }
        try:
            print("开始执行调试流程：进入选座购买详情页")
            clicked = self._click_purchase_button()
            result["ok"] = clicked
            result["entry_route"] = self.last_purchase_entry_result.get("route")
            result["activity_after"] = getattr(self.driver, "current_activity", "")
            result["package_after"] = getattr(self.driver, "current_package", "")
            print(f"调试结果: {json.dumps(result, ensure_ascii=False)}")
            if clicked and hold_seconds > 0:
                print(f"已进入购票入口，保持 {hold_seconds} 秒供人工观察...")
                time.sleep(hold_seconds)
            return result
        except Exception as e:
            result["error"] = str(e)
            result["activity_after"] = getattr(self.driver, "current_activity", "")
            result["package_after"] = getattr(self.driver, "current_package", "")
            print(f"调试流程异常: {json.dumps(result, ensure_ascii=False)}")
            return result
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass

    def _select_price(self):
        """选择票档：优先按配置索引，失败则兜底点击可选票档"""
        print("选择票价...")
        try:
            price_container = self.driver.find_element(By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout')
            target_price = price_container.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().className("android.widget.FrameLayout").index({self.config.price_index}).clickable(true)'
            )
            self.driver.execute_script('mobile: clickGesture', {'elementId': target_price.id})
            return True
        except Exception as e:
            print(f"按索引选择票价失败，尝试兜底方案: {e}")

        try:
            price_container = self.driver.find_element(By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout')
            clickable_prices = price_container.find_elements(
                AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().clickable(true)'
            )
            if clickable_prices:
                self.driver.execute_script('mobile: clickGesture', {'elementId': clickable_prices[0].id})
                return True
        except Exception as e:
            print(f"票档兜底点击失败: {e}")
        return False

    def run_ticket_grabbing(self):
        """执行抢票主流程"""
        try:
            print("开始抢票流程...")
            start_time = time.time()

            # 1. 已在目标详情页，仅保留开售前刷新等待
            if getattr(self.config, 'enable_refresh', False):
                print("等待开售（下拉刷新中）...")
                self._wait_for_tickets_open(
                    max_attempts=self.config.max_refresh_attempts,
                    interval=self.config.refresh_interval,
                )

            # 2. 开售后点击购票
            if not self._click_purchase_button():
                print("未找到购票入口，流程终止")
                return False

            # 3. 选择票档
            if not self._select_price():
                print("未能选择票档，流程终止")
                return False

            # 4. 下单确认并提交
            print("确认购买...")
            self.smart_wait_and_click(
                By.ID,
                "btn_buy_view",
                backup_selectors=[
                    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*确定.*|.*购买.*")')
                ],
                timeout=1.5
            )

            print("提交订单...")
            submit_selectors = [
                (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("立即提交")'),
                (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*提交.*|.*确认.*")'),
                (By.XPATH, '//*[contains(@text,"提交")]')
            ]
            self.smart_wait_and_click(*submit_selectors[0], submit_selectors[1:])

            end_time = time.time()
            print(f"抢票流程完成，耗时: {end_time - start_time:.2f}秒")
            return True

        except Exception as e:
            print(f"抢票过程发生错误: {e}")
            return False
        finally:
            time.sleep(1)  # 给最后的操作一点时间
            self.driver.quit()

    def run_with_retry(self, max_retries=3):
        """带重试机制的抢票"""
        for attempt in range(max_retries):
            print(f"第 {attempt + 1} 次尝试...")
            if self.run_ticket_grabbing():
                print("抢票成功！")
                return True
            else:
                print(f"第 {attempt + 1} 次尝试失败")
                if attempt < max_retries - 1:
                    print("2秒后重试...")
                    time.sleep(2)
                    # 重新初始化驱动
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self._setup_driver()

        print("所有尝试均失败")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="大麦抢票自动化脚本")
    parser.add_argument(
        "--debug-enter-seat-detail",
        action="store_true",
        help="仅执行进入选座购票详情页的调试流程",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=20,
        help="调试模式下进入后保持页面秒数",
    )
    args = parser.parse_args()

    bot = DamaiBot()
    if args.debug_enter_seat_detail:
        debug_result = bot.debug_enter_seat_purchase_detail(hold_seconds=args.hold_seconds)
        sys.exit(0 if debug_result.get("ok") else 1)
    bot.run_with_retry(max_retries=3)
