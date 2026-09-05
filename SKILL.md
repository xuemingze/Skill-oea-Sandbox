---
name: skill-sandbox
description: AI Agent 技能安全沙箱与行为-用途评估系统。支持对任何 SKILL.md 进行领域识别、动态测试材料构建、越权隔离拦截与 LLM-as-Judge 真实产物一致性评估。支持 CLI 与 PySide6 GUI 双模式。
argument-hint: "<skill-dir-or-skill-file>"
---

# Skill Sandbox (AI Agent 技能安全沙箱)

安全隔离与自动化评判 AI 技能（SKILL.md / 技能包）的测试评估套件。

## 适用场景
- 评估第三方技能或外部导入技能的安全性（文件越权、环境变量探测、敏感路径访问）
- 自动生成领域专属测试物料（代码评审/OCR票据/工作流/知识库等），执行闭环测试
- LLM-as-Judge 多维度评判：行为与用途一致性、产物与定义一致性、安全合规性

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
# 启动图形界面 (支持自动拉起后端、日志实时流式渲染、偏差报告展示)
python frontend/main.py --port 8000
```

## 核心能力
1. **领域感知与测试流定制**：自动识别 `code_development`, `ocr_document`, `memory_knowledge`, `workflow_automation` 等技能领域并动态提供测试样例。
2. **底层安全隔离与拦截**：内核级 Hook 监控文件 I/O，拦截越权写操作并实时输出单行 JSON 追踪日志。
3. **多维 LLM-as-Judge 报告**：评估产物真实度，给出具体代码 Bug 或路径证据，输出结构化判决。
