# -*- coding: utf-8 -*-
"""
用户控制器 - 对应 Go 项目的 UserController.go
定义所有用户相关的 API 路由端点

线程模型(2026-09-28 修复"启动刷课没反应"):
  业务服务全是同步阻塞(SQLite/HTTP/文件IO), 若直接在 async 路由里调用会
  阻塞 FastAPI 事件循环——刷课高强度运行时会拖死整个 API(所有请求长时间
  无响应, 前端表现为"点了没反应, 重启后端才恢复")。
  修复: GET 路由改为同步 def(FastAPI 自动放线程池执行);
        POST 路由保留 async 读取 body, 业务处理用 run_in_threadpool 下沉线程池;
        SSE 保持 async(StreamingResponse 需要)。
"""
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from web.service import user_service

router = APIRouter()


@router.get("/accountList")
def account_list():
    """拉取账号列表"""
    return user_service.user_list_service()


@router.post("/addAccount")
async def add_account(request: Request):
    """添加账号"""
    body = await request.json()
    return await run_in_threadpool(user_service.add_user_service, body)


@router.post("/deleteAccount")
async def delete_account(request: Request):
    """删除账号"""
    body = await request.json()
    return await run_in_threadpool(user_service.delete_user_service, body)


@router.post("/updateAccount")
async def update_account(request: Request):
    """修改账号信息"""
    body = await request.json()
    return await run_in_threadpool(user_service.update_user_service, body)


@router.post("/accountLoginCheck")
async def account_login_check(request: Request):
    """账号登录检测"""
    body = await request.json()
    return await run_in_threadpool(user_service.account_login_check_service, body)


@router.post("/zhihuishu/session/import")
async def import_zhihuishu_session(request: Request):
    """导入并校验用户主动提交的智慧树会话，不读取本地浏览器数据。"""
    body = await request.json()
    return await run_in_threadpool(
        user_service._zhihuishu_session_service, body)


@router.post("/zhihuishu/session/clear")
async def clear_zhihuishu_session(request: Request):
    """清理指定智慧树账号的加密会话。"""
    body = await request.json()
    return await run_in_threadpool(
        user_service._clear_zhihuishu_session_service, body)


@router.get("/getAccountInformForUid/{uid}")
def get_account_inform(uid: str):
    """拉取账号配置数据"""
    return user_service.get_account_inform_service(uid)


@router.get("/getAccountCourseList/{uid}")
def account_course_list(uid: str, refresh: int = 0):
    """获取课程列表(2026-10-22: refresh=1 强制绕过缓存刷新)"""
    return user_service.account_course_list_service(
        uid, force_refresh=bool(refresh))


@router.get("/courseDetailStat/{uid}/{course_id}")
def course_detail_stat(uid: str, course_id: str):
    """课程详情统计(作业x/y+考试x/y, 进度页懒加载, 2026-10-13)"""
    return user_service.course_detail_stat_service(uid, course_id)


@router.get("/getRuntimeStatus/{uid}")
def get_runtime_status(uid: str):
    """运行时实时状态(2026-10-22: 当前阶段/课程/任务点/考试进度/gate预约)"""
    return user_service.runtime_status_service(uid)


@router.get("/startBrush/{uid}")
def start_brush(uid: str):
    """启动刷课"""
    return user_service.start_brush_service(uid)


@router.get("/stopBrush/{uid}")
def stop_brush(uid: str):
    """停止刷课"""
    return user_service.stop_brush_service(uid)


@router.get("/streamLog/{log_id}")
async def stream_log(log_id: str):
    """SSE 日志推送(保持 async: StreamingResponse 需要)"""
    return StreamingResponse(
        user_service.stream_log_generator(log_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/importConfig")
async def import_config():
    """从程序目录 config.yaml 批量导入账号"""
    return await run_in_threadpool(user_service.import_config_service)


@router.get("/logTail")
def log_tail(lines: int = 200, date: str = "", account: str = "",
             order: str = "desc", offset: int = 0):
    """读取日志尾部 N 行(外部分离前端轮询用)

    account 为空=全局日志; 指定=账号独立日志(目录名如 19013841897_备注)
    2026-10-22: order=desc(默认倒序,最新行在前)/asc; offset=N 分页加载更早
    """
    return user_service.log_tail_service(lines=lines, date=date,
                                         account=account,
                                         order=order, offset=offset)


@router.get("/logAccounts")
def log_accounts():
    """账号日志目录清单(前端下拉用)"""
    return user_service.log_accounts_service()
