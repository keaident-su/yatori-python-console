# -*- coding: utf-8 -*-
"""
FastAPI 服务器初始化 - 对应 Go 项目的 ServerInit.go
包含 CORS 中间件、日志中间件、静态文件服务
"""
import os
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from utils.log import log_print, INFO


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(title="Yatori Console API", version="2.6.2")

    # CORS 中间件 - 对应 Go 的 Cors()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS", "PUT", "DELETE"],
        allow_headers=["Origin", "Content-Type", "Authorization"],
    )

    # 注册路由
    from web.router import register_routes
    register_routes(app)

    # 静态文件服务 - 对应 Go 的 /web/*filepath
    assets_web = Path("./assets/web")
    if assets_web.exists():
        # 静态资源目录
        static_dir = assets_web / "_next" / "static"
        if static_dir.exists():
            app.mount("/web/_next/static", StaticFiles(directory=str(static_dir)),
                      name="next_static")

        # SPA 路由 fallback
        @app.get("/web/{filepath:path}")
        async def serve_web(filepath: str):
            file_path = assets_web / filepath
            # 如果是静态资源文件
            if file_path.exists() and file_path.is_file() and file_path.suffix:
                return FileResponse(str(file_path))
            # 否则返回 index.html（前端路由）
            index_path = assets_web / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return JSONResponse({"error": "Frontend app not found"}, status_code=404)

    # 404 处理 - 对应 Go 的 NoRoute
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        path = request.url.path
        if path.startswith("/api"):
            return JSONResponse({"error": "API endpoint not found", "path": path},
                                status_code=404)
        if path.startswith("/web"):
            index_path = Path("./assets/web/index.html")
            if index_path.exists():
                return FileResponse(str(index_path))
            return JSONResponse({"error": "Frontend app not found"}, status_code=404)
        return JSONResponse({"error": "Page not found", "path": path}, status_code=404)

    return app
