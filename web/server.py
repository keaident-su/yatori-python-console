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

# 程序版本号(登录/认证响应回传, 便于前端确认部署版本)
APP_VERSION = "3.1.1"


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


def _is_local(request: Request) -> bool:
    """请求是否来自本机(内置界面应急通道判定)

    管理界面仅允许本机(127.0.0.1/::1)访问; 外网一律 404 伪装;
    本机请求同时豁免"强制加密"要求(内置界面直连便捷性)。
    """
    try:
        host = (request.client.host if request.client else "") or ""
        return host in ("127.0.0.1", "::1", "0:0:0:0:0:0:0:1")
    except Exception:
        return False


def _register_auth_plugins(app: FastAPI, web_auth) -> None:
    """注册私有部署增强路由(认证接口 + 内置管理界面静态服务)

    仅在 web/auth.py 存在时调用(私有部署模式); 开源基础模式不注册。
    """
    # ---- 认证接口(白名单): 口令(=webSecret)换取会话令牌 ----
    @app.post("/api/v1/login")
    async def api_login(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        ip = (request.client.host if request.client else "") or "?"
        token, err = web_auth.login(str(body.get("secret", "")), ip)
        if token:
            return JSONResponse({"code": 200, "message": "登录成功",
                                 "data": {"token": token,
                                          "version": APP_VERSION}})
        return JSONResponse({"code": 401, "message": err or "登录失败"},
                            status_code=401)

    @app.get("/api/v1/authCheck")
    async def api_auth_check(request: Request):
        ok = web_auth.verify(web_auth.bearer_of(request))
        return JSONResponse({"code": 200,
                             "data": {"authenticated": bool(ok),
                                      "version": APP_VERSION}})

    # 内置管理界面静态服务(仅经秘密入口 + 仅限本机访问; 外网一律404)
    static_root = _resolve_static_root()
    entry = web_auth.secret_entry()
    if static_root is not None:
        next_static = static_root / "_next" / "static"

        @app.get("/%s/_next/static/{filepath:path}" % entry)
        async def next_static_serve(request: Request, filepath: str):
            if not _is_local(request):
                return JSONResponse({"error": "Not Found"}, status_code=404)
            fp = next_static / filepath
            if fp.exists() and fp.is_file():
                return FileResponse(str(fp))
            return JSONResponse({"error": "Not Found"}, status_code=404)

        @app.get("/%s" % entry)
        async def entry_root(request: Request):
            if not _is_local(request):
                return JSONResponse({"error": "Not Found"}, status_code=404)
            return RedirectResponse("/%s/" % entry)

        @app.get("/%s/{filepath:path}" % entry)
        async def serve_web(request: Request, filepath: str):
            if not _is_local(request):
                return JSONResponse({"error": "Not Found"}, status_code=404)
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


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(title="Yatori Console API", version=APP_VERSION)

    # 私有部署增强模块(不参与开源): 文件存在时自动启用加密通道+访问认证
    # (web/crypto_channel.py、web/auth.py; 缺失时回退到开源基础模式)
    try:
        from web.crypto_channel import install_encrypted_channel
        from web import auth as web_auth
    except ImportError:
        install_encrypted_channel = None
        web_auth = None

    if web_auth is not None:
        # 加密通道(内层): X-Yatori-Enc 请求/响应体 AES-256-GCM 加解密
        install_encrypted_channel(app)

        # 访问认证: 所有 /api(除 login) 要求 Bearer 令牌; 管理界面走秘密入口
        from starlette.middleware.base import BaseHTTPMiddleware

        class AuthGuardMiddleware(BaseHTTPMiddleware):

            async def dispatch(self, request, call_next):
                path = request.url.path
                if path.startswith("/api"):
                    # 强制加密通道: 外网请求必须带 X-Yatori-Enc 头(本机豁免)
                    enc_ok = (request.headers.get("x-yatori-enc") == "1")
                    if not enc_ok and not _is_local(request):
                        return JSONResponse(
                            {"code": 401, "message": __import__("utils.i18n", fromlist=["srv_msg"]).srv_msg("未登录或登录已过期")},
                            status_code=401)
                    # 登录/校验接口白名单(不返回敏感数据)
                    if path in ("/api/v1/login", "/api/v1/authCheck"):
                        return await call_next(request)
                    token = web_auth.bearer_of(request)
                    if not token:
                        # SSE(EventSource 无法自定义头)等场景支持 query 参数传令牌
                        token = request.query_params.get("token", "")
                    if not web_auth.verify(token):
                        return JSONResponse(
                            {"code": 401, "message": __import__("utils.i18n", fromlist=["srv_msg"]).srv_msg("未登录或登录已过期")},
                            status_code=401)
                return await call_next(request)

        app.add_middleware(AuthGuardMiddleware)

    # CORS 中间件(最外层, 处理跨域预检) - 支持宝塔等外部分离前端直连
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from web.router import register_routes
    register_routes(app)

    # 桌面GUI本地桥(2026-10-23): /ui 静态页 + /ui/api 本地免密接口(仅127.0.0.1+token)
    try:
        from web.ui_bridge import mount_ui
        mount_ui(app)
    except Exception:
        pass

    if web_auth is not None:
        _register_auth_plugins(app, web_auth)

    # 根路径与旧入口不再展示管理界面(伪装 404, 不暴露信息)
    @app.get("/")
    async def root_hidden():
        return JSONResponse({"error": "Not Found"}, status_code=404)

    @app.get("/web")
    async def web_hidden():
        return JSONResponse({"error": "Not Found"}, status_code=404)

    @app.get("/web/{rest:path}")
    async def web_hidden_sub(rest: str):
        return JSONResponse({"error": "Not Found"}, status_code=404)

    # 404 处理 - 对应 Go 的 NoRoute
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        path = request.url.path
        if path.startswith("/api"):
            return JSONResponse({"error": "API endpoint not found", "path": path},
                                status_code=404)
        return JSONResponse({"error": "Page not found", "path": path},
                            status_code=404)

    return app
