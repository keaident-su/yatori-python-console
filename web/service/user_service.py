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

from config.config import User, CoursesCustom, _apply_yaml_mapping
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
        users, total = user_mapper.query_users(session, page=1, page_size=50)
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
        # 可选扩展字段(备注/课程自定义/通知邮箱/推送/代理, 界面与导入用)
        for _k in ("remarkName", "informEmails", "showdocSw",
                   "showdocUrls", "isProxy", "coursesCustom"):
            if _k in body and body[_k] not in (None, "", [], {}):
                user_config[_k] = body[_k]
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

    # 扩展配置(备注名/课程自定义等)合并进 user_config_json
    if ("coursesCustom" in body) or ("remarkName" in body):
        _s0 = get_session()
        try:
            _po = user_mapper.query_user(_s0, uid=uid)
            if _po:
                _cfgj = _po.user_config_turn_entity()
                if "coursesCustom" in body:
                    _cfgj["coursesCustom"] = body["coursesCustom"]
                if "remarkName" in body:
                    _cfgj["remarkName"] = body["remarkName"]
                update_map["user_config_json"] = json.dumps(
                    _cfgj, ensure_ascii=False)
        finally:
            _s0.close()

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
    if activity is None:
        # 未点过"课程列表"时直接启动: 懒构建活动
        activity = _build_user_activity(user)
        if activity is None:
            return Response(code=400, message="该平台暂不支持Web模式").to_dict()
        global_var.put_user_activity(uid, activity)

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
    """根据用户类型构建对应的 Activity 实例 - 支持全部 11 个平台"""
    config_data = user_po.user_config_turn_entity()
    account_type = user_po.account_type

    # 课程自定义配置(界面/导入保存的完整 coursesCustom)
    cc = CoursesCustom()
    cc_data = config_data.get("coursesCustom",
                              config_data.get("courses_custom", {}))
    if isinstance(cc_data, dict):
        _apply_yaml_mapping(cc_data, cc)

    user = User(
        account_type=config_data.get("accountType", account_type),
        url=config_data.get("URL", config_data.get("url", user_po.url)),
        remark_name=config_data.get("remarkName",
                                    config_data.get("remark_name", "")),
        account=config_data.get("account", user_po.account),
        password=config_data.get("password", user_po.password),
        is_proxy=int(config_data.get("isProxy",
                                     config_data.get("is_proxy", 0)) or 0),
        inform_emails=config_data.get("informEmails",
                                      config_data.get("inform_emails", [])) or [],
        showdoc_sw=int(config_data.get("showdocSw",
                                       config_data.get("showdoc_sw", 0)) or 0),
        showdoc_urls=config_data.get("showdocUrls",
                                     config_data.get("showdoc_urls", [])) or [],
        courses_custom=cc,
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
    elif account_type in ("WEBAN", "ZHIHUISHU"):
        from web.activity.generic_activity import GenericActivity
        return GenericActivity(user, account_type)
    return None


# ============ Web 模式: 全局配置加载与批量导入 ============

def load_web_setting():
    """加载 Web 模式的全局设置(界面启动刷课时注入)

    优先读取程序目录 config.yaml 的 setting 段(与控制台模式行为一致),
    并顺带把配置注入多答题源引擎(幂等), 确保题库/AI/本地缓存生效。
    """
    setting = None
    try:
        if os.path.exists("./config.yaml"):
            from config.config import read_config
            setting = read_config("./config.yaml").setting
    except Exception:
        setting = None
    if setting is None:
        from config.config import Setting
        setting = Setting()
    try:
        from logic.core.answer_engine import configure_answer_engine
        configure_answer_engine(setting)
    except Exception:
        pass
    return setting


def import_config_service() -> dict:
    """从程序目录 config.yaml 导入全部账号(界面"导入配置"按钮)

    - 账号: 按 (平台, URL, 账号) 去重后批量入库, 完整保留
      coursesCustom/备注名/通知邮箱/ShowDoc/代理等全部字段;
    - 设置: 无需入库——刷课启动时由 load_web_setting() 直接读取 config.yaml。
    """
    if not os.path.exists("./config.yaml"):
        return Response(
            code=400,
            message="未找到程序目录下的 config.yaml, 请先用配置生成器导出并放到程序目录").to_dict()
    try:
        from config.config import read_config
        cfg = read_config("./config.yaml")
    except Exception as e:
        return Response(code=400, message=f"解析 config.yaml 失败: {e}").to_dict()

    from dataclasses import asdict
    imported, skipped = 0, 0
    session = get_session()
    try:
        for u in cfg.users:
            existing = user_mapper.query_user(
                session, account_type=u.account_type,
                url=u.url, account=u.account)
            if existing:
                skipped += 1
                continue
            user_config = {
                "accountType": u.account_type,
                "URL": u.url,
                "remarkName": u.remark_name,
                "account": u.account,
                "password": u.password,
                "isProxy": u.is_proxy,
                "informEmails": list(u.inform_emails or []),
                "showdocSw": u.showdoc_sw,
                "showdocUrls": list(u.showdoc_urls or []),
                "coursesCustom": asdict(u.courses_custom),
            }
            po = UserPO(
                uid=str(uuid.uuid4()), account_type=u.account_type,
                url=u.url, account=u.account, password=u.password,
                user_config_json=json.dumps(user_config, ensure_ascii=False))
            err = user_mapper.insert_user(session, po)
            if err:
                skipped += 1
            else:
                imported += 1
        return Response(
            code=200,
            message=f"导入完成: 新增 {imported} 个账号, 跳过 {skipped} 个(已存在或失败)",
            data={"imported": imported, "skipped": skipped,
                  "total": len(cfg.users)}).to_dict()
    finally:
        session.close()
