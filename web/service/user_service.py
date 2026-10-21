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


def _zhihuishu_session_service(body: dict) -> dict:
    """导入并校验用户主动提交的智慧树 Cookie/token。"""
    from logic.zhihuishu.api import ManagedSession, validate_session_detail
    from logic.zhihuishu.auth_state import (
        parse_user_cookies, save_session, session_key,
    )

    uid = str(body.get("uid", "")).strip()
    if not uid:
        return Response(code=400, message="UID 不能为空").to_dict()
    db = get_session()
    try:
        user = user_mapper.query_user(db, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()
        if user.account_type != "ZHIHUISHU":
            return Response(code=400, message="该接口仅支持智慧树账号").to_dict()
        raw_cookies = body.get("cookies", body.get("cookie", ""))
        token = str(body.get("token", "") or "").strip()
        if not raw_cookies:
            return Response(code=400,
                            message="请主动提交智慧树 Cookie；token 需与 Cookie 一并提交").to_dict()
        try:
            jar = parse_user_cookies(raw_cookies)
        except ValueError as exc:
            return Response(code=400, message=f"Cookie 格式无效: {exc}").to_dict()
        candidate = ManagedSession(cookies=jar)
        validation = validate_session_detail(candidate)
        if validation.status != "LOGIN_SUCCESS":
            return Response(code=400, message=validation.message or
                            "会话校验失败或已过期，请提交当前有效的智慧树会话",
                            data=validation.__dict__).to_dict()
        save_session(session_key(user.account), candidate.cookies, token=token)
        return Response(code=200, message="智慧树会话已校验并加密保存",
                        data={"status": "LOGIN_SUCCESS",
                              "cookieCount": len(candidate.cookies)}).to_dict()
    finally:
        db.close()


def _clear_zhihuishu_session_service(body: dict) -> dict:
    """清理指定智慧树账号的加密会话。"""
    from logic.zhihuishu.auth_state import delete_session, session_key
    uid = str(body.get("uid", "")).strip()
    if not uid:
        return Response(code=400, message="UID 不能为空").to_dict()
    db = get_session()
    try:
        user = user_mapper.query_user(db, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()
        if user.account_type != "ZHIHUISHU":
            return Response(code=400, message="该接口仅支持智慧树账号").to_dict()
        delete_session(session_key(user.account))
        return Response(code=200, message="智慧树加密会话已清理").to_dict()
    finally:
        db.close()


def user_list_service() -> dict:
    """拉取账号列表"""
    session = get_session()
    try:
        users, total = user_mapper.query_users(session, page=1, page_size=50)
        res_user_list = []
        for user in users:
            user_dict = struct_to_map(user)
            # 2026-10-19: 身份信息(学校/姓名/学号)提升到顶层, 供前端展示/搜索/筛选
            try:
                import json as _json
                _cfg = _json.loads(user_dict.get("userConfigJson") or "{}")
                if not isinstance(_cfg, dict):
                    _cfg = {}
            except Exception:
                _cfg = {}
            user_dict["school"] = _cfg.get("school", "")
            user_dict["realName"] = _cfg.get("realName", "")
            user_dict["stuNo"] = _cfg.get("stuNo", "")
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

        # ★ 2026-10-08 修复: 新增账号后清理同名残留缓存(防御性; 新uid理论无缓存)
        try:
            global_var.remove_user_activity(uid)
        except Exception:
            pass

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

    # 运行中拦截: 删除运行中的账号会导致刷课线程异常
    if uid and _is_account_running(uid):
        return Response(
            code=400,
            message="账号正在刷课中，无法删除，请先停止刷课").to_dict()

    zhs_session_id = ""
    if account_type == "ZHIHUISHU" or uid:
        from logic.zhihuishu.auth_state import session_key
        lookup = get_session()
        try:
            existing = user_mapper.query_user(
                lookup, uid=uid, account_type=account_type,
                url=url, account=account)
            if existing and existing.account_type == "ZHIHUISHU":
                zhs_session_id = session_key(existing.account)
        finally:
            lookup.close()

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

        if zhs_session_id:
            from logic.zhihuishu.auth_state import delete_session
            delete_session(zhs_session_id)

        # ★ 2026-10-08 修复: 删除账号后同步清理内存中的 Activity 缓存,
        # 避免僵尸活动对象残留(与"编辑后不同步"同类问题的防御性修复)
        if uid:
            try:
                global_var.remove_user_activity(uid)
            except Exception:
                pass

        return Response(code=200, message="删除成功").to_dict()
    finally:
        session.close()


def _is_account_running(uid: str) -> bool:
    """账号是否正在刷课中(基于内存活动状态)"""
    try:
        activity = global_var.get_user_activity(uid)
        return bool(activity is not None and
                    getattr(activity, "is_running", False))
    except Exception:
        return False


def update_user_service(body: dict) -> dict:
    """更新账号信息"""
    uid = body.get("uid", "")
    if not uid:
        return Response(code=400, message="UID 不能为空").to_dict()

    # 运行中拦截: 运行中的账号修改配置不会影响本次刷课,
    # 必须停止后再修改，避免"改了不生效"的困惑
    if _is_account_running(uid):
        return Response(
            code=400,
            message="账号正在刷课中，无法修改配置信息，请先停止刷课").to_dict()

    update_map = {}
    if body.get("accountType"):
        update_map["account_type"] = body["accountType"]
    if body.get("url"):
        update_map["url"] = body["url"]
    if body.get("account"):
        update_map["account"] = body["account"]
    if body.get("password"):
        update_map["password"] = body["password"]

    # 扩展配置(备注名/课程自定义/通知邮箱/推送/代理)合并进 user_config_json
    _EXT_KEYS = ("coursesCustom", "remarkName", "informEmails",
                 "showdocSw", "showdocUrls", "isProxy")
    if any(_k in body for _k in _EXT_KEYS):
        _s0 = get_session()
        try:
            _po = user_mapper.query_user(_s0, uid=uid)
            if _po:
                _cfgj = _po.user_config_turn_entity()
                for _k in _EXT_KEYS:
                    if _k in body:
                        _cfgj[_k] = body[_k]
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
        # ★ 2026-10-08 修复"编辑账号不同步到刷课"BUG:
        # 写库成功后必须失效内存中缓存的 Activity(内含构建时的旧User快照),
        # 否则 startBrush 会复用旧 Activity 跑旧配置(停止再启动也无效,
        # 只有重启后端才恢复)。移除后下次启动会按最新库数据懒重建。
        try:
            global_var.remove_user_activity(uid)
        except Exception:
            pass
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


# 2026-10-22 查课提速(方案A): 进程级TTL缓存——查课全量实时拉取需300-400+请求串行等待
#   (课程列表+每课任务点/互动测验/综合成绩), 实测15-45秒; 前端30秒轮询叠加恶性循环。
#   缓存90秒: 轮询命中缓存秒回; ?refresh=1 强制刷新绕过缓存。
_COURSE_LIST_CACHE = {}
_COURSE_LIST_TTL = 90


def account_course_list_service(uid: str, force_refresh: bool = False) -> dict:
    """获取课程列表(2026-10-22: 加TTL缓存+refresh强制刷新)"""
    import time as _t
    if not force_refresh:
        _hit = _COURSE_LIST_CACHE.get(str(uid))
        if _hit and (_t.time() - float(_hit.get("ts", 0))) < _COURSE_LIST_TTL:
            return _hit.get("data") or {}
    try:
        return _account_course_list_service_uncached(uid)
    except Exception:
        raise
    finally:
        pass


def _account_course_list_service_uncached(uid: str) -> dict:
    """获取课程列表(实时全量拉取, 结果写入缓存)"""
    import time as _t
    _resp = _account_course_list_service_impl(uid)
    try:
        _COURSE_LIST_CACHE[str(uid)] = {"ts": _t.time(), "data": _resp}
    except Exception:
        pass
    return _resp


def _account_course_list_service_impl(uid: str) -> dict:
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
            # 2026-10-13: 附带账号的"只刷/排除课程"配置(供进度页过滤显示)
            _inc, _exc = [], []
            try:
                _cc = getattr(user, "courses_custom", None)
                if _cc is not None:
                    _inc = [str(x) for x in
                            (getattr(_cc, "include_courses", []) or [])
                            if str(x).strip()]
                    _exc = [str(x) for x in
                            (getattr(_cc, "exclude_courses", []) or [])
                            if str(x).strip()]
            except Exception:
                pass
            # 2026-10-15: 注入平台名称+账号(前端进度页展示"平台：智慧树 · 账号：xxx")
            try:
                from web.activity.generic_activity import _PLATFORM_DISPLAY
                _at = (getattr(user, "account_type", "") or "").upper()
                _plat = _PLATFORM_DISPLAY.get(_at, _at)
                if _plat:
                    for _c in (course_list or []):
                        if isinstance(_c, dict):
                            _c.setdefault("platform", _plat)
            except Exception:
                _plat = ""
            _acct = str(getattr(user, "account", "") or "")
            return Response(
                code=200,
                message="拉取信息成功",
                data={"courseList": course_list,
                      "includeCourses": _inc,
                      "excludeCourses": _exc,
                      "platform": _plat,
                      "account": _acct}
            ).to_dict()

        return Response(code=200, message="拉取信息成功",
                        data={"courseList": []}).to_dict()
    finally:
        session.close()


def course_detail_stat_service(uid: str, course_id: str) -> dict:
    """课程详情统计(作业x/y+考试x/y, 2026-10-13 进度页懒加载)"""
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()
        activity = global_var.get_user_activity(user.uid)
        if activity is None:
            from web.activity.base_activity import UserActivityBase
            activity = _build_user_activity(user)
            if activity:
                global_var.put_user_activity(user.uid, activity)
    finally:
        session.close()
    if not activity or not hasattr(activity, "course_detail_stat"):
        return Response(code=200, message="该平台暂不支持",
                        data={"supported": False}).to_dict()
    try:
        data = activity.course_detail_stat(str(course_id))
    except Exception as e:
        return Response(code=500, message=f"统计失败: {str(e)[:120]}").to_dict()
    data["courseId"] = str(course_id)
    return Response(code=200, message="OK", data=data).to_dict()


def start_brush_service(uid: str) -> dict:
    """启动刷课(2026-09-28: 全链路日志 + 明确成败语义)

    排查"启动没反应"时看以下日志定位卡在哪一步:
    收到请求 → 查库取用户 → 构建活动 → 已运行检查 → 线程下发
    """
    from utils.log import log_print, INFO, Green, Yellow, Red, BoldRed
    _u8 = str(uid)[:8]
    log_print(INFO, "[Web]", Green, f"收到启动刷课请求 uid={_u8}..")
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            log_print(INFO, "[Web]", Red, f"启动失败: 用户不存在 uid={_u8}..")
            return Response(code=400, message="用户不存在").to_dict()
        account = user.account
        # 账号日志上下文用: 备注名(可能为空)
        try:
            _cd = user.user_config_turn_entity()
            _remark = str(_cd.get("remarkName", "") or "")
        except Exception:
            _remark = ""
    except Exception as e:
        log_print(INFO, "[Web]", Red, f"启动失败: 查询用户异常 {type(e).__name__}: {e}")
        return Response(code=500, message=f"查询用户异常: {e}").to_dict()
    finally:
        session.close()

    activity = global_var.get_user_activity(uid)
    if activity is None:
        # 未点过"课程列表"时直接启动: 懒构建活动
        activity = _build_user_activity(user)
        if activity is None:
            log_print(INFO, "[Web]", Red,
                      f"启动失败: {account} 该平台暂不支持Web模式")
            return Response(code=400, message="该平台暂不支持Web模式").to_dict()
        global_var.put_user_activity(uid, activity)
        log_print(INFO, "[Web]", f"账号 {account} 活动对象已构建")

    # 已运行检查(明确提示, 避免"点了没反应"的困惑)
    if getattr(activity, "is_running", False):
        log_print(INFO, "[Web]", Yellow,
                  f"启动被忽略: {account} 刷课已在运行中(如需重启请先停止)")
        return Response(
            code=400,
            message="该账号刷课已在运行中，请先停止再启动").to_dict()

    # 账号日志上下文(2026-09-30): 刷课线程内日志自动带 [账号|备注] 前缀,
    # 并同时写入独立文件 assets/logs/accounts/{账号}_{备注}/{日期}.log
    def _runner():
        from utils.log import set_log_account, clear_log_account
        set_log_account(account, _remark)
        try:
            activity.start()
        finally:
            clear_log_account()

    try:
        t = threading.Thread(target=_runner, daemon=True,
                             name=f"start-{_u8}")
        t.start()
    except Exception as e:
        log_print(INFO, "[Web]", BoldRed, f"启动线程失败: {account} {e}")
        return Response(code=500, message=f"启动线程失败: {e}").to_dict()

    log_print(INFO, "[Web]", Green,
              f"已下发启动指令: {account} (后台线程执行登录与刷课)")
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
        uid=user_po.uid,
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

    注意: read_config() 在配置异常时会 sys.exit(1)(抛 SystemExit),
    Web 场景绝不能让服务退出 —— 此处显式捕获并回退默认设置。
    """
    setting = None
    try:
        if os.path.exists("./config.yaml"):
            from config.config import read_config
            setting = read_config("./config.yaml").setting
        else:
            from utils.log import log_print, INFO, BoldRed
            log_print(INFO, BoldRed,
                      "[Web配置] 未找到程序目录 config.yaml, 使用默认设置")
    except SystemExit:
        setting = None
        from utils.log import log_print, INFO, BoldRed
        log_print(INFO, BoldRed,
                  "[Web配置] config.yaml 解析失败, 已回退默认设置(服务不退出)")
    except Exception as e:
        setting = None
        from utils.log import log_print, INFO, BoldRed
        log_print(INFO, BoldRed,
                  f"[Web配置] config.yaml 读取异常({e}), 已回退默认设置")
    if setting is None:
        from config.config import Setting
        setting = Setting()
    # 性能策略热更新: 同步环境变量(front端保存 fullCpuMode/performanceGear 后即时生效)
    try:
        _bs = setting.basic_setting
        os.environ["YATORI_FULL_CPU"] = "1" if _bs.full_cpu_mode == 1 else "0"
        os.environ["YATORI_PERF_GEAR"] = str(
            _bs.performance_gear or "aggressive")
    except Exception:
        pass
    try:
        from logic.core.answer_engine import configure_answer_engine
        configure_answer_engine(setting)
    except Exception as e:
        from utils.log import log_print, INFO, BoldRed
        log_print(INFO, BoldRed,
                  f"[Web配置] 答题引擎注入失败(重启后生效): {e}")
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


def log_accounts_service() -> dict:
    """列出账号日志目录清单(前端下拉用)

    扫描 assets/logs/accounts/* 目录, 返回账号目录名与可用日志文件。
    """
    base = os.path.join(".", "assets", "logs", "accounts")
    items = []
    try:
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                p = os.path.join(base, name)
                if not os.path.isdir(p):
                    continue
                try:
                    files = sorted(
                        [f for f in os.listdir(p) if f.endswith(".log")],
                        reverse=True)
                except OSError:
                    files = []
                items.append({"name": name, "files": files[:60]})
    except OSError as e:
        return Response(code=500, message=f"读取账号日志目录失败: {e}").to_dict()
    return Response(code=200, message="ok",
                    data={"accounts": items,
                          "today": time.strftime("%Y-%m-%d")}).to_dict()


def log_tail_service(lines: int = 200, date: str = "", account: str = "",
                     order: str = "desc", offset: int = 0) -> dict:
    """读取日志文件尾部 N 行(外部分离前端轮询用; 加密通道下与 SSE 等效)

    account 为空=全局日志(assets/logs/{date}.log);
    指定=账号独立日志(assets/logs/accounts/{account}/{date}.log)

    性能(2026-09-28): 旧实现 f.readlines() 每次读整个文件——高强度刷课时
    日志可达数百MB, 加上路由阻塞事件循环, 前端轮询会拖垮整个后端。
    现改为 deque 流式尾读(内存只占 N 行), 当前文件不足时向前回溯轮转备份。

    2026-10-22 需求升级(倒序+完整历史+分页):
      · order=desc(默认)→返回时按时间倒序(最新行在最前); asc=正序
      · offset=N →跳过最新的N行, 用于"加载更早"(逐页向后翻历史)
      · 上限 2000 → 10000 行
    """
    try:
        lines = max(1, min(int(lines or 200), 10000))
    except (TypeError, ValueError):
        lines = 200
    try:
        offset = max(0, min(int(offset or 0), 200000))
    except (TypeError, ValueError):
        offset = 0
    _desc = str(order or "desc").lower() != "asc"
    log_id = (date or time.strftime("%Y-%m-%d")).strip()
    if account:
        # 目录穿越防护: 账号名仅允许单层目录
        safe = str(account).replace("\\", "/").strip("/")
        if "/" in safe or ".." in safe:
            return Response(code=400, message="非法账号名").to_dict()
        log_path = f"./assets/logs/accounts/{safe}/{log_id}.log"
    else:
        log_path = f"./assets/logs/{log_id}.log"
    if not os.path.exists(log_path):
        return Response(code=200, message="ok",
                        data={"lines": [], "date": log_id,
                              "order": "desc" if _desc else "asc",
                              "offset": offset, "hasMore": False}).to_dict()
    try:
        from collections import deque
        # 需要 lines+offset 行(尾部)才能切出"更早的一页"
        _need = lines + offset
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            tail = list(deque(f, maxlen=_need))
        # 当前文件不够时, 向前回溯轮转备份(.log.1 是最新备份)
        if len(tail) < _need:
            for i in range(1, 6):
                backup = f"{log_path}.{i}"
                if not os.path.exists(backup):
                    break
                with open(backup, "r", encoding="utf-8",
                          errors="replace") as f:
                    prev = list(deque(f, maxlen=_need - len(tail)))
                tail = prev + tail
                if len(tail) >= _need:
                    break
        _has_more = len(tail) >= _need
        tail = [ln.rstrip("\r\n") for ln in tail]
        # 分页: 跳过最新 offset 行, 取更早的 lines 行
        if offset:
            tail = tail[:max(0, len(tail) - offset)]
        page = tail[-lines:] if len(tail) > lines else tail
        if _desc:
            page = list(reversed(page))
    except OSError as e:
        return Response(code=500, message=f"读取日志失败: {e}").to_dict()
    return Response(code=200, message="ok",
                    data={"lines": page, "date": log_id,
                          "order": "desc" if _desc else "asc",
                          "offset": offset, "hasMore": _has_more}).to_dict()
