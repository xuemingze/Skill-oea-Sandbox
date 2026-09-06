# Skill-oea-Sandbox (AI 智能体技能安全沙箱与多维评估系统)

> **Skill-oea-Sandbox** (Operational Evaluation & Analysis) 是一套专为 AI Agent 技能包（`SKILL.md`）打造的全真沙箱测试与多维度行为评估分析系统。系统原生支持 **AI 智能体自主调用 (Skill 模式)** 与 **PySide6 可视化桌面应用 (GUI 模式)** 双平台无缝协同。

---

## 🌟 核心特性概览 (v1.3.0)

### 1. 🛡️ 5 大核心安全审查项深度审计
沙箱在执行初期自动对技能源码进行静态特征分析，覆盖 5 大高危审查维度并在终端与报告中逐项呈现：
- **🌐 1. 网络调用审查**：扫描 `fetch`, `curl`, `axios`, `http`, `requests`, `urllib`, `aiohttp`, `httpx`, `socket` 等外联通信；
- **💻 2. Shell/进程执行审查**：扫描 `child_process`, `subprocess`, `os.system`, `os.popen`, `eval`, `exec`, `spawn` 等底层命令执行；
- **🔑 3. 环境与凭据/密钥访问**：扫描 `process.env`, `os.environ`, `os.getenv`, `API_KEY`, `TOKEN`, `SECRET` 等敏感读取；
- **🔏 4. Base64 编码模式（潜在混淆）**：扫描 `b64decode`, `Buffer.from(..., 'base64')`, `atob` 与长 Base64 特征串；
- **📦 5. 非文本二进制文件探测**：扫描 `.exe`, `.dll`, `.so`, `.bin`, `.pyc`, `.pyd`, `.wasm`, `.vbs`, `.bat`, `.cmd`。

### 2. 📁 技能工程目录树追溯 (`Node-Tree`)
- 执行初期自动提取并以结构化树形展示被测技能的完整文件清单与大小；
- 精准标注出具有越权、路径逃逸或敏感异常代码片段所在的文件名与具体行号。

### 3. 🎛️ 交互式测试材料输入面板 (GUI 增强)
- 支持多行自定义业务测试指令与用户话术（Prompt）输入；
- 支持多格式图片（JPG/PNG/WEBP/BMP）与代码/业务数据文件（PY/JSON/CSV/MD/DOCX）自由上传与沙箱隔离注入。

### 4. ♻️ 评判报告与临时目录生命周期回收机制 (核心新增)
- **初次初始化协商**：前端启动或 Agent 首次注册时弹出模态弹窗确认回收周期（默认7天），写入 `sandbox_reports/_config/recycle_policy.json`；
- **多目录过期扫描**：覆盖持久化报告目录 `sandbox_reports/` 与沙箱运行临时目录 `.cowork-temp/`，按 `mtime` 划分 `已过期` 与 `即将过期`；
- **安全防误删暂存区**：删除操作先移入 `_trash/` 暂存 24 小时，支持误操作追溯；
- **提炼归档与索引库**：一键打包压缩至 `_archives/` 并自动在 `archive_index.json` 中维护提炼摘要；
- **可视化表格控件**：GUI 包含独立回收周期控件、扫描进度条与过期列表表格，支持一键清理、打开文件、打开目录与单条处置。

### 5. ⚖️ LLM-as-Judge 深度四维评估与 GUI 全景渲染
- 新增 **偏差剖析 (Deviation Analysis)**、**可用性判定 (Usability Verdict)** 与 **针对性修复建议 (Actionable Recommendations)**；
- GUI 终端控制台自动拉取并以专属高亮卡片完整渲染 `# 🛡️ AI 技能全真沙箱测试与多维评估分析报告`。

---

## 📁 项目工程目录

