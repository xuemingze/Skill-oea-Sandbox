# -*- coding: utf-8 -*-
import os
import time
import json
import shutil
import zipfile
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

class ReportRecycleManager:
    def __init__(self, workspace_root: str = None):
        if not workspace_root:
            workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.workspace_root = os.path.abspath(workspace_root)
        self.reports_dir = os.path.join(self.workspace_root, "sandbox_reports")
        self.cowork_dir = os.path.join(self.workspace_root, ".cowork-temp")
        self.config_dir = os.path.join(self.reports_dir, "_config")
        self.trash_dir = os.path.join(self.reports_dir, "_trash")
        self.archive_dir = os.path.join(self.reports_dir, "_archives")
        self.policy_file = os.path.join(self.config_dir, "recycle_policy.json")
        self.archive_index_file = os.path.join(self.archive_dir, "archive_index.json")
        
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.reports_dir, self.config_dir, self.trash_dir, self.archive_dir]:
            os.makedirs(d, exist_ok=True)

    def get_policy(self) -> Dict[str, Any]:
        if os.path.exists(self.policy_file):
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "is_configured": False,
            "retention_days": 7,
            "auto_scan_on_startup": True,
            "trash_retention_hours": 24,
            "last_scan_time": None
        }

    def save_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_dirs()
        cur = self.get_policy()
        cur.update(policy)
        cur["is_configured"] = True
        cur["updated_at"] = datetime.now().isoformat()
        with open(self.policy_file, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        return cur

    def scan_files(self, retention_days: Optional[int] = None) -> Dict[str, Any]:
        policy = self.get_policy()
        days = retention_days if retention_days is not None else policy.get("retention_days", 7)
        now_ts = time.time()
        cutoff_expired = now_ts - (days * 86400)
        cutoff_soon = cutoff_expired + 86400
        
        items = []
        total_size = 0
        
        if os.path.exists(self.reports_dir):
            for entry in os.listdir(self.reports_dir):
                if entry in ("_config", "_trash", "_archives"):
                    continue
                p = os.path.join(self.reports_dir, entry)
                item = self._inspect_path(p, cutoff_expired, cutoff_soon, "report")
                if item:
                    items.append(item)
                    total_size += item["size_bytes"]

        if os.path.exists(self.cowork_dir):
            for entry in os.listdir(self.cowork_dir):
                if entry.startswith("test_input_samples"):
                    continue
                p = os.path.join(self.cowork_dir, entry)
                item = self._inspect_path(p, cutoff_expired, cutoff_soon, "cowork_temp")
                if item:
                    items.append(item)
                    total_size += item["size_bytes"]

        self._cleanup_old_trash()
        
        overdue_count = sum(1 for i in items if i["status"] == "已过期")
        soon_count = sum(1 for i in items if i["status"] == "即将过期")
        
        policy["last_scan_time"] = datetime.now().isoformat()
        self.save_policy(policy)
        
        return {
            "retention_days": days,
            "total_items": len(items),
            "overdue_count": overdue_count,
            "soon_count": soon_count,
            "total_size_bytes": total_size,
            "total_size_str": self._format_size(total_size),
            "items": sorted(items, key=lambda x: (x["status"] != "已过期", -x["mtime"]))
        }

    def _inspect_path(self, path: str, cutoff_expired: float, cutoff_soon: float, category: str) -> Optional[Dict[str, Any]]:
        try:
            mtime = os.path.getmtime(path)
            if os.path.isdir(path):
                size = sum(os.path.getsize(os.path.join(r, f)) for r, _, files in os.walk(path) for f in files if os.path.exists(os.path.join(r, f)))
            else:
                size = os.path.getsize(path)
                
            skill_name = self._extract_skill_name(path)
            
            if mtime <= cutoff_expired:
                status = "已过期"
            elif mtime <= cutoff_soon:
                status = "即将过期"
            else:
                status = "正常"

            return {
                "name": os.path.basename(path),
                "path": os.path.abspath(path),
                "category": category,
                "skill_name": skill_name,
                "size_bytes": size,
                "size_str": self._format_size(size),
                "mtime": mtime,
                "created_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "status": status,
                "is_dir": os.path.isdir(path)
            }
        except Exception:
            return None

    def _extract_skill_name(self, path: str) -> str:
        base = os.path.basename(path)
        if base.endswith(".json") and "_" in base:
            parts = base.split("_")
            if len(parts) >= 2:
                return parts[1]
        elif "sandbox-" in base:
            return "临时沙箱环境"
        return "通用测试产物"

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes} B"

    def move_to_trash(self, target_paths: List[str]) -> Dict[str, Any]:
        self._ensure_dirs()
        moved = []
        errors = []
        for p in target_paths:
            if not os.path.exists(p):
                continue
            try:
                base_name = os.path.basename(p)
                dest = os.path.join(self.trash_dir, f"{int(time.time())}_{base_name}")
                shutil.move(p, dest)
                moved.append({"source": p, "trash": dest})
            except Exception as e:
                errors.append({"path": p, "error": str(e)})
        return {"action": "trash", "success_count": len(moved), "errors": errors, "moved": moved}

    def archive_and_distill(self, target_paths: List[str]) -> Dict[str, Any]:
        self._ensure_dirs()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"archive_{timestamp}.zip"
        zip_path = os.path.join(self.archive_dir, zip_name)
        
        archived_files = []
        errors = []
        skills_involved = set()
        
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in target_paths:
                if not os.path.exists(p):
                    continue
                try:
                    skill_name = self._extract_skill_name(p)
                    skills_involved.add(skill_name)
                    if os.path.isdir(p):
                        for root, _, files in os.walk(p):
                            for f in files:
                                full_p = os.path.join(root, f)
                                arcname = os.path.relpath(full_p, os.path.dirname(p))
                                z.write(full_p, arcname)
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        z.write(p, os.path.basename(p))
                        os.remove(p)
                    archived_files.append(os.path.basename(p))
                except Exception as e:
                    errors.append({"path": p, "error": str(e)})

        index_data = []
        if os.path.exists(self.archive_index_file):
            try:
                with open(self.archive_index_file, "r", encoding="utf-8") as f:
                    index_data = json.load(f)
            except Exception:
                pass
                
        index_entry = {
            "archive_zip": zip_name,
            "created_at": datetime.now().isoformat(),
            "skills": list(skills_involved),
            "files_count": len(archived_files),
            "files": archived_files
        }
        index_data.append(index_entry)
        
        with open(self.archive_index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
            
        return {
            "action": "archive",
            "archive_file": zip_path,
            "files_archived": len(archived_files),
            "errors": errors
        }

    def distill_and_archive(self, target_paths: List[str]) -> Dict[str, Any]:
        return self.archive_and_distill(target_paths)

    def _cleanup_old_trash(self):
        if not os.path.exists(self.trash_dir):
            return
        cutoff_trash = time.time() - (24 * 3600)
        for entry in os.listdir(self.trash_dir):
            p = os.path.join(self.trash_dir, entry)
            try:
                if os.path.getmtime(p) < cutoff_trash:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
            except Exception:
                pass
