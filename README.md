# Skill Sandbox (AI Agent 技能安全沙箱 & 多维评估系统)

> **双平台深度支持**：既可以作为标准的 **AI Agent 技能 (Skill)** 供大模型直接调度，也可以作为独立的 **PySide6 桌面 GUI 客户端** / **FastAPI 异步微服务** 供开发者进行可视化本地调试、靶向物料注入与多维评估。

---

## 🌟 核心特性 (v1.1.3)

- 🛡️ **底层安全沙箱与精准溯源**：
  - **工程目录树追溯 (`Node-Tree`)**：自动遍历并高亮呈现被测技能的完整文件目录树与文件尺寸。
  - **源码敏感特征定位 (`Node-Vulnerability-Trace`)**：静态代码分析精准扫描定位跨层工作区逃逸（`..` 目录越界）、未受控常驻后台死循环等异常特征的代码行号与风险。
  - **沙箱内核 Hook 阻断**：严格限制文件 I/O 隔离域，坚决拦截越权外部写入，防污染屏障实时生效。

- 🎛️ **交互式测试材料面板 (GUI)**：
  - **自定义话术输入 (Prompt)**：支持输入业务测试话术与用户提示词（如“请审查这段Python代码的Bug”、“提取发票抬头与金额”），留空则自适应领域匹配。
  - **多格式物料上传与管理**：支持上传待测代码文件（`.py`）、业务数据（`.json`/`.csv`）、文档（`.md`/`.pdf`）及票据图片（`.jpg`/`.png` 等），自动隔离注入沙箱。

- ⚖️ **LLM-as-Judge 深度可解释与可执行评估报告**：
  - **用途-行为一致性**：评估技能实际行为是否符合声称定位（如 AST 语法分析、StateDB 装配校验等）。
  - **产物-定义一致性**：评估生成的报告、清单或数据是否真实有效。
  - **安全性合理性**：列出越权拦截的绝对路径与防污染屏障有效性。
  - **偏差剖析 (Deviation Analysis)**：精准剖析行为与用途的偏离细节。
  - **可用性判定 (Usability Verdict)**：给出明确的可用性判定级别（Pass / 有条件可用 Conditional Pass / Needs Review）。
  - **针对性修复建议 (Actionable Recommendations)**：给出代码与架构层面的可落地整改建议。

- 🚀 **系统健壮性与跨平台体验**：
  - **无死锁流式管道**：子进程与后端无阻塞通信，彻底杜绝 I/O 阻塞卡死。
  - **Windows UTF-8 全链路贯通**：集成 PEP 540 UTF-8 模式，彻底杜绝终端中文菱形乱码。

---

## 📂 项目结构

```text
skill-sandbox/
├── SKILL.md              # AI Agent 技能定义文件（双平台标准入口）
├── README.md             # 项目详细说明文档
├── requirements.txt      # 运行依赖环境清单
├── backend/
│   ├── main.py           # FastAPI + WebSocket 异步后端入口（含自动落盘机制）
│   ├── sandbox_manager.py# 沙箱管理器核心（含目录树追溯、敏感代码定位与 Judge 报告）
│   └── requirements.txt  # 后端独立依赖
├── frontend/
│   └── main.py           # PySide6 GUI 桌面客户端（含交互式材料面板与全景报告渲染）
└── skill/
    └── skill.md          # 示例测试流程工作流文件
```

---

## 🚀 使用指南

### 平台一：作为 AI Agent 技能使用 (Skill 模式)

将本仓库放置于智能体技能目录（如 `~/.agents/skills/skill-sandbox` 或 `~/AppData/Roaming/LobsterAI/SKILLs/skill-sandbox`），Agent 会根据 `SKILL.md` 自动加载并调用。

#### 命令行调用沙箱测试
```bash
# 启动后端服务 (默认端口 8000)
python backend/main.py --port 8000
```

---

### 平台二：作为桌面 GUI 应用程序使用 (GUI 模式)

#### 1. 安装依赖
```bash
python -m pip install -r requirements.txt
```

#### 2. 启动桌面客户端
```bash
python frontend/main.py
```

#### 3. 支持的命令行快速测试参数
```bash
# 自动加载技能并带自定义物料一键运行
python frontend/main.py --auto-run --port 8000   --skill-file "SKILL.md"   --work-dir "path/to/your-skill-package"   --user-prompt "请深度审查这段订单结算逻辑"   --material-file "path/to/order_service.py"   --material-image "path/to/invoice.jpg"
```

---

## 📊 深度评估分析报告 Demo (LLM Judge)

```markdown
# 🛡️ AI 技能全真沙箱测试与多维评估分析报告

## 一、技能工程结构与敏感源头追溯
### 📁 工程文件目录树
├── empire_bootstrap.py (10.0 KB)
├── README.md (2.2 KB)
└── SKILL.md (1.4 KB)

### 🔍 敏感与越权代码源头定位
- **[工作区逃逸/跨层目录越界]** `empire_bootstrap.py` (第11行): `BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))`
  - *风险*: 试图跳出自身技能目录访问宿主工作区，破坏沙箱文件隔离边界。
- **[未受控常驻后台死循环]** `empire_bootstrap.py` (第142行): `"    while True:\n"`
  - *风险*: 无退出条件的长周期后台循环，易产生孤儿进程与系统资源长期占用。

---

## 二、多维评判偏差深度剖析 (Deviation Analysis)
- **声称用途**: `Empire Genesis V2 (帝国创世纪-自检版)` (主领域: `系统架构/基础设施装配`)
- **偏差剖析**: 路径与架构偏离: 检出[2]处敏感代码，存在工作区逃逸假定或未受控后台进程风险。

---

## 三、可用性判定 (Usability Verdict)
- **判定结论**: **有条件可用 (Conditional Pass)**
- **任务能力评估**: 核心业务逻辑正常有效，但在非标准层级目录运行或受限权限环境中可能因路径越权假定发生异常，需完成路径适配。

---

## 四、修复与优化建议 (Actionable Recommendations)
1. 修复 empire_bootstrap.py (第11行): 避免使用 os.path.join(..., '..', '..') 硬编码相对路径，建议改用 os.environ.get('OPENCLAW_WORKSPACE') 或动态向上寻根机制。
2. 优化 empire_bootstrap.py (第142行): 避免在脚本内部 while True 阻塞死循环，建议配合系统级守护进程 (如 Cron / Task Scheduler) 触发周期巡检。
```

---

## 📄 License
MIT License
