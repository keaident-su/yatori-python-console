# -*- coding: utf-8 -*-
"""
[2026-10-24 V3.0.8] 数据库初始化 -> 已改为 config.yaml(ConfigStore) 唯一事实源。

保留 sqlite_init() / get_session() 的调用兼容:
- sqlite_init(): 初始化 ConfigStore, 并一次性迁移旧 yatori.db(若存在, 只读迁移, 文件保留作备份)
- get_session():  返回兼容用的空会话对象(不再有真实数据库连接)
"""
import os

from dao.config_store import ConfigStore

_engine = None
_SessionFactory = None
_store = None


class _DummySession:
    """兼容旧接口的空会话(数据库已被 config.yaml 取代)"""

    def add(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def query(self, *a, **k):
        raise RuntimeError("数据库已移除(改为 config.yaml), 请使用 user_mapper 接口")


def sqlite_init(db_path: str = "yatori.db"):
    """
    [V3.0.8] 初始化配置存储(config.yaml 唯一事实源)
    - 首次启动时把旧 sqlite 中的账号(含原 uid)一次性迁入 config.yaml
    - db 文件不删除, 仅作历史备份, 之后不再读写
    """
    global _store
    _store = ConfigStore.instance()
    try:
        if os.path.exists(db_path):
            _store.migrate_from_sqlite(db_path)
    except Exception as e:
        try:
            print(f"[Init] 旧数据库迁移异常(忽略): {e}")
        except Exception:
            pass
    return _store


def get_session():
    """[V3.0.8] 兼容接口: 返回空会话对象"""
    return _DummySession()
