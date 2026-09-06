---
name: skill-oea-sandbox
description: AI Agent 技能安全沙箱与行为评估分析系统 (OEA: Operational Evaluation & Analysis)。支持对任何 SKILL.md 进行领域识别、动态测试材料构建、5大核心安全项审计、越权隔离拦截与 LLM-as-Judge 真实产物一致性评估。支持 CLI 与 PySide6 GUI 双模式。
argument-hint: "<skill-dir-or-skill-file>"
---

# Skill-oea-Sandbox (AI Agent 技能行为评估分析沙箱)

安全隔离与自动化多维评判 AI 技能（SKILL.md / 技能包）的测试评估套件。

## 适用场景
- 评估第三方技能或外部导入技能的安全性（网络外联、Shell执行、环境凭证探测、Base64混淆、二进制载荷）
- 自动生成领域专属测试物料（代码评审/OCR票据/工作流/知识库/系统架构等），执行闭环测试
- LLM-as-Judge 深度四维评判：行为与用途一致性、产物与定义一致性、安全合规性、偏差剖析与可用性判定

## 快速使用

### 1. 作为 AI Agent 命令行技能执行
直接调用沙箱后端或运行脚本进行快速测试：
```bash
# 启动后端服务
python backend/main.py --port 8000

# 运行特定技能测试 (支持直接指定技能目录或 skill.md)
python backend/sandbox_manager.py --skill "path/to/skill-package"
```

### 2. 作为桌面 GUI 可视化工具使用
```bash
# 启动图形界面 (支持交互式材料面板、日志实时流式渲染、全景 Markdown 评估报告展示)
python frontend/main.py --port 8000
```

## 核心能力
1. **领域感知与测试流定制**：自动识别 `code_development`, `ocr_document`, `memory_knowledge`, `workflow_automation`, `system_architecture` 等技能领域并动态提供测试样例。
2. **5 大核心安全审查项深度审计**：静态深度分析与沙箱内核 Hook 双重拦截，全方位覆盖网络调用、Shell 执行、密钥环境、Base64 混淆与二进制文件。
3. **多维 LLM-as-Judge 深度报告**：输出工程目录树、敏感源头定位、偏差剖析、可用性判定及代码级修复建议。

## AI 主导的报告与临时文件生命周期回收机制 (Lifecycle Recycling Protocol)

当作为 AI Agent 调用本技能或维护沙箱测试环境时，必须遵循以下自主生命周期回收规约：

### 1. 初始化协商规约 (First-Run Policy Negotiation)
- **触发条件**：在首次初始化技能或执行测试前，检查 `sandbox_reports/_config/recycle_policy.json` 是否存在。
- **自主行为**：若未配置策略，AI Agent **必须主动向用户发起回收周期协商**（默认推荐 7 天，支持 3/7/14/30 天或自定义天数），并将确认结果持久化写入配置：
  ```bash
  python -c "from backend.recycle_manager import ReportRecycleManager; rm = ReportRecycleManager('.'); rm.save_policy({'retention_days': 7, 'is_configured': True})"
  ```

### 2. 主动扫描与过期研判 (Active Scanning & Expiration Triage)
- **触发时机**：测试执行完毕后、或收到用户日常巡检指令时。
- **扫描命令**：
  ```bash
  python -c "from backend.recycle_manager import ReportRecycleManager; rm = ReportRecycleManager('.'); print(rm.scan_files())"
  ```
- **研判目标**：全量覆盖 `sandbox_reports/`（持久化报告）与 `.cowork-temp/`（沙箱运行临时目录），依据文件 `mtime` 自动划分为 `已过期 (Overdue)` 与 `即将过期 (Expiring Soon)`。

### 3. 周期到达交互与提炼归档/清理流程 (Lifecycle Expiration Workflow)
当检测到存在 `已过期` 的报告或临时文件时，AI Agent **必须主动向用户汇报并提供三种处置方案**：
1. **方案 A：移入回收站清理 (Trash)**：
   - 行为：调用 `rm.move_to_trash(expired_paths)` 将文件安全移入 `sandbox_reports/_trash/` 暂存 24 小时；
   - 意义：杜绝直接硬删除，提供 24h 误操作回滚保护。
2. **方案 B：提炼归档 (Distill & Archive)**：
   - 行为：调用 `rm.archive_and_distill(expired_paths)` 将报告与关键产物打包压缩至 `sandbox_reports/_archives/archive_YYYYMMDD_HHMMSS.zip`，并自动更新 `sandbox_reports/_archives/archive_index.json` 索引库；
   - 意义：浓缩历史评判结论与审计产物，释放工作区空间。
3. **方案 C：顺延/取消 (Postpone)**：
   - 行为：保留当前文件，自动顺延记录下次扫描时间戳。

### 4. 安全约束与红线 (Safety Guardrails)
- 严禁未经用户二次确认直接执行永久批量物理删除；
- 临时目录 `.cowork-temp/` 与报告目录 `sandbox_reports/` 的清理操作必须具备可追溯的审计日志。
