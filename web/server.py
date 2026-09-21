# -*- coding: utf-8 -*-
"""
FastAPI 服务器初始化 - 对应 Go 项目的 ServerInit.go
包含 CORS 中间件、日志中间件、内置管理界面静态服务
"""
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles

from utils.log import log_print, INFO


def _resolve_static_root() -> Path | None:
    """定位内置管理界面静态目录(多级探测)

    优先级: 源码目录 web/static → 打包解压目录(_MEIPASS/web/static)
            → 兼容旧版 assets/web
    """
    candidates = [
        Path(__file__).resolve().parent / "static",
        Path(getattr(sys, "_MEIPASS", ".")) / "web" / "static",
        Path("./assets/web"),
    ]
    for p in candidates:
        try:
            if p.is_dir():
                return p
        except OSError:
            continue
    return None


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(title="Yatori Console API", version="V1.2.0")

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

    # 内置管理界面静态服务(图形界面入口)
    static_root = _resolve_static_root()
    if static_root is not None:
        next_static = static_root / "_next" / "static"
        if next_static.is_dir():
            app.mount("/web/_next/static",
                      StaticFiles(directory=str(next_static)),
                      name="next_static")

        @app.get("/")
        async def root_redirect():
            return RedirectResponse("/web/")

        @app.get("/web/{filepath:path}")
        async def serve_web(filepath: str):
            file_path = static_root / filepath
            # 静态资源文件直接返回
            if file_path.exists() and file_path.is_file() and file_path.suffix:
                return FileResponse(str(file_path))
            # 其余返回 index.html(前端路由/根路径)
            index_path = static_root / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return JSONResponse({"error": "Frontend app not found"},
                                status_code=404)
    else:
        @app.get("/")
        async def root_info():
            return JSONResponse({
                "name": "Yatori Console API",
                "hint": "未找到内置管理界面(web/static), 仅提供 API",
                "api_test": "/api/test",
            })

    # 404 处理 - 对应 Go 的 NoRoute
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        path = request.url.path
        if path.startswith("/api"):
            return JSONResponse({"error": "API endpoint not found", "path": path},
                                status_code=404)
        if static_root is not None:
            index_path = static_root / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
        return JSONResponse({"error": "Page not found", "path": path},
                            status_code=404)

    return app
