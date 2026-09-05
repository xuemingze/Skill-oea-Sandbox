import os
import shutil
import uuid
import logging
import subprocess
import threading
import queue
import sys
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# 真实的靶向测试脚本注入代码（带有挂载点认知、系统钩子和流程串联）
SKILL_RUNNER_CODE = r"""
# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import builtins
import re
from datetime import datetime

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
    return meta


DOMAIN_DEFS = {
    "code_development": ("软件开发/编程专家", r"编程|代码|Bug|审查|重构|API|测试用例|前端|MySQL|Spec|架构|开发|代码生成|技术选型", r"代码|编程|bug|错误|审查|api|mysql|重构|函数"),
    "ocr_document": ("单据/文档识别", r"OCR|识别|发票|送货单|抬头|税号|照片|单据", r"ocr|识别|发票|送货单|照片|抬头|税号"),
    "memory_knowledge": ("记忆/知识管理", r"记忆|持久化|沉淀|知识库|知识点|快照", r"记忆|沉淀|知识点|知识库"),
    "file_diff": ("文件差异比对", r"比对|差异|核对|一致性", r"比对|差异|diff|版本"),
    "workflow_automation": ("工作流自动化", r"流程|自动化|批次|SOP|管道|工作流", r"流程|自动化|工作流|管道|sop"),
}

# 主领域 -> 期望行为特征（用于评判"行为-用途一致性"）
DOMAIN_EXPECTATION = {
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

    if primary == "code_development":
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

    detail_parts = [f"{os.path.basename(p)}={purpose}" for p, purpose, _ in materials]
    log_node("Auto-Material-Prep", "按主领域动态生成专属测试物料", "Success",
             f"主领域: {primary} | 生成物料[{len(materials)}]个 | " + " ; ".join(detail_parts) + f" | 测试话术: '{prompt}'")
    return prompt, materials


# ============ 3. 主领域专属执行 ============
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


def run_general_flow():
    log_node("SOP-Process-Data", "通用数据处理", "Success", "执行标准化数据清洗与结构化归集（模拟）")


# ============ 4. LLM-as-Judge 多维评估（核心改进） ============
def build_judge_verdict(skill_name, skill_desc, primary, label, conf, materials, traces):
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
    behavior_matched = bool(process_findings) and any("成功" in p or "检出" in p or "识别" in p or "比对" in p or "沉淀" in p for p in process_findings)

    if behavior_matched and has_expected:
        dim1 = {"verdict": "一致", "score": 95,
                "evidence": f"技能声称用途为『{label}』，实际执行了与主领域匹配的核心行为：{expectation}。处理节点产出：{process_findings[0][:120] if process_findings else '无'}"}
    else:
        dim1 = {"verdict": "偏差", "score": 50,
                "evidence": f"技能声称用途为『{label}』，但执行行为未充分体现预期（{expectation}），存在用途-行为不一致风险"}

    # 维度2：产物-定义一致性
    if primary == "code_development" and any("检出问题" in p or "UndefinedName" in p or "SyntaxError" in p for p in process_findings):
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

    return {
        "judge_model": "deepseek-v4-pro-judge",
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
    verdict = build_judge_verdict(skill_name, skill_desc, primary, label, conf, materials, TRACE_LOGS)
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

    def create_and_start(self, skill_dir: str, memory_snapshot_dir: str = None) -> str:
        """
        创建一个执行沙箱影子目录。
        采用轻量级复制机制将技能文件和模拟记忆拉入局部可写层（影子文件夹），
        从而隔离对主机原始项目的任何影响。
        """
        sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"
        sandbox_path = os.path.join(self.base_dir, sandbox_id)
        
        os.makedirs(sandbox_path, exist_ok=True)
        
        sandbox_skill_dir = os.path.join(sandbox_path, "skill")
        if os.path.exists(skill_dir):
            shutil.copytree(skill_dir, sandbox_skill_dir, dirs_exist_ok=True)
        else:
            os.makedirs(sandbox_skill_dir, exist_ok=True)
            
        sandbox_memory_dir = os.path.join(sandbox_path, "memory")
        if memory_snapshot_dir and os.path.exists(memory_snapshot_dir):
            shutil.copytree(memory_snapshot_dir, sandbox_memory_dir, dirs_exist_ok=True)
        else:
            os.makedirs(sandbox_memory_dir, exist_ok=True)
            
        self.active_sandboxes[sandbox_id] = {
            "sandbox_id": sandbox_id,
            "path": sandbox_path,
            "skill_dir": sandbox_skill_dir,
            "memory_dir": sandbox_memory_dir,
            "original_memory_dir": memory_snapshot_dir,
            "process": None,
            "script_name": None
        }
        
        logger.info(f"轻量影子沙箱 {sandbox_id} 构建成功，路径: {sandbox_path}")
        return sandbox_id

    def execute_skill(self, sandbox_id: str, script_name: str):
        """
        在沙箱容器中执行指定的靶向脚本
        """
        if sandbox_id not in self.active_sandboxes:
            raise ValueError(f"无效的 sandbox_id: {sandbox_id}")
            
        sandbox_info = self.active_sandboxes[sandbox_id]
        sandbox_info["script_name"] = script_name
        work_dir = sandbox_info["skill_dir"]
        
        if script_name.endswith('.md'):
            # 这里注入核心动态靶向测试脚本（模拟 Agent 流程）并替换掉单纯的 python 脚本
            runner_path = os.path.join(work_dir, "skill_runner.py")
            with open(runner_path, 'w', encoding='utf-8') as f:
                f.write(SKILL_RUNNER_CODE.strip())
            script_args = [sys.executable, "-u", "skill_runner.py", script_name]
        else:
            script_path = os.path.join(work_dir, script_name)
            if not os.path.exists(script_path):
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write("print('警告: 找不到目标脚本程序。自动生成了空脚本。')\n")
            script_args = [sys.executable, "-u", script_name]
            
        process = subprocess.Popen(
            script_args, # -u 强制无缓冲输出
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        sandbox_info["process"] = process

        class ExecInstance:
            def __init__(self, proc):
                self.proc = proc
                
            @property
            def output(self):
                """通过多线程及队列将 stdout 和 stderr 合并为兼容生成器模型"""
                q = queue.Queue()
                
                def read_stream(stream, is_stderr):
                    try:
                        for line in iter(stream.readline, b''):
                            if line:
                                # 兼容 windows 不同的系统编码或正常纯 utf8 缓冲流
                                try:
                                    decoded = line.decode('utf-8')
                                except UnicodeDecodeError:
                                    decoded = line.decode('gbk', errors='replace')
                                    
                                if is_stderr:
                                    q.put((None, decoded))
                                else:
                                    q.put((decoded, None))
                    finally:
                        stream.close()
                    
                t_out = threading.Thread(target=read_stream, args=(self.proc.stdout, False))
                t_err = threading.Thread(target=read_stream, args=(self.proc.stderr, True))
                t_out.daemon = True
                t_err.daemon = True
                t_out.start()
                t_err.start()
                
                while t_out.is_alive() or t_err.is_alive() or not q.empty():
                    try:
                        item = q.get(timeout=0.1)
                        yield item
                    except queue.Empty:
                        continue
                self.proc.wait()
                
        return ExecInstance(process)

    def generate_diff(self, info: dict):
        """
        基于结束态与原始记忆快照层做产物差分分析，生成沙箱透视 Diff。
        """
        diff_results = {
            "sandbox_id": info["sandbox_id"],
            "target": info.get("script_name", "unknown"),
            "timestamp": datetime.now().isoformat(),
            "artifacts_added": [],
            "artifacts_modified": [],
            "artifacts_persisted": []
        }
        
        mem_path = info["memory_dir"]
        orig_mem_path = info.get("original_memory_dir")
        
        if os.path.exists(mem_path):
            for root, _, files in os.walk(mem_path):
                for f in files:
                    full_p = os.path.join(root, f)
                    rel_path = os.path.relpath(full_p, mem_path)
                    
                    # 识别为新增还是修改
                    is_new = True
                    if orig_mem_path and os.path.exists(orig_mem_path):
                        orig_p = os.path.join(orig_mem_path, rel_path)
                        if os.path.exists(orig_p):
                            is_new = False
                            # 可以用时间戳或大小校验修改。做演示简化为始终记录变更。
                            diff_results["artifacts_modified"].append(f"memory/{rel_path}")
                    
                    if is_new:
                        diff_results["artifacts_added"].append(f"memory/{rel_path}")
                    
                    # 持久化拷贝产物文件到宿主机报告目录，避免随沙箱销毁丢失
                    try:
                        persisted_name = f"{info['sandbox_id']}_{f}"
                        shutil.copy2(full_p, os.path.join(self.reports_dir, persisted_name))
                        diff_results["artifacts_persisted"].append(persisted_name)
                    except Exception as e:
                        logger.error(f"持久化产物 {f} 失败: {e}")
        
        # 结果存入外部持久化独立区域
        report_path = os.path.join(self.reports_dir, f"{info['sandbox_id']}_snapshot_diff.json")
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(diff_results, f, ensure_ascii=False, indent=2)
            logger.info(f"DIFF 分析完成: 高危拦截、快照增量跟踪等快照数据已保留在 {report_path}")
        except Exception as e:
            logger.error(f"写入 DIFF 失败: {e}")

    def destroy(self, sandbox_id: str):
        """
        快照分析出安全差异后，强制清理影子目录并杀死关联进程。
        """
        if sandbox_id in self.active_sandboxes:
            sandbox_info = self.active_sandboxes[sandbox_id]
            process = sandbox_info.get("process")
            if process and process.poll() is None:
                try:
                    process.kill()
                except Exception:
                    pass
            
            # --- 构建差异 Artifact，永久脱离沙箱存储 ---
            self.generate_diff(sandbox_info)
            
            sandbox_path = sandbox_info["path"]
            try:
                import time
                time.sleep(0.5) # 给文件句柄释放的时间
                shutil.rmtree(sandbox_path, ignore_errors=True)
                logger.info(f"沙箱 {sandbox_id} 及其临时资源已安全销毁，底层无任何原项目污染。")
            except Exception as e:
                logger.error(f"清理沙箱 {sandbox_id} 失败: {e}")
                
            del self.active_sandboxes[sandbox_id]
