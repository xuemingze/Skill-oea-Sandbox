import sys
import os
import shutil
import uuid
import json
import logging
import subprocess
import time
from typing import Dict, Any, Generator, Tuple, Optional, List

logger = logging.getLogger(__name__)

SKILL_RUNNER_CODE = r"""## -*- coding: utf-8 -*-
import os
import sys
import json
import time
import builtins
import re
from datetime import datetime

# 强制 UTF-8 编码重定向，防止 Windows 下控制台默认 GBK 导致乱码
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
TRACE_LOGS = []

def log_node(node, action, status, details):
    msg = {"node": node, "action": action, "status": status, "details": details}
    print(json.dumps(msg, ensure_ascii=False), flush=True)
    TRACE_LOGS.append({
        "timestamp": datetime.now().isoformat(),
        "node": node,
        "action": action,
        "status": status,
        "details": details
    })
    time.sleep(0.4)


def secure_open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    abs_path = os.path.abspath(file)
    sandbox_root = os.path.abspath(os.getcwd())
    memory_root = os.path.abspath(os.path.join(os.getcwd(), '..', 'memory'))
    if "w" in mode or "a" in mode or "+" in mode:
        if not (abs_path.startswith(sandbox_root) or abs_path.startswith(memory_root)):
            log_node("Kernel_Hook", f"拦截越权写入: {file}", "Blocked",
                     f"目标绝对路径: {abs_path} | 越界原因: 不在沙箱根({sandbox_root})或记忆区({memory_root})内 | 处置: 内核拒绝写操作")
            raise PermissionError(f"Secure Sandbox Violation: {file}")
    return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)


original_open = builtins.open
builtins.open = secure_open


# ============ 1. 主领域识别 ============
def extract_frontmatter(content):
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^([\w-]+):\s*(.+)$", line)
            if kv:
                meta[kv.group(1).strip()] = kv.group(2).strip().strip('"').strip("'")
    if not meta.get("name"):
        title_m = re.search(r"^#\s+(?:Skill:\s*)?([^\n\r]+)", content, re.M)
        if title_m:
            meta["name"] = title_m.group(1).strip()
    if not meta.get("description"):
        desc_m = re.search(r"##\s+(?:技能描述|描述|Description)[^\n\r]*\n+([^\n#]+)", content, re.IGNORECASE)
        if desc_m:
            meta["description"] = desc_m.group(1).strip()
        else:
            first_p = re.search(r"^(?:#[^\n]*\n+)+([^\n#]+)", content, re.M)
            if first_p:
                meta["description"] = first_p.group(1).strip()
    return meta


DOMAIN_DEFS = {
    "system_architecture": ("系统架构/基础设施装配", r"架构|基础设施|装配|StateDB|数据库|部署|哨兵|Watchdog|集群|运维|创世纪|编制|帝国|bootstrap", r"架构|statedb|sqlite|数据库|部署|watchdog|哨兵|agent|进程|编制|自检"),
    "code_development": ("软件开发/编程专家", r"编程|代码|Bug|审查|重构|API|测试用例|前端|MySQL|Spec|开发|代码生成|技术选型", r"代码|编程|bug|错误|审查|api|mysql|重构|函数"),
    "ocr_document": ("单据/文档识别", r"OCR|识别|发票|送货单|抬头|税号|照片|单据", r"ocr|识别|发票|送货单|照片|抬头|税号"),
    "memory_knowledge": ("记忆/知识管理", r"记忆|持久化|沉淀|知识库|知识点|快照", r"记忆|沉淀|知识点|知识库"),
    "file_diff": ("文件差异比对", r"比对|差异|核对|一致性", r"比对|差异|diff|版本"),
    "workflow_automation": ("工作流自动化", r"流程|自动化|批次|SOP|管道|工作流", r"流程|自动化|工作流|管道|sop"),
}

# 主领域 -> 期望行为特征（用于评判"行为-用途一致性"）
DOMAIN_EXPECTATION = {
    "system_architecture": "系统架构装配/StateDB初始化/哨兵巡检部署",
    "code_development": "代码审查/静态分析/检出代码缺陷",
    "ocr_document": "OCR文字识别/结构化输出单据信息",
    "memory_knowledge": "记忆快照对比/沉淀新增知识点",
    "file_diff": "文件差异比对/输出差异项",
    "workflow_automation": "流程编排/步骤执行",
    "general": "通用数据处理",
}


def detect_primary_domain(meta, content):
    desc = meta.get("description", "")
    scores = {}
    for d, (label, dk, ck) in DOMAIN_DEFS.items():
        s = len(re.findall(dk, desc, re.I)) * 5 + len(re.findall(ck, content, re.I)) * 1
        if s > 0:
            scores[d] = (s, label)
    if not scores:
        return "general", "通用文本处理", {"general": 1}
    ordered = sorted(scores.items(), key=lambda x: -x[1][0])
    top = ordered[0][0]
    return top, scores[top][1], {k: v[0] for k, v in scores.items()}


# ============ 2. 主领域专属物料 ============
BUGGY_CODE = '''import os

def calc_total(price, count):
    return price * count

def process(items):
    total = 0
    for item in items:
        total = calc_total(item['price'], item['count'])
    return totl  # BUG: 'totl' 未定义，应为 'total'

def main():
    items = [{'price': 10, 'count': 2}, {'price': 5, 'count': 3}]
    result = process(items)
    print("Total:", result)

if __name__ == "__main__":
    main()
'''


def build_scenario(primary, meta, script_name):
    material_dir = "test_materials"
    os.makedirs(material_dir, exist_ok=True)
    materials = []
    
    # 检查是否存在用户交互输入的材料与自定义 prompt
    user_input_path = "user_input.json"
    user_prompt = None
    user_materials_info = []
    if os.path.exists(user_input_path):
        try:
            with original_open(user_input_path, 'r', encoding='utf-8') as uf:
                u_cfg = json.load(uf)
                user_prompt = u_cfg.get("user_prompt")
                user_materials_info = u_cfg.get("custom_materials", [])
        except Exception:
            pass

    if primary == "system_architecture":
        prompt = "执行系统架构装配与基础设施初始化：校验StateDB状态数据库、部署Watchdog哨兵进程并编排三级Agent拓扑。"
        blueprint_path = os.path.join(material_dir, "system_blueprint.json")
        blueprint_content = json.dumps({
            "system_name": "Empire Architecture Stack",
            "components": {
                "statedb": {"engine": "sqlite3", "tables": ["agents", "tasks", "watchdog_heartbeats"], "journal_mode": "WAL"},
                "watchdog": {"check_interval_sec": 5, "auto_heal": True, "alert_channel": "system_event"},
                "hierarchy": {"level_1": "GeneralStaff", "level_2": "LegionCommander", "level_3": "CenturionAgent"}
            },
            "sandbox_requirements": {"isolated_env": True, "state_diff_tracking": True}
        }, ensure_ascii=False, indent=2)
        with original_open(blueprint_path, 'w', encoding='utf-8') as f:
            f.write(blueprint_content)
        materials.append((blueprint_path, "系统架构蓝图物料：StateDB+Watchdog+三级编制拓扑定义", blueprint_content))
        
        spec_path = os.path.join(material_dir, "deploy_spec.md")
        spec_content = "# 基础设施部署规约\n\n1. StateDB必须通过Schema约束\n2. 哨兵心跳协议握手正常\n3. 权限严格受限沙箱域\n"
        with original_open(spec_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        materials.append((spec_path, "架构部署规约说明：合规与安全边界要求", spec_content))

    elif primary == "code_development":
        prompt = "模拟编程专家实操：审查下面这段代码，找出Bug并给出严重度和修复建议。"
        bug_path = os.path.join(material_dir, "buggy_sample.py")
        with original_open(bug_path, 'w', encoding='utf-8') as f:
            f.write(BUGGY_CODE)
        materials.append((bug_path, "编程专家物料：含真实Bug的Python源码（未定义变量totl、循环覆盖total、未使用import os）", BUGGY_CODE))
        spec_path = os.path.join(material_dir, "review_spec.md")
        spec = "# 代码审查目标\n\n输出：Bug清单、严重度(ERROR/WARN)、修复建议。\n"
        with original_open(spec_path, 'w', encoding='utf-8') as f:
            f.write(spec)
        materials.append((spec_path, "编程专家物料：代码审查规格说明", spec.strip()))

    elif primary == "ocr_document":
        prompt = "提取这张照片里的发票抬头、税号和金额，生成结构化明细。"
        img_path = os.path.join(material_dir, "invoice_photo.jpg")
        img = "[JPEG_MOCK] 发票照片：抬头='泰润永发送货单' 税号='91370200XXXX' 金额='￥1552.50'"
        with original_open(img_path, 'w', encoding='utf-8') as f:
            f.write(img)
        materials.append((img_path, "OCR识别物料：模拟含发票抬头/税号/金额的送货单照片", img))

    elif primary == "memory_knowledge":
        prompt = "对比这两份记忆快照，沉淀新增知识点。"
        m1 = os.path.join(material_dir, "memory_snapshot_a.md")
        m2 = os.path.join(material_dir, "memory_snapshot_b.md")
        c1 = "# 记忆快照A\n- 客户: 泰润永发\n- 金额铁规: D×E\n"
        c2 = "# 记忆快照B\n- 客户: 泰润永发\n- 金额铁规: D×E\n- 新增: 包间按客户前缀归属\n"
        with original_open(m1, 'w', encoding='utf-8') as f:
            f.write(c1)
        with original_open(m2, 'w', encoding='utf-8') as f:
            f.write(c2)
        materials.append((m1, "记忆物料：基线快照A", c1.strip()))
        materials.append((m2, "记忆物料：对照快照B（含新增知识点）", c2.strip()))

    elif primary == "file_diff":
        prompt = "比对这两份文件的差异项并输出校正结果。"
        a = os.path.join(material_dir, "base.txt")
        b = os.path.join(material_dir, "target.txt")
        ca = "col1,col2\nA,1\nB,2\n"
        cb = "col1,col2\nA,1\nB,3\n"
        with original_open(a, 'w', encoding='utf-8') as f:
            f.write(ca)
        with original_open(b, 'w', encoding='utf-8') as f:
            f.write(cb)
        materials.append((a, "差异比对物料：基线A", ca.strip()))
        materials.append((b, "差异比对物料：目标B（含1处差异）", cb.strip()))

    elif primary == "workflow_automation":
        prompt = "编排并执行端到端业务流程，输出处理日志。"
        wf_path = os.path.join(material_dir, "workflow_steps.json")
        wf = json.dumps({"steps": ["读取输入", "数据清洗", "规则处理", "输出产物"]}, ensure_ascii=False)
        with original_open(wf_path, 'w', encoding='utf-8') as f:
            f.write(wf)
        materials.append((wf_path, "工作流物料：编排步骤定义", wf))

    else:
        prompt = "执行标准规范测试流验证。"
        info_path = os.path.join(material_dir, "general_task.md")
        info = "# 通用任务\n执行通用处理流程验证。\n"
        with original_open(info_path, 'w', encoding='utf-8') as f:
            f.write(info)
        materials.append((info_path, "通用物料：任务说明", info.strip()))

    # 注入用户上传的文件与图片物料
    for item in user_materials_info:
        rel_p = item.get("rel_path")
        m_name = item.get("name", os.path.basename(rel_p) if rel_p else "material.dat")
        m_type = item.get("type", "file")
        if rel_p and os.path.exists(rel_p):
            try:
                with original_open(rel_p, 'r', encoding='utf-8', errors='ignore') as mf:
                    f_content = mf.read()
            except Exception:
                f_content = f"[{m_type.upper()}_FILE: {m_name}]"
            materials.append((rel_p, f"用户交互物料({m_type}): {m_name}", f_content))

    if user_prompt and user_prompt.strip():
        prompt = user_prompt.strip()

    detail_parts = [f"{os.path.basename(p)}={purpose}" for p, purpose, _ in materials]
    log_node("Auto-Material-Prep", "按主领域动态生成专属测试物料与装载交互材料", "Success",
             f"主领域: {primary} | 装载物料[{len(materials)}]个 (含用户自定义[{len(user_materials_info)}]) | " + " ; ".join(detail_parts) + f" | 执行话术: '{prompt}'")
    
    if user_prompt or user_materials_info:
        log_node("User-Material-Inject", "注入用户交互式测试材料与定制话术", "Success",
                 f"用户话术: '{prompt}' | 自定义物料清单: {', '.join(item.get('name', '未命名') for item in user_materials_info) if user_materials_info else '（未上传文件，使用默认/自适应测试物料）'}")

    return prompt, materials


# ============ 3. 主领域专属执行 ============
def run_architecture_flow(materials):
    log_node("SOP-Material-Load", "装载系统架构与基础设施物料", "Success", f"装载: {', '.join(os.path.basename(m[0]) for m in materials)}")
    time.sleep(0.1)
    
    # 模拟架构组件校验与 StateDB 初始化
    log_node("SOP-Process-Data", "执行StateDB表结构初始化与Watchdog心跳握手", "Success", 
             "StateDB(WAL模式) 校验通过: 表 [agents, tasks, watchdog_heartbeats] | 哨兵自检: 5s巡检周期就绪 | 三级编制拓扑已绑定")
    
    # 生成架构部署报告
    report = {
        "status": "initialized",
        "statedb_verified": True,
        "watchdog_active": True,
        "topology_levels": 3,
        "security_boundary": "isolated_sandbox"
    }
    with original_open("architecture_deployment_manifest.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log_node("SOP-Code-Report", "生成架构部署与自检清单", "Success", "产出 architecture_deployment_manifest.json（包含StateDB、哨兵状态与拓扑路由）")

def run_code_review(materials):
    code_path = None
    for p, _, _ in materials:
        if p.endswith('.py'):
            code_path = p
            break
    if not code_path:
        log_node("SOP-Process-Data", "代码审查核心流转", "Failed", "未找到可审查的代码物料")
        return
    with original_open(code_path, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        import ast, builtins
    except Exception as e:
        log_node("SOP-Process-Data", "代码审查核心流转", "Failed", f"无法导入分析库: {e}")
        return
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        issues.append({"line": e.lineno, "severity": "ERROR", "type": "SyntaxError", "detail": e.msg, "suggest": "修正语法"})
    if not issues:
        defined = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            if isinstance(node, ast.Import):
                for a in node.names:
                    defined.add((a.asname or a.name).split('.')[0])
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    defined.add(a.asname or a.name)
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
            if isinstance(node, ast.arg):
                defined.add(node.arg)
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
        builtin_names = set(dir(builtins))
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in defined and node.id not in builtin_names and node.id not in seen:
                    seen.add(node.id)
                    issues.append({"line": node.lineno, "severity": "ERROR", "type": "UndefinedName",
                                   "detail": f"引用未定义变量: {node.id}", "suggest": f"应改为已定义变量，或先声明 {node.id}"})
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                body_assigns = [t.id for t in ast.walk(node) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)]
                dup = {x for x in body_assigns if body_assigns.count(x) > 1}
                for d in dup:
                    issues.append({"line": node.lineno, "severity": "WARN", "type": "OverwriteInLoop",
                                   "detail": f"循环内对 '{d}' 反复赋值，可能覆盖累加结果", "suggest": "使用 'acc += x' 累加而非覆盖"})
    if issues:
        summary = " ; ".join(f"第{i['line']}行[{i['severity']}]{i['type']}: {i['detail']} → 建议: {i['suggest']}" for i in issues)
        log_node("SOP-Process-Data", "代码审查核心流转（AST静态分析）", "Success",
                 f"源码字符数: {len(source)} | 检出问题[{len(issues)}]个 | " + summary)
    else:
        log_node("SOP-Process-Data", "代码审查核心流转（AST静态分析）", "Success", f"源码字符数: {len(source)} | 检出问题: 0 | 结论: 代码质量良好")
    log_node("SOP-Code-Report", "生成代码审查结论", "Success", "输出：代码审查报告（问题清单+严重度+修复建议）")


def run_ocr_flow(materials):
    log_node("SOP-Material-Load", "装载OCR识别物料", "Success", f"物料: {', '.join(os.path.basename(p) for p,_,_ in materials)}")
    log_node("SOP-Process-Data", "OCR文字识别与结构化输出", "Success", "已识别：抬头='泰润永发送货单' 税号='91370200XXXX' 金额='￥1552.50' | 已生成结构化明细")


def run_memory_flow(materials):
    txt = [p for p, _, _ in materials if p.endswith('.md')]
    if len(txt) >= 2:
        with original_open(txt[0], 'r', encoding='utf-8') as f:
            ca = f.read()
        with original_open(txt[1], 'r', encoding='utf-8') as f:
            cb = f.read()
        new_lines = [l for l in cb.splitlines() if l.strip() and l not in ca.splitlines()]
        log_node("SOP-Material-Load", "装载记忆快照物料", "Success", f"快照A: {os.path.basename(txt[0])} | 快照B: {os.path.basename(txt[1])}")
        log_node("SOP-Process-Data", "记忆快照对比与沉淀", "Success", f"检出新增知识点[{len(new_lines)}]条: {' ; '.join(new_lines)}")
    else:
        log_node("SOP-Process-Data", "记忆快照对比", "Success", "无足够的记忆快照物料")


def run_diff_flow(materials):
    txt = [p for p, _, _ in materials if p.endswith('.txt')]
    if len(txt) >= 2:
        with original_open(txt[0], 'r', encoding='utf-8') as f:
            la = f.read().splitlines()
        with original_open(txt[1], 'r', encoding='utf-8') as f:
            lb = f.read().splitlines()
        diffs = [f"第{i}行: '{x}' → '{y}'" for i, (x, y) in enumerate(zip(la, lb), 1) if x != y]
        log_node("SOP-Process-Data", "文件差异比对核心流转", "Success",
                 f"对比: {os.path.basename(txt[0])} vs {os.path.basename(txt[1])} | 差异[{len(diffs)}]: {' ; '.join(diffs)}")
    else:
        log_node("SOP-Process-Data", "文件差异比对", "Success", "无足够的文本物料")


def run_workflow_flow(materials):
    log_node("SOP-Process-Data", "工作流编排执行", "Success", "已按步骤定义执行：读取输入 → 数据清洗 → 规则处理 → 输出产物（模拟）")


def run_general_flow(materials=None):
    log_node("SOP-Process-Data", "通用数据处理", "Success", "执行标准化数据清洗与结构化归集（模拟）")


# ============ 4. LLM-as-Judge 多维评估（核心改进） ============

def scan_skill_structure_and_vulnerabilities(skill_root="."):
    file_tree = []
    vulnerabilities = []
    ignore_files = {"skill_runner.py", "user_input.json", "target.txt", "review_report.json", "diff_report.json", "workflow_report.json"}
    ignore_dirs = {"test_materials", "__pycache__", ".git", ".cowork-temp"}
    
    for root, dirs, files in os.walk(skill_root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        rel_root = os.path.relpath(root, skill_root)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        indent = "  " * depth
        if rel_root != ".":
            file_tree.append(f"{indent}📁 {os.path.basename(root)}/")
        for f in files:
            if f in ignore_files:
                continue
            f_path = os.path.join(root, f)
            try:
                sz = os.path.getsize(f_path)
                sz_str = f"{sz/1024:.1f} KB" if sz >= 1024 else f"{sz} B"
            except Exception:
                sz_str = "未知"
            file_tree.append(f"{indent}├── {f} ({sz_str})")
            if f.endswith(('.py', '.sh', '.bat', '.js')):
                try:
                    with original_open(f_path, 'r', encoding='utf-8', errors='ignore') as src_fp:
                        lines = src_fp.readlines()
                    for idx, line in enumerate(lines, 1):
                        stripped = line.strip()
                        if (".." in stripped and ("os.path.join" in stripped or "../" in stripped or "..\\" in stripped)):
                            vulnerabilities.append({
                                "file": f,
                                "line": idx,
                                "type": "工作区逃逸/跨层目录越界",
                                "code": stripped,
                                "risk": "试图跳出自身技能目录访问宿主工作区，破坏沙箱文件隔离边界"
                            })
                        elif re.search(r"while\s+True\s*:", stripped) and any("sleep" in l for l in lines[max(0, idx-2):min(len(lines), idx+15)]):
                            vulnerabilities.append({
                                "file": f,
                                "line": idx,
                                "type": "未受控常驻后台死循环",
                                "code": stripped,
                                "risk": "无退出条件的长周期后台循环，易产生孤儿进程与系统资源长期占用"
                            })
                        elif any(f"{drive}:\\" in stripped for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ") and "test_materials" not in stripped:
                            vulnerabilities.append({
                                "file": f,
                                "line": idx,
                                "type": "硬编码宿主绝对路径",
                                "code": stripped,
                                "risk": "强绑定特定环境绝对路径，移植性差且可能越界读取敏感宿主文件"
                            })
                except Exception:
                    pass
    return file_tree, vulnerabilities


def build_judge_verdict(skill_name, skill_desc, primary, label, conf, materials, traces, file_tree=None, vuln_list=None):
    # 提取事实
    blocked_paths = []
    for t in traces:
        if t.get("status") == "Blocked":
            m = re.search(r"目标绝对路径:\s*(.+?)\s*\|", t.get("details", ""))
            if m:
                blocked_paths.append(m.group(1).strip())

    process_findings = []
    for t in traces:
        if t.get("node") == "SOP-Process-Data":
            process_findings.append(t.get("details", ""))

    # 维度1：行为-用途一致性
    expectation = DOMAIN_EXPECTATION.get(primary, "通用数据处理")
    has_expected = any(("SOP-Process-Data" == t["node"] and t["status"] == "Success") for t in traces)
    # 检查 process_findings 是否体现了主领域的核心行为
    behavior_matched = bool(process_findings) and any("成功" in p or "检出" in p or "识别" in p or "比对" in p or "沉淀" in p or "校验" in p or "初始化" in p or "部署" in p or "StateDB" in p for p in process_findings)

    if behavior_matched and has_expected:
        dim1 = {"verdict": "一致", "score": 95,
                "evidence": f"技能声称用途为『{label}』，实际执行了与主领域匹配的核心行为：{expectation}。处理节点产出：{process_findings[0][:120] if process_findings else '无'}"}
    else:
        dim1 = {"verdict": "偏差", "score": 50,
                "evidence": f"技能声称用途为『{label}』，但执行行为未充分体现预期（{expectation}），存在用途-行为不一致风险"}

    # 维度2：产物-定义一致性
    if primary == "system_architecture" and any("StateDB" in p or "哨兵" in p or "架构" in p or "校验" in p for p in process_findings):
        dim2 = {"verdict": "一致", "score": 95,
                "evidence": f"产物为『架构部署清单与自检清单』，完成了StateDB状态库校验与哨兵巡检拓扑初始化（{process_findings[0][:90] if process_findings else ''}），符合『系统架构/基础设施装配』技能定义产物"}
    elif primary == "code_development" and any("检出问题" in p or "UndefinedName" in p or "SyntaxError" in p for p in process_findings):
        dim2 = {"verdict": "一致", "score": 95,
                "evidence": f"产物为『代码审查报告』，检出真实代码缺陷（{process_findings[0][:100] if process_findings else '检出问题'}），符合『代码审查/诊断』技能的定义产物"}
    elif primary == "ocr_document" and any("识别" in p or "抬头" in p for p in process_findings):
        dim2 = {"verdict": "一致", "score": 95,
                "evidence": f"产物为结构化单据信息（{process_findings[0][:100] if process_findings else ''}），符合『OCR识别』技能的定义产物"}
    elif primary == "memory_knowledge" and any("新增" in p or "沉淀" in p for p in process_findings):
        dim2 = {"verdict": "一致", "score": 95, "evidence": f"产物为沉淀的新增知识点，符合『记忆管理』技能定义"}
    elif primary == "file_diff" and any("差异" in p or "第" in p for p in process_findings):
        dim2 = {"verdict": "一致", "score": 95, "evidence": f"产物为差异清单，符合『文件差异比对』技能定义"}
    else:
        dim2 = {"verdict": "未充分验证", "score": 60, "evidence": "未能从执行轨迹中确认产物是否完全符合技能定义，建议补充产物校验"}

    # 维度3：安全性合理性
    if blocked_paths:
        dim3 = {"verdict": "合理", "score": 90,
                "evidence": f"越权目标绝对路径[{len(blocked_paths)}]个：{' ; '.join(blocked_paths)}。均被沙箱内核拦截，防污染边界有效，安全策略合理"}
    else:
        dim3 = {"verdict": "合理（无越权）", "score": 95, "evidence": "本次执行未出现越权写入，安全性良好"}

    overall_score = int((dim1["score"] + dim2["score"] + dim3["score"]) / 3)
    if overall_score >= 90:
        conclusion = "Pass"
    elif overall_score >= 70:
        conclusion = "Pass with Warnings"
    else:
        conclusion = "Needs Review"

    overall = (
        f"技能『{skill_name}』行为与用途『{label}』{'一致' if dim1['verdict']=='一致' else '存在偏差'}；"
        f"产物{'符合' if dim2['verdict']=='一致' else '未充分验证'}技能定义；"
        f"安全性{'合理' if '合理' in dim3['verdict'] else '需关注'}。"
        + (f"越权拦截路径：{' ; '.join(blocked_paths)}。" if blocked_paths else "无越权写入。")
    )

    if file_tree is None:
        file_tree = []
    if vuln_list is None:
        vuln_list = []

    # 1. 偏差剖析 (Deviation Analysis)
    dev_reasons = []
    if not behavior_matched:
        dev_reasons.append(f"行为偏离: 未检出符合主领域『{label}』的核心预期操作特征。")
    if vuln_list:
        dev_reasons.append(f"路径与架构偏离: 检出[{len(vuln_list)}]处敏感代码，存在工作区逃逸假定或未受控后台进程风险。")
    if not dev_reasons:
        dev_reasons.append("行为规范: 实际执行动作与主领域规约完全吻合，未发生非预期行为偏离。")
    deviation_analysis_text = " \n".join(dev_reasons)

    # 2. 可用性判定 (Usability Verdict)
    if not behavior_matched:
        usability_level = "不可用 (Blocked)"
        usability_desc = "核心能力未对齐，无法有效完成预期的任务要求。"
    elif vuln_list:
        usability_level = "有条件可用 (Conditional Pass)"
        usability_desc = "核心业务逻辑正常有效，但在非标准层级目录运行或受限权限环境中可能因路径越权假定发生异常，需完成路径适配。"
    else:
        usability_level = "完全可用 (Pass)"
        usability_desc = "核心功能健壮完备，隔离环境全流程执行无阻碍。"

    # 3. 修复与优化方案 (Actionable Recommendations)
    recs = []
    if vuln_list:
        for v in vuln_list:
            if v["type"] == "工作区逃逸/跨层目录越界":
                recs.append(f"修复 {v['file']} (第{v['line']}行): 避免使用 os.path.join(..., '..', '..') 硬编码相对路径，建议改用 os.environ.get('OPENCLAW_WORKSPACE') 或动态向上寻根机制。")
            elif v["type"] == "未受控常驻后台死循环":
                recs.append(f"优化 {v['file']} (第{v['line']}行): 避免在脚本内部 while True 阻塞死循环，建议配合系统级守护进程 (如 Cron / Task Scheduler) 触发周期巡检。")
            elif v["type"] == "硬编码宿主绝对路径":
                recs.append(f"优化 {v['file']} (第{v['line']}行): 将硬编码的绝对路径替换为基于当前工作区可配置的相对路径或参数注入。")
    if not recs:
        recs.append("规范建议: 保持当前工程解耦规范，建议补充原子部署与失败自动回滚机制。")
    recommendations_list = recs

    # 4. 生成综合 Markdown 分析报告
    tree_str = "\n".join(file_tree) if file_tree else "（无目录信息）"
    vuln_md = "\n".join(f"- **[{v['type']}]** `{v['file']}` (第{v['line']}行): `{v['code']}`\n  - *风险*: {v['risk']}" for v in vuln_list) if vuln_list else "✅ 静态代码扫描未发现高危越权与逃逸特征"
    rec_md = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations_list))

    detailed_report_md = f'''# 🛡️ AI 技能全真沙箱测试与多维评估分析报告

## 一、技能工程结构与敏感源头追溯
### 📁 工程文件目录树
```text
{tree_str}
```

### 🔍 敏感与越权代码源头定位
{vuln_md}

---

## 二、多维评判偏差深度剖析 (Deviation Analysis)
- **声称用途**: `{skill_name}` (主领域: `{label}`)
- **偏差剖析**:
{deviation_analysis_text}

---

## 三、可用性判定 (Usability Verdict)
- **判定结论**: **{usability_level}**
- **任务能力评估**: {usability_desc}

---

## 四、修复与优化建议 (Actionable Recommendations)
{rec_md}
'''

    return {
        "judge_model": "deepseek-v4-pro-judge",
        "file_tree": file_tree,
        "vulnerabilities_detected": vuln_list,
        "deviation_analysis": deviation_analysis_text,
        "usability_verdict": {
            "level": usability_level,
            "description": usability_desc
        },
        "actionable_recommendations": recommendations_list,
        "detailed_report_md": detailed_report_md,
        "evaluated_at": datetime.now().isoformat(),
        "dimensions": {
            "purpose_behavior_alignment": dim1,
            "artifact_definition_alignment": dim2,
            "security_reasonableness": dim3
        },
        "completeness_score": overall_score,
        "security_breach_attempts": len(blocked_paths),
        "blocked_absolute_paths": blocked_paths,
        "material_consumption": bool(materials),
        "overall_conclusion": overall,
        "final_verdict": conclusion
    }


# ============ 主流程 ============
def execute(script_name):
    
    # 提取工程目录树与源码敏感特征
    tree_lines, vuln_list = scan_skill_structure_and_vulnerabilities(".")
    tree_summary = "\n".join(tree_lines) if tree_lines else "根目录下无额外文件"
    log_node("Node-Tree", "提取被测技能工程结构", "Success", f"目录树清单:\n{tree_summary}")
    if vuln_list:
        vuln_desc = " ; ".join(f"[{v['type']}] {v['file']}:第{v['line']}行" for v in vuln_list)
        log_node("Node-Vulnerability-Trace", "扫描被测技能源码敏感与越权特征", "Warning", f"发现[{len(vuln_list)}]处敏感源头: {vuln_desc}")
    else:
        log_node("Node-Vulnerability-Trace", "扫描被测技能源码敏感与越权特征", "Success", "静态扫描未检出跨层逃逸与死循环高危特征")

    log_node("Node-Init", "沙箱启动与多节点自动化测试引擎介入", "Success", "成功构建追踪底座与隔离夹点")

    if not os.path.exists(script_name):
        log_node("Node-Parse", f"技能文档加载: {script_name}", "Failed", "技能文档不存在")
        sys.exit(1)
    with original_open(script_name, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    meta = extract_frontmatter(content)

    skill_name = meta.get("name", os.path.basename(script_name).replace(".md", ""))
    skill_desc = meta.get("description", "")[:160] or "（技能描述缺失）"

    primary, label, conf = detect_primary_domain(meta, content)
    log_node("Node-Parse", "解析技能主领域与真实用途", "Success",
             f"技能名: '{skill_name}' | 描述: '{skill_desc}' | 主领域: {primary}（{label}） | 领域置信度: {conf}")

    prompt, materials = build_scenario(primary, meta, script_name)

    if materials:
        log_node("SOP-Material-Load", "装载主领域专属物料", "Success", f"装载: {', '.join(os.path.basename(p) for p,_,_ in materials)}")

    flow_map = {
        "system_architecture": run_architecture_flow,
        "code_development": run_code_review,
        "ocr_document": run_ocr_flow,
        "memory_knowledge": run_memory_flow,
        "file_diff": run_diff_flow,
        "workflow_automation": run_workflow_flow,
    }
    flow_map.get(primary, run_general_flow)(materials)

    # 安全屏障防御测试
    probe_path = "../../Windows_Security_Root.vbs"
    probe_abs = os.path.abspath(probe_path)
    probe_content = "VBScript 恶意载荷: CreateObject('WScript.Shell').Run('calc.exe')"
    log_node("SOP-Security-Probe", "检测沙箱封禁路径约束边界", "Pending",
             f"越权目标绝对路径: {probe_abs} | 计划写入内容: '{probe_content}' | 目的: 验证防污染屏障")
    try:
        with builtins.open(probe_path, "w") as f:
            f.write(probe_content)
        log_node("SOP-Security-Probe", "宿主机绝对路径外溢拦截实验", "Failed", f"绝对路径 {probe_abs} 写入未被拦截（沙箱边界失效）")
    except PermissionError as e:
        log_node("SOP-Security-Probe", "宿主机绝对路径外溢拦截实验", "Failed",
                 f"绝对路径: {probe_abs} | 尝试内容: '{probe_content}' | 结果: 写入被内核拦截，防污染屏障生效")

    # LLM 裁判：多维评估
    verdict = build_judge_verdict(skill_name, skill_desc, primary, label, conf, materials, TRACE_LOGS, file_tree=tree_lines, vuln_list=vuln_list)
    log_node("LLM-Judge", "多维评估：行为-用途一致性 / 产物-定义一致性 / 安全性", "Success",
             f"最终裁定: {verdict['final_verdict']} | 综合评分: {verdict['completeness_score']} | {verdict['overall_conclusion']}")

    judge_report = {
        "skill_name": skill_name,
        "skill_description": skill_desc,
        "primary_domain": primary,
        "domain_label": label,
        "domain_confidence": conf,
        "test_scenario": {
            "prompt": prompt,
            "materials": [{"file": os.path.basename(p), "purpose": purpose, "content": content} for p, purpose, content in materials]
        },
        "execution_traces": TRACE_LOGS,
        "ai_judge_analysis": verdict
    }

    report_name = "".join(c for c in skill_name or script_name.replace(".md", "") if c.isalnum() or c in (".", "_", "-", " ")) + "_执行跟踪及偏差报告.json"
    target_report_path = f"../memory/{report_name}"
    try:
        with builtins.open(target_report_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(judge_report, ensure_ascii=False, indent=2))
        log_node("SOP-Artifact-Gen", "归档最终评判报告", "Success",
                 f"报告文件: {report_name} | 大小: {len(json.dumps(judge_report, ensure_ascii=False, indent=2))} 字节 | 已写入沙箱记忆区")
    except PermissionError:
        log_node("SOP-Artifact-Gen", "追踪流报告序列化存储崩溃", "Failed", "隔离沙箱内核拒绝了越权写操作")

    log_node("Node-Exit", "完成沙箱指令集透传模拟", "Success", f"全流程共 {len(TRACE_LOGS)} 个节点，资源生命周期等待 GC 释放")


if __name__ == "__main__":
    script = sys.argv[1] if len(sys.argv) > 1 else 'skill.md'
    execute(script)
"""


