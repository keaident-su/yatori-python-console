# -*- coding: utf-8 -*-
"""
[2026-10-24 V3.0.8] user_mapper 适配层 —— 数据库已移除, 改为 config.yaml(ConfigStore)。

保持与旧版完全一致的函数签名与返回值语义(会话参数兼容接收但不使用),
使上层 100+ 处调用(web/logic 各处)零改动。
"""
import json
from typing import List, Optional, Tuple

from dao.config_store import ConfigStore
from entity.pojo import UserPO


def _store() -> ConfigStore:
    return ConfigStore.instance()


def _row_to_po(row: dict) -> UserPO:
    """yaml 行 -> UserPO 瞬时对象(未挂会话, 属性与 user_config_turn_entity 均可用)"""
    cfg = {k: v for k, v in row.items()
           if k not in ("uid", "accountType", "url", "account", "password")}
    cfg["accountType"] = row.get(
        "accountType") or row.get("account_type") or ""
    cfg["URL"] = row.get("url") or ""
    cfg["account"] = row.get("account") or ""
    cfg["password"] = row.get("password") or ""
    return UserPO(
        uid=str(row.get("uid") or ""),
        account_type=cfg["accountType"],
        url=cfg["URL"],
        account=cfg["account"],
        password=cfg["password"],
        user_config_json=json.dumps(cfg, ensure_ascii=False),
    )


def _po_to_row(user: UserPO) -> dict:
    try:
        cfg = json.loads(user.user_config_json or "{}")
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    row = {
        "uid": user.uid,
        "accountType": cfg.get("accountType") or user.account_type or "",
        "url": cfg.get("URL") or cfg.get("url") or user.url or "",
        "account": cfg.get("account") or user.account or "",
        "password": cfg.get("password") or user.password or "",
    }
    # [V3.0.9] 不再白名单: 保留全部扩展键(school/realName/stuNo/coursesCustom/
    # remarkName/informEmails/... 及未来任何字段), 避免身份三要素等被丢掉
    for k, v in cfg.items():
        if k in ("accountType", "URL", "url", "account", "password"):
            continue
        if k in ("courses_custom", "coursesCustom"):
            row["coursesCustom"] = v if isinstance(v, dict) else {}
        elif v not in (None, "", [], {}):
            row[k] = v
    row.setdefault("coursesCustom", {})
    return row


def insert_user(session=None, user: UserPO = None) -> Optional[str]:
    """插入用户(签名兼容旧版)"""
    try:
        return _store().insert_user_row(_po_to_row(user))
    except Exception as e:
        return f"插入数据失败: {str(e)}"


def delete_user(session=None, uid: str = "", account_type: str = "",
                url: str = "", account: str = "") -> Optional[str]:
    """删除用户(动态条件, 签名兼容旧版)"""
    try:
        _store().delete_users(uid=uid, account_type=account_type,
                              url=url, account=account)
        return None
    except Exception as e:
        return f"删除用户失败: {str(e)}"


def query_users(session=None, page: int = 1,
                page_size: int = 10) -> Tuple[List[UserPO], int]:
    """分页查询(返回 UserPO 瞬时对象列表, 按 uid 升序)"""
    rows, total = _store().list_users(page=page, page_size=page_size)
    return [_row_to_po(r) for r in rows], total


def query_user(session=None, uid: str = "", account_type: str = "",
               url: str = "", account: str = "",
               password: str = "") -> Optional[UserPO]:
    """查询单个用户(动态条件, 签名兼容旧版)"""
    row = _store().find_user(uid=uid, account_type=account_type,
                             url=url, account=account, password=password)
    return _row_to_po(row) if row else None


def update_user(session=None, uid: str = "",
                update_data: dict = None) -> Optional[str]:
    """更新指定 UID(update_data 为旧列名风格: account_type/url/account/
    password/user_config_json)——内部映射为 yaml 键风格并合并。"""
    if not uid:
        return "更新失败: UID 不能为空"
    try:
        patch = {}
        ud = update_data or {}
        if "account_type" in ud:
            patch["accountType"] = ud["account_type"]
        for k_src, k_dst in (("url", "url"), ("account", "account"),
                             ("password", "password")):
            if k_src in ud:
                patch[k_dst] = ud[k_src]
        if "user_config_json" in ud:
            try:
                cfg = json.loads(ud["user_config_json"] or "{}")
                if not isinstance(cfg, dict):
                    cfg = {}
            except Exception:
                cfg = {}
            # [V3.0.9] 不再白名单: user_config_json 的全部扩展键均合并回 yaml 行
            # (含 school/realName/stuNo 身份三要素), 避免保存时被覆盖丢失
            for k, v in cfg.items():
                if k in ("accountType", "URL", "url", "account", "password"):
                    continue
                if k in ("courses_custom", "coursesCustom"):
                    patch["coursesCustom"] = v if isinstance(v, dict) else {}
                elif v not in (None, "", [], {}):
                    patch[k] = v
        return _store().update_user_row(uid, patch)
    except Exception as e:
        return f"更新用户失败: {str(e)}"
