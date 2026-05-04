import argparse
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
SCRIPT_PATH = BASE_DIR / "damai_app_v2.py"
APPIUM_STATUS_URL = "http://127.0.0.1:4723/status"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5001

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
                [sys.executable, str(SCRIPT_PATH.name)],
                cwd=str(BASE_DIR),
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
                [sys.executable, str(SCRIPT_PATH.name)],
                cwd=str(BASE_DIR),
                stdout=stdout_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._started_at = time.time()
            self._last_exit_code = None
            return True, "抢票脚本已重启", self._snapshot()


manager = TicketProcessManager()
debug_manager = TicketProcessManager()


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
                str(SCRIPT_PATH.name),
                "--debug-enter-seat-detail",
                "--hold-seconds",
                "30",
            ],
            cwd=str(BASE_DIR),
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        debug_manager._started_at = time.time()
        debug_manager._last_exit_code = None
        return json_response(True, "已触发进入选座购买详情页调试", debug_manager._snapshot())


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
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)


def run_control_panel_dev():
    host = os.getenv("CONTROL_PANEL_HOST", DEFAULT_HOST)
    port = int(os.getenv("CONTROL_PANEL_PORT", str(DEFAULT_PORT)))
    app.run(host=host, port=port, debug=True, use_reloader=True)


if __name__ == "__main__":
    run_control_panel()