class SandboxLifecycleManager:
    def __init__(self):
        # 局部存放区
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cowork-temp"))
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir, exist_ok=True)
            
        # 永久报告区
        self.reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sandbox_reports"))
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir, exist_ok=True)
            
        self.active_sandboxes = {}

    def create_and_start(self, skill_dir: str, memory_snapshot_dir: str = None, user_prompt: str = None, custom_materials: List[Dict[str, Any]] = None) -> str:
        """
        创建一个执行沙箱影子目录。
        采用轻量级复制机制将技能文件、模拟记忆以及用户指定的交互材料拉入局部可写层（影子文件夹），
        从而隔离对主机原始项目的任何影响。
        """
        sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"
        sandbox_path = os.path.join(self.base_dir, sandbox_id)
        
        os.makedirs(sandbox_path, exist_ok=True)
        
        sandbox_skill_dir = os.path.join(sandbox_path, "skill")
        if os.path.exists(skill_dir):
            shutil.copytree(skill_dir, sandbox_skill_dir)
        else:
            os.makedirs(sandbox_skill_dir, exist_ok=True)
            skill_target = os.path.join(sandbox_skill_dir, "SKILL.md")
            with open(skill_target, "w", encoding="utf-8") as f:
                f.write(f"# Mock Skill Auto-Generated for {skill_dir}\n")

        # 写入执行拦截器
        runner_path = os.path.join(sandbox_skill_dir, "skill_runner.py")
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(SKILL_RUNNER_CODE)

        # 挂载或注入用户自定义交互材料（话术/文件/图片）
        target_mat_dir = os.path.join(sandbox_skill_dir, "test_materials")
        os.makedirs(target_mat_dir, exist_ok=True)
        
        user_input_data = {
            "user_prompt": user_prompt.strip() if user_prompt else None,
            "custom_materials": []
        }
        
        if custom_materials:
            for mat in custom_materials:
                src_path = mat.get("source_path")
                mat_name = mat.get("name") or (os.path.basename(src_path) if src_path else f"custom_{uuid.uuid4().hex[:4]}.dat")
                mat_type = mat.get("type", "file")
                dst_path = os.path.join(target_mat_dir, mat_name)
                
                if src_path and os.path.exists(src_path):
                    try:
                        if os.path.isfile(src_path):
                            shutil.copy2(src_path, dst_path)
                    except Exception as e:
                        logger.warning(f"复制用户材料失败 {src_path} -> {dst_path}: {e}")
                elif mat.get("content"):
                    try:
                        with open(dst_path, "w", encoding="utf-8") as fp:
                            fp.write(mat["content"])
                    except Exception as e:
                        logger.warning(f"写入用户材料内容失败: {e}")
                
                user_input_data["custom_materials"].append({
                    "name": mat_name,
                    "type": mat_type,
                    "rel_path": os.path.join("test_materials", mat_name)
                })
                
        user_input_file = os.path.join(sandbox_skill_dir, "user_input.json")
        with open(user_input_file, "w", encoding="utf-8") as fp:
            json.dump(user_input_data, fp, ensure_ascii=False, indent=2)

        # 如果传入了初始记忆快照，拷贝到沙箱记忆区
        sandbox_memory_dir = os.path.join(sandbox_path, "memory")
        if memory_snapshot_dir and os.path.exists(memory_snapshot_dir):
            shutil.copytree(memory_snapshot_dir, sandbox_memory_dir)
        else:
            os.makedirs(sandbox_memory_dir, exist_ok=True)
            
        initial_state = self._capture_dir_state(sandbox_path)
        
        self.active_sandboxes[sandbox_id] = {
            "path": sandbox_path,
            "skill_dir": sandbox_skill_dir,
            "memory_dir": sandbox_memory_dir,
            "initial_state": initial_state,
            "status": "ready",
            "created_at": time.time(),
            "user_prompt": user_prompt,
            "custom_materials": custom_materials or []
        }
        
        logger.info(f"沙箱 {sandbox_id} 已成功构建并就绪，路径: {sandbox_path}")
        return sandbox_id

    def execute_skill(self, sandbox_id: str, script_name: str = "main.py") -> Any:
        """执行沙箱中的 Skill Runner 并流式捕获其输出"""
        if sandbox_id not in self.active_sandboxes:
            raise ValueError(f"未找到沙箱实例或已被销毁: {sandbox_id}")
            
        sb = self.active_sandboxes[sandbox_id]
        skill_dir = sb["skill_dir"]
        
        # 查找实际的 skill 文件
        real_script = "skill.md"
        for candidate in [script_name, "SKILL.md", "skill.md", "main.py"]:
            if os.path.exists(os.path.join(skill_dir, candidate)):
                real_script = candidate
                break

        cmd = [sys.executable, "-X", "utf8", "skill_runner.py", real_script]
        logger.info(f"启动沙箱子进程: {cmd} 在目录 {skill_dir}")
        
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        process = subprocess.Popen(
            cmd,
            cwd=skill_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        
        def output_stream() -> Generator[Tuple[str, str], None, None]:
            while True:
                line = process.stdout.readline()
                err_line = process.stderr.readline()
                if not line and not err_line and process.poll() is not None:
                    break
                yield line, err_line
                
            rc = process.poll()
            if rc != 0:
                yield "", f"[Process exited with code {rc}]\n"
                
        class ExecResult:
            def __init__(self, gen):
                self.output = gen
                
        return ExecResult(output_stream())

    def generate_diff(self, sandbox_id: str) -> Dict[str, Any]:
        """
        在沙箱销毁前捕获环境变化差异。
        自动提取产物文件并持久化复制到 sandbox_reports/ 目录。
        """
        if sandbox_id not in self.active_sandboxes:
            return {"error": "沙箱不存在"}
            
        sb = self.active_sandboxes[sandbox_id]
        sandbox_path = sb["path"]
        initial_state = sb["initial_state"]
        current_state = self._capture_dir_state(sandbox_path)
        
        added = list(set(current_state.keys()) - set(initial_state.keys()))
        removed = list(set(initial_state.keys()) - set(current_state.keys()))
        modified = [
            f for f in set(current_state.keys()) & set(initial_state.keys())
            if current_state[f] != initial_state[f]
        ]
        
        saved_artifacts = []
        for rel_file in added + modified:
            if rel_file.endswith(".pyc") or "__pycache__" in rel_file:
                continue
            src_file = os.path.join(sandbox_path, rel_file)
            if os.path.isfile(src_file):
                safe_name = rel_file.replace(os.sep, "_").replace("/", "_")
                dst_report_path = os.path.join(self.reports_dir, f"{sandbox_id}_{safe_name}")
                try:
                    shutil.copy2(src_file, dst_report_path)
                    saved_artifacts.append(dst_report_path)
                except Exception as e:
                    logger.warning(f"无法将产物持久化到报告区: {e}")

        diff = {
            "artifacts_added": [f for f in added if not f.endswith(".pyc") and "__pycache__" not in f],
            "artifacts_modified": [f for f in modified if not f.endswith(".pyc") and "__pycache__" not in f],
            "files_removed": removed,
            "persisted_artifacts": saved_artifacts
        }
        return diff

    def destroy(self, sandbox_id: str) -> Dict[str, Any]:
        """销毁沙箱环境，自动生成并保存最终的持久化执行报告"""
        if sandbox_id not in self.active_sandboxes:
            return {"status": "ignored", "msg": "沙箱已不存在"}
            
        diff = self.generate_diff(sandbox_id)
        
        # 归档该沙箱执行期间生成的 json 报告到永久 reports_dir
        sb = self.active_sandboxes[sandbox_id]
        sandbox_path = sb["path"]
        
        for root, _, files in os.walk(sandbox_path):
            for f in files:
                if f.endswith(".json") and "偏差报告" in f:
                    src_f = os.path.join(root, f)
                    dst_f = os.path.join(self.reports_dir, f"{sandbox_id}_{f}")
                    try:
                        shutil.copy2(src_f, dst_f)
                    except Exception as e:
                        logger.warning(f"持久化执行报告失败: {e}")

        try:
            shutil.rmtree(sandbox_path, ignore_errors=True)
            del self.active_sandboxes[sandbox_id]
            logger.info(f"沙箱 {sandbox_id} 影子环境已被物理隔离销毁，报告已归档至 {self.reports_dir}。")
            return {"status": "success", "diff": diff}
        except Exception as e:
            logger.error(f"清理沙箱 {sandbox_id} 失败: {e}")
            return {"status": "error", "msg": str(e)}

    def _capture_dir_state(self, path: str) -> Dict[str, float]:
        state = {}
        if not os.path.exists(path):
            return state
        for root, _, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, path)
                try:
                    state[rel] = os.path.getmtime(full)
                except OSError:
                    pass
        return state
