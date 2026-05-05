import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from flask import Flask, jsonify, render_template


BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "ticket_runner.log"
SCRIPT_PATH_V2 = BASE_DIR.parent / "damai_appium" / "damai_app_v2.py"
SCRIPT_PATH_V3 = BASE_DIR / "main.py"
SCRIPT_PATH = SCRIPT_PATH_V3  # V3 目录下默认用 V3
APPIUM_STATUS_URL = "http://127.0.0.1:4723/status"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5001

# ADB 路径（与 damai_v3/main.py 中 ADB_DIR 一致）
_ADB_DIR = r"C:\Users\wangqian\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe"
ADB_EXE = Path(_ADB_DIR) / "platform-tools" / "adb.exe"

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


class TicketProcessManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._started_at = None
        self._last_exit_code = None

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def _snapshot(self):
        running = self.is_running()
        pid = self._process.pid if running else None
        uptime_sec = int(time.time() - self._started_at) if running and self._started_at else 0
        if not running and self._process is not None and self._last_exit_code is None:
            self._last_exit_code = self._process.poll()
        return {
            "running": running,
            "pid": pid,
            "uptime_sec": uptime_sec,
            "started_at": self._started_at,
            "last_exit_code": self._last_exit_code,
        }

    def status(self):
        with self._lock:
            return self._snapshot()

    def run(self):
        with self._lock:
            if self.is_running():
                return False, "抢票脚本已在运行中", self._snapshot()

            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            stdout_handle = LOG_PATH.open("a", encoding="utf-8", buffering=1)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            stdout_handle.write(f"\n========== run at {timestamp} ==========\n")
            self._process = subprocess.Popen(
                [sys.executable, str(SCRIPT_PATH)],
                cwd=str(SCRIPT_PATH.parent),
                stdout=stdout_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._started_at = time.time()
            self._last_exit_code = None
            return True, "抢票脚本已启动", self._snapshot()

    def _terminate_process_tree(self, pid):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def stop(self):
        with self._lock:
            if not self.is_running():
                return False, "当前没有运行中的抢票脚本", self._snapshot()

            pid = self._process.pid
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._terminate_process_tree(pid)
                self._process.wait(timeout=3)

            self._last_exit_code = self._process.poll()
            return True, "抢票脚本已停止", self._snapshot()

    def restart(self):
        with self._lock:
            if self.is_running():
                pid = self._process.pid
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._terminate_process_tree(pid)
                    self._process.wait(timeout=3)
                self._last_exit_code = self._process.poll()

            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            stdout_handle = LOG_PATH.open("a", encoding="utf-8", buffering=1)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            stdout_handle.write(f"\n========== restart at {timestamp} ==========\n")
            self._process = subprocess.Popen(
                [sys.executable, str(SCRIPT_PATH)],
                cwd=str(SCRIPT_PATH.parent),
                stdout=stdout_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._started_at = time.time()
            self._last_exit_code = None
            return True, "抢票脚本已重启", self._snapshot()


manager = TicketProcessManager()
debug_manager = TicketProcessManager()
click_debug_manager = TicketProcessManager()


def json_response(ok, message, data=None):
    return jsonify({"ok": ok, "message": message, "data": data or {}})


def appium_status():
    try:
        with urlopen(APPIUM_STATUS_URL, timeout=2) as response:
            status = response.status
        if status == 200:
            return True, "Appium 可用"
        return False, f"Appium 响应异常: HTTP {status}"
    except URLError as exc:
        return False, f"Appium 不可用: {exc.reason}"
    except Exception as exc:
        return False, f"Appium 状态检查失败: {exc}"


@app.get("/")
def index():
    return render_template("control_panel.html")


@app.post("/api/run")
def run_ticket():
    ok, message, data = manager.run()
    return json_response(ok, message, data)


@app.post("/api/stop")
def stop_ticket():
    ok, message, data = manager.stop()
    return json_response(ok, message, data)


@app.post("/api/restart")
def restart_ticket():
    ok, message, data = manager.restart()
    return json_response(ok, message, data)


@app.post("/api/debug-enter-seat-detail")
def debug_enter_seat_detail():
    with debug_manager._lock:
        if debug_manager.is_running():
            return json_response(False, "选座详情调试任务已在运行中", debug_manager._snapshot())

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        stdout_handle.write(f"\n========== debug enter seat detail at {timestamp} ==========\n")
        debug_manager._process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--debug-enter-seat-detail",
                "--hold-seconds",
                "30",
            ],
            cwd=str(SCRIPT_PATH.parent),
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        debug_manager._started_at = time.time()
        debug_manager._last_exit_code = None
        return json_response(True, "已触发进入选座购买详情页调试", debug_manager._snapshot())


@app.post("/api/debug-click")
def debug_click():
    from flask import request
    data = request.get_json(silent=True) or {}

    # 新格式: positions 数组
    positions = data.get("positions")
    # 旧格式: 单坐标 x/y
    x = data.get("x")
    y = data.get("y")
    interval = float(data.get("interval", 0.5))
    loop = bool(data.get("loop", False))

    if positions is not None:
        # 新格式：多位置点击
        if not isinstance(positions, list) or len(positions) == 0:
            return json_response(False, "positions 必须是非空数组")
        for p in positions:
            if not isinstance(p, dict) or "x" not in p or "y" not in p:
                return json_response(False, "positions 每个元素必须包含 x 和 y")
            p.setdefault("count", 1)
        pos_json = json.dumps(positions)
    elif x is not None and y is not None:
        # 旧格式：单坐标，内部转为 positions
        try:
            x = int(x)
            y = int(y)
        except (ValueError, TypeError):
            return json_response(False, "x 和 y 必须为整数")
        count = int(data.get("count", 1))
        positions = [{"x": x, "y": y, "count": count}]
        pos_json = json.dumps(positions)
    else:
        return json_response(False, "缺少 positions 或 (x, y) 坐标")

    with click_debug_manager._lock:
        if click_debug_manager.is_running():
            return json_response(False, "调试点击任务已在运行中",
                                 click_debug_manager._snapshot())

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        stdout_handle.write(f"\n========== debug click at {timestamp}, "
                            f"positions={pos_json}, interval={interval}"
                            f"{', loop=True' if loop else ''} ==========\n")

        if loop and x is not None:
            # 循环模式：使用旧的 --click-x/--click-y/--click-loop 参数
            cmd = [
                sys.executable,
                str(SCRIPT_PATH_V3),
                "--debug-click",
                "--click-x", str(x),
                "--click-y", str(y),
                "--click-interval", str(interval),
                "--click-loop",
            ]
        else:
            cmd = [
                sys.executable,
                str(SCRIPT_PATH_V3),
                "--debug-click",
                "--click-positions", pos_json,
                "--click-interval", str(interval),
            ]

        click_debug_manager._process = subprocess.Popen(
            cmd,
            cwd=str(SCRIPT_PATH_V3.parent),
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        click_debug_manager._started_at = time.time()
        click_debug_manager._last_exit_code = None
        if positions and len(positions) > 1:
            desc = f"已触发 {len(positions)} 个位置点击"
        elif loop:
            desc = f"已触发坐标 ({x}, {y}) 循环点击"
        else:
            p = positions[0]
            desc = f"已触发坐标 ({p['x']}, {p['y']}) 点击 {p['count']} 次, 间隔 {interval}s"
        return json_response(True, desc + " 调试",
                             click_debug_manager._snapshot())


@app.get("/api/screenshot")
def screenshot():
    try:
        proc = subprocess.run(
            [str(ADB_EXE), "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return json_response(False, f"ADB 截图失败: {proc.stderr.decode()}")
        from flask import Response
        return Response(proc.stdout, mimetype="image/png")
    except FileNotFoundError:
        return json_response(False, "adb.exe 未找到，请检查 ADB_DIR 配置")
    except subprocess.TimeoutExpired:
        return json_response(False, "ADB 截图超时，请检查设备连接")


@app.get("/api/device-size")
def device_size():
    try:
        proc = subprocess.run(
            [str(ADB_EXE), "shell", "wm", "size"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        # 输出格式: "Physical size: 1080x1920"
        line = proc.stdout.strip()
        if "Override size" in line:
            # 如果存在 Override 行，取最后一行 Physical size
            lines = line.split("\n")
            line = [l for l in lines if "Physical size" in l][-1]
        size_str = line.split(":")[-1].strip()
        w, h = size_str.split("x")
        return json_response(True, "ok", {"width": int(w), "height": int(h)})
    except Exception as e:
        return json_response(False, f"获取设备尺寸失败: {e}")


@app.get("/api/status")
def status():
    return json_response(True, "ok", manager.status())


@app.get("/api/appium-status")
def appium_health():
    ok, message = appium_status()
    return json_response(ok, message, {"healthy": ok})


@app.get("/api/logs")
def logs():
    max_lines = 300
    if not LOG_PATH.exists():
        return json_response(True, "暂无日志", {"lines": [], "text": ""})
    with LOG_PATH.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    tail = lines[-max_lines:]
    return json_response(True, "ok", {"lines": tail, "text": "".join(tail)})


def run_control_panel():
    parser = argparse.ArgumentParser(description="抢票控制台")
    parser.add_argument("--host", default=os.getenv("CONTROL_PANEL_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("CONTROL_PANEL_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.getenv("CONTROL_PANEL_DEBUG", "0").lower() in {"1", "true", "yes", "on"},
        help="启用 Flask debug 与热重载",
    )
    parser.add_argument(
        "--version",
        default="v3",
        choices=["v2", "v3"],
        help="选择抢票脚本版本（默认 v3）",
    )
    args = parser.parse_args()

    global SCRIPT_PATH
    if args.version == "v2":
        SCRIPT_PATH = SCRIPT_PATH_V2

    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)


def run_control_panel_dev():
    host = os.getenv("CONTROL_PANEL_HOST", DEFAULT_HOST)
    port = int(os.getenv("CONTROL_PANEL_PORT", str(DEFAULT_PORT)))
    app.run(host=host, port=port, debug=True, use_reloader=True)


if __name__ == "__main__":
    run_control_panel()
