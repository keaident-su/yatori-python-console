# -*- coding: utf-8 -*-
"""
数据库初始化 - 对应 Go 项目的 SqliteInit.go
使用 SQLAlchemy 初始化 SQLite 数据库连接并自动建表
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from entity.pojo import Base

# 全局引擎和会话工厂
_engine = None
_SessionFactory = None


def sqlite_init(db_path: str = "yatori.db"):
    """
    初始化 SQLite 数据库
    :param db_path: 数据库文件路径
    :return: sessionmaker 实例
    """
    global _engine, _SessionFactory

    _engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # 开启 WAL 模式，提升并发性能
    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    # 自动创建表
    Base.metadata.create_all(_engine)

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _SessionFactory


def get_session() -> Session:
    """获取数据库会话"""
    if _SessionFactory is None:
        raise RuntimeError("数据库未初始化，请先调用 sqlite_init()")
    return _SessionFactory()
