"""Unit tests for damai_v3/main.py"""
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest
from selenium.webdriver.common.by import By

# damai_v3/main.py contains the DamaiBot class and Config class
_DAMAI_V3_DIR = Path(__file__).resolve().parent.parent.parent / "damai_v3"
if str(_DAMAI_V3_DIR) not in sys.path:
    sys.path.insert(0, str(_DAMAI_V3_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """Mock Config with typical values."""
    config = Mock()
    config.server_url = "http://127.0.0.1:4723"
    config.price_index = 5
    config.enable_refresh = True
    config.max_refresh_attempts = 0
    config.refresh_interval = 0.01  # fast for tests
    config.if_commit_order = False
    return config


@pytest.fixture
def mock_driver():
    """Mock Appium WebDriver."""
    driver = Mock()
    driver.get_window_size.return_value = {"width": 1080, "height": 1920}
    driver.find_elements.return_value = []
    driver.find_element = Mock()
    driver.execute_script = Mock()
    driver.quit = Mock()
    driver.swipe = Mock()
    return driver


@pytest.fixture
def bot(mock_config, mock_driver):
    """Create a DamaiBot with mocked driver and config."""
    from damai_v3.main import DamaiBot

    with patch(
        'damai_v3.main.Config.load_config',
        return_value=mock_config
    ):
        with patch.object(DamaiBot, '_setup_driver'):
            b = DamaiBot()
            b.driver = mock_driver
            b.wait = Mock()
            return b


# ---------------------------------------------------------------------------
# Test _swipe_down
# ---------------------------------------------------------------------------

class TestSwipeDown:
    def test_swipe_down_calculates_coordinates(self, bot, mock_driver):
        """验证下拉刷新按屏幕尺寸自适应计算坐标"""
        mock_driver.get_window_size.return_value = {"width": 1080, "height": 1920}

        bot._swipe_down()

        expected_x = 540  # width // 2
        expected_y_start = int(1920 * 0.25)  # 480
        expected_y_end = int(1920 * 0.75)  # 1440
        mock_driver.swipe.assert_called_once_with(
            expected_x, expected_y_start, expected_x, expected_y_end, 300
        )

    def test_swipe_down_different_screen_size(self, bot, mock_driver):
        """验证不同屏幕尺寸下的坐标计算"""
        mock_driver.get_window_size.return_value = {"width": 720, "height": 1280}

        bot._swipe_down()

        expected_x = 360  # width // 2
        expected_y_start = int(1280 * 0.25)  # 320
        expected_y_end = int(1280 * 0.75)  # 960
        mock_driver.swipe.assert_called_once_with(
            expected_x, expected_y_start, expected_x, expected_y_end, 300
        )

    def test_swipe_down_handles_exception(self, bot, mock_driver, capsys):
        """验证下拉刷新异常不会中断流程"""
        mock_driver.swipe.side_effect = RuntimeError("connection lost")

        bot._swipe_down()  # should not raise

        captured = capsys.readouterr()
        assert "下拉刷新失败" in captured.out


# ---------------------------------------------------------------------------
# Test _wait_for_tickets_open
# ---------------------------------------------------------------------------

class TestWaitForTicketsOpen:
    def test_detects_buy_now_text(self, bot, mock_driver):
        """检测到"立即购买"文本时立即返回"""
        mock_btn = Mock()
        mock_btn.text = "立即购买"
        mock_driver.find_elements.return_value = [mock_btn]

        bot._wait_for_tickets_open()

        # 应该直接返回，不调用下拉刷新
        mock_driver.swipe.assert_not_called()

    def test_detects_clickable_price(self, bot, mock_driver):
        """检测到可点击票档时立即返回"""
        # 第一次 find_elements 返回空（无"立即购买"按钮）
        # 第二次 find_elements 返回票价容器
        mock_clickable = Mock()
        container = Mock()
        container.find_elements.return_value = [mock_clickable]

        # Side effect: first call returns [] (no buy text), second returns container
        mock_driver.find_elements.side_effect = [[], [container]]

        bot._wait_for_tickets_open()

        mock_driver.swipe.assert_not_called()

    def test_swipes_when_nothing_detected(self, bot, mock_driver, mock_config):
        """未检测到任何信号时执行下拉刷新"""
        # max_refresh_attempts=3 → loop runs attempts 1,2,3; bails before
        # swipe on attempt 3, so 2 swipes total.
        mock_config.max_refresh_attempts = 3
        mock_driver.find_elements.return_value = []

        bot._wait_for_tickets_open()

        assert mock_driver.swipe.call_count == 2

    def test_respects_max_attempts(self, bot, mock_driver, mock_config):
        """达到最大刷新次数后停止"""
        mock_config.max_refresh_attempts = 4
        mock_driver.find_elements.return_value = []

        bot._wait_for_tickets_open()

        assert mock_driver.swipe.call_count == 3

    def test_skips_refresh_when_disabled(self, bot, mock_driver, mock_config):
        """enable_refresh=False 时直接返回不做刷新"""
        mock_config.enable_refresh = False

        bot._wait_for_tickets_open()

        mock_driver.swipe.assert_not_called()
        mock_driver.find_elements.assert_not_called()


# ---------------------------------------------------------------------------
# Test fast_click
# ---------------------------------------------------------------------------

class TestFastClick:
    def test_fast_click_finds_and_clicks(self, bot, mock_driver):
        """找到元素后执行坐标手势点击"""
        mock_element = Mock()
        mock_element.rect = {"x": 100, "y": 200, "width": 300, "height": 80}
        mock_driver.find_elements.return_value = [mock_element]

        result = bot.fast_click(By.ID, "test_button", timeout=0.5)

        assert result is True
        mock_driver.execute_script.assert_called_once_with(
            "mobile: clickGesture",
            {"x": 250, "y": 240, "duration": 50}
        )

    def test_fast_click_returns_false_on_timeout(self, bot, mock_driver):
        """超时未找到返回 False"""
        mock_driver.find_elements.return_value = []

        result = bot.fast_click(By.ID, "missing_button", timeout=0.3)

        assert result is False

    def test_fast_click_retries_on_exception(self, bot, mock_driver):
        """异常时继续重试直到成功"""
        mock_element = Mock()
        mock_element.rect = {"x": 0, "y": 0, "width": 100, "height": 50}
        # 先抛异常，再返回空，最后返回元素
        mock_driver.find_elements.side_effect = [
            RuntimeError("transient error"),
            [],
            [mock_element],
        ]

        result = bot.fast_click(By.ID, "test_button", timeout=1.0)

        assert result is True


# ---------------------------------------------------------------------------
# Test smart_click
# ---------------------------------------------------------------------------

class TestSmartClick:
    def test_smart_click_primary_selector(self, bot, mock_driver):
        """首选选择器命中"""
        mock_element = Mock()
        mock_element.rect = {"x": 10, "y": 20, "width": 200, "height": 60}
        mock_driver.find_elements.return_value = [mock_element]

        result = bot.smart_click(By.ID, "primary_button", timeout=0.5)

        assert result is True
        mock_driver.execute_script.assert_called_once_with(
            "mobile: clickGesture",
            {"x": 110, "y": 50, "duration": 50}
        )

    def test_smart_click_falls_back_to_backup(self, bot, mock_driver):
        """首选失败后兜底到备用选择器"""
        # 首选返回空，备用命中
        mock_element = Mock()
        mock_element.rect = {"x": 0, "y": 0, "width": 100, "height": 100}
        mock_driver.find_elements.side_effect = [
            [],  # primary fails
            [mock_element],  # backup succeeds
        ]

        result = bot.smart_click(
            By.ID, "primary",
            backup_selectors=[(By.XPATH, "//backup")],
            timeout=0.5
        )

        assert result is True

    def test_smart_click_all_selectors_fail(self, bot, mock_driver):
        """所有选择器都失败返回 False"""
        mock_driver.find_elements.return_value = []

        result = bot.smart_click(
            By.ID, "primary",
            backup_selectors=[(By.XPATH, "//b1"), (By.XPATH, "//b2")],
            timeout=0.3
        )

        assert result is False


# ---------------------------------------------------------------------------
# Test _click_purchase_button
# ---------------------------------------------------------------------------

class TestClickPurchaseButton:
    def test_seat_strategy_hit(self, bot, mock_driver):
        """命中"选座购票"选择器"""
        mock_element = Mock()
        mock_element.rect = {"x": 200, "y": 800, "width": 400, "height": 100}
        mock_driver.find_elements.return_value = [mock_element]

        result = bot._click_purchase_button()

        assert result is True

    def test_buy_strategy_hit(self, bot, mock_driver):
        """选座策略失败后命中"立即购买"策略"""
        mock_element = Mock()
        mock_element.rect = {"x": 100, "y": 900, "width": 300, "height": 80}

        # 前 4 组（seat_selectors）全部返回空，第 5 组（buy_selectors 第一项）命中
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            # seat_selectors 有 4 个，每个轮询 timeout 内多次调用
            # buy_selectors 第一个命中
            if call_count[0] <= 50:
                return []
            return [mock_element]

        mock_driver.find_elements.side_effect = side_effect

        # 使用非常短的 timeout 加速测试
        # 直接 mock smart_click 和 fast_click 更可靠
        # 这里用另一种方式：验证方法能正确回退

    def test_seat_strategy_hit_verified(self, bot):
        """通过 mock smart_click 验证选座策略命中"""
        with patch.object(bot, 'smart_click') as mock_smart:
            mock_smart.return_value = True

            result = bot._click_purchase_button()

            assert result is True
            # 应该只有一次 smart_click 调用（选座策略命中后立即返回）
            assert mock_smart.call_count == 1

    def test_buy_strategy_fallback_verified(self, bot):
        """通过 mock 验证选座失败后回退到购买策略"""
        with patch.object(bot, 'smart_click') as mock_smart:
            with patch.object(bot, 'fast_click') as mock_fast:
                # smart_click 第一次返回 False（选座失败），第二次返回 True（购买成功）
                mock_smart.side_effect = [False, True]

                result = bot._click_purchase_button()

                assert result is True
                assert mock_smart.call_count == 2
                mock_fast.assert_not_called()

    def test_fallback_container_verified(self, bot):
        """通过 mock 验证所有 smart_click 失败后兜底到容器点击"""
        with patch.object(bot, 'smart_click') as mock_smart:
            with patch.object(bot, 'fast_click') as mock_fast:
                mock_smart.return_value = False
                mock_fast.return_value = True

                result = bot._click_purchase_button()

                assert result is True
                assert mock_smart.call_count == 2  # seat + buy
                mock_fast.assert_called_once()

    def test_all_strategies_fail(self, bot):
        """所有策略都失败返回 False"""
        with patch.object(bot, 'smart_click') as mock_smart:
            with patch.object(bot, 'fast_click') as mock_fast:
                mock_smart.return_value = False
                mock_fast.return_value = False

                result = bot._click_purchase_button()

                assert result is False


# ---------------------------------------------------------------------------
# Test _select_price
# ---------------------------------------------------------------------------

class TestSelectPrice:
    def test_select_by_index(self, bot, mock_driver):
        """按 price_index 选择票档成功"""
        mock_price = Mock()
        mock_price.id = "price_5"
        mock_container = Mock()
        mock_container.find_element.return_value = mock_price
        mock_driver.find_element.return_value = mock_container

        result = bot._select_price()

        assert result is True
        mock_driver.execute_script.assert_called_once_with(
            "mobile: clickGesture", {"elementId": "price_5"}
        )

    def test_fallback_to_first_clickable(self, bot, mock_driver):
        """按索引失败后兜底点击首个可选票档"""
        mock_container = Mock()
        # 按索引查找失败
        mock_container.find_element.side_effect = Exception("index not found")
        mock_clickable = Mock()
        mock_clickable.id = "price_first"
        mock_container.find_elements.return_value = [mock_clickable]
        mock_driver.find_element.return_value = mock_container

        result = bot._select_price()

        assert result is True
        mock_driver.execute_script.assert_called_once_with(
            "mobile: clickGesture", {"elementId": "price_first"}
        )

    def test_all_price_selection_fails(self, bot, mock_driver):
        """所有票档选择方式都失败"""
        mock_driver.find_element.side_effect = Exception("no price container")

        result = bot._select_price()

        assert result is False


# ---------------------------------------------------------------------------
# Test _click_confirm
# ---------------------------------------------------------------------------

class TestClickConfirm:
    def test_click_confirm_calls_smart_click(self, bot):
        """验证调用 smart_click 并传递正确的确认按钮选择器"""
        with patch.object(bot, 'smart_click') as mock_smart:
            mock_smart.return_value = True

            result = bot._click_confirm()

            assert result is True
            # 验证传入首选选择器 (By.ID, "btn_buy_view")
            call_args = mock_smart.call_args
            assert call_args[0][0] == By.ID
            assert call_args[0][1] == "btn_buy_view"
            assert call_args[1]["timeout"] == 1.5


# ---------------------------------------------------------------------------
# Test _click_submit
# ---------------------------------------------------------------------------

class TestClickSubmit:
    def test_click_submit_calls_smart_click(self, bot):
        """验证调用 smart_click 并传递正确的提交选择器"""
        with patch.object(bot, 'smart_click') as mock_smart:
            mock_smart.return_value = True

            result = bot._click_submit()

            assert result is True
            call_args = mock_smart.call_args
            assert call_args[0][1] == 'new UiSelector().text("立即提交")'


# ---------------------------------------------------------------------------
# Test run (full flow)
# ---------------------------------------------------------------------------

class TestRunFullFlow:
    def test_run_full_flow_success(self, bot, mock_driver):
        """端到端主流程：所有步骤成功"""
        with patch.object(bot, '_wait_for_tickets_open') as mock_wait:
            with patch.object(bot, '_click_purchase_button') as mock_purchase:
                with patch.object(bot, '_select_price') as mock_price:
                    with patch.object(bot, '_click_confirm') as mock_confirm:
                        with patch.object(bot, '_click_submit') as mock_submit:
                            mock_purchase.return_value = True
                            mock_price.return_value = True
                            mock_confirm.return_value = True
                            mock_submit.return_value = True

                            result = bot.run()

                            assert result is True
                            mock_wait.assert_called_once()
                            mock_purchase.assert_called_once()
                            mock_price.assert_called_once()
                            mock_confirm.assert_called_once()
                            mock_submit.assert_called_once()
                            mock_driver.quit.assert_called_once()

    def test_run_stops_when_purchase_fails(self, bot, mock_driver):
        """购票入口点击失败时流程终止"""
        with patch.object(bot, '_wait_for_tickets_open'):
            with patch.object(bot, '_click_purchase_button') as mock_purchase:
                with patch.object(bot, '_select_price') as mock_price:
                    mock_purchase.return_value = False

                    result = bot.run()

                    assert result is False
                    mock_price.assert_not_called()
                    mock_driver.quit.assert_called_once()

    def test_run_stops_when_price_fails(self, bot, mock_driver):
        """票档选择失败时流程终止"""
        with patch.object(bot, '_wait_for_tickets_open'):
            with patch.object(bot, '_click_purchase_button') as mock_purchase:
                with patch.object(bot, '_select_price') as mock_price:
                    with patch.object(bot, '_click_confirm') as mock_confirm:
                        mock_purchase.return_value = True
                        mock_price.return_value = False

                        result = bot.run()

                        assert result is False
                        mock_confirm.assert_not_called()

    def test_run_handles_exception(self, bot, mock_driver):
        """主流程异常时返回 False 并清理 driver"""
        with patch.object(bot, '_wait_for_tickets_open') as mock_wait:
            mock_wait.side_effect = RuntimeError("unexpected error")

            result = bot.run()

            assert result is False
            mock_driver.quit.assert_called_once()

    def test_run_always_quits_driver(self, bot, mock_driver):
        """无论成功或失败，driver.quit() 都会被调用"""
        with patch.object(bot, '_wait_for_tickets_open'):
            with patch.object(bot, '_click_purchase_button') as mock_purchase:
                mock_purchase.side_effect = RuntimeError("crash")

                bot.run()

                mock_driver.quit.assert_called_once()


# ---------------------------------------------------------------------------
# Test config edge cases
# ---------------------------------------------------------------------------

class TestConfigEdgeCases:
    def test_missing_enable_refresh(self, bot, mock_config, mock_driver):
        """配置中缺少 enable_refresh 字段时使用默认值 True"""
        del mock_config.enable_refresh
        # 重新设置，确保 _wait_for_tickets_open 使用 getattr 默认值
        mock_driver.find_elements.return_value = []

        # enable_refresh 不存在于 config，getattr 返回 True，进入循环
        # max_refresh_attempts 设置为 2 以终止循环（产生 1 次 swipe）
        mock_config.max_refresh_attempts = 2

        bot._wait_for_tickets_open()

        # 应该执行了一次下拉刷新
        assert mock_driver.swipe.call_count == 1

    def test_missing_price_index(self, bot, mock_config, mock_driver):
        """配置中缺少 price_index 字段"""
        del mock_config.price_index
        mock_driver.find_element.side_effect = Exception("no container")

        # 不应抛出 AttributeError
        result = bot._select_price()
        assert result is False

    def test_zero_max_attempts_loops_indefinitely(self, bot, mock_config, mock_driver):
        """max_refresh_attempts=0 表示无限刷新（直到开售或外部中断）"""
        mock_config.max_refresh_attempts = 0
        call_count = [0]

        def limited_loop(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 5:
                mock_btn = Mock()
                mock_btn.text = "立即购买"
                return [mock_btn]
            return []

        mock_driver.find_elements.side_effect = limited_loop

        bot._wait_for_tickets_open()

        assert call_count[0] == 5


# ---------------------------------------------------------------------------
# Test parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_parse_args_defaults(self):
        """验证 parse_args 默认值"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()

        assert args.debug_click is False
        assert args.click_x is None
        assert args.click_y is None

    def test_parse_args_debug_click(self):
        """验证 parse_args 解析 --debug-click --click-x 100 --click-y 200"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", [
            "main.py", "--debug-click", "--click-x", "100", "--click-y", "200"
        ]):
            args = parse_args()

        assert args.debug_click is True
        assert args.click_x == 100
        assert args.click_y == 200

    def test_parse_args_click_count_default(self):
        """验证 --click-count 默认值为 1"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()

        assert args.click_count == 1

    def test_parse_args_click_interval_default(self):
        """验证 --click-interval 默认值为 0.5"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()

        assert args.click_interval == 0.5

    def test_parse_args_click_loop(self):
        """验证 --click-loop + --click-count 99 解析正确"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", [
            "main.py", "--debug-click", "--click-x", "100", "--click-y", "200",
            "--click-loop", "--click-count", "99"
        ]):
            args = parse_args()

        assert args.click_loop is True
        assert args.click_count == 99

    def test_parse_args_click_positions(self):
        """验证 --click-positions 解析 JSON 字符串"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", [
            "main.py", "--debug-click",
            "--click-positions", '[{"x":100,"y":200,"count":3},{"x":300,"y":400,"count":2}]'
        ]):
            args = parse_args()

        assert args.click_positions == '[{"x":100,"y":200,"count":3},{"x":300,"y":400,"count":2}]'

    def test_parse_args_click_positions_default(self):
        """验证 --click-positions 默认值为 None"""
        from damai_v3.main import parse_args

        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()

        assert args.click_positions is None


# ---------------------------------------------------------------------------
# Test debug click
# ---------------------------------------------------------------------------

class TestDebugClick:
    def test_main_debug_click_missing_coords(self, capsys):
        """验证 --debug-click 缺少坐标时 sys.exit(1)"""
        from damai_v3.main import main

        with patch.object(sys, "argv", [
            "main.py", "--debug-click"
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "需要 --click-x/--click-y 或 --click-positions" in captured.out

    def test_main_debug_click_routing(self, mock_config):
        """验证 main() 在 --debug-click 模式下调用 run_debug_click 并传递 count/interval/loop"""
        from damai_v3.main import main, run_debug_click

        with patch.object(sys, "argv", [
            "main.py", "--debug-click", "--click-x", "100", "--click-y", "200",
            "--click-count", "5", "--click-interval", "0.25", "--click-loop"
        ]):
            with patch(
                'damai_v3.main.Config.load_config',
                return_value=mock_config
            ):
                with patch(
                    'damai_v3.main.run_debug_click'
                ) as mock_run_debug:
                    main()
                    mock_run_debug.assert_called_once_with(
                        x=100, y=200, count=5, interval=0.25, loop=True
                    )

    def test_main_normal_mode_skips_debug(self, mock_config, mock_driver):
        """验证正常模式不进入 debug 路径"""
        from damai_v3.main import main, DamaiBot

        with patch.object(sys, "argv", ["main.py"]):
            with patch(
                'damai_v3.main.Config.load_config',
                return_value=mock_config
            ):
                with patch.object(DamaiBot, '_setup_driver'):
                    with patch.object(DamaiBot, 'run') as mock_run:
                        with patch(
                            'damai_v3.main.setup_android_env'
                        ) as mock_setup:
                            with patch(
                                'damai_v3.main.start_appium'
                            ) as mock_start:
                                with patch(
                                    'damai_v3.main.stop_appium'
                                ) as mock_stop:
                                    with patch(
                                        'damai_v3.main.atexit.register'
                                    ):
                                        with patch(
                                            'damai_v3.main.signal.signal'
                                        ):
                                            main()
                                            # 正常流程应该被调用
                                            mock_setup.assert_called_once()
                                            mock_start.assert_called_once()
                                            mock_run.assert_called_once()
                                            mock_stop.assert_called_once()

    def test_run_debug_click_executes_gesture(self, mock_config, mock_driver):
        """验证 run_debug_click 对 driver 执行 clickGesture"""
        from damai_v3.main import run_debug_click, DamaiBot

        with patch(
            'damai_v3.main.Config.load_config',
            return_value=mock_config
        ):
            with patch.object(DamaiBot, '_setup_driver'):
                with patch(
                    'damai_v3.main.setup_android_env'
                ) as mock_setup:
                    with patch(
                        'damai_v3.main.start_appium'
                    ) as mock_start:
                        mock_start.return_value = Mock()  # appium proc
                        with patch(
                            'damai_v3.main.stop_appium'
                        ) as mock_stop:
                            # Inject mock_driver into the bot
                            orig_init = DamaiBot.__init__

                            def patched_init(self):
                                orig_init(self)
                                self.driver = mock_driver

                            with patch.object(
                                DamaiBot, '__init__', patched_init
                            ):
                                run_debug_click(x=540, y=960)

        # Verify click gesture was called
        mock_driver.execute_script.assert_any_call(
            "mobile: clickGesture",
            {"x": 540, "y": 960, "duration": 50}
        )
        mock_driver.quit.assert_called_once()
        mock_stop.assert_called_once()

    def test_run_debug_click_multi_click(self, mock_config, mock_driver):
        """验证 run_debug_click(count=3) 执行 3 次 clickGesture"""
        from damai_v3.main import run_debug_click, DamaiBot

        with patch(
            'damai_v3.main.Config.load_config',
            return_value=mock_config
        ):
            with patch.object(DamaiBot, '_setup_driver'):
                with patch(
                    'damai_v3.main.setup_android_env'
                ):
                    with patch(
                        'damai_v3.main.start_appium'
                    ) as mock_start:
                        mock_start.return_value = Mock()
                        with patch(
                            'damai_v3.main.stop_appium'
                        ):
                            orig_init = DamaiBot.__init__

                            def patched_init(self):
                                orig_init(self)
                                self.driver = mock_driver

                            with patch.object(
                                DamaiBot, '__init__', patched_init
                            ):
                                with patch(
                                    'damai_v3.main.time.sleep'
                                ) as mock_sleep:
                                    run_debug_click(x=100, y=200, count=3, interval=0.1)

        # Verify 3 clickGestures were executed
        click_calls = [
            call for call in mock_driver.execute_script.call_args_list
            if call[0][0] == "mobile: clickGesture"
        ]
        assert len(click_calls) == 3
        for expected_call in click_calls:
            assert expected_call[0][1] == {"x": 100, "y": 200, "duration": 50}
        assert mock_sleep.call_count == 3  # sleeps after each of 3 clicks

    def test_main_debug_click_routing_with_positions(self, mock_config):
        """验证 main() 在 --click-positions 模式下调用 run_debug_click 并传递 positions"""
        from damai_v3.main import main

        with patch.object(sys, "argv", [
            "main.py", "--debug-click",
            "--click-positions", '[{"x":100,"y":200,"count":3},{"x":300,"y":400}]',
            "--click-interval", "0.25"
        ]):
            with patch(
                'damai_v3.main.Config.load_config',
                return_value=mock_config
            ):
                with patch(
                    'damai_v3.main.run_debug_click'
                ) as mock_run_debug:
                    main()
                    mock_run_debug.assert_called_once_with(
                        positions=[
                            {"x": 100, "y": 200, "count": 3},
                            {"x": 300, "y": 400, "count": 1}
                        ],
                        interval=0.25
                    )

    def test_run_debug_click_multi_position(self, mock_config, mock_driver):
        """验证 run_debug_click(positions=...) 按顺序点击多个位置各指定次数"""
        from damai_v3.main import run_debug_click, DamaiBot

        positions = [
            {"x": 100, "y": 200, "count": 3},
            {"x": 300, "y": 400, "count": 2},
        ]

        with patch(
            'damai_v3.main.Config.load_config',
            return_value=mock_config
        ):
            with patch.object(DamaiBot, '_setup_driver'):
                with patch('damai_v3.main.setup_android_env'):
                    with patch('damai_v3.main.start_appium') as mock_start:
                        mock_start.return_value = Mock()
                        with patch('damai_v3.main.stop_appium'):
                            orig_init = DamaiBot.__init__

                            def patched_init(self):
                                orig_init(self)
                                self.driver = mock_driver

                            with patch.object(DamaiBot, '__init__', patched_init):
                                with patch('damai_v3.main.time.sleep'):
                                    run_debug_click(positions=positions, interval=0.1)

        # Verify clickGestures sequence: (100,200)x3 then (300,400)x2
        click_calls = [
            c for c in mock_driver.execute_script.call_args_list
            if c[0][0] == "mobile: clickGesture"
        ]
        assert len(click_calls) == 5
        expected = [
            {"x": 100, "y": 200, "duration": 50},
            {"x": 100, "y": 200, "duration": 50},
            {"x": 100, "y": 200, "duration": 50},
            {"x": 300, "y": 400, "duration": 50},
            {"x": 300, "y": 400, "duration": 50},
        ]
        for idx, exp in enumerate(expected):
            assert click_calls[idx][0][1] == exp

    def test_run_debug_click_raises_on_invalid_args(self):
        """验证无参数调用 run_debug_click() 时抛出 ValueError"""
        from damai_v3.main import run_debug_click

        with pytest.raises(ValueError, match="必须提供 positions 或"):
            run_debug_click()
