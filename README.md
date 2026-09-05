# Skill Sandbox (AI 智能体技能安全沙箱与多维评估系统)
> **双平台驱动**：支持作为 **AI Agent 独立调用技能 (Skill 模式)** 与 **PySide6 桌面 GUI 可视化仿真终端** 双模式协同运行。
> 基于领域感知自动构建测试材料，隔离执行全真工作流，提供包含 **5 大核心安全审查项** 与 **LLM-as-Judge 深度四维评估分析**。

## 🌟 核心特性概览

1. **🛡️ 5 大核心安全审查项深度审计**：
   - **🌐 网络调用审查**：扫描 `fetch`, `curl`, `axios`, `http`, `requests`, `urllib`, `aiohttp`, `httpx`, `socket`；
   - **💻 Shell/进程执行审查**：扫描 `child_process`, `subprocess`, `os.system`, `os.popen`, `eval`, `exec`, `spawn`；
   - **🔑 环境与凭证/密钥访问**：扫描 `process.env`, `os.environ`, `os.getenv`, `API_KEY`, `TOKEN`, `SECRET`；
   - **🔏 Base64 编码模式（潜在混淆）**：扫描 `b64decode`, `Buffer.from(..., 'base64')`, `atob` 及高熵特征串；
   - **📦 非文本二进制文件探测**：扫描 `.exe`, `.dll`, `.so`, `.bin`, `.pyc`, `.pyd`, `.wasm`, `.vbs`, `.bat`, `.cmd`。

2. **📁 技能工程文件目录树追溯 (`Node-Tree`)**：
   - 执行初期自动提取并展示被测技能完整工程文件拓扑与尺寸，精准标注敏感/越权代码所在的文件名与行号。

3. **🎛️ 交互式测试材料输入面板 (GUI 增强)**：
   - 支持自定义测试指令/话术（Prompt）、多格式图片（JPG/PNG/WEBP）与代码/业务数据文件（PY/JSON/CSV/MD/DOCX）自由上传与隔离注入。

4. **⚖️ LLM-as-Judge 深度四维评估分析**：
   - 包含 **偏差剖析 (Deviation Analysis)**、**可用性判定 (Usability Verdict)** 与 **可执行修复建议 (Actionable Recommendations)**。

5. **🖥️ GUI 仿真终端控制台全景渲染与防抖归档**：
   - 流式日志高亮渲染、WebSocket 自动刷盘与 `QTimer` 防抖轮询拉取，100% 呈现完整 Markdown 评估报告。

6. **🚀 底层通信加固与 Windows PEP 540 UTF-8 全链路贯通**：
   - 根除子进程双管道阻塞死锁，强制 `-X utf8` 与 `PYTHONUTF8=1`，彻底杜绝中文菱形乱码。

---

## 🚀 双平台使用指南

### 平台一：作为 AI Agent 技能使用 (Skill 模式)

将本仓库放置于智能体技能目录（如 `~/.agents/skills/skill-sandbox` 或 `~/.SKILLs/skill-sandbox`），Agent 会根据 `SKILL.md` 自动加载并调用。

#### 命令行测试调用：
```bash
# 启动后端服务
python backend/main.py --port 8000

# 运行特定技能测试
python backend/sandbox_manager.py --skill "path/to/skill-package"
```

### 平台二：作为桌面 GUI 可视化工具使用

```bash
# 启动图形界面
python frontend/main.py --port 8000

# 自动化运行模式 (带自定义话术与测试材料)
python frontend/main.py --auto-run --port 8000 \
  --skill-file "SKILL.md" \
  --work-dir "path/to/your-skill-package" \
  --user-prompt "请深度审查这段支付结算逻辑" \
  --material-file "path/to/pay_service.py" \
  --material-image "path/to/receipt.jpg"
```

---

## 📊 评估分析报告展示范例 (Report Demo)

```markdown
# 🛡️ AI 技能全真沙箱测试与多维评估分析报告

## 一、技能工程结构与敏感源头追溯
### 📁 工程文件目录树
├── empire_bootstrap.py (10.0 KB)
├── README.md (2.2 KB)
└── SKILL.md (1.4 KB)

### 🛡️ 5 大核心安全审查项命中情况
- **⚠️ [工作区逃逸/跨层目录越界]**: 检出 [1] 处潜在风险
  - `empire_bootstrap.py` (第11行): `BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))`
- **⚠️ [未受控常驻后台死循环]**: 检出 [1] 处潜在风险
  - `empire_bootstrap.py` (第142行): `"    while True:\n"`
- **✅ [网络调用审查]**: 通过 (未检出可疑调用与特征)
- **✅ [环境与密钥凭据访问]**: 通过 (未检出可疑调用与特征)
- **✅ [Base64编码/潜在混淆]**: 通过 (未检出可疑调用与特征)

---

## 二、多维评判偏差深度剖析 (Deviation Analysis)
- **声称用途**: `Empire Genesis V2` (主领域: `系统架构/基础设施装配`)
- **偏差剖析**: 路径与架构偏离: 检出[2]处敏感代码，存在工作区逃逸假定或未受控后台进程风险。

---

## 三、可用性判定 (Usability Verdict)
- **判定结论**: **有条件可用 (Conditional Pass)**
- **任务能力评估**: 核心业务逻辑正常有效，但在非标准层级目录运行或受限权限环境中可能因路径越权假定发生异常，需完成路径适配。

---

## 四、修复与优化建议 (Actionable Recommendations)
1. 修复 empire_bootstrap.py (第11行): 避免使用 os.path.join(..., '..', '..') 硬编码相对路径，建议改用 os.environ.get('OPENCLAW_WORKSPACE') 或动态向上寻根机制。
2. 优化 empire_bootstrap.py (第142行): 避免在脚本内部 while True 阻塞死循环，建议配合系统级守护进程触发周期巡检。
```
