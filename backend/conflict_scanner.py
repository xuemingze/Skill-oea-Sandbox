# -*- coding: utf-8 -*-
"""
全局技能关键词冲突扫描与预警模块 (Skill Keyword Conflict Scanner)
"""

import os
import re
import yaml
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple

DEFAULT_SKILL_SCAN_PATHS = [
    os.path.expanduser("~/.SKILLs"),
    os.path.expanduser("~/AppData/Roaming/LobsterAI/SKILLs"),
    os.path.expanduser("~/.agents/skills"),
    os.path.expanduser("~/state/workspace-main/skills"),
    "C:/Users/Administrator/AppData/Local/Programs/LobsterAI/resources/cfmind/skills",
    "D:/项目/技能包",
    "D:/项目/skill_sandbox/skill"
]

DOMAIN_KEYWORDS_MAP = {
    "code_development": ("软件开发/编程专家", ["代码", "编程", "重构", "debug", "测试用例", "python", "javascript", "api", "git", "review", "开发", "code", "dev"]),
    "system_architecture": ("系统架构/基础设施", ["架构", "基础设施", "statedb", "sqlite", "数据库", "部署", "watchdog", "哨兵", "docker", "集群", "architecture"]),
    "ocr_document": ("文档识别/票据OCR", ["ocr", "发票", "收据", "票据", "图片转文字", "表格提取", "凭证", "报销", "invoice", "receipt"]),
    "memory_knowledge": ("知识图谱/记忆管理", ["记忆", "知识库", "知识图谱", "沉淀", "资料库", "笔记", "备忘录", "obsidian", "ima", "markdown", "knowledge", "memory"]),
    "financial_audit": ("财务审计/核算风控", ["财务", "审计", "对账", "损益", "资产负债", "现金流", "凭证", "科目", "sox", "reconciliation", "audit", "financial"]),
    "media_generation": ("音视频与图像生成", ["视频", "图像", "绘图", "文生图", "图生视频", "tts", "语音", "ffmpeg", "播客", "meme", "image", "video", "audio"]),
    "workflow_automation": ("工作流编排/流程调度", ["工作流", "任务流", "sop", "自动化", "编排", "调度", "pipeline", "taskflow", "workflow", "automation"])
}

# 常见中英文停用词、虚词、纯通用动词与无歧义单字（单独出现时不具备意图辨识度）
STOP_WORDS = {
    "for", "with", "this", "that", "from", "into", "when", "then", "your", "what", "where", "which",
    "and", "the", "are", "can", "use", "using", "all", "each", "both", "such", "how", "has", "have", "been",
    "via", "about", "across", "should", "wants", "like", "will", "would", "could", "also", "some",
    "user", "users", "needs", "need", "any", "not", "only", "well", "such", "than", "other", "into",
    "trigger", "triggers", "triggered", "specific", "specified", "support", "supports", "supported",
    " 用于", "支持", "实现", "负责", "以及", "通过", "进行", "可以", "帮助", "使用", "完成", "基于", "提供", "相关", "包括",
    "作为", "能够", "需要", "针对", "根据", "如果", "当前", "操作", "用户", "触发", "需求", "等等", "功能", "执行",
    "a", "an", "the", "in", "on", "at", "by", "to", "of", "or", "as", "is", "it", "if", "be"
}

# 单独出现时必须忽略的纯动词与CLI工具名（必须与实体名词组合成动宾短语或三元组才允许触发）
ISOLATED_VERBS_AND_CLI = {
    "write", "create", "generate", "make", "build", "run", "exec", "execute", "start", "stop",
    "search", "find", "query", "lookup", "fetch", "get", "check", "test", "audit", "review",
    "edit", "update", "modify", "change", "delete", "remove", "clean", "drop", "save",
    "cli", "cmd", "command", "tool", "tools", "script", "app", "service", "task", "process",
    "写", "查", "做", "建", "改", "删", "跑", "读", "看", "调", "测", "审", "测", "导", "发"
}


