# -*- coding: utf-8 -*-
"""
路由注册 - 对应 Go 项目的 router.go
定义所有 API v1 路由
"""
from fastapi import FastAPI

from web.controller.user_controller import router as user_router


def register_routes(app: FastAPI):
    """注册所有路由"""

    # API 测试端点
    @app.get("/api/test")
    async def api_test():
        return {"message": "API working"}

    # API v1 路由组
    app.include_router(user_router, prefix="/api/v1", tags=["User API"])
