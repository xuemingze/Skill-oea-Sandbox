# -*- coding: utf-8 -*-
import sys
import os

frontend_dir = os.path.dirname(os.path.abspath(__file__))
if frontend_dir not in sys.path:
    sys.path.insert(0, frontend_dir)

try:
    from .recycle_panel import RecycleManagerPanel
except (ImportError, ValueError):
    from recycle_panel import RecycleManagerPanel

import json
import argparse
import socket
import re
import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QPlainTextEdit,
    QGroupBox, QFileDialog, QSplitter, QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QTextCursor, QFont, QColor, QIcon
import subprocess
import websocket
import threading
import time

API_BASE_URL = "http://127.0.0.1:{port}/api/v1/sandbox"
WS_LOGS_URL = "ws://127.0.0.1:{port}/ws/logs"


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class BackendServerManager:
    def __init__(self):
        self.process = None
        self.backend_main = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "backend", "main.py"
        )
        self.error_log = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sandbox_backend_err.log"
        )

    def launch(self, port=8000) -> bool:
        if self.process is not None:
            return True
        if not os.path.exists(self.backend_main):
            return False

        try:
            err_file = open(self.error_log, "w", encoding="utf-8", errors="replace")
            self.process = subprocess.Popen(
                [sys.executable, self.backend_main, "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=err_file,
                cwd=os.path.dirname(self.backend_main),
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            return True
        except Exception:
            return False

    def health_check(self, port=8000, retries=8, interval=0.8) -> bool:
        url = f"http://127.0.0.1:{port}/api/v1/health"
        for _ in range(retries):
            if self.process is not None and self.process.poll() is not None:
                return False
            try:
                r = requests.get(url, timeout=1)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(interval)
        return False

    def get_error_log(self, max_lines=5) -> str:
        if not os.path.exists(self.error_log):
            return ""
        try:
            with open(self.error_log, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
            clean_lines = [ansi_re.sub("", l).strip() for l in lines if l.strip()]
            diag = []
            for l in clean_lines:
                if any(kw in l for kw in ["Errno", "error while attempting to bind", "Address already in use", "Error:", "Traceback"]):
                    diag.append(l)
            if diag:
                return " | ".join(diag[-max_lines:])
            return " | ".join(clean_lines[-max_lines:]) if clean_lines else ""
        except Exception:
            return ""

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


class BackendStartWorker(QThread):
    log = Signal(str, str)
    ready = Signal(int)
    failed = Signal(str)

    def __init__(self, server_manager, port):
        super().__init__()
        self.server_manager = server_manager
        self.port = port

    def run(self):
        self.log.emit("INFO", f"正在拉起本地后端服务 (端口 {self.port})...")
        if not self.server_manager.launch(self.port):
            self.failed.emit("后端启动失败: 无法执行启动命令或文件缺失")
            return

        self.log.emit("INFO", "后端进程已启动，等待健康检查就绪...")
        if self.server_manager.health_check(self.port):
            self.log.emit("INFO", f"✅ 后端服务已就绪 (端口 {self.port})")
            self.ready.emit(self.port)
        else:
            diag = self.server_manager.get_error_log()
            if diag:
                msg = f"后端健康检查超时 (端口 {self.port} 异常退出)。诊断: {diag}"
            else:
                msg = f"后端健康检查超时，端口 {self.port} 未响应"
            self.failed.emit(f"后端启动失败: {msg}")


class WebSocketLogWorker(QThread):
    log_received = Signal(str)
    connection_closed = Signal()

    def __init__(self, ws_url):
        super().__init__()
        self.ws_url = ws_url
        self.ws = None
        self._is_running = True

    def run(self):
        def on_message(ws, message):
            self.log_received.emit(message)

        def on_error(ws, error):
            self.log_received.emit(f"[WS ERROR] 连接异常: {error}")

        def on_close(ws, close_status_code, close_msg):
            self.log_received.emit(f"[WS] 连接已断开 ({close_status_code})")
            self.connection_closed.emit()

        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        self.ws.run_forever()

    def stop(self):
        self._is_running = False
        if self.ws:
            self.ws.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Skill 安全沙箱测试与评判工作台 (AI Agent & GUI 双平台)")
        self.resize(1150, 880)

        self.container_id = None
        self.ws_worker = None
        self.server_manager = BackendServerManager()
        self.custom_materials = []  # 存储用户添加的材料对象: [{"type": "image"|"file", "name": "...", "source_path": "...", "size_str": "..."}]

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # 1. 测试环境配置区
        config_group = QGroupBox("⚙️ 测试环境与目标配置")
        config_layout = QVBoxLayout()

        # Skill 目录
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Skill 工作区路径:"))
        default_skill_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill")
        self.edit_skill_dir = QLineEdit(default_skill_dir)
        row1.addWidget(self.edit_skill_dir, 1)
        btn_browse_skill = QPushButton("浏览目录...")
        btn_browse_skill.clicked.connect(lambda: self.browse_directory(self.edit_skill_dir))
        row1.addWidget(btn_browse_skill)

        # 目标 Skill 文件
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("目标 Skill 文件:"))
        self.edit_script_name = QLineEdit("skill.md")
        row2.addWidget(self.edit_script_name, 1)
        btn_browse_script = QPushButton("选择文件...")
        btn_browse_script.clicked.connect(lambda: self.browse_file(self.edit_script_name))
        row2.addWidget(btn_browse_script)

        # 记忆副本与端口
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("记忆副本路径:"))
        self.edit_memory_dir = QLineEdit()
        self.edit_memory_dir.setPlaceholderText("历史记忆数据文件夹路径（可选，若无则留空）")
        row3.addWidget(self.edit_memory_dir, 1)
        btn_browse_memory = QPushButton("浏览目录...")
        btn_browse_memory.clicked.connect(lambda: self.browse_directory(self.edit_memory_dir))
        row3.addWidget(btn_browse_memory)

        row3.addWidget(QLabel("后端端口:"))
        self.edit_port = QLineEdit("8000")
        self.edit_port.setFixedWidth(65)
        row3.addWidget(self.edit_port)

        config_layout.addLayout(row1)
        config_layout.addLayout(row2)
        config_layout.addLayout(row3)
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

        # 2. 新增：交互式测试材料输入面板 (用户话术 / 图片 / 文件)
        material_group = QGroupBox("🎛️ 交互式测试材料 (用户话术指令 / 测试图片 / 待测业务文件)")
        material_layout = QVBoxLayout()
        material_layout.setSpacing(8)

        # 话术输入框
        prompt_label_row = QHBoxLayout()
        prompt_label_row.addWidget(QLabel("💬 自定义测试话术 / 业务指令 (Prompt):"))
        btn_clear_prompt = QPushButton("清空话术")
        btn_clear_prompt.setFixedHeight(22)
        btn_clear_prompt.clicked.connect(lambda: self.edit_user_prompt.clear())
        prompt_label_row.addWidget(btn_clear_prompt)
        prompt_label_row.addStretch(1)
        material_layout.addLayout(prompt_label_row)

        self.edit_user_prompt = QPlainTextEdit()
        self.edit_user_prompt.setFixedHeight(68)
        self.edit_user_prompt.setPlaceholderText(
            "💡 在此输入测试话术/业务指令（例如：'请审查这段Python代码的Bug与严重漏洞'、'提取照片中的送货单发票金额和抬头'）。\n"
            "留空则根据技能的主领域（如 code_development / ocr_document / memory_knowledge）自动匹配自适应测试物料。"
        )
        material_layout.addWidget(self.edit_user_prompt)

        # 交互材料工具条
        mat_toolbar = QHBoxLayout()
        btn_add_image = QPushButton("📷 添加测试图片...")
        btn_add_image.setStyleSheet("padding: 4px 10px; font-weight: bold;")
        btn_add_image.clicked.connect(self.add_image_material)
        mat_toolbar.addWidget(btn_add_image)

        btn_add_file = QPushButton("📄 添加测试文件 (代码/表格/数据)...")
        btn_add_file.setStyleSheet("padding: 4px 10px; font-weight: bold;")
        btn_add_file.clicked.connect(self.add_file_material)
        mat_toolbar.addWidget(btn_add_file)

        btn_clear_all_mat = QPushButton("🧹 清空材料清单")
        btn_clear_all_mat.clicked.connect(self.clear_materials)
        mat_toolbar.addWidget(btn_clear_all_mat)

        self.lbl_material_count = QLabel("已装载材料: 0 份")
        self.lbl_material_count.setStyleSheet("color: #666; font-size: 12px; margin-left: 8px;")
        mat_toolbar.addWidget(self.lbl_material_count)
        mat_toolbar.addStretch(1)
        material_layout.addLayout(mat_toolbar)

        # 已添加材料列表
        self.list_materials = QListWidget()
        self.list_materials.setFixedHeight(75)
        self.list_materials.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_materials.setStyleSheet(
            "QListWidget { background-color: #fcfcfc; border: 1px solid #dcdcdc; border-radius: 4px; padding: 2px; }\n"
            "QListWidget::item { padding: 3px 6px; border-bottom: 1px solid #f0f0f0; }\n"
            "QListWidget::item:selected { background-color: #e6f2ff; color: #0066cc; }"
        )
        material_layout.addWidget(self.list_materials)

        material_group.setLayout(material_layout)
        main_layout.addWidget(material_group)

        # 3. 控制按钮栏
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 启动沙箱测试与评判")
        self.btn_start.setFixedHeight(36)
        self.btn_start.setStyleSheet(
            "QPushButton { background-color: #007acc; color: white; font-size: 14px; font-weight: bold; border-radius: 4px; padding: 6px 16px; }\n"
            "QPushButton:hover { background-color: #005999; }\n"
            "QPushButton:disabled { background-color: #cccccc; color: #888888; }"
        )
        self.btn_start.clicked.connect(self.start_sandbox_test)

        self.btn_stop = QPushButton("🛑 终止并销毁沙箱")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background-color: #d9534f; color: white; font-size: 14px; font-weight: bold; border-radius: 4px; padding: 6px 16px; }\n"
            "QPushButton:hover { background-color: #c9302c; }\n"
            "QPushButton:disabled { background-color: #cccccc; color: #888888; }"
        )
        self.btn_stop.clicked.connect(self.stop_sandbox_test)

        btn_layout.addWidget(self.btn_start, 3)
        btn_layout.addWidget(self.btn_stop, 1)
        main_layout.addLayout(btn_layout)

        # 4. 仿真终端控制台 (流式输出)
        term_group = QGroupBox("💻 仿真终端控制台 (实时状态追踪 / Hook 拦截 / 事实日志)")
        term_layout = QVBoxLayout()
        self.text_terminal = QTextEdit()
        self.text_terminal.setReadOnly(True)
        self.text_terminal.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, 'Courier New', monospace; font-size: 12px; line-height: 1.4;")
        term_layout.addWidget(self.text_terminal)
        term_group.setLayout(term_layout)
        main_layout.addWidget(term_group, 2)

    def add_image_material(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择测试图片文件", "",
            "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp);;所有文件 (*.*)"
        )
        for f in files:
            if os.path.exists(f):
                self._append_material_item("image", f)

    def add_file_material(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择业务测试文件 (代码/数据/表格/文本)", "",
            "所有支持文件 (*.py *.json *.csv *.md *.txt *.pdf *.docx *.*);;Python (*.py);;JSON (*.json);;所有文件 (*.*)"
        )
        for f in files:
            if os.path.exists(f):
                self._append_material_item("file", f)

    def _append_material_item(self, mat_type: str, file_path: str):
        # 避免重复添加同路径
        if any(m["source_path"] == file_path for m in self.custom_materials):
            return
        
        file_name = os.path.basename(file_path)
        try:
            size_b = os.path.getsize(file_path)
            size_str = format_file_size(size_b)
        except OSError:
            size_str = "未知大小"

        item_data = {
            "type": mat_type,
            "name": file_name,
            "source_path": file_path,
            "size_str": size_str
        }
        self.custom_materials.append(item_data)
        
        icon_str = "🖼️" if mat_type == "image" else "📄"
        item_text = f"{icon_str} [{mat_type.upper()}] {file_name} ({size_str}) -> {file_path}"
        list_item = QListWidgetItem(item_text)
        list_item.setToolTip(f"双击或按Delete键移除: {file_path}")
        self.list_materials.addItem(list_item)
        
        self.lbl_material_count.setText(f"已装载材料: {len(self.custom_materials)} 份")

    def clear_materials(self):
        self.custom_materials.clear()
        self.list_materials.clear()
        self.lbl_material_count.setText("已装载材料: 0 份")

    def get_custom_materials_payload(self):
        payload = []
        for m in self.custom_materials:
            payload.append({
                "type": m["type"],
                "name": m["name"],
                "source_path": m["source_path"]
            })
        return payload

    def browse_directory(self, target_line_edit):
        dir_path = QFileDialog.getExistingDirectory(self, "选择工作区目录")
        if dir_path:
            target_line_edit.setText(dir_path)

    def browse_file(self, target_line_edit):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择目标 Skill 文件", "", "Markdown Files (*.md);;Python Files (*.py);;All Files (*.*)")
        if file_path:
            target_line_edit.setText(os.path.basename(file_path))
            dir_name = os.path.dirname(file_path)
            if dir_name:
                self.edit_skill_dir.setText(dir_name)

    def append_log(self, level, message):
        color_map = {
            "INFO": "#569CD6",
            "WARN": "#CE9178",
            "ERROR": "#F44747",
            "SUCCESS": "#4EC9B0",
            "NODE": "#DCDCAA",
            "USER": "#C586C0",
            "JUDGE": "#E5C07B",
            "VERDICT": "#98C379"
        }
        color = color_map.get(level, "#D4D4D4")
        
        cursor = self.text_terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_terminal.setTextCursor(cursor)
        
        html_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self.text_terminal.insertHtml(f'<span style="color:{color};">[{level}] {html_msg}</span><br>')
        
        sb = self.text_terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_sandbox_test(self):
        self.text_terminal.clear()

        skill_dir = self.edit_skill_dir.text().strip()
        script_name = self.edit_script_name.text().strip()
        memory_dir = self.edit_memory_dir.text().strip()
        user_prompt = self.edit_user_prompt.toPlainText().strip()

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
        materials_payload = self.get_custom_materials_payload()
        
        self.req_data = {
            "skill_dir": skill_dir,
            "memory_snapshot_dir": memory_dir if memory_dir else None,
            "target_script": script_name,
            "user_prompt": user_prompt if user_prompt else None,
            "custom_materials": materials_payload
        }

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        if user_prompt or materials_payload:
            self.append_log("USER", f"装载用户交互输入: 话术='{user_prompt or '（默认自适应）'}' | 材料数量={len(materials_payload)}")

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
                self.append_log("SUCCESS", f"✅ 沙箱环境就绪，ID [{self.container_id}]，建立日志流...")

                ws_url = f"{WS_LOGS_URL.format(port=port)}/{self.container_id}?script_name={self.edit_script_name.text().strip()}"
                self.ws_worker = WebSocketLogWorker(ws_url)
                self.ws_worker.log_received.connect(self.handle_stream_log)
                self.ws_worker.connection_closed.connect(self.on_ws_closed)
                self.ws_worker.start()
            else:
                self.append_log("ERROR", f"沙箱初始化失败: {res_json.get('msg')}")
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
        except Exception as e:
            self.append_log("ERROR", f"请求沙箱服务异常: {str(e)}")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    @Slot(str)
    def _on_backend_failed(self, err_msg):
        self.append_log("ERROR", err_msg)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    @Slot(str)
    def handle_stream_log(self, raw_msg):
        clean_msg = raw_msg.strip()
        if not clean_msg:
            return

        json_str = None
        if clean_msg.startswith("{") and clean_msg.endswith("}"):
            json_str = clean_msg
        elif "[STDOUT]" in clean_msg:
            part = clean_msg.split("[STDOUT]", 1)[1].strip()
            if part.startswith("{") and part.endswith("}"):
                json_str = part

        if json_str:
            try:
                data = json.loads(json_str)
                node = data.get("node", "Node")
                action = data.get("action", "")
                status = data.get("status", "")
                details = data.get("details", "")

                level = "INFO"
                if status == "Success":
                    level = "SUCCESS"
                elif status in ["Warning", "Blocked"]:
                    level = "WARN"
                elif status in ["Failed", "Error"]:
                    level = "ERROR"

                # 针对 LLM 最终裁定节点做专属醒目高亮
                if node == "LLM-Judge" or "裁定" in action or "评判" in action:
                    self.append_log("JUDGE", f"⚖️ [{node}] 操作: {action} | 状态: {status}")
                    self.append_log("VERDICT", f"   📢 【最终裁定内容】: {details}")
                    return

                formatted = f"► [{node}] 操作: {action} | 状态: {status} | 细节: {details}"
                self.append_log(level, formatted)
                return
            except json.JSONDecodeError:
                pass

        if clean_msg.startswith("[STDERR]"):
            self.append_log("ERROR", clean_msg)
        elif clean_msg.startswith("[系统]"):
            self.append_log("INFO", clean_msg)
        elif clean_msg.startswith("[系统异常]"):
            self.append_log("ERROR", clean_msg)
        else:
            self.append_log("INFO", clean_msg)

    def on_ws_closed(self):
        self.append_log("INFO", "日志流接收完毕，正在拉取多维深度评估报告...")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        # 启动重试拉取机制（解决后端异步写入的毫秒级时间差）
        QTimer.singleShot(300, lambda: self.fetch_and_display_report(retry_count=0))

    def fetch_and_display_report(self, retry_count=0):
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox_reports")
        found_report = False
        
        if self.container_id and os.path.exists(reports_dir):
            for f in os.listdir(reports_dir):
                if self.container_id in f and "执行跟踪" in f and f.endswith(".json"):
                    found_report = True
                    try:
                        rep_path = os.path.join(reports_dir, f)
                        with open(rep_path, "r", encoding="utf-8") as rf:
                            rep = json.load(rf)
                            j = rep.get("ai_judge_analysis", {})
                            
                            # 1. 优先完整输出 Markdown 深度分析报告
                            detailed_md = j.get("detailed_report_md", "")
                            if detailed_md:
                                self.append_log("JUDGE", "============================================================")
                                self.append_log("JUDGE", "📊 【LLM-as-Judge 深度评估分析报告 (完整内容)】")
                                for line in detailed_md.splitlines():
                                    if line.startswith("# "):
                                        self.append_log("JUDGE", f"  {line}")
                                    elif line.startswith("## "):
                                        self.append_log("JUDGE", f"<br><b>{line}</b>")
                                    elif line.startswith("### "):
                                        self.append_log("INFO", f"  {line}")
                                    elif line.startswith("- **") or line.startswith("1. ") or line.startswith("2. "):
                                        self.append_log("VERDICT" if "判定" in line or "一致" in line else "WARN", f"  {line}")
                                    elif line.strip():
                                        self.append_log("INFO", f"  {line}")
                                self.append_log("SUCCESS", f"📁 评估报告 JSON 文件已持久化归档: {rep_path}")
                                self.append_log("JUDGE", "============================================================")
                            else:
                                # 回退输出结构化卡片
                                self.append_log("JUDGE", "============================================================")
                                self.append_log("VERDICT", f"🌟 最终裁定: {j.get('final_verdict', 'Pass')} | 综合评分: {j.get('completeness_score', 90)} 分")
                                self.append_log("INFO", f"📋 总体结论: {j.get('overall_conclusion', '')}")
                                self.append_log("SUCCESS", f"📁 报告文件: {rep_path}")
                                self.append_log("JUDGE", "============================================================")
                            return
                    except Exception as e:
                        self.append_log("ERROR", f"解析评判报告失败: {str(e)}")
                        return

        # 若未找到报告且重试次数小于 6 次，则继续轮询等待后端落盘
        if not found_report and retry_count < 6:
            QTimer.singleShot(300, lambda: self.fetch_and_display_report(retry_count + 1))
        elif not found_report:
            if retry_count < 8:
                # 每 300ms 重试一次，直到后端落盘完成
                QTimer.singleShot(300, lambda: self.fetch_and_display_report(retry_count + 1))
            else:
                self.append_log("WARN", "⚠️ 暂未检索到本次执行生成的持久化评估报告文件（可能沙箱测试仍在执行中或未生成产物）。")

    def stop_sandbox_test(self):
        if not self.container_id:
            return

        self.append_log("WARN", f"正在向后端申请销毁沙箱环境: {self.container_id}")
        try:
            res = requests.delete(f"{API_BASE_URL.format(port=self.port)}/{self.container_id}")
            self.append_log("SUCCESS", f"销毁指令响应: {res.json().get('msg')}")
        except Exception as e:
            self.append_log("ERROR", f"请求沙箱销毁失败: {str(e)}")

        if self.ws_worker:
            self.ws_worker.stop()

        self.server_manager.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def closeEvent(self, event):
        if self.ws_worker:
            self.ws_worker.stop()
        self.server_manager.stop()
        event.accept()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skill Sandbox GUI")
    parser.add_argument("--auto-run", action="store_true", help="启动后自动执行一次测试")
    parser.add_argument("--port", type=int, default=8000, help="指定后端端口")
    parser.add_argument("--skill-file", type=str, default="skill.md", help="指定测试的目标 skill 文件")
    parser.add_argument("--work-dir", type=str, default="", help="指定工作区路径")
    parser.add_argument("--user-prompt", type=str, default="", help="指定用户测试话术")
    parser.add_argument("--material-file", type=str, action="append", help="添加自定义文件材料")
    parser.add_argument("--material-image", type=str, action="append", help="添加自定义图片材料")

    args, unknown = parser.parse_known_args()

    app = QApplication(sys.argv)
    window = MainWindow()

    if args.port:
        window.edit_port.setText(str(args.port))
    if args.skill_file:
        window.edit_script_name.setText(args.skill_file)
    if args.work_dir and os.path.exists(args.work_dir):
        window.edit_skill_dir.setText(args.work_dir)
    if args.user_prompt:
        window.edit_user_prompt.setPlainText(args.user_prompt)
    if args.material_image:
        for img in args.material_image:
            if os.path.exists(img):
                window._append_material_item("image", img)
    if args.material_file:
        for f in args.material_file:
            if os.path.exists(f):
                window._append_material_item("file", f)

    window.show()

    if args.auto_run:
        QTimer.singleShot(500, window.start_sandbox_test)

    sys.exit(app.exec())