class SkillConflictScanner:
    def __init__(self, scan_paths: Optional[List[str]] = None):
        self.scan_paths = scan_paths or DEFAULT_SKILL_SCAN_PATHS
        self.skills_db: Dict[str, Dict[str, Any]] = {}
        self.keyword_index: Dict[str, List[str]] = {}  # keyword -> list of skill_ids

    def scan_all_skills(self) -> Dict[str, Any]:
        """全量扫描技能并构建索引与冲突报告"""
        self.skills_db.clear()
        self.keyword_index.clear()
        scanned_dirs = set()

        for base_path in self.scan_paths:
            norm_path = os.path.normpath(base_path)
            if not os.path.exists(norm_path) or norm_path in scanned_dirs:
                continue
            scanned_dirs.add(norm_path)
            self._scan_directory(norm_path)

        # 构建关键词倒排索引
        for skill_id, meta in self.skills_db.items():
            for kw in meta.get("keywords", []):
                norm_kw = kw.strip().lower()
                if not norm_kw or norm_kw in STOP_WORDS or len(norm_kw) < 2:
                    continue
                if norm_kw not in self.keyword_index:
                    self.keyword_index[norm_kw] = []
                if skill_id not in self.keyword_index[norm_kw]:
                    self.keyword_index[norm_kw].append(skill_id)

        # 分析冲突
        conflicts = self._analyze_conflicts()
        domain_catalog = self._build_domain_catalog()

        return {
            "total_skills": len(self.skills_db),
            "total_unique_keywords": len(self.keyword_index),
            "domain_catalog": domain_catalog,
            "conflicts": conflicts,
            "skills": self.skills_db,
            "scan_time": datetime.now().isoformat()
        }

    def _scan_directory(self, dir_path: str):
        """遍历目录寻找 SKILL.md 或 skill.yaml"""
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                if file.lower() in ("skill.md", "skill.yaml", "skill.json"):
                    full_path = os.path.join(root, file)
                    skill_meta = self._parse_skill_file(full_path)
                    if skill_meta and skill_meta["id"] not in self.skills_db:
                        self.skills_db[skill_meta["id"]] = skill_meta

    def _parse_skill_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            if os.path.isdir(file_path):
                for candidate in ("SKILL.md", "skill.md", "skill.yaml", "skill.json"):
                    cand_path = os.path.join(file_path, candidate)
                    if os.path.isfile(cand_path):
                        file_path = cand_path
                        break
                else:
                    return None

            if not os.path.isfile(file_path):
                return None

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            parent_dir_name = os.path.basename(os.path.dirname(os.path.abspath(file_path)))
            skill_id = parent_dir_name or os.path.splitext(os.path.basename(file_path))[0]
            name = skill_id
            description = ""
            keywords = []

            # 解析 Frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        fm = yaml.safe_load(parts[1])
                        if isinstance(fm, dict):
                            name = fm.get("name", name)
                            description = fm.get("description", "")
                            kw_raw = fm.get("keywords", fm.get("triggers", []))
                            if isinstance(kw_raw, list):
                                keywords.extend([str(k) for k in kw_raw])
                            elif isinstance(kw_raw, str):
                                keywords.extend([k.strip() for k in re.split(r"[,;，；|]+", kw_raw) if k.strip()])
                    except Exception:
                        pass

            if not description:
                lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
                if lines:
                    description = lines[0][:200]

            extracted_kws = self._extract_trigger_keywords(name, description, content)
            for ekw in extracted_kws:
                if ekw.lower() not in [k.lower() for k in keywords] and ekw.lower() not in STOP_WORDS:
                    keywords.append(ekw)

            # 判定主领域
            primary_domain, domain_label = self._classify_domain(name, description, content, keywords)

            return {
                "id": skill_id,
                "name": name,
                "path": file_path,
                "description": description,
                "domain": primary_domain,
                "domain_label": domain_label,
                "keywords": [k for k in keywords if k.lower() not in STOP_WORDS][:12]
            }
        except Exception:
            return None

    def _extract_trigger_keywords(self, name: str, description: str, content: str) -> List[str]:
        """从技能名称、描述与文本中提取触发词（强化实体+意图名词短语，过滤单独的纯动词与CLI指令）"""
        tokens = set()
        clean_name = name.lower().replace("skill-", "").replace("-skill", "")

        # 1. 从技能名提取复合短语（若包含连接符则优先提取完整词组）
        if "-" in clean_name or "_" in clean_name:
            tokens.add(clean_name.replace("-", " ").replace("_", " "))
        for part in re.split(r"[-_.\s]+", clean_name):
            if len(part) >= 2 and part.lower() not in STOP_WORDS and part.lower() not in ISOLATED_VERBS_AND_CLI:
                tokens.add(part.lower())

        # 2. 从描述中提取动宾短语（动词 + 意向名词，如 write article / review code / search stock / 记录知识卡）
        text = f"{name} {description}"
        
        # 英文动宾复合模式: (verb) (adj/det)? (noun)
        en_vp_patterns = [
            r"\b(write|create|generate|draft|author)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-]+)\b",
            r"\b(review|audit|check|test|inspect)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\b",
            r"\b(search|query|find|lookup|fetch)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\b",
            r"\b(manage|track|sync|monitor|export)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\b"
        ]
        for pat in en_vp_patterns:
            for m in re.finditer(pat, text, re.I):
                verb = m.group(1).lower()
                noun = m.group(2).lower()
                if noun not in STOP_WORDS and noun not in ISOLATED_VERBS_AND_CLI and len(noun) >= 2:
                    tokens.add(f"{verb} {noun}")
                    tokens.add(noun)

        # 中文动宾复合模式: (用于/支持/实现)? (动词) + (名词)
        zh_patterns = [
            r"用于([\u4e00-\u9fa5]{2,6})",
            r"支持([\u4e00-\u9fa5]{2,6})",
            r"实现([\u4e00-\u9fa5]{2,6})",
            r"([撰写|生成|创建|输出|编写])([\u4e00-\u9fa5]{2,6})",
            r"([审查|审计|对账|排错|测试])([\u4e00-\u9fa5]{2,6})",
            r"([查询|检索|搜索|获取])([\u4e00-\u9fa5]{2,6})",
            r"([管理|同步|沉淀|记录])([\u4e00-\u9fa5]{2,6})"
        ]
        for pat in zh_patterns:
            for m in re.finditer(pat, text):
                val = m.group(len(m.groups())).strip()
                if len(val) >= 2 and val not in STOP_WORDS and val not in ISOLATED_VERBS_AND_CLI:
                    tokens.add(val)

        # 3. 匹配领域特征专有实体词（如 invoice, ast, memory, stock, ffmpeg, 12306 等）
        for _, (_, domain_kws) in DOMAIN_KEYWORDS_MAP.items():
            for dkw in domain_kws:
                if dkw in text.lower() and dkw not in STOP_WORDS and dkw not in ISOLATED_VERBS_AND_CLI:
                    tokens.add(dkw)

        # 最终严格过滤单独的动词与CLI指令
        valid_tokens = []
        for t in tokens:
            t_norm = t.strip().lower()
            if not t_norm or t_norm in STOP_WORDS or t_norm in ISOLATED_VERBS_AND_CLI:
                continue
            # 单字中文过滤
            if len(t_norm) == 1 and '\u4e00' <= t_norm <= '\u9fff':
                continue
            valid_tokens.append(t_norm)

        return valid_tokens[:12]

    def _classify_domain(self, name: str, description: str, content: str, keywords: List[str]) -> Tuple[str, str]:
        """分类技能所属领域"""
        text = f"{name} {description} {' '.join(keywords)} {content[:500]}".lower()
        best_domain = "workflow_automation"
        best_label = "工作流编排/通用任务"
        max_score = 0

        for d_key, (d_label, d_kws) in DOMAIN_KEYWORDS_MAP.items():
            score = 0
            for kw in d_kws:
                if kw in text:
                    score += 2 if (kw in name.lower() or kw in description.lower()) else 1
            if score > max_score:
                max_score = score
                best_domain = d_key
                best_label = d_label

        return best_domain, best_label

    def _analyze_conflicts(self) -> List[Dict[str, Any]]:
        """分析关键词冲突与交叉覆盖"""
        conflict_list = []
        for kw, skill_ids in self.keyword_index.items():
            if len(skill_ids) > 1:
                involved_skills = []
                domains = set()
                for sid in skill_ids:
                    s_meta = self.skills_db[sid]
                    involved_skills.append({
                        "id": sid,
                        "name": s_meta["name"],
                        "domain": s_meta["domain"],
                        "domain_label": s_meta["domain_label"],
                        "path": s_meta["path"]
                    })
                    domains.add(s_meta["domain"])

                is_cross_domain = len(domains) > 1
                severity = "CRITICAL" if len(skill_ids) >= 4 else ("HIGH" if is_cross_domain else "MEDIUM")

                conflict_list.append({
                    "keyword": kw,
                    "hit_count": len(skill_ids),
                    "severity": severity,
                    "is_cross_domain": is_cross_domain,
                    "skills": involved_skills,
                    "suggestion": (
                        f"关键词 '{kw}' 跨 {len(domains)} 个领域被 {len(skill_ids)} 个技能共用，极易造成意图路由歧义，建议在 SKILL.md 中限定前置条件或使用专属触发前缀"
                        if is_cross_domain else
                        f"同领域内存在 {len(skill_ids)} 个技能共用 '{kw}'，建议明确各技能的细分场景差异"
                    )
                })

        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        conflict_list.sort(key=lambda x: (order.get(x["severity"], 3), -x["hit_count"]))
        return conflict_list

    def _build_domain_catalog(self) -> Dict[str, Dict[str, Any]]:
        """按领域构建索引目录"""
        catalog = {}
        for d_key, (d_label, _) in DOMAIN_KEYWORDS_MAP.items():
            catalog[d_key] = {
                "label": d_label,
                "skills_count": 0,
                "skills": []
            }

        for sid, meta in self.skills_db.items():
            dom = meta["domain"]
            if dom not in catalog:
                catalog[dom] = {"label": meta["domain_label"], "skills_count": 0, "skills": []}
            catalog[dom]["skills"].append({
                "id": sid,
                "name": meta["name"],
                "keywords": meta["keywords"],
                "path": meta["path"]
            })
            catalog[dom]["skills_count"] += 1

        return catalog

    def check_skill_conflict(self, target_skill_path: str) -> Dict[str, Any]:
        """单技能冲突检测（用于沙箱运行前与测试报告生成）"""
        scan_res = self.scan_all_skills()
        target_meta = self._parse_skill_file(target_skill_path)
        if not target_meta:
            return {"target_skill": target_skill_path, "conflicts": [], "conflict_count": 0}

        target_kws = [k.lower() for k in target_meta.get("keywords", []) if k.lower() not in STOP_WORDS]
        matched_conflicts = []

        for conf in scan_res["conflicts"]:
            if conf["keyword"].lower() in target_kws:
                other_skills = [s for s in conf["skills"] if s["path"] != target_meta["path"] and s["id"] != target_meta["id"]]
                if other_skills:
                    matched_conflicts.append({
                        "keyword": conf["keyword"],
                        "severity": conf["severity"],
                        "is_cross_domain": conf["is_cross_domain"],
                        "conflicting_skills": other_skills,
                        "suggestion": conf["suggestion"]
                    })

        return {
            "target_skill_id": target_meta["id"],
            "target_skill_name": target_meta["name"],
            "target_domain": target_meta["domain_label"],
            "target_keywords": target_meta["keywords"],
            "total_global_skills_scanned": scan_res["total_skills"],
            "conflicts": matched_conflicts,
            "conflict_count": len(matched_conflicts)
        }

    def generate_conflict_markdown(self, conflict_analysis: Dict[str, Any]) -> str:
        if not conflict_analysis or "conflicts" not in conflict_analysis:
            return "### ⚠️ 触发关键词冲突预警 (Keyword Conflict Warning)\n- 无关键词冲突数据"

        target_name = conflict_analysis.get("target_skill_name", "当前技能")
        target_kws = conflict_analysis.get("target_keywords", [])
        conflicts = conflict_analysis.get("conflicts", [])
        conflict_count = conflict_analysis.get("conflict_count", 0)
        total_global = conflict_analysis.get("total_global_skills_scanned", 0)

        lines = [
            "### ⚠️ 触发关键词冲突预警与多技能覆盖分析 (Keyword Conflict & Overlap Warning)",
            f"- **当前技能**: `{target_name}` | **触发词总数**: `{len(target_kws)}` 个 | **全域比对基数**: `{total_global}` 个已安装技能",
            f"- **冲突/交叉覆盖命中数**: `{conflict_count}` 个"
        ]

        if conflict_count == 0:
            lines.append("\n> ✅ **触发词审计通过**：未在全域已安装技能库中发现交叉重叠触发词，多技能并存时不会发生歧义误触发。")
            return "\n".join(lines)

        critical_conflicts = [c for c in conflicts if c.get("severity") == "CRITICAL"]
        high_conflicts = [c for c in conflicts if c.get("severity") == "HIGH"]
        medium_conflicts = [c for c in conflicts if c.get("severity") == "MEDIUM"]

        if critical_conflicts or high_conflicts:
            lines.append("\n#### 🚨 严重与高危冲突 (Cross-Domain Conflict - 跨领域歧义触发风险)")
            lines.append("> **风险提示**: 以下关键词被不同领域的其他技能定义为触发词，可能导致 AI Agent 在调用时产生跨域误判：")
            for c in (critical_conflicts + high_conflicts):
                other_names = ", ".join([f"`{s['id']}`({s.get('domain_label', s.get('domain', '未知'))})" for s in c["conflicting_skills"]])
                lines.append(f"- 🔴 关键词 **`{c['keyword']}`**: 与 **{len(c['conflicting_skills'])}** 个跨领域技能冲突 -> {other_names}")
                lines.append(f"  - *优化建议*: {c.get('suggestion', '')}")

        if medium_conflicts:
            lines.append("\n#### 🟡 潜在同域重叠 (Same-Domain Overlap - 领域内分流竞争)")
            lines.append("> **提示**: 以下关键词在同领域技能中存在重叠，可能导致同类任务调度分流不明确：")
            for c in medium_conflicts:
                other_names = ", ".join([f"`{s['id']}`" for s in c["conflicting_skills"]])
                lines.append(f"- 🟡 关键词 **`{c['keyword']}`**: 与 **{len(c['conflicting_skills'])}** 个同域技能重叠 -> {other_names}")
                lines.append(f"  - *优化建议*: {c.get('suggestion', '')}")

        lines.append("\n#### 💡 触发词优化与消歧建议 (Disambiguation Recommendations)")
        lines.append("1. **强化前缀与专有词约束**: 将高频通用词（如 `review`, `diff`, `ocr`）升级为具名专有触发词（如 `python-ast-review`, `invoice-ocr-parser`）；")
        lines.append("2. **细化描述分流**: 在 `SKILL.md` 的 frontmatter `description` 中明确声明排他边界与禁止匹配场景；")
        lines.append("3. **意图前置探测**: 为当前技能配置明确的前提激活环境与参数检测规则，避免关键词单纯匹配触发。")

        return "\n".join(lines)

    def classify_keywords_by_pattern(self) -> Dict[str, Any]:
        """依据介词/通用动词（via, cli, search, write, code等）对全域关键词进行分类统计"""
        if not self.skills_db:
            self.scan_all_skills()

        pattern_groups = {
            "via_channel": {"label": "通道与协议 (via/channel/protocol)", "pattern": r"(via|channel|proto|http|ws|smtp|imap|api)", "keywords": []},
            "cli_terminal": {"label": "命令行与终端 (cli/cmd/exec/tool)", "pattern": r"(cli|cmd|bash|shell|terminal|exec|command|run)", "keywords": []},
            "search_query": {"label": "检索与发现 (search/query/find/fetch)", "pattern": r"(search|query|find|fetch|lookup|explore|seek)", "keywords": []},
            "write_doc": {"label": "生成与写作 (write/create/generate/note)", "pattern": r"(write|create|gen|author|draft|note|record|card)", "keywords": []},
            "code_dev": {"label": "代码与开发 (code/dev/debug/review)", "pattern": r"(code|dev|debug|review|ast|lint|compile|test|build)", "keywords": []},
            "data_analyze": {"label": "数据与分析 (data/analyze/audit/diff)", "pattern": r"(data|stat|analyze|audit|diff|reconcil|finance|calc)", "keywords": []},
            "other_generic": {"label": "其他通用触发词", "pattern": r".*", "keywords": []}
        }

        import re
        classified = {}
        for kw, sids in self.keyword_index.items():
            matched_group = "other_generic"
            for g_key, g_info in pattern_groups.items():
                if g_key == "other_generic":
                    continue
                if re.search(g_info["pattern"], kw, re.I):
                    matched_group = g_key
                    break
            
            if matched_group not in classified:
                classified[matched_group] = []
            classified[matched_group].append({
                "keyword": kw,
                "skill_count": len(sids),
                "skills": [self.skills_db[sid]["name"] for sid in sids if sid in self.skills_db],
                "is_conflict": len(sids) > 1
            })

        return {
            "pattern_definitions": {k: v["label"] for k, v in pattern_groups.items()},
            "groups": classified
        }

    def extract_skill_triplets(self) -> List[Dict[str, Any]]:
        """按「实体名词 + 动词意图 + 领域约束」提取完整三元组，实现精准领域对齐与消歧（杜绝单独动词/CLI的泛化误唤醒）"""
        if not self.skills_db:
            self.scan_all_skills()

        triplets = []
        for sid, meta in self.skills_db.items():
            domain_label = meta["domain_label"]
            name = meta["name"]
            desc = meta["description"]
            
            # 从技能描述与触发词提炼「实体名词 (Entity) + 动词意图 (Intent) + 领域 (Domain)」
            for kw in meta["keywords"]:
                # 判定动词意图与对应实体名词（例: write a book -> entity: book, intent: write / 撰写）
                parts = kw.split()
                if len(parts) >= 2:
                    first_w = parts[0].lower()
                    rest_entity = " ".join(parts[1:])
                    if first_w in ["write", "create", "draft", "author", "撰写", "编写", "写"]:
                        intent = "撰写/创作"
                        entity = rest_entity
                    elif first_w in ["search", "query", "find", "fetch", "lookup", "查询", "检索", "查"]:
                        intent = "检索/查询"
                        entity = rest_entity
                    elif first_w in ["review", "audit", "check", "test", "inspect", "审查", "调试", "测试"]:
                        intent = "审查/评估"
                        entity = rest_entity
                    elif first_w in ["ocr", "extract", "parse", "抽取", "解析", "识别"]:
                        intent = "抽取/识别"
                        entity = rest_entity
                    elif first_w in ["diff", "compare", "reconcile", "比对", "核对", "对账"]:
                        intent = "比对/核算"
                        entity = rest_entity
                    else:
                        intent = "执行"
                        entity = kw
                else:
                    entity = kw
                    intent = "执行"
                    # 根据领域和技能名推断意图
                    if "writer" in name or "journal" in name or "note" in name:
                        intent = "撰写/沉淀"
                    elif "search" in name or "query" in name or "explorer" in name:
                        intent = "检索/查询"
                    elif "review" in name or "audit" in name or "testing" in name or "debug" in name:
                        intent = "审查/调试"
                    elif "ocr" in name:
                        intent = "抽取/识别"
                    elif "analyzer" in name or "analysis" in name:
                        intent = "深度分析"

                triplets.append({
                    "skill_id": sid,
                    "skill_name": name,
                    "keyword": kw,
                    "entity": entity,
                    "intent": intent,
                    "domain": domain_label,
                    "triplet_expr": f"[{domain_label}] 针对 <{entity}> 发起 <{intent}> -> 唤醒 『{name}』",
                    "description": desc
                })

        return triplets

    def export_ai_routing_prompt(self, domain_filter: Optional[str] = None) -> str:
        """提取特定领域或全域的精简路由子集，生成高质量 AI Agent 提示词"""
        if not self.skills_db:
            self.scan_all_skills()

        triplets = self.extract_skill_triplets()
        if domain_filter and domain_filter != "全部领域":
            triplets = [t for t in triplets if t["domain"] == domain_filter]

        # 按领域分组聚合
        domain_groups = {}
        for t in triplets:
            dom = t["domain"]
            if dom not in domain_groups:
                domain_groups[dom] = {}
            sid = t["skill_id"]
            if sid not in domain_groups[dom]:
                domain_groups[dom][sid] = {
                    "name": t["skill_name"],
                    "desc": t["description"],
                    "keywords": set(),
                    "triplets": []
                }
            domain_groups[dom][sid]["keywords"].add(t["keyword"])
            domain_groups[dom][sid]["triplets"].append(f"<{t['entity']}> + <{t['intent']}>")

        lines = [
            "# AI Agent 意图分发与技能路由规则库 (Skill Routing Protocol)",
            f"> 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 领域范围: {domain_filter or '全域'}",
            "",
            "## 1. 意图决策总则",
            "- 当且仅当用户输入命中下述【实体 + 动词意图】三元组或触发关键词时，主动激活对应技能；",
            "- 若用户指令存在歧义，优先根据上下文业务领域及精简三元组进行精准分流；",
            "- 严禁跨领域误唤醒通用词重叠的同名意图技能。",
            "",
            "## 2. 领域技能精简路由表"
        ]

        for dom, skills_map in domain_groups.items():
            lines.append(f"\n### 🏛️ 领域: {dom}")
            for sid, sinfo in skills_map.items():
                kw_str = ", ".join([f"`{k}`" for k in sorted(sinfo["keywords"])])
                lines.append(f"\n#### ⚡ 技能: `{sinfo['name']}`")
                lines.append(f"- **功能定义**: {sinfo['desc']}")
                lines.append(f"- **唤醒关键词**: {kw_str}")
                lines.append("- **精简意图三元组规则**:")
                for tr in sorted(set(sinfo["triplets"]))[:6]:
                    lines.append(f"  - 命中 {tr} -> 唤醒 `{sinfo['name']}`")

        return "\n".join(lines)

