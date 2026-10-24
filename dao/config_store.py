# -*- coding: utf-8 -*-
"""
[2026-10-24 V3.0.8] ConfigStore —— config.yaml 作为唯一事实源的内存存储层。

设计（用户定夺：兼容层迁移 + 保留原 uid + 自动补 uid）:
- 内存中持有完整 config.yaml 结构(dict): {setting: {...}, users: [...]}
- 所有账号增删改 → 内存更新 → 立即原子落盘(tmp -> os.replace)，线程锁保护
- 启动时: ①若旧 yatori.db 存在且 yaml 里没有该账号 → 一次性迁移(保留原 uid, db 文件保留作备份)
          ②yaml 中缺 uid 的账号自动生成 uuid 并回写
- 对上层提供与原先 user_mapper 等价的接口(见 dao/user_mapper.py 适配)
"""
import json
import os
import threading
import time
import uuid

import yaml

_LOCK = threading.RLock()
_CFG_PATH = "./config.yaml"


class ConfigStore:
    """config.yaml 单例存储(内存 + 原子落盘)"""

    _inst = None

    @classmethod
    def instance(cls) -> "ConfigStore":
        if cls._inst is None:
            with _LOCK:
                if cls._inst is None:
                    cls._inst = ConfigStore()
        return cls._inst

    def __init__(self, path: str = None):
        self.path = path or _CFG_PATH
        self.data = {"setting": {}, "users": []}
        self.load()

    # ---------------- 文件 IO ----------------
    def load(self):
        with _LOCK:
            raw = {}
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            if not isinstance(raw.get("users"), list):
                raw["users"] = []
            if not isinstance(raw.get("setting"), dict):
                raw["setting"] = {}
            self.data = raw
            # 自动补 uid(用户手写 yaml 新增账号的场景)
            dirty = False
            for u in self.data["users"]:
                if isinstance(u, dict) and not u.get("uid"):
                    u["uid"] = str(uuid.uuid4())
                    dirty = True
            if dirty:
                self._save_locked()

    def _save_locked(self):
        """调用方需已持锁；原子写: tmp -> replace"""
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.dump(self.data, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            os.replace(tmp, self.path)
        except Exception as e:
            try:
                print(f"[ConfigStore] 保存 config.yaml 失败: {e}")
            except Exception:
                pass

    def save(self):
        with _LOCK:
            self._save_locked()

    def reload(self):
        self.load()

    # ---------------- setting ----------------
    def get_setting(self) -> dict:
        with _LOCK:
            st = self.data.get("setting") or {}
            return json.loads(json.dumps(st, ensure_ascii=False, default=str))

    def update_setting(self, patch: dict) -> dict:
        """深合并白名单段并落盘"""
        with _LOCK:
            cur = self.data.setdefault("setting", {})
            for sec in ("basicSetting", "aiSetting", "emailInform",
                        "showdocInform", "answerSetting", "restSetting"):
                if isinstance(patch.get(sec), dict):
                    tgt = cur.setdefault(sec, {})
                    if isinstance(tgt, dict):
                        tgt.update(patch[sec])
            self._save_locked()
            return self.get_setting()

    # ---------------- users ----------------
    def _users(self) -> list:
        return self.data.setdefault("users", [])

    @staticmethod
    def _match(u: dict, uid="", account_type="", url="", account="",
               password="") -> bool:
        if not isinstance(u, dict):
            return False
        if uid and str(u.get("uid", "")) != str(uid):
            return False
        if account_type:
            at = u.get("accountType") or u.get("account_type") or ""
            if str(at) != str(account_type):
                return False
        if url:
            if str(u.get("url") or "") != str(url):
                return False
        if account:
            if str(u.get("account") or "") != str(account):
                return False
        if password:
            if str(u.get("password") or "") != str(password):
                return False
        return True

    def list_users(self, page: int = 1, page_size: int = 500):
        """返回 (行列表副本, 总数)，按 uid 升序(与原排序一致)"""
        with _LOCK:
            rows = [dict(u) for u in self._users() if isinstance(u, dict)]
            rows.sort(key=lambda x: str(x.get("uid", "")))
            total = len(rows)
            start = max(0, (int(page) - 1) * int(page_size))
            return rows[start:start + int(page_size)], total

    def all_users(self) -> list:
        with _LOCK:
            return [dict(u) for u in self._users() if isinstance(u, dict)]

    def find_user(self, uid="", account_type="", url="", account="",
                  password=""):
        with _LOCK:
            for u in self._users():
                if self._match(u, uid, account_type, url, account, password):
                    return dict(u)
            return None

    def insert_user_row(self, row: dict) -> str:
        """插入一行(已含 uid 则沿用, 否则生成); 返回错误串或 None"""
        with _LOCK:
            if not isinstance(row, dict) or not row.get("account"):
                return "账号不能为空"
            if self._match_any(row):
                return "该账号已存在"
            u = dict(row)
            if not u.get("uid"):
                u["uid"] = str(uuid.uuid4())
            self._users().append(u)
            self._save_locked()
            return None

    def _match_any(self, row: dict) -> bool:
        at = row.get("accountType") or row.get("account_type") or ""
        for u in self._users():
            if not isinstance(u, dict):
                continue
            if (str(u.get("account") or "") == str(row.get("account") or "")
                    and str(u.get("accountType") or u.get("account_type") or "") == str(at)
                    and str(u.get("url") or "") == str(row.get("url") or "")):
                return True
        return False

    def update_user_row(self, uid: str, patch: dict) -> str:
        """按 uid 更新一行(yaml 键风格: accountType/url/account/password/... )"""
        with _LOCK:
            if not uid:
                return "UID 不能为空"
            for u in self._users():
                if isinstance(u, dict) and str(u.get("uid", "")) == str(uid):
                    for k, v in (patch or {}).items():
                        if k == "uid":
                            continue
                        u[k] = v
                    self._save_locked()
                    return None
            return "账号不存在"

    def delete_users(self, uid="", account_type="", url="", account="") -> int:
        with _LOCK:
            before = len(self._users())
            remain = [u for u in self._users()
                      if not (isinstance(u, dict)
                              and self._match(u, uid, account_type, url, account))]
            self.data["users"] = remain
            n = before - len(remain)
            if n:
                self._save_locked()
            return n

    # ---------------- 首次迁移旧 sqlite ----------------
    def migrate_from_sqlite(self, db_path: str = "yatori.db") -> dict:
        """把旧 yatori.db 的 users 一次性并入 yaml(保留原 uid; 不删除 db 文件)"""
        stats = {"migrated": 0, "skipped": 0}
        if not os.path.exists(db_path):
            return stats
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT uid, account_type, url, account, password, "
                "user_config_json FROM users").fetchall()
            con.close()
        except Exception as e:
            print(f"[ConfigStore] 读取旧数据库失败(跳过迁移): {e}")
            return stats
        with _LOCK:
            changed = False
            for r in rows:
                try:
                    cfg = json.loads(r["user_config_json"] or "{}")
                    if not isinstance(cfg, dict):
                        cfg = {}
                except Exception:
                    cfg = {}
                row = {
                    "uid": r["uid"],
                    "accountType": cfg.get("accountType")
                    or r["account_type"] or "",
                    "url": cfg.get("URL") or cfg.get("url") or r["url"] or "",
                    "account": cfg.get("account") or r["account"] or "",
                    "password": cfg.get("password") or r["password"] or "",
                    "coursesCustom": cfg.get("coursesCustom")
                    or cfg.get("courses_custom") or {},
                }
                # [V3.0.9] 全键迁移: 保留全部扩展字段(remarkName/informEmails/
                # school/realName/stuNo/... 及未来任何键), 不再白名单丢失
                for k, v in cfg.items():
                    if k in ("accountType", "URL", "url", "account",
                             "password", "coursesCustom", "courses_custom"):
                        continue
                    if v not in (None, "", [], {}):
                        row[k] = v
                # 判重: 账号+平台已存在→合并缺失扩展键(不覆盖已有值)+补uid
                exist = None
                for u in self._users():
                    if (isinstance(u, dict)
                            and str(u.get("account") or "") == str(row["account"])
                            and str(u.get("accountType") or u.get("account_type") or "")
                            == str(row["accountType"])):
                        exist = u
                        break
                if exist is not None:
                    merged = False
                    if not exist.get("uid"):
                        exist["uid"] = row["uid"]
                        merged = True
                    # 关键: 把旧库中的身份要素/扩展键补回(已有值不覆盖)
                    for k, v in row.items():
                        if k in ("uid", "accountType", "account", "password",
                                 "url", "coursesCustom"):
                            continue
                        if v not in (None, "", [], {}) and not exist.get(k):
                            exist[k] = v
                            merged = True
                    if merged:
                        changed = True
                        stats["migrated"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    self._users().append(row)
                    changed = True
                    stats["migrated"] += 1
            if changed:
                self._save_locked()
        if stats["migrated"]:
            print(f"[ConfigStore] 旧数据库账户已迁移至 config.yaml: "
                  f"{stats['migrated']} 个(跳过{stats['skipped']})")
        return stats
