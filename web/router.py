# -*- coding: utf-8 -*-
"""
路由注册 - 对应 Go 项目的 router.go
定义所有 API v1 路由
"""
from fastapi import FastAPI

from web.controller.config_controller import router as config_router
from web.controller.user_controller import router as user_router
from web.controller.tiku_controller import router as tiku_router

# 私有部署增强模块(不参与开源): 文件存在时自动启用对应路由
# (web/controller/cert_controller.py、face_controller.py; 缺失时回到开源基础模式)
try:
    from web.controller.cert_controller import router as cert_router
except ImportError:
    cert_router = None
try:
    from web.controller.face_controller import router as face_router
except ImportError:
    face_router = None


def register_routes(app: FastAPI):
    """注册所有路由"""

    # API 测试端点
    @app.get("/api/test")
    async def api_test():
        return {"message": "API working"}

    # API v1 路由组
    app.include_router(user_router, prefix="/api/v1", tags=["User API"])
    if cert_router is not None:
        app.include_router(cert_router, prefix="/api/v1", tags=["Cert API"])
    if face_router is not None:
        app.include_router(face_router, prefix="/api/v1", tags=["Face API"])
    app.include_router(config_router, prefix="/api/v1", tags=["Config API"])
    app.include_router(tiku_router, prefix="/api/v1", tags=["Tiku API"])
