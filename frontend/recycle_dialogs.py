# -*- coding: utf-8 -*-
import os, sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, 
    QButtonGroup, QSpinBox, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

class RecyclePolicyInitDialog(QDialog):
    """首次初始化回收周期协商弹窗"""
    def __init__(self, parent=None, current_days=7):
        super().__init__(parent)
        self.setWindowTitle("🛡️ 报告与临时文件回收策略初始化协商")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.selected_days = current_days
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("<b>📦 报告与沙箱临时文件回收生命周期协商</b>")
        title.setStyleSheet("font-size: 14px; color: #61AFEF;")
        layout.addWidget(title)

        tip = QLabel("为了避免长期评判报告与沙箱运行日志过度占用磁盘空间，请选择自动回收周期：")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #ABB2BF; line-height: 1.4;")
        layout.addWidget(tip)

        self.btn_group = QButtonGroup(self)
        self.r1 = QRadioButton("3 天 (敏捷开发 / 快速测试)")
        self.r2 = QRadioButton("7 天 (标准推荐 / 平衡审计与空间)")
        self.r3 = QRadioButton("14 天 (深度审计 / 保留两周分析)")
        self.r4 = QRadioButton("30 天 (长期归档 / 周期性复盘)")
        self.r5 = QRadioButton("自定义周期:")

        self.btn_group.addButton(self.r1, 3)
        self.btn_group.addButton(self.r2, 7)
        self.btn_group.addButton(self.r3, 14)
        self.btn_group.addButton(self.r4, 30)
        self.btn_group.addButton(self.r5, 0)

        self.r2.setChecked(True)

        layout.addWidget(self.r1)
        layout.addWidget(self.r2)
        layout.addWidget(self.r3)
        layout.addWidget(self.r4)

        custom_row = QHBoxLayout()
        custom_row.addWidget(self.r5)
        self.spin_custom = QSpinBox()
        self.spin_custom.setRange(1, 365)
        self.spin_custom.setValue(self.selected_days)
        self.spin_custom.setSuffix(" 天")
        self.spin_custom.setEnabled(False)
        custom_row.addWidget(self.spin_custom)
        custom_row.addStretch()
        layout.addLayout(custom_row)

        self.r5.toggled.connect(lambda checked: self.spin_custom.setEnabled(checked))

        sec_tip = QLabel("💡 <i>安全机制：到期文件清理前必须二次确认，并移至 _trash 暂存 24 小时以供回滚。</i>")
        sec_tip.setStyleSheet("color: #98C379; font-size: 11px;")
        layout.addWidget(sec_tip)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("确认并保存策略")
        btn_ok.setStyleSheet("background: #98C379; color: #1E1E1E; font-weight: bold; padding: 6px 16px;")
        btn_ok.clicked.connect(self.on_accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def on_accept(self):
        btn_id = self.btn_group.checkedId()
        if btn_id == 0:
            self.selected_days = self.spin_custom.value()
        else:
            self.selected_days = btn_id
        self.accept()


class RecycleConfirmActionDialog(QDialog):
    """周期到达交互二次确认弹窗"""
    def __init__(self, parent=None, expired_count=0, total_size_str=""):
        super().__init__(parent)
        self.setWindowTitle("⚠️ 报告与临时文件回收到达处理确认")
        self.setMinimumWidth(480)
        self.choice = "cancel"
        self.expired_count = expired_count
        self.total_size_str = total_size_str
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel(f"<b>⚠️ 检测到 {self.expired_count} 个过期文件/产物 (共占用 {self.total_size_str})</b>")
        title.setStyleSheet("font-size: 13px; color: #E5C07B;")
        layout.addWidget(title)

        desc = QLabel("这些文件已达到设定的保留周期，请选择处理方式：")
        layout.addWidget(desc)

        btn_box = QVBoxLayout()
        btn_box.setSpacing(10)

        self.btn_trash = QPushButton("🗑️ 移动到回收站删除 (先在 _trash 暂存 24 小时，可回滚)")
        self.btn_trash.setStyleSheet("background: #E06C75; color: white; padding: 8px; text-align: left;")
        self.btn_trash.clicked.connect(lambda: self.select_choice("trash"))
        btn_box.addWidget(self.btn_trash)

        self.btn_archive = QPushButton("📦 提炼归档 (压缩为带时间戳 ZIP 并自动维护索引)")
        self.btn_archive.setStyleSheet("background: #61AFEF; color: white; padding: 8px; text-align: left;")
        self.btn_archive.clicked.connect(lambda: self.select_choice("archive"))
        btn_box.addWidget(self.btn_archive)

        self.btn_cancel = QPushButton("❌ 取消操作 (保留现状并顺延至下次扫描)")
        self.btn_cancel.setStyleSheet("background: #3E4451; color: white; padding: 8px; text-align: left;")
        self.btn_cancel.clicked.connect(lambda: self.select_choice("cancel"))
        btn_box.addWidget(self.btn_cancel)

        layout.addLayout(btn_box)

    def select_choice(self, choice):
        self.choice = choice
        self.accept()
