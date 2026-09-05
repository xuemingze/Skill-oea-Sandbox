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
