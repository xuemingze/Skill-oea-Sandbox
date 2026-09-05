import sys
import os
import argparse
import subprocess
import time
import requests
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QGroupBox, QFileDialog
)
from PySide6.QtCore import QThread, Signal, Slot, QTimer, Qt
from PySide6.QtGui import QTextCursor

import websocket  # pip install websocket-client

logger = logging.getLogger(__name__)

API_BASE_URL = "http://127.0.0.1:{port}/api/v1/sandbox"
WS_BASE_URL = "ws://127.0.0.1:{port}/ws/logs"
HEALTH_URL = "http://127.0.0.1:{port}/api/v1/health"

# 日志级别 -> 终端颜色映射
LEVEL_COLORS = {
    "INFO": "#a6e22e",    # 标准输出/正常 -> 绿色
    "SYSTEM": "#66d9ef",  # 系统提示 -> 蓝色
    "WARNING": "#fd971f", # 警告 -> 橙色
    "ERROR": "#f92672",   # 报错/拦截警告 -> 红色
    "FATAL": "#f92672",   # 致命 -> 红色
}


class BackendServerManager:
    """跨平台后端子进程生命周期管理器。"""

    def __init__(self):
        self.process = None
        self.backend_main = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "backend", "main.py",
        )
        self.error_log = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sandbox_backend_err.log",
        )

    def launch(self, port: int):
        """非阻塞拉起后端服务（子进程，标准输出/错误重定向避免阻塞 GUI）。"""
        if self.process is not None and self.process.poll() is None:
            return
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [sys.executable, self.backend_main, "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=self._open_err_log(),
            creationflags=creationflags,
        )

    def health_check(self, port: int, retries: int = 5, interval: float = 1.0) -> bool:
        """轮询健康检查接口，确认服务就绪。"""
        url = HEALTH_URL.format(port=port)
        for _ in range(retries):
            time.sleep(interval)
            if self.process is not None and self.process.poll() is not None:
                # 后端进程已退出，无需再等
                return False
            try:
                r = requests.get(url, timeout=1)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
        return False

    def _open_err_log(self):
        """打开后端错误日志文件句柄（stderr 重定向目标）。"""
        try:
            return open(self.error_log, "w", encoding="utf-8", errors="replace")
        except Exception:
            return subprocess.DEVNULL

    def get_error_log(self, lines=12):
        """读取后端 stderr 日志末尾几行，提取关键诊断信息（去 ANSI 颜色码与乱码）。"""
        try:
            if not os.path.exists(self.error_log):
                return ""
            with open(self.error_log, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            # 去掉 ANSI 转义序列
            raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
            # 提取关键诊断片段（错误码/端口/地址占用）
            key = []
            for pat in [r"Errno\s+\d+", r"error while attempting to bind", r"address already in use",
                        r"bind on address \([^)]*\)", r"Errno \[?\d+\]?", r"can't connect"]:
                m = re.search(pat, raw)
                if m:
                    key.append(m.group(0).strip())
            if key:
                return " | ".join(key[-3:])
            lines_tail = re.split(r"\n+", raw.strip())
            return " ".join(lines_tail[-lines:]).strip()
        except Exception:
            return ""

    def stop(self):
        """温和 terminate，3 秒未退出则强制 kill，杜绝僵尸进程。"""
        if self.process is None:
            return
        proc = self.process
        self.process = None
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


class BackendStartWorker(QThread):
    """后台线程：拉起后端 + 健康检查，避免阻塞 Qt 主事件循环。"""
    ready = Signal(int)      # 后端就绪，携带端口
    failed = Signal(str)     # 启动失败，携带错误信息
    log = Signal(str, str)   # level, message

    def __init__(self, manager: BackendServerManager, port: int):
        super().__init__()
        self.manager = manager
        self.port = port

    def run(self):
        try:
            self.log.emit("SYSTEM", f"正在拉起本地后端服务 (端口 {self.port})...")
            self.manager.launch(self.port)
            self.log.emit("SYSTEM", "后端进程已启动，等待健康检查就绪...")
            if self.manager.health_check(self.port):
                self.log.emit("SYSTEM", f"✅ 后端服务已就绪 (端口 {self.port})")
                self.ready.emit(self.port)
            else:
                err = self.manager.get_error_log()
                if err:
                    self.failed.emit(f"后端健康检查超时。启动诊断: {err}")
                else:
                    self.failed.emit(f"后端健康检查超时，端口 {self.port} 未响应（若端口被占请换端口，日志: sandbox_backend_err.log）")
        except Exception as e:
            self.failed.emit(str(e))


class LogReceiverThread(QThread):
    """后台线程：建立 WebSocket 长连接并捕获流式日志。"""
    log_received = Signal(str, str)  # level, message
    finished_signal = Signal()

    def __init__(self, container_id: str, script_name: str, port: int):
        super().__init__()
        self.container_id = container_id
        self.script_name = script_name
        self.port = port
        self.ws = None
        self._is_running = True

    def run(self):
        import urllib.parse
        encoded_script = urllib.parse.quote(self.script_name)
        ws_url = WS_BASE_URL.format(port=self.port) + f"/{self.container_id}?script_name={encoded_script}"
        try:
            self.ws = websocket.create_connection(ws_url, timeout=10)
            while self._is_running:
                try:
                    message = self.ws.recv()
                    if not message:
                        break
                    if message.startswith("[STDOUT]"):
                        self.log_received.emit("INFO", message[len("[STDOUT]"):].strip())
                    elif message.startswith("[STDERR]"):
                        self.log_received.emit("ERROR", message[len("[STDERR]"):].strip())
                    elif message.startswith("[系统异常]"):
                        self.log_received.emit("FATAL", message.strip())
                    else:
                        self.log_received.emit("SYSTEM", message.strip())
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    break
        except Exception as e:
            self.log_received.emit("FATAL", f"连接沙箱日志流失败: {e}")
        finally:
            if self.ws:
                self.ws.close()
            self.finished_signal.emit()

    def stop(self):
        self._is_running = False
        if self.ws:
            self.ws.close()
        self.quit()
        self.wait()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Skill 沙箱测试工作站")
        self.resize(800, 620)

        self.container_id = None
        self.log_thread = None
        self.start_worker = None
        self.server_manager = BackendServerManager()

        self.init_ui()

    # ---------------------------------------------------------------- UI
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        config_group = QGroupBox("测试环境配置")
        config_layout = QVBoxLayout()

        # Skill 目录
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Skill 工作区路径:"))
        self.edit_skill_dir = QLineEdit(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill"))
        row1.addWidget(self.edit_skill_dir)
        btn_browse_skill = QPushButton("浏览...")
        btn_browse_skill.clicked.connect(lambda: self.browse_directory(self.edit_skill_dir))
        row1.addWidget(btn_browse_skill)

        # 目标 Skill 文件
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("目标 Skill 文件:"))
        self.edit_script_name = QLineEdit("skill.md")
        row2.addWidget(self.edit_script_name)
        btn_browse_script = QPushButton("浏览...")
        btn_browse_script.clicked.connect(lambda: self.browse_file(self.edit_script_name))
        row2.addWidget(btn_browse_script)

        # 记忆副本（可选）
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("记忆副本路径:"))
        self.edit_memory_dir = QLineEdit()
        self.edit_memory_dir.setPlaceholderText("请选择历史记忆数据文件，若无则留空")
        row3.addWidget(self.edit_memory_dir)
        btn_browse_memory = QPushButton("浏览...")
        btn_browse_memory.clicked.connect(lambda: self.browse_directory(self.edit_memory_dir))
        row3.addWidget(btn_browse_memory)

        # 后端端口
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("后端端口:"))
        self.edit_port = QLineEdit("8000")
        row4.addWidget(self.edit_port)
        row4.addStretch(1)

        config_layout.addLayout(row1)
        config_layout.addLayout(row2)
        config_layout.addLayout(row3)
        config_layout.addLayout(row4)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 启动测试")
        self.btn_start.clicked.connect(self.start_sandbox_test)
        self.btn_stop = QPushButton("🛑 终止并回收")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_sandbox_test)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        config_layout.addLayout(btn_layout)

        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

        # 终端
        term_group = QGroupBox("仿真终端控制台 (流式输出)")
        term_layout = QVBoxLayout()
        self.text_terminal = QTextEdit()
        self.text_terminal.setReadOnly(True)
        self.text_terminal.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                padding: 10px;
            }
        """)
        term_layout.addWidget(self.text_terminal)
        term_group.setLayout(term_layout)
        main_layout.addWidget(term_group, stretch=1)

    # ------------------------------------------------------- 文件/目录选择
    def browse_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(
            self, "选择目录", line_edit.text() if line_edit.text() else ".")
        if directory:
            line_edit.setText(directory)

    def browse_file(self, line_edit):
        start_dir = "."
        if self.edit_skill_dir.text() and os.path.exists(self.edit_skill_dir.text()):
            start_dir = self.edit_skill_dir.text()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择测试对象", start_dir, "Markdown 文件 (*.md);;所有文件 (*)")
        if file_path:
            line_edit.setText(os.path.basename(file_path))

    # ------------------------------------------------------- 日志
    def append_log(self, level: str, message: str):
        import json
        color = LEVEL_COLORS.get(level, "#d4d4d4")
        
        try:
            # 灏濊瘯瑙ｆ瀽鏄惁涓虹壒瀹氱粨鏋勭殑JSON鏃ュ志
            if message.strip().startswith("{") and message.strip().endswith("}"):
                data = json.loads(message.strip())
                if "node" in data and "action" in data and "status" in data and "details" in data:
                    node = data["node"]
                    action = data["action"]
                    status = data["status"]
                    details = data["details"]
                    
                    status_color = "#a6e22e" if status == "Success" else "#f92672" if status in ["Failed", "Blocked"] else "#fd971f"
                    
                    formatted_msg = f"▸ <b>[{node}]</b> <span style='color:#66d9ef'>操作: {action}</span> | <span style='color:{status_color}'>状态 {status}</span> | 细节: {details}"
                    self.text_terminal.moveCursor(QTextCursor.End)
                    self.text_terminal.insertHtml(f"<div>{formatted_msg}</div>")
                    self.text_terminal.moveCursor(QTextCursor.End)
                    return
        except Exception:
            pass
            
        clean_msg = (message.replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace("\n", "<br>"))
        html = f'<span style="color: {color};">{clean_msg}</span><br>'
        self.text_terminal.moveCursor(QTextCursor.End)
        self.text_terminal.insertHtml(html)
        self.text_terminal.moveCursor(QTextCursor.End)

    # ------------------------------------------------------- 启动测试
    @Slot()
    def start_sandbox_test(self):
        self.text_terminal.clear()

        skill_dir = self.edit_skill_dir.text().strip()
        script_name = self.edit_script_name.text().strip()
        memory_dir = self.edit_memory_dir.text().strip()

        if not script_name:
            self.append_log("ERROR", "目标 Skill 文件不能为空")
            return
        if not skill_dir:
            self.append_log("ERROR", "Skill 工作区路径不能为空")
            return

        try:
            port = int(self.edit_port.text().strip())
        except ValueError:
            self.append_log("ERROR", f"端口号非法: {self.edit_port.text()}")
            return

        self.port = port
        self.req_data = {
            "skill_dir": skill_dir,
            "memory_snapshot_dir": memory_dir if memory_dir else None,
            "target_script": script_name,
        }

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        # 后台异步拉起后端 + 健康检查，不阻塞 UI
        self.start_worker = BackendStartWorker(self.server_manager, port)
        self.start_worker.log.connect(self.append_log)
        self.start_worker.ready.connect(self._on_backend_ready)
        self.start_worker.failed.connect(self._on_backend_failed)
        self.start_worker.start()

    @Slot(int)
    def _on_backend_ready(self, port):
        try:
            res = requests.post(
                API_BASE_URL.format(port=port) + "/start",
                json=self.req_data, timeout=5)
            res_json = res.json()

            if res_json.get("status") == "success":
                self.container_id = res_json.get("container_id")
                self.append_log("SYSTEM", f"✅ 沙箱环境就绪，ID [{self.container_id}]，建立日志流...")
                self.log_thread = LogReceiverThread(
                    self.container_id, self.req_data["target_script"], port)
                self.log_thread.log_received.connect(self.append_log)
                self.log_thread.finished_signal.connect(self.on_sandbox_finished)
                self.log_thread.start()
            else:
                self.append_log("FATAL", f"创建沙箱失败: {res_json.get('msg')}")
                self._shutdown_backend()
                self.reset_ui()
        except Exception as e:
            self.append_log("FATAL", f"无法联通后端调度服务: {e}")
            self._shutdown_backend()
            self.reset_ui()

    @Slot(str)
    def _on_backend_failed(self, msg):
        self.append_log("FATAL", f"后端启动失败: {msg}")
        self._shutdown_backend()
        self.reset_ui()

    # ------------------------------------------------------- 停止/清理
    @Slot()
    def stop_sandbox_test(self):
        self.append_log("SYSTEM", "⚠️ 正在终止执行并回收资源...")
        if self.log_thread:
            self.log_thread.stop()
            self.log_thread = None
        if self.container_id:
            try:
                requests.delete(
                    API_BASE_URL.format(port=self.port) + f"/{self.container_id}", timeout=2)
            except Exception:
                pass
            self.container_id = None
        self._shutdown_backend()
        self.reset_ui()

    @Slot()
    def on_sandbox_finished(self):
        self.append_log("SYSTEM", "🚀 沙箱执行完毕，正在自动清理...")
        if self.container_id:
            try:
                requests.delete(
                    API_BASE_URL.format(port=self.port) + f"/{self.container_id}", timeout=2)
            except Exception:
                pass
            self.container_id = None
        self.log_thread = None
        self._shutdown_backend()
        self.reset_ui()

    def _shutdown_backend(self):
        self.server_manager.stop()

    def reset_ui(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def closeEvent(self, event):
        """窗口关闭时安全清理后端进程与日志线程。"""
        if self.log_thread:
            self.log_thread.stop()
        self._shutdown_backend()
        event.accept()


def parse_args():
    parser = argparse.ArgumentParser(description="Skill 沙箱测试工作站 GUI")
    parser.add_argument("--work-dir", type=str, help="初始化的 Skill 工作区路径")
    parser.add_argument("--skill-file", type=str, help="初始化的目标 Skill 文件 (.md)")
    parser.add_argument("--memory-dir", type=str, help="初始化的记忆副本路径 (可选)")
    parser.add_argument("--port", type=str, default="8000", help="后端服务端口 (默认 8000)")
    parser.add_argument("--auto-run", action="store_true", help="加载完成后自动触发测试")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()

    app = QApplication(sys.argv)
    window = MainWindow()

    if args.work_dir:
        window.edit_skill_dir.setText(args.work_dir)
    if args.skill_file:
        window.edit_script_name.setText(args.skill_file)
    if args.memory_dir:
        window.edit_memory_dir.setText(args.memory_dir)
    if args.port:
        window.edit_port.setText(args.port)

    window.show()

    if args.auto_run:
        QTimer.singleShot(500, window.start_sandbox_test)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()