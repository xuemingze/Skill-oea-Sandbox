# -*- coding: utf-8 -*-
import os, sys, json, requests, subprocess
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, 
    QProgressBar, QMessageBox, QWidget, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer

frontend_dir = os.path.dirname(os.path.abspath(__file__))
if frontend_dir not in sys.path:
    sys.path.insert(0, frontend_dir)

try:
    from .recycle_dialogs import RecyclePolicyInitDialog, RecycleConfirmActionDialog
except (ImportError, ValueError, SystemError):
    from recycle_dialogs import RecyclePolicyInitDialog, RecycleConfirmActionDialog

class RecycleManagerPanel(QGroupBox):
    """报告与沙箱临时文件回收管理组件"""
    def __init__(self, parent_window, backend_url="http://127.0.0.1:8000"):
        super().__init__("📦 报告与临时文件回收生命周期管理", parent_window)
        self.win = parent_window
        self.backend_url = backend_url
        self.scanned_items = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 1. 回收周期配置与手工扫描栏
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("回收周期:"))
        self.spin_retention = QSpinBox()
        self.spin_retention.setRange(1, 365)
        self.spin_retention.setValue(7)
        self.spin_retention.setSuffix(" 天")
        self.spin_retention.setStyleSheet("padding: 2px 6px;")
        top_row.addWidget(self.spin_retention)

        self.btn_save_policy = QPushButton("💾 保存周期")
        self.btn_save_policy.clicked.connect(self.save_policy)
        top_row.addWidget(self.btn_save_policy)

        top_row.addSpacing(10)
        self.btn_scan = QPushButton("🔍 立即扫描过期文件")
        self.btn_scan.setStyleSheet("background: #61AFEF; color: white; font-weight: bold; padding: 4px 12px;")
        self.btn_scan.clicked.connect(self.do_scan)
        top_row.addWidget(self.btn_scan)

        top_row.addStretch()
        self.lbl_stats = QLabel("已就绪 (支持 sandbox_reports 及 .cowork-temp 自动回收)")
        self.lbl_stats.setStyleSheet("color: #ABB2BF;")
        top_row.addWidget(self.lbl_stats)

        layout.addLayout(top_row)

        # 扫描进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # 忙碌滚动模式
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 2. 批量操作工具栏
        action_row = QHBoxLayout()
        self.btn_clean_all = QPushButton("🗑️ 一键清理全部过期 (暂存 _trash 24h)")
        self.btn_clean_all.setStyleSheet("background: #E06C75; color: white; padding: 3px 8px;")
        self.btn_clean_all.clicked.connect(lambda: self.batch_action("trash"))
        action_row.addWidget(self.btn_clean_all)

        self.btn_archive_all = QPushButton("📦 一键提炼归档全部")
        self.btn_archive_all.setStyleSheet("background: #98C379; color: #1E1E1E; font-weight: bold; padding: 3px 8px;")
        self.btn_archive_all.clicked.connect(lambda: self.batch_action("archive"))
        action_row.addWidget(self.btn_archive_all)

        action_row.addStretch()
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.do_scan)
        action_row.addWidget(self.btn_refresh)
        layout.addLayout(action_row)

        # 3. 过期文件表格
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "技能名称", "文件/目录路径", "所属分类", "大小", "生成时间", "状态", "操作"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet("QTableWidget { background: #21252B; color: #ABB2BF; font-size: 11px; } QHeaderView::section { background: #282C34; color: #D4D4D4; font-weight: bold; }")
        self.table.setMaximumHeight(160)
        layout.addWidget(self.table)

    def load_initial_policy(self):
        """检查并加载后端策略配置，若未初始化则唤起模态对话框"""
        try:
            r = requests.get(f"{self.backend_url}/api/v1/recycle/policy", timeout=2)
            if r.status_code == 200:
                data = r.json().get("policy", {})
                is_conf = data.get("is_configured", False)
                days = data.get("retention_days", 7)
                self.spin_retention.setValue(days)
                if not is_conf:
                    dlg = RecyclePolicyInitDialog(self.win, current_days=days)
                    if dlg.exec() == RecyclePolicyInitDialog.Accepted:
                        self.spin_retention.setValue(dlg.selected_days)
                        self.save_policy(silent=True)
                        self.win.append_log("SUCCESS", f"📦 已初始化报告回收周期为: {dlg.selected_days} 天")
                self.do_scan(silent=True)
        except Exception as e:
            pass

    def save_policy(self, silent=False):
        days = self.spin_retention.value()
        try:
            r = requests.post(f"{self.backend_url}/api/v1/recycle/policy", json={"retention_days": days}, timeout=3)
            if r.status_code == 200 and not silent:
                self.win.append_log("SUCCESS", f"💾 回收策略已保存: 周期设为 {days} 天")
                self.do_scan()
        except Exception as e:
            if not silent:
                self.win.append_log("ERROR", f"保存回收策略失败: {e}")

    def do_scan(self, silent=False):
        self.set_busy(True)
        if not silent:
            self.win.append_log("INFO", "🔍 正在扫描 sandbox_reports 及 .cowork-temp 中的过期文件...")
        QTimer.singleShot(100, lambda: self._execute_scan_request(silent))

    def _execute_scan_request(self, silent):
        try:
            r = requests.post(f"{self.backend_url}/api/v1/recycle/scan", json={"retention_days": self.spin_retention.value()}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                self.scanned_items = data.get("items", [])
                self.populate_table(data)
                if not silent:
                    self.win.append_log("SUCCESS", f"✅ 扫描完成: 检索到 {data.get('total_items',0)} 项，其中已过期 {data.get('overdue_count',0)} 项，共占用 {data.get('total_size_str','0 B')}")
            else:
                if not silent:
                    self.win.append_log("WARN", "扫描请求返回异常")
        except Exception as e:
            if not silent:
                self.win.append_log("ERROR", f"扫描执行失败: {e}")
        finally:
            self.set_busy(False)

    def set_busy(self, busy):
        self.btn_scan.setEnabled(not busy)
        self.btn_clean_all.setEnabled(not busy)
        self.btn_archive_all.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.progress_bar.setVisible(busy)

    def populate_table(self, data):
        items = data.get("items", [])
        self.table.setRowCount(len(items))
        overdue_cnt = data.get("overdue_count", 0)
        expiring_cnt = data.get("expiring_soon_count", 0)
        self.lbl_stats.setText(f"总计: {len(items)} | 已过期: <b style='color:#E06C75;'>{overdue_cnt}</b> | 即将过期: <b style='color:#E5C07B;'>{expiring_cnt}</b> | 大小: {data.get('total_size_str','0 B')}")

        for row, it in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(it.get("skill_name", "未知")))
            self.table.setItem(row, 1, QTableWidgetItem(it.get("name", "")))
            self.table.setItem(row, 2, QTableWidgetItem("报告产物" if it.get("category")=="report" else "沙箱临时目录"))
            self.table.setItem(row, 3, QTableWidgetItem(it.get("size_str", "")))
            self.table.setItem(row, 4, QTableWidgetItem(it.get("mtime_str", "")[:16]))

            status_item = QTableWidgetItem(it.get("status", "正常"))
            if it.get("status") == "已过期":
                status_item.setForeground(Qt.red)
            elif it.get("status") == "即将过期":
                status_item.setForeground(Qt.yellow)
            else:
                status_item.setForeground(Qt.green)
            self.table.setItem(row, 5, status_item)

            # 操作按钮栏
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)
            btn_layout.setSpacing(4)

            btn_open = QPushButton("📄")
            btn_open.setToolTip("打开文件")
            btn_open.setFixedWidth(24)
            btn_open.clicked.connect(lambda _, p=it.get("path"): self.open_file(p))
            btn_layout.addWidget(btn_open)

            btn_dir = QPushButton("📁")
            btn_dir.setToolTip("在文件管理器中定位")
            btn_dir.setFixedWidth(24)
            btn_dir.clicked.connect(lambda _, p=it.get("path"): self.open_dir(p))
            btn_layout.addWidget(btn_dir)

            btn_single = QPushButton("❌")
            btn_single.setToolTip("单项清理或归档")
            btn_single.setFixedWidth(24)
            btn_single.clicked.connect(lambda _, item=it: self.single_action(item))
            btn_layout.addWidget(btn_single)

            self.table.setCellWidget(row, 6, btn_widget)

    def open_file(self, path):
        if not os.path.exists(path):
            self.win.append_log("WARN", f"目标文件已不存在: {path}")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self.win.append_log("ERROR", f"打开文件失败: {e}")

    def open_dir(self, path):
        if not os.path.exists(path):
            self.win.append_log("WARN", f"目标路径已不存在: {path}")
            return
        try:
            if os.path.isfile(path):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(path)}"')
            else:
                subprocess.Popen(f'explorer "{os.path.abspath(path)}"')
        except Exception as e:
            self.win.append_log("ERROR", f"定位目录失败: {e}")

    def single_action(self, item):
        dlg = RecycleConfirmActionDialog(self.win, expired_count=1, total_size_str=item.get("size_str", ""))
        if dlg.exec() == RecycleConfirmActionDialog.Accepted and dlg.choice != "cancel":
            self.execute_clean_api(dlg.choice, [item.get("path")])

    def batch_action(self, action):
        overdue_paths = [it.get("path") for it in self.scanned_items if it.get("status") == "已过期"]
        if not overdue_paths:
            QMessageBox.information(self.win, "提示", "当前列表中没有已过期的文件需要处理。")
            return
        dlg = RecycleConfirmActionDialog(self.win, expired_count=len(overdue_paths), total_size_str="")
        if dlg.exec() == RecycleConfirmActionDialog.Accepted and dlg.choice != "cancel":
            self.execute_clean_api(dlg.choice, overdue_paths)

    def execute_clean_api(self, action, paths):
        try:
            r = requests.post(f"{self.backend_url}/api/v1/recycle/clean", json={"action": action, "paths": paths}, timeout=10)
            if r.status_code == 200:
                res = r.json()
                action_text = "移动到回收站暂存" if action == "trash" else "提炼归档至 ZIP"
                self.win.append_log("SUCCESS", f"✅ 已成功将 [{len(paths)}] 个文件/目录 {action_text}")
                self.do_scan()
            else:
                self.win.append_log("ERROR", "回收清理接口调用返回异常")
        except Exception as e:
            self.win.append_log("ERROR", f"执行回收操作失败: {e}")
