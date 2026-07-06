# -*- coding: utf-8 -*-
"""
用户控制器 - 对应 Go 项目的 UserController.go
定义所有用户相关的 API 路由端点
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from web.service import user_service

router = APIRouter()


@router.get("/accountList")
async def account_list(request: Request):
    """拉取账号列表"""
    return user_service.user_list_service()


@router.post("/addAccount")
async def add_account(request: Request):
    """添加账号"""
    body = await request.json()
    return user_service.add_user_service(body)


@router.post("/deleteAccount")
async def delete_account(request: Request):
    """删除账号"""
    body = await request.json()
    return user_service.delete_user_service(body)


@router.post("/updateAccount")
async def update_account(request: Request):
    """修改账号信息"""
    body = await request.json()
    return user_service.update_user_service(body)


@router.post("/accountLoginCheck")
async def account_login_check(request: Request):
    """账号登录检测"""
    body = await request.json()
    return user_service.account_login_check_service(body)


@router.get("/getAccountInformForUid/{uid}")
async def get_account_inform(uid: str):
    """拉取账号配置数据"""
    return user_service.get_account_inform_service(uid)


@router.get("/getAccountCourseList/{uid}")
async def account_course_list(uid: str):
    """获取课程列表"""
    return user_service.account_course_list_service(uid)


@router.get("/startBrush/{uid}")
async def start_brush(uid: str):
    """启动刷课"""
    return user_service.start_brush_service(uid)


@router.get("/stopBrush/{uid}")
async def stop_brush(uid: str):
    """停止刷课"""
    return user_service.stop_brush_service(uid)


@router.get("/streamLog/{log_id}")
async def stream_log(log_id: str):
    """SSE 日志推送"""
    return StreamingResponse(
        user_service.stream_log_generator(log_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
