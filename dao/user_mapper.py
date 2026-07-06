# -*- coding: utf-8 -*-
"""
用户数据访问层 - 对应 Go 项目的 UserMapper.go
提供用户的增删改查操作
"""
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from entity.pojo import UserPO


def insert_user(session: Session, user: UserPO) -> Optional[str]:
    """
    插入用户
    :return: None 成功, 错误信息字符串 失败
    """
    try:
        session.add(user)
        session.commit()
        return None
    except Exception as e:
        session.rollback()
        return f"插入数据失败: {str(e)}"


def delete_user(session: Session, uid: str = "", account_type: str = "",
                url: str = "", account: str = "") -> Optional[str]:
    """
    删除用户（动态条件拼接）
    :return: None 成功, 错误信息字符串 失败
    """
    try:
        query = session.query(UserPO)
        if uid:
            query = query.filter(UserPO.uid == uid)
        if account_type:
            query = query.filter(UserPO.account_type == account_type)
        if url:
            query = query.filter(UserPO.url == url)
        if account:
            query = query.filter(UserPO.account == account)
        query.delete()
        session.commit()
        return None
    except Exception as e:
        session.rollback()
        return f"删除用户失败: {str(e)}"


def query_users(session: Session, page: int = 1,
                page_size: int = 10) -> Tuple[List[UserPO], int]:
    """
    分页查询用户
    :return: (用户列表, 总数)
    """
    total = session.query(func.count(UserPO.uid)).scalar() or 0
    offset = (page - 1) * page_size
    users = (session.query(UserPO)
             .order_by(UserPO.uid.asc())
             .limit(page_size)
             .offset(offset)
             .all())
    return users, total


def query_user(session: Session, uid: str = "", account_type: str = "",
               url: str = "", account: str = "",
               password: str = "") -> Optional[UserPO]:
    """
    查询单个用户（动态条件拼接）
    :return: UserPO 或 None
    """
    query = session.query(UserPO)
    if uid:
        query = query.filter(UserPO.uid == uid)
    if account_type:
        query = query.filter(UserPO.account_type == account_type)
    if url:
        query = query.filter(UserPO.url == url)
    if account:
        query = query.filter(UserPO.account == account)
    if password:
        query = query.filter(UserPO.password == password)
    return query.first()


def update_user(session: Session, uid: str,
                update_data: dict) -> Optional[str]:
    """
    更新指定 UID 用户信息
    :param uid: 用户 UID
    :param update_data: 要更新的字段字典
    :return: None 成功, 错误信息字符串 失败
    """
    if not uid:
        return "更新失败: UID 不能为空"
    try:
        session.query(UserPO).filter(UserPO.uid == uid).update(update_data)
        session.commit()
        return None
    except Exception as e:
        session.rollback()
        return f"更新用户失败: {str(e)}"
