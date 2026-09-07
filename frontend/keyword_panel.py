# -*- coding: utf-8 -*-
import os, sys, json, csv
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, 
    QProgressBar, QMessageBox, QComboBox, QFileDialog, QSplitter,
    QGroupBox, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

frontend_dir = os.path.dirname(os.path.abspath(__file__))
if frontend_dir not in sys.path:
    sys.path.insert(0, frontend_dir)
root_dir = os.path.dirname(frontend_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from backend.conflict_scanner import SkillConflictScanner
except (ImportError, ValueError):
    try:
        from conflict_scanner import SkillConflictScanner
    except (ImportError, ValueError):
        SkillConflictScanner = None


class KeywordManagerPanel(QWidget):
    def __init__(self, main_win=None):
        super().__init__()
        self.win = main_win
        self.scanner = SkillConflictScanner() if SkillConflictScanner else None
        self.scan_result = {}
        self.all_keywords_data = []
        self.filtered_keywords_data = []
        self.init_ui()
        QTimer.singleShot(400, self.do_scan)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 1. 顶部控制栏
        top_bar = QHBoxLayout()
        self.lbl_stats = QLabel("📊 触发词库: 正在提取全域技能...")
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #333; font-size: 13px;")
        top_bar.addWidget(self.lbl_stats)

        top_bar.addStretch(1)

        self.btn_rescan = QPushButton("🔄 重新扫描触发词库")
        self.btn_rescan.setStyleSheet("padding: 5px 12px; font-weight: bold; background: #007acc; color: white; border-radius: 4px;")
        self.btn_rescan.clicked.connect(self.do_scan)
        top_bar.addWidget(self.btn_rescan)

        self.btn_export_ai = QPushButton("🤖 一键导出喂给 AI (定制意图路由与消歧)")
        self.btn_export_ai.setStyleSheet("padding: 5px 14px; font-weight: bold; background: #28a745; color: white; border-radius: 4px;")
        self.btn_export_ai.clicked.connect(self.export_for_ai)
        top_bar.addWidget(self.btn_export_ai)

        self.btn_export_csv = QPushButton("📑 导出 CSV 表格")
        self.btn_export_csv.setStyleSheet("padding: 5px 10px; background: #6c757d; color: white; border-radius: 4px;")
        self.btn_export_csv.clicked.connect(self.export_csv)
        top_bar.addWidget(self.btn_export_csv)

        layout.addLayout(top_bar)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 2. 搜索与过滤工具栏
        filter_bar = QHBoxLayout()
        lbl_search = QLabel("🔍 关键词/技能检索:")
        lbl_search.setStyleSheet("font-weight: bold; color: #555;")
        filter_bar.addWidget(lbl_search)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入触发词、技能名称、领域或描述关键字即时过滤...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.apply_filter)
        filter_bar.addWidget(self.search_input, 2)

        lbl_filter_domain = QLabel("领域筛选:")
        lbl_filter_domain.setStyleSheet("font-weight: bold; color: #555; margin-left: 8px;")
        filter_bar.addWidget(lbl_filter_domain)

        self.combo_domain = QComboBox()
        self.combo_domain.addItems(["全部领域", "软件开发/编程专家", "系统架构/基础设施", "文档识别/票据OCR", "知识图谱/记忆管理", "财务审计/核算风控", "音视频与图像生成", "工作流编排/通用任务"])
        self.combo_domain.currentTextChanged.connect(self.apply_filter)
        filter_bar.addWidget(self.combo_domain)

        lbl_filter_conflict = QLabel("冲突状态:")
        lbl_filter_conflict.setStyleSheet("font-weight: bold; color: #555; margin-left: 8px;")
        filter_bar.addWidget(lbl_filter_conflict)

        self.combo_conflict = QComboBox()
        self.combo_conflict.addItems(["全部触发词", "仅展示存在冲突项 (>1技能)", "唯一专属触发词 (1技能)"])
        self.combo_conflict.currentTextChanged.connect(self.apply_filter)
        filter_bar.addWidget(self.combo_conflict)

        layout.addLayout(filter_bar)

        # 3. 关键词主表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["序号", "触发词 (Keyword)", "对应技能数", "冲突等级/状态", "默认/所属技能 (下拉切换)", "技能所属领域", "技能意图描述"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setColumnWidth(4, 260)

        layout.addWidget(self.table, 1)

    def do_scan(self):
        if not self.scanner:
            self.lbl_stats.setText("⚠️ 未加载到关键词扫描模块")
            return

        self.progress_bar.setVisible(True)
        self.btn_rescan.setEnabled(False)

        try:
            self.scan_result = self.scanner.scan_all_skills()
            self._build_table_dataset()
            self.apply_filter()
            if self.win and hasattr(self.win, 'append_log'):
                self.win.append_log("SUCCESS", f"✅ 全域触发词库扫描就绪: 提取到 {len(self.all_keywords_data)} 个独立触发词，涵盖 {self.scan_result.get('total_skills', 0)} 个技能包")
        except Exception as e:
            if self.win and hasattr(self.win, 'append_log'):
                self.win.append_log("ERROR", f"全域触发词库扫描失败: {e}")
        finally:
            self.progress_bar.setVisible(False)
            self.btn_rescan.setEnabled(True)

    def _build_table_dataset(self):
        skills_db = self.scan_result.get("skills", {})
        kw_index = self.scanner.keyword_index if self.scanner else {}
        conflicts_map = {c["keyword"].lower(): c for c in self.scan_result.get("conflicts", [])}

        dataset = []
        for kw, skill_ids in kw_index.items():
            count = len(skill_ids)
            conf = conflicts_map.get(kw.lower())

            if conf:
                severity = conf.get("severity", "MEDIUM")
                if severity == "CRITICAL":
                    status_text = f"🔴 严重冲突 ({count}技能共用)"
                    status_color = "#d9534f"
                elif severity == "HIGH":
                    status_text = f"🟠 跨域重叠 ({count}技能)"
                    status_color = "#f0ad4e"
                else:
                    status_text = f"🟡 同域竞争 ({count}技能)"
                    status_color = "#5bc0de"
            else:
                status_text = "🟢 唯一专属"
                status_color = "#28a745"

            # 构建涉及技能的详细信息列表
            skills_info = []
            for sid in skill_ids:
                s_meta = skills_db.get(sid, {})
                skills_info.append({
                    "id": sid,
                    "name": s_meta.get("name", sid),
                    "domain": s_meta.get("domain", "workflow_automation"),
                    "domain_label": s_meta.get("domain_label", "通用任务"),
                    "description": s_meta.get("description", "暂无描述"),
                    "path": s_meta.get("path", "")
                })

            dataset.append({
                "keyword": kw,
                "count": count,
                "status_text": status_text,
                "status_color": status_color,
                "severity": conf.get("severity", "NONE") if conf else "NONE",
                "skills": skills_info,
                "primary_skill": skills_info[0] if skills_info else {}
            })

        # 排序：优先按技能数量倒序，其次按关键词字母排序
        dataset.sort(key=lambda x: (-x["count"], x["keyword"]))
        self.all_keywords_data = dataset

    def apply_filter(self):
        search_txt = self.search_input.text().strip().lower()
        sel_domain = self.combo_domain.currentText()
        sel_conflict = self.combo_conflict.currentText()

        filtered = []
        for item in self.all_keywords_data:
            kw = item["keyword"].lower()
            skills = item["skills"]

            # 1. 冲突过滤
            if sel_conflict == "仅展示存在冲突项 (>1技能)" and item["count"] <= 1:
                continue
            elif sel_conflict == "唯一专属触发词 (1技能)" and item["count"] > 1:
                continue

            # 2. 领域过滤
            if sel_domain != "全部领域":
                domain_match = any(s.get("domain_label") == sel_domain for s in skills)
                if not domain_match:
                    continue

            # 3. 关键字模糊搜索
            if search_txt:
                match_kw = search_txt in kw
                match_skills = any(search_txt in s.get("id", "").lower() or search_txt in s.get("name", "").lower() or search_txt in s.get("description", "").lower() for s in skills)
                if not (match_kw or match_skills):
                    continue

            filtered.append(item)

        self.filtered_keywords_data = filtered
        self.lbl_stats.setText(f"📊 触发词库: 检索到 {len(self.filtered_keywords_data)} / {len(self.all_keywords_data)} 个触发词 (共覆盖 {self.scan_result.get('total_skills', 0)} 个技能包)")
        self.render_table()

    def render_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.filtered_keywords_data))

        for row, item in enumerate(self.filtered_keywords_data):
            # 列0: 序号
            it_idx = QTableWidgetItem(str(row + 1))
            it_idx.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, it_idx)

            # 列1: 触发词
            it_kw = QTableWidgetItem(item["keyword"])
            font_kw = QFont()
            font_kw.setBold(True)
            it_kw.setFont(font_kw)
            it_kw.setForeground(QColor("#005999"))
            self.table.setItem(row, 1, it_kw)

            # 列2: 对应技能数
            it_count = QTableWidgetItem(str(item["count"]))
            it_count.setTextAlignment(Qt.AlignCenter)
            font_cnt = QFont()
            font_cnt.setBold(True)
            it_count.setFont(font_cnt)
            self.table.setItem(row, 2, it_count)

            # 列3: 冲突等级/状态
            it_status = QTableWidgetItem(item["status_text"])
            it_status.setTextAlignment(Qt.AlignCenter)
            it_status.setForeground(QColor(item["status_color"]))
            self.table.setItem(row, 3, it_status)

            # 列4: 下拉列表显示触发词默认技能
            skills = item["skills"]
            combo = QComboBox()
            for s in skills:
                combo.addItem(f"📦 {s['name']} ({s['id']})", s)
            
            # 列5 & 列6 初始联动
            p_skill = skills[0] if skills else {}
            it_domain = QTableWidgetItem(p_skill.get("domain_label", "未知"))
            it_domain.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, it_domain)

            it_desc = QTableWidgetItem(p_skill.get("description", ""))
            it_desc.setToolTip(f"路径: {p_skill.get('path', '')}\n描述: {p_skill.get('description', '')}")
            self.table.setItem(row, 6, it_desc)

            # 绑定下拉切换事件，实时更新对应的领域与描述
            def make_change_handler(r, cmb):
                def on_combo_changed(idx):
                    s_data = cmb.itemData(idx)
                    if s_data:
                        it_dom = self.table.item(r, 5)
                        if it_dom:
                            it_dom.setText(s_data.get("domain_label", "未知"))
                        it_ds = self.table.item(r, 6)
                        if it_ds:
                            it_ds.setText(s_data.get("description", ""))
                            it_ds.setToolTip(f"路径: {s_data.get('path', '')}\n描述: {s_data.get('description', '')}")
                return on_combo_changed

            combo.currentIndexChanged.connect(make_change_handler(row, combo))
            self.table.setCellWidget(row, 4, combo)

    def export_for_ai(self):
        """生成专门喂给 AI 的 Prompt 与 Markdown 路由定制字典"""
        if not self.all_keywords_data:
            QMessageBox.information(self, "提示", "当前触发词库为空，请先重新扫描。")
            return

        default_file = os.path.join(os.path.expanduser("~"), f"AI_Skill_Routing_Keywords_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        save_path, _ = QFileDialog.getSaveFileName(self, "导出给 AI 的意图定制字典", default_file, "Markdown (*.md);;JSON (*.json)")
        if not save_path:
            return

        is_json = save_path.endswith(".json")
        try:
            if is_json:
                export_obj = {
                    "system_prompt_instruction": "你是一个智能意图路由器。根据用户的输入指令，检索以下触发词与意图定义，精准分发到对应的专属技能，避免在冲突触发词下产生歧义误判。",
                    "generated_at": datetime.now().isoformat(),
                    "total_keywords": len(self.all_keywords_data),
                    "keywords": self.all_keywords_data
                }
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(export_obj, f, ensure_ascii=False, indent=2)
            else:
                lines = [
                    "# 🤖 AI Agent 技能意图分发与关键词路由定制表 (Skill Intent Routing Matrix)",
                    f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | **覆盖独立触发词**: {len(self.all_keywords_data)} 个 | **总技能数**: {self.scan_result.get('total_skills', 0)} 个\n",
                    "## 📌 AI System Instruction (系统提示词)",
                    "```markdown",
                    "【意图路由与技能唤醒准则】",
                    "1. 当用户输入包含以下触发词时，请依据【默认推荐技能】与【意图描述】精准唤醒对应技能；",
                    "2. 若遇到标注为 [🔴严重冲突] 或 [🟠跨域重叠] 的多技能共用词，请结合用户上下文语境与领域特征进行消歧，不可泛化误触发；",
                    "3. 严禁越权调用未声明当前触发意图的无关技能。",
                    "```\n",
                    "## 📋 全域触发词与技能映射索引 (Keyword-to-Skill Routing Table)\n",
                    "| 序号 | 触发关键词 (Keyword) | 冲突状态 | 关联技能数 | 推荐默认技能 | 所属领域 | 技能意图与功能描述 |",
                    "| :---: | :--- | :---: | :---: | :--- | :---: | :--- |"
                ]

                for idx, item in enumerate(self.all_keywords_data):
                    kw = item["keyword"]
                    status = item["status_text"]
                    count = item["count"]
                    skills = item["skills"]
                    p_skill = skills[0] if skills else {}

                    skill_names_str = f"`{p_skill.get('name', '未知')}`"
                    if count > 1:
                        other_names = ", ".join([s.get('name', s.get('id')) for s in skills[1:]])
                        skill_names_str += f" *(备选: {other_names})*"

                    domain = p_skill.get("domain_label", "通用任务")
                    desc = p_skill.get("description", "").replace("\n", " ").replace("|", "/")[:120]

                    lines.append(f"| {idx+1} | **`{kw}`** | {status} | {count} | {skill_names_str} | {domain} | {desc} |")

                lines.append("\n## 💡 歧义词优化建议 (Disambiguation Rules)")
                for c in self.scan_result.get("conflicts", [])[:30]:
                    lines.append(f"- **`{c['keyword']}`** ({c['severity']}): 与 {len(c['skills'])} 个技能重叠 -> {c['suggestion']}")

                with open(save_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))

            QMessageBox.information(self, "导出成功", f"🎉 已成功导出 AI 技能意图定制表：\n{save_path}\n\n可直接将其复制/作为上下文喂给 AI 用于技能路由微调！")
            if self.win and hasattr(self.win, 'append_log'):
                self.win.append_log("SUCCESS", f"✅ 已导出 AI 意图定制表: {save_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出文件失败: {e}")

    def export_csv(self):
        """导出 CSV 标准表格"""
        if not self.all_keywords_data:
            QMessageBox.information(self, "提示", "当前触发词库为空，请先重新扫描。")
            return

        default_file = os.path.join(os.path.expanduser("~"), f"Skill_Keywords_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        save_path, _ = QFileDialog.getSaveFileName(self, "导出 CSV 表格", default_file, "CSV (*.csv)")
        if not save_path:
            return

        try:
            with open(save_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["序号", "触发关键词", "关联技能数", "冲突状态", "推荐技能", "备选技能列表", "所属领域", "技能意图描述", "文件路径"])
                for idx, item in enumerate(self.all_keywords_data):
                    skills = item["skills"]
                    p_skill = skills[0] if skills else {}
                    other_skills = "; ".join([s.get("name", s.get("id")) for s in skills[1:]])
                    writer.writerow([
                        idx + 1,
                        item["keyword"],
                        item["count"],
                        item["status_text"],
                        p_skill.get("name", ""),
                        other_skills,
                        p_skill.get("domain_label", ""),
                        p_skill.get("description", ""),
                        p_skill.get("path", "")
                    ])
            QMessageBox.information(self, "导出成功", f"🎉 已成功导出 CSV 表格：\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出 CSV 失败: {e}")
