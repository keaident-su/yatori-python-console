# -*- coding: utf-8 -*-
"""
路由注册 - 对应 Go 项目的 router.go
定义所有 API v1 路由
"""
from fastapi import FastAPI

from web.controller.cert_controller import router as cert_router
from web.controller.config_controller import router as config_router
from web.controller.face_controller import router as face_router
from web.controller.user_controller import router as user_router
from web.controller.tiku_controller import router as tiku_router


def register_routes(app: FastAPI):
    """注册所有路由"""

    # API 测试端点
    @app.get("/api/test")
    async def api_test():
        return {"message": "API working"}

    # API v1 路由组
    app.include_router(user_router, prefix="/api/v1", tags=["User API"])
    app.include_router(cert_router, prefix="/api/v1", tags=["Cert API"])
    app.include_router(face_router, prefix="/api/v1", tags=["Face API"])
    app.include_router(config_router, prefix="/api/v1", tags=["Config API"])
    app.include_router(tiku_router, prefix="/api/v1", tags=["Tiku API"])