```text
skill-oea-sandbox/
├── SKILL.md                 # AI Agent 技能定义文件（双平台标准入口）
├── README.md                # 系统架构与多维评判使用说明
├── requirements.txt         # 基础运行环境依赖清单
├── skill/
│   └── skill.md             # 内置示例测试流程与越权防御规范
├── backend/
│   ├── main.py              # FastAPI 后端服务与 WebSocket 实时日志流
│   ├── sandbox_manager.py   # 沙箱隔离引擎、领域识别与 LLM 评判生成器
│   ├── recycle_manager.py   # 生命周期回收管理引擎（扫描/暂存/归档）
│   └── requirements.txt     # 后端服务依赖
├── frontend/
│   ├── main.py              # PySide6 可视化仿真终端控制台
│   ├── recycle_dialogs.py   # 初始化协商与周期到达二次确认弹窗
│   └── recycle_panel.py     # 回收周期控件、进度条与过期列表表格
└── sandbox_reports/         # 持久化评判报告与归档总目录
    ├── _config/             # 回收策略配置 (recycle_policy.json)
    ├── _trash/              # 回收站安全暂存区 (24h 保护)
    └── _archives/           # 提炼归档 zip 与索引库 (archive_index.json)
```

---

## 🚀 双平台使用指南

### 平台一：作为 AI Agent 技能使用 (Skill 模式)

将本仓库放置于智能体技能目录（如 `~/.agents/skills/skill-oea-sandbox` 或 `~/.SKILLs/skill-oea-sandbox`），Agent 会根据 `SKILL.md` 自动加载并调用。

#### 1. 执行全真沙箱测试
```bash
python backend/main.py --port 8000
```

#### 2. AI 主导的生命周期回收指令
```bash
# 扫描过期报告与临时文件
python -c "from backend.recycle_manager import ReportRecycleManager; rm = ReportRecycleManager('.'); print(rm.scan_files())"
```

---

### 平台二：作为独立桌面 GUI 应用使用 (GUI 模式)

#### 1. 安装依赖
```bash
pip install -r requirements.txt
```

#### 2. 启动桌面端可视化控制台
```bash
python frontend/main.py
```

#### 3. 命令行一键参数化执行
```bash
python frontend/main.py --auto-run --port 8000 \
  --skill-file "SKILL.md" \
  --work-dir "path/to/your-skill-package" \
  --user-prompt "请深度审查这段支付结算逻辑" \
  --material-file "path/to/order_service.py" \
  --material-image "path/to/invoice.jpg"
```

---

## 📊 评估分析报告展示范例 (Report Demo)

```markdown
# 🛡️ AI 技能全真沙箱测试与多维评估分析报告

## 一、技能工程结构与敏感源头追溯
### 📁 工程文件目录树
├── skill_main.py (10.0 KB)
├── README.md (2.2 KB)
└── SKILL.md (1.4 KB)

### 🛡️ 5 大核心安全审查项命中情况
- **✅ [网络调用审查]**: 通过 (未检出可疑外联通信)
- **✅ [Shell/进程执行]**: 通过 (未检出任意命令执行)
- **✅ [环境与密钥凭据]**: 通过 (未检出环境变量嗅探与硬编码 Key)
- **✅ [Base64潜在混淆]**: 通过 (未检出 Base64 隐藏 Payload)
- **✅ [非文本二进制文件]**: 通过 (未捆绑不可信二进制载荷)

---

## 二、多维评判偏差深度剖析 (Deviation Analysis)
- **声称用途**: `sample-skill (通用示例技能)`
- **偏差剖析**:
  - 行为高度规范: 实际执行动作与声明功能规约完全吻合，未发生非预期行为偏离。

---

## 三、可用性判定 (Usability Verdict)
- **判定结论**: 完全可用 (Pass)
- **综合得分**: 93 / 100
- **任务能力评估**: 核心业务逻辑完整健壮，各执行节点在沙箱隔离环境中顺畅运行。

---

## 四、修复与优化建议 (Actionable Recommendations)
1. 规范建议: 保持当前工程模块解耦规范，建议后续持续优化临时文件清理与异常回滚机制。
```
