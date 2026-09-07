# -*- coding: utf-8 -*-
import os, sys, json, requests, subprocess
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, 
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, 
    QProgressBar, QMessageBox, QWidget, QAbstractItemView, QSplitter
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
    """报告与沙箱临时文件回收生命周期管理组件（横向双表 + 搜索过滤版）"""
    def __init__(self, parent_window, backend_url="http://127.0.0.1:8000"):
        super().__init__("📦 报告与临时文件回收生命周期管理", parent_window)
        self.win = parent_window
        self.backend_url = backend_url
        self.all_items = []      # 全部扫描结果（按时间倒序）
        self.filtered_all = []   # 过滤后的全部列表
        self.filtered_spec = []  # 过滤后的状态列表（过期/最新）
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 10, 8, 8)

        # 1. 顶部控制栏：回收周期设置 + 搜索栏 + 扫描操作
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # 回收周期设置控件
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

        top_row.addSpacing(6)

        # 往期搜索栏
        top_row.addWidget(QLabel("🔍 搜索报告:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入技能名/文件名/路径/日期进行实时检索...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.apply_filter)
        self.search_input.setStyleSheet("padding: 3px 8px; background: #1E2227; color: #ABB2BF; border: 1px solid #3E4451; border-radius: 3px;")
        top_row.addWidget(self.search_input, stretch=2)

        # 扫描按钮与全局目录入口
        self.btn_scan = QPushButton("🔍 立即扫描")
        self.btn_scan.setStyleSheet("background: #61AFEF; color: white; font-weight: bold; padding: 4px 10px;")
        self.btn_scan.clicked.connect(self.do_scan)
        top_row.addWidget(self.btn_scan)

        self.btn_open_all_dir = QPushButton("📂 打开报告根目录")
        self.btn_open_all_dir.setToolTip("一键打开 sandbox_reports 根路径")
        self.btn_open_all_dir.setStyleSheet("padding: 4px 8px;")
        self.btn_open_all_dir.clicked.connect(self.open_reports_root_dir)
        top_row.addWidget(self.btn_open_all_dir)

        main_layout.addLayout(top_row)

        # 扫描进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # 2. 横向双表布局（QSplitter 保证自适应与拖拽调节）
        tables_splitter = QSplitter(Qt.Horizontal)
        tables_splitter.setChildrenCollapsible(False)

        # === 表一：全局报告表（所有历史生成报告，倒序排列） ===
        group_table1 = QGroupBox("📋 全局报告表 (按生成时间倒序)")
        group_table1.setStyleSheet("QGroupBox { font-weight: bold; color: #61AFEF; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        layout_t1 = QVBoxLayout(group_table1)
        layout_t1.setContentsMargins(4, 10, 4, 4)
        layout_t1.setSpacing(4)

        bar_t1 = QHBoxLayout()
        self.lbl_t1_stats = QLabel("共计 0 项")
        self.lbl_t1_stats.setStyleSheet("color: #ABB2BF; font-weight: normal; font-size: 11px;")
        bar_t1.addWidget(self.lbl_t1_stats)
        bar_t1.addStretch()
        layout_t1.addLayout(bar_t1)

        self.table_all = QTableWidget(0, 6)
        self.table_all.setHorizontalHeaderLabels([
            "技能名称", "报告/文件名称", "大小", "生成时间", "类型", "操作"
        ])
        self._setup_table_style(self.table_all)
        layout_t1.addWidget(self.table_all)
        tables_splitter.addWidget(group_table1)

        # === 表二：过期/最新状态表（专项显示过期项与最新待处理项） ===
        group_table2 = QGroupBox("⚠️ 过期 / 最新待处理状态表")
        group_table2.setStyleSheet("QGroupBox { font-weight: bold; color: #E5C07B; margin-top: 6px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
        layout_t2 = QVBoxLayout(group_table2)
        layout_t2.setContentsMargins(4, 10, 4, 4)
        layout_t2.setSpacing(4)

        bar_t2 = QHBoxLayout()
        self.lbl_t2_stats = QLabel("已过期: 0 | 即将过期: 0")
        self.lbl_t2_stats.setStyleSheet("color: #ABB2BF; font-weight: normal; font-size: 11px;")
        bar_t2.addWidget(self.lbl_t2_stats)
        bar_t2.addStretch()

        self.btn_clean_all = QPushButton("🗑️ 一键清理过期")
        self.btn_clean_all.setStyleSheet("background: #E06C75; color: white; padding: 2px 6px; font-size: 11px;")
        self.btn_clean_all.clicked.connect(lambda: self.batch_action("trash"))
        bar_t2.addWidget(self.btn_clean_all)

        self.btn_archive_all = QPushButton("📦 一键提炼归档")
        self.btn_archive_all.setStyleSheet("background: #98C379; color: #1E1E1E; font-weight: bold; padding: 2px 6px; font-size: 11px;")
        self.btn_archive_all.clicked.connect(lambda: self.batch_action("archive"))
        bar_t2.addWidget(self.btn_archive_all)

        layout_t2.addLayout(bar_t2)

        self.table_status = QTableWidget(0, 6)
        self.table_status.setHorizontalHeaderLabels([
            "技能名称", "文件名", "状态", "生成时间", "大小", "操作"
        ])
        self._setup_table_style(self.table_status)
        layout_t2.addWidget(self.table_status)
        tables_splitter.addWidget(group_table2)

        # 设置左右均分占比
        tables_splitter.setSizes([500, 500])
        tables_splitter.setMaximumHeight(220)
        tables_splitter.setMinimumHeight(150)
        main_layout.addWidget(tables_splitter)

    def _setup_table_style(self, table: QTableWidget):
        """配置表格通用的自适应列宽和样式"""
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet("""
            QTableWidget {
                background: #21252B;
                color: #ABB2BF;
                font-size: 11px;
                border: 1px solid #3E4451;
            }
            QHeaderView::section {
                background: #282C34;
                color: #D4D4D4;
                font-weight: bold;
                font-size: 11px;
                padding: 2px 4px;
                border: 1px solid #1E2227;
            }
        """)

    def load_initial_policy(self):
        """检查并加载后端或本地策略配置，若未初始化则唤起模态对话框"""
        policy_loaded = False
        try:
            r = requests.get(f"{self.backend_url}/api/v1/recycle/policy", timeout=2)
            if r.status_code == 200:
                data = r.json().get("policy", {})
                is_conf = data.get("is_configured", False)
                days = data.get("retention_days", 7)
                self.spin_retention.setValue(days)
                policy_loaded = True
                if not is_conf:
                    dlg = RecyclePolicyInitDialog(self.win, current_days=days)
                    if dlg.exec() == RecyclePolicyInitDialog.Accepted:
                        self.spin_retention.setValue(dlg.selected_days)
                        self.save_policy(silent=True)
                        self.win.append_log("SUCCESS", f"📦 已初始化报告回收周期为: {dlg.selected_days} 天")
                self.do_scan(silent=True)
                return
        except Exception:
            pass

        # 若后端未启动，回退到本地读取
        try:
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(cur_dir)
            backend_dir = os.path.join(parent_dir, "backend")
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            from recycle_manager import ReportRecycleManager
            mgr = ReportRecycleManager()
            pol = mgr.get_policy()
            is_conf = pol.get("is_configured", False)
            days = pol.get("retention_days", 7)
            self.spin_retention.setValue(days)
            if not is_conf:
                dlg = RecyclePolicyInitDialog(self.win, current_days=days)
                if dlg.exec() == RecyclePolicyInitDialog.Accepted:
                    self.spin_retention.setValue(dlg.selected_days)
                    mgr.save_policy(dlg.selected_days)
                    self.win.append_log("SUCCESS", f"📦 已初始化报告回收周期为: {dlg.selected_days} 天")
            self.do_scan(silent=True)
        except Exception:
            self.do_scan(silent=True)

    def save_policy(self, silent=False):
        days = self.spin_retention.value()
        saved = False
        # 1. 优先尝试 REST API 保存
        try:
            r = requests.post(f"{self.backend_url}/api/v1/recycle/policy", json={"retention_days": days}, timeout=3)
            if r.status_code == 200:
                saved = True
        except Exception:
            saved = False

        # 2. 若 API 离线，自动无缝切换本地嵌入式引擎直接保存策略
        if not saved:
            try:
                from recycle_manager import ReportRecycleManager
            except (ImportError, ValueError):
                backend_dir = os.path.abspath(os.path.join(frontend_dir, "..", "backend"))
                if backend_dir not in sys.path:
                    sys.path.insert(0, backend_dir)
                from recycle_manager import ReportRecycleManager
            try:
                mgr = ReportRecycleManager()
                mgr.save_policy(days)
                saved = True
            except Exception as e:
                if not silent:
                    self.win.append_log("ERROR", f"本地引擎保存回收策略失败: {e}")
                return

        if saved:
            if not silent:
                self.win.append_log("SUCCESS", f"💾 回收策略已保存: 周期设为 {days} 天")
            self.do_scan(silent=silent)

    def do_scan(self, silent=False):
        self.set_busy(True)
        if not silent:
            self.win.append_log("INFO", "🔍 正在扫描 sandbox_reports 及 .cowork-temp 中的历史与过期文件...")
        QTimer.singleShot(100, lambda: self._execute_scan_request(silent))

    def _execute_scan_request(self, silent):
        try:
            # 1. 优先尝试通过后端 REST API 扫描
            try:
                r = requests.post(f"{self.backend_url}/api/v1/recycle/scan", json={"retention_days": self.spin_retention.value()}, timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    raw_items = data.get("items", [])
                    raw_items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
                    self.all_items = raw_items
                    self.apply_filter()
                    if not silent:
                        self.win.append_log("SUCCESS", f"✅ 扫描完成: 检索到 {len(self.all_items)} 项历史产物，已过期 {data.get('overdue_count',0)} 项")
                    return
            except Exception:
                pass

            # 2. 若后端服务尚未启动或 API 请求未响应，直接采用本地直读引擎执行扫描
            ReportRecycleManager = None
            try:
                # 尝试从 backend 目录动态导入
                cur_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(cur_dir)
                backend_dir = os.path.join(parent_dir, "backend")
                if backend_dir not in sys.path:
                    sys.path.insert(0, backend_dir)
                if parent_dir not in sys.path:
                    sys.path.insert(0, parent_dir)
                
                from recycle_manager import ReportRecycleManager
            except Exception:
                try:
                    from backend.recycle_manager import ReportRecycleManager
                except Exception:
                    pass

            if ReportRecycleManager:
                try:
                    mgr = ReportRecycleManager()
                    data = mgr.scan_files(retention_days=self.spin_retention.value())
                    raw_items = data.get("items", [])
                    raw_items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
                    self.all_items = raw_items
                    self.apply_filter()
                    if not silent:
                        self.win.append_log("SUCCESS", f"✅ [本地引擎] 扫描完成: 检索到 {len(self.all_items)} 项历史产物，已过期 {data.get('overdue_count',0)} 项")
                    return
                except Exception as le:
                    if not silent:
                        self.win.append_log("ERROR", f"本地扫描引擎执行异常: {le}")
                    return
            else:
                if not silent:
                    self.win.append_log("WARN", "扫描服务暂时不可用，请确认沙箱服务或网络连接")
        finally:
            self.set_busy(False)

    def set_busy(self, busy):
        self.btn_scan.setEnabled(not busy)
        self.btn_clean_all.setEnabled(not busy)
        self.btn_archive_all.setEnabled(not busy)
        self.progress_bar.setVisible(busy)

    def apply_filter(self):
        """根据搜索栏关键字实时过滤双表数据"""
        kw = self.search_input.text().strip().lower()
        if not kw:
            self.filtered_all = list(self.all_items)
        else:
            self.filtered_all = [
                it for it in self.all_items
                if kw in it.get("skill_name", "").lower()
                or kw in it.get("name", "").lower()
                or kw in it.get("path", "").lower()
                or kw in it.get("created_at", "").lower()
                or kw in it.get("status", "").lower()
            ]

        # 表二：专项仅显示状态为【已过期】或【即将过期】的待处理项
        self.filtered_spec = [
            it for it in self.filtered_all
            if it.get("status") in ["已过期", "即将过期"]
        ]

        self.render_tables()

    def render_tables(self):
        """渲染横向双表数据"""
        # 1. 渲染表一：全局报告表
        self.table_all.setRowCount(len(self.filtered_all))
        self.lbl_t1_stats.setText(f"共计 {len(self.filtered_all)} 项 (已按时间倒序)")
        for row, it in enumerate(self.filtered_all):
            self.table_all.setItem(row, 0, QTableWidgetItem(it.get("skill_name", "未知")))
            self.table_all.setItem(row, 1, QTableWidgetItem(it.get("name", "")))
            self.table_all.setItem(row, 2, QTableWidgetItem(it.get("size_str", "")))
            self.table_all.setItem(row, 3, QTableWidgetItem(it.get("created_at", "")[:16]))
            self.table_all.setItem(row, 4, QTableWidgetItem("报告产物" if it.get("category")=="report" else "沙箱临时目录"))
            self.table_all.setCellWidget(row, 5, self._create_row_actions(it))

        # 2. 渲染表二：过期/最新状态表
        self.table_status.setRowCount(len(self.filtered_spec))
        overdue_cnt = sum(1 for it in self.filtered_spec if it.get("status") == "已过期")
        soon_cnt = sum(1 for it in self.filtered_spec if it.get("status") == "即将过期")
        self.lbl_t2_stats.setText(f"展示 {len(self.filtered_spec)} 项 | 已过期: <b style='color:#E06C75;'>{overdue_cnt}</b> | 临期: <b style='color:#E5C07B;'>{soon_cnt}</b>")

        for row, it in enumerate(self.filtered_spec):
            self.table_status.setItem(row, 0, QTableWidgetItem(it.get("skill_name", "未知")))
            self.table_status.setItem(row, 1, QTableWidgetItem(it.get("name", "")))
            
            status_item = QTableWidgetItem(it.get("status", "正常"))
            if it.get("status") == "已过期":
                status_item.setForeground(Qt.red)
            elif it.get("status") == "即将过期":
                status_item.setForeground(Qt.yellow)
            else:
                status_item.setForeground(Qt.green)
            self.table_status.setItem(row, 2, status_item)

            self.table_status.setItem(row, 3, QTableWidgetItem(it.get("created_at", "")[:16]))
            self.table_status.setItem(row, 4, QTableWidgetItem(it.get("size_str", "")))
            self.table_status.setCellWidget(row, 5, self._create_row_actions(it))

    def _create_row_actions(self, it):
        """生成表格单行操作栏（打开文件、打开目录、单项清理）"""
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(1, 1, 1, 1)
        btn_layout.setSpacing(3)

        btn_open = QPushButton("📄")
        btn_open.setToolTip("打开文件 (系统默认应用)")
        btn_open.setFixedWidth(24)
        btn_open.clicked.connect(lambda _, p=it.get("path"): self.open_file(p))
        btn_layout.addWidget(btn_open)

        btn_dir = QPushButton("📁")
        btn_dir.setToolTip("在文件管理器中定位目录")
        btn_dir.setFixedWidth(24)
        btn_dir.clicked.connect(lambda _, p=it.get("path"): self.open_dir(p))
        btn_layout.addWidget(btn_dir)

        btn_single = QPushButton("❌")
        btn_single.setToolTip("单项清理或归档")
        btn_single.setFixedWidth(24)
        btn_single.clicked.connect(lambda _, item=it: self.single_action(item))
        btn_layout.addWidget(btn_single)

        return btn_widget

    def open_reports_root_dir(self):
        """打开报告根目录 sandbox_reports"""
        root_reports = os.path.abspath(os.path.join(frontend_dir, "..", "sandbox_reports"))
        os.makedirs(root_reports, exist_ok=True)
        self.open_dir(root_reports)

    def open_file(self, path):
        if not os.path.exists(path):
            self.win.append_log("WARN", f"目标文件已不存在: {path}")
            return
        try:
            os.startfile(os.path.abspath(path))
        except Exception as e:
            self.win.append_log("ERROR", f"打开文件失败: {e}")

    def open_dir(self, path):
        if not os.path.exists(path):
            self.win.append_log("WARN", f"目标路径已不存在: {path}")
            return
        try:
            abs_p = os.path.abspath(path)
            if os.path.isfile(abs_p):
                subprocess.Popen(f'explorer /select,"{abs_p}"')
            else:
                subprocess.Popen(f'explorer "{abs_p}"')
        except Exception as e:
            self.win.append_log("ERROR", f"定位目录失败: {e}")

    def single_action(self, item):
        dlg = RecycleConfirmActionDialog(self.win, expired_count=1, total_size_str=item.get("size_str", ""))
        if dlg.exec() == RecycleConfirmActionDialog.Accepted and dlg.choice != "cancel":
            self.execute_clean_api(dlg.choice, [item.get("path")])

    def batch_action(self, action):
        overdue_paths = [it.get("path") for it in self.all_items if it.get("status") == "已过期"]
        if not overdue_paths:
            QMessageBox.information(self.win, "提示", "当前列表中没有已过期的文件需要处理。")
            return
        dlg = RecycleConfirmActionDialog(self.win, expired_count=len(overdue_paths), total_size_str="")
        if dlg.exec() == RecycleConfirmActionDialog.Accepted and dlg.choice != "cancel":
            self.execute_clean_api(dlg.choice, overdue_paths)

    def execute_clean_api(self, action, paths):
        # 1. 优先尝试 REST API（若后端在线）
        api_success = False
        try:
            r = requests.post(f"{self.backend_url}/api/v1/recycle/action", json={"action": action, "paths": paths}, timeout=3)
            if r.status_code == 200:
                api_success = True
        except Exception:
            api_success = False

        # 2. 若 API 离线/失败，自动无缝切换本地嵌入式引擎直接执行
        if not api_success:
            try:
                from recycle_manager import ReportRecycleManager
            except (ImportError, ValueError):
                backend_dir = os.path.abspath(os.path.join(frontend_dir, "..", "backend"))
                if backend_dir not in sys.path:
                    sys.path.insert(0, backend_dir)
                from recycle_manager import ReportRecycleManager

            try:
                mgr = ReportRecycleManager()
                if action == "trash":
                    res = mgr.move_to_trash(paths)
                elif action == "archive":
                    res = mgr.archive_and_distill(paths)
                else:
                    res = {"status": "success"}
                api_success = True
            except Exception as le:
                self.win.append_log("ERROR", f"本地回收清理引擎执行异常: {le}")
                return

        if api_success:
            action_text = "移动到回收站暂存 (_trash 24h)" if action == "trash" else "提炼归档至 ZIP (_archives)"
            self.win.append_log("SUCCESS", f"✅ 已成功将 [{len(paths)}] 个文件/目录 {action_text}")
            self.do_scan()
