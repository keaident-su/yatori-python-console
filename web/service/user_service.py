# -*- coding: utf-8 -*-
"""
用户业务逻辑 - 对应 Go 项目的 UserService.go
实现所有用户相关的业务处理
"""
import json
import os
import time
import uuid
import threading
from typing import Generator

from dao.database import get_session
from dao import user_mapper
from entity.pojo import UserPO
from entity.vo import (
    Response, AddAccountRequest, DeleteAccountRequest,
    AccountLoginCheckRequest, CourseInformResponse
)
from global_state import global_var
from utils.object_utils import struct_to_map
from utils.log import log_print, INFO


def user_list_service() -> dict:
    """拉取账号列表"""
    session = get_session()
    try:
        users, total = user_mapper.query_users(session, page=1, page_size=10)
        res_user_list = []
        for user in users:
            user_dict = struct_to_map(user)
            activity = global_var.get_user_activity(user.uid)
            if activity is not None and hasattr(activity, 'is_running'):
                user_dict["isRunning"] = activity.is_running
            else:
                user_dict["isRunning"] = False
            res_user_list.append(user_dict)

        return Response(
            code=200,
            message="拉取账号成功",
            data={"users": res_user_list, "total": total}
        ).to_dict()
    finally:
        session.close()


def add_user_service(body: dict) -> dict:
    """添加账号"""
    account_type = body.get("accountType", "")
    url = body.get("url", "")
    account = body.get("account", "")
    password = body.get("password", "")

    session = get_session()
    try:
        # 检测账号是否已存在
        existing = user_mapper.query_user(
            session, account_type=account_type, url=url, account=account
        )
        if existing:
            return Response(code=400, message="该账号已存在").to_dict()

        uid = str(uuid.uuid4())
        user_config = {
            "accountType": account_type,
            "URL": url,
            "account": account,
            "password": password,
        }
        user_po = UserPO(
            uid=uid,
            account_type=account_type,
            url=url,
            account=account,
            password=password,
            user_config_json=json.dumps(user_config, ensure_ascii=False),
        )

        err = user_mapper.insert_user(session, user_po)
        if err:
            return Response(code=400, message=err).to_dict()

        return Response(
            code=200,
            message="添加账号成功",
            data=struct_to_map(user_po)
        ).to_dict()
    finally:
        session.close()


def delete_user_service(body: dict) -> dict:
    """删除账号"""
    uid = body.get("uid", "")
    account_type = body.get("accountType", "")
    url = body.get("url", "")
    account = body.get("account", "")

    session = get_session()
    try:
        if uid:
            err = user_mapper.delete_user(session, uid=uid)
        elif account_type and account:
            err = user_mapper.delete_user(
                session, account_type=account_type, url=url, account=account
            )
        else:
            return Response(code=400, message="缺少必要参数").to_dict()

        if err:
            return Response(code=400, message="删除失败").to_dict()

        return Response(code=200, message="删除成功").to_dict()
    finally:
        session.close()


def update_user_service(body: dict) -> dict:
    """更新账号信息"""
    uid = body.get("uid", "")
    if not uid:
        return Response(code=400, message="UID 不能为空").to_dict()

    update_map = {}
    if body.get("accountType"):
        update_map["account_type"] = body["accountType"]
    if body.get("url"):
        update_map["url"] = body["url"]
    if body.get("account"):
        update_map["account"] = body["account"]
    if body.get("password"):
        update_map["password"] = body["password"]

    if not update_map:
        return Response(code=400, message="没有可更新的字段").to_dict()

    session = get_session()
    try:
        err = user_mapper.update_user(session, uid, update_map)
        if err:
            return Response(code=500, message=err).to_dict()
        return Response(code=200, message="更新成功").to_dict()
    finally:
        session.close()


def account_login_check_service(body: dict) -> dict:
    """账号登录检测"""
    uid = body.get("uid", "")
    if uid:
        session = get_session()
        try:
            user = user_mapper.query_user(session, uid=uid)
            if not user:
                return Response(code=400, message="该账号不存在").to_dict()
        finally:
            session.close()

    return Response(code=200, message="账号登录正常").to_dict()


def get_account_inform_service(uid: str) -> dict:
    """获取账号配置信息"""
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()
        return Response(
            code=200,
            message="拉取信息成功",
            data={"user": struct_to_map(user)}
        ).to_dict()
    finally:
        session.close()


def account_course_list_service(uid: str) -> dict:
    """获取课程列表"""
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()

        activity = global_var.get_user_activity(user.uid)
        if activity is None:
            # 构建用户活动
            from web.activity.base_activity import UserActivityBase
            activity = _build_user_activity(user)
            if activity:
                global_var.put_user_activity(user.uid, activity)

        if activity and hasattr(activity, 'pull_course_list'):
            course_list = activity.pull_course_list()
            return Response(
                code=200,
                message="拉取信息成功",
                data={"courseList": course_list}
            ).to_dict()

        return Response(code=200, message="拉取信息成功",
                        data={"courseList": []}).to_dict()
    finally:
        session.close()


def start_brush_service(uid: str) -> dict:
    """启动刷课"""
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="用户不存在").to_dict()
    finally:
        session.close()

    activity = global_var.get_user_activity(uid)
    if activity:
        t = threading.Thread(target=activity.start, daemon=True)
        t.start()

    return Response(code=200, message="启动成功").to_dict()


def stop_brush_service(uid: str) -> dict:
    """停止刷课"""
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="用户不存在").to_dict()
    finally:
        session.close()

    activity = global_var.get_user_activity(uid)
    if activity:
        activity.stop()

    return Response(code=200, message="停止成功").to_dict()


def stream_log_generator(log_id: str) -> Generator[str, None, None]:
    """SSE 日志流生成器"""
    log_path = f"./assets/logs/{log_id}.log"
    if not os.path.exists(log_path):
        yield f"data: error: log file not found\n\n"
        return

    with open(log_path, 'r', encoding='utf-8') as f:
        while True:
            line = f.readline()
            if line:
                yield f"data: {line}\n\n"
            else:
                time.sleep(0.5)


def _build_user_activity(user_po: UserPO):
    """根据用户类型构建对应的 Activity 实例 - 支持全部 9 个平台"""
    config_data = user_po.user_config_turn_entity()
    account_type = user_po.account_type

    from config.config import User
    user = User(
        account_type=config_data.get("accountType", account_type),
        url=config_data.get("URL", config_data.get("url", "")),
        account=config_data.get("account", user_po.account),
        password=config_data.get("password", user_po.password),
    )

    if account_type == "XUEXITONG":
        from web.activity.xuexitong_activity import XXTActivity
        return XXTActivity(user)
    elif account_type == "YINGHUA":
        from web.activity.yinghua_activity import YingHuaActivity
        return YingHuaActivity(user)
    elif account_type == "ENAEA":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "ENAEA")
    elif account_type == "CQIE":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "CQIE")
    elif account_type == "KETANGX":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "KETANGX")
    elif account_type == "WELEARN":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "WELEARN")
    elif account_type == "ICVE":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "ICVE")
    elif account_type == "QSXT":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "QSXT")
    elif account_type == "HQKJ":
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, "HQKJ")
    return None
