# -*- coding: utf-8 -*-
"""桌面GUI本地桥(2026-10-23)

为 pywebview 桌面窗口 / 本地浏览器提供免AES加密的本地REST API：
  - 仅允许 127.0.0.1/localhost 访问
  - 每次启动生成随机 UI_TOKEN，窗口URL携带，前端请求头 X-UI-Token 校验
  - /ui           → React 构建产物静态托管(web/static/ui)
  - /ui/api/*     → 薄封装现有 service 层(账号/任务/进度/日志/配置/题库/状态)

设计原则: 不复制业务逻辑, 全部委托 user_service / config_controller / runtime_status。
"""
import os
import io
import json
import time
import base64
import secrets
import functools

from utils.i18n import srv_msg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool  # [V3.2.1] 耗时IO线程池化

# 全局token(启动时生成; pywebview启动器会读取注入窗口URL)
# [V3.2.0] 支持环境变量 YATORI_UI_TOKEN 固定(运维/自动化验收用);
# 同时将 token 落盘到 assets/logs/ui_token.txt(仅本机可读, 供本机运维与 GUI 自动化驱动)
UI_TOKEN = (os.environ.get("YATORI_UI_TOKEN")
            or "").strip() or secrets.token_urlsafe(24)
try:
    # [V3.2.0] 冻结(PyInstaller)后 __file__ 在 _MEI 临时目录, 落盘需用程序目录
    import sys as _sys
    if getattr(_sys, "frozen", False):
        _prog_dir = os.path.dirname(os.path.abspath(_sys.executable))
    else:
        _prog_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _tok_dir = os.path.join(_prog_dir, "assets", "logs")
    os.makedirs(_tok_dir, exist_ok=True)
    _tok_file = os.path.join(_tok_dir, "ui_token.txt")
    with open(_tok_file, "w", encoding="utf-8") as _tf:
        _tf.write(UI_TOKEN)
    try:
        os.chmod(_tok_file, 0o600)
    except Exception:
        pass
except Exception:
    pass

# 静态目录(React构建产物)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIST = os.path.join(_BASE, "web", "static", "ui")
BG_DIR = os.path.join(_BASE, "assets")

router = APIRouter(prefix="/ui/api", tags=["ui"])


def _local_only(request: Request) -> bool:
    try:
        host = (request.client.host or "").split(":")[0]
        return host in ("127.0.0.1", "::1", "localhost")
    except Exception:
        return False


def _ok(data=None, msg=""):
    return JSONResponse({"code": 200, "msg": msg or "ok", "data": data})


def _err(msg, code=400):
    return JSONResponse({"code": code, "msg": str(msg)[:300], "data": None})


def _ok_svc(x=None, msg=""):
    """[V3.1.2] service 返回值适配:
    若 service 已返回完整响应 dict(含 code) 则直接透传(并归一 message->msg),
    否则包一层 _ok。修复"双层包裹"导致前端拿到 {code,message,data} 的 JSON 串问题。
    """
    if isinstance(x, dict) and "code" in x:
        if "msg" not in x and "message" in x:
            x["msg"] = x.get("message")
        return JSONResponse(x)
    return _ok(x, msg)


def _guard(request: Request):
    """本地+token双校验; 返回 None=通过 或 JSONResponse=拒绝"""
    if not _local_only(request):
        return _err(srv_msg("仅允许本机访问"), 403)
    tk = request.headers.get(
        "X-UI-Token", "") or request.query_params.get("token", "")
    if tk != UI_TOKEN:
        return _err("令牌无效", 401)
    return None


def _svc():
    from web.service import user_service
    return user_service


# ---------------- 账号 ----------------
@router.get("/ping")
def ui_ping(request: Request):
    g = _guard(request)
    if g:
        return g
    return _ok({"app": "yatori-ui", "ts": int(time.time())})


@router.get("/accounts")
def ui_accounts(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        data = _svc().user_list_service()
        accs = data.get("data") or data
        if isinstance(accs, dict):
            # user_list_service 返回 {code,message,data:{users:[...]}}
            accs = (accs.get("users") or accs.get("userList")
                    or accs.get("list") or [])
        # 附运行状态
        out = []
        for a in (accs or []):
            try:
                uid = str(a.get("uid", "") or a.get("account", ""))
                a2 = dict(a)
                a2["running"] = bool(_svc()._is_account_running(uid))
                # [2026-10-24] 附 platformType 与 coursesCustom(供GUI全字段编辑回填)
                try:
                    a2["platformType"] = (a2.get("accountType")
                                          or a2.get("account_type") or "")
                    _ucj = a2.get("userConfigJson") or "{}"
                    _uc = json.loads(_ucj) if isinstance(
                        _ucj, str) else (_ucj or {})
                    _cc = _uc.get("coursesCustom") or _uc.get(
                        "courses_custom") or {}
                    a2["coursesCustom"] = _cc if isinstance(_cc, dict) else {}
                    a2["informEmails"] = (_uc.get("informEmails")
                                          or a2.get("informEmails") or [])
                    a2["showdocSw"] = _uc.get(
                        "showdocSw", a2.get("showdocSw", 0))
                    a2["showdocUrls"] = (_uc.get("showdocUrls")
                                         or a2.get("showdocUrls") or [])
                    a2["isProxy"] = _uc.get("isProxy", a2.get("isProxy", 0))
                    # [V3.0.8] 备注名提升到顶层(GUI列表显示备注而非账号)
                    a2["remarkName"] = (_uc.get("remarkName")
                                        or a2.get("remarkName") or "")
                except Exception:
                    a2.setdefault("coursesCustom", {})
                out.append(a2)
            except Exception:
                out.append(a)
        return _ok(out)
    except Exception as e:
        return _err(e, 500)


def _norm_body_platform(body: dict) -> dict:
    # [V3.2.0] GUI 前端字段为 platformType, 后端 service 读 accountType;
    # 历史断链导致 GUI 新增账号平台写空(用户报错根因), 此处双向补齐
    if isinstance(body, dict):
        if not body.get("accountType") and body.get("platformType"):
            body["accountType"] = body["platformType"]
        if not body.get("platformType") and body.get("accountType"):
            body["platformType"] = body["accountType"]
    return body


@router.post("/account/add")
async def ui_add_account(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = _norm_body_platform(await request.json())
        return _ok_svc(_svc().add_user_service(body))
    except Exception as e:
        return _err(e, 500)


@router.post("/account/delete")
async def ui_del_account(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        return _ok_svc(_svc().delete_user_service(body))
    except Exception as e:
        return _err(e, 500)


@router.post("/account/update")
async def ui_upd_account(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = _norm_body_platform(await request.json())
        return _ok_svc(_svc().update_user_service(body))
    except Exception as e:
        return _err(e, 500)


@router.post("/account/logincheck")
async def ui_login_check(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        return _ok_svc(_svc().account_login_check_service(body))
    except Exception as e:
        return _err(e, 500)


# ---------------- 任务控制 ----------------
@router.post("/task/start")
async def ui_start(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        # [V3.2.5] 启动来源标记: 前端自报(GUI手动/Web前端手动/GUI批量/Web批量)
        # 或脚本显式传(批量/守护), 缺省=未标注; 附接口名+客户端IP 便于排查
        _src = str(body.get("source") or "未标注")[:16]
        _ip = request.client.host if request.client else ""
        return _ok_svc(_svc().start_brush_service(
            str(body.get("uid", "")), source=_src,
            meta={"iface": "/ui/api/task/start", "ip": _ip}))
    except Exception as e:
        return _err(e, 500)


@router.post("/task/stop")
async def ui_stop(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        return _ok_svc(_svc().stop_brush_service(str(body.get("uid", ""))))
    except Exception as e:
        return _err(e, 500)


@router.get("/task/status/{uid}")
def ui_status(request: Request, uid: str):
    g = _guard(request)
    if g:
        return g
    try:
        running = _svc()._is_account_running(uid)
        rt = {}
        try:
            from web.service import runtime_status as rts
            rt = rts.get(uid) or {}
        except Exception:
            pass
        return _ok({"running": running, "runtime": rt})
    except Exception as e:
        return _err(e, 500)


# ---------------- 课程进度 ----------------
@router.get("/courses/{uid}")
def ui_courses(request: Request, uid: str, force: int = 0):
    g = _guard(request)
    if g:
        return g
    try:
        return _ok_svc(_svc().account_course_list_service(uid, force_refresh=bool(force)))
    except Exception as e:
        return _err(e, 500)


@router.get("/rtstatus/{uid}")
def ui_rtstatus(request: Request, uid: str):
    g = _guard(request)
    if g:
        return g
    try:
        return _ok_svc(_svc().runtime_status_service(uid))
    except Exception as e:
        return _err(e, 500)


@router.get("/inform/{uid}")
def ui_inform(request: Request, uid: str):
    g = _guard(request)
    if g:
        return g
    try:
        return _ok_svc(_svc().get_account_inform_service(uid))
    except Exception as e:
        return _err(e, 500)


# ---------------- 日志 ----------------
@router.get("/logs/accounts")
def ui_log_accounts(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        return _ok_svc(_svc().log_accounts_service())
    except Exception as e:
        return _err(e, 500)


# ---------------- [V3.0.11] 多语言(运行时插拔语言包) ----------------
# 语言包目录: assets/i18n/{lang}.json (丢文件即支持新语种)
@router.get("/i18n/list")
def ui_i18n_list(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        import glob as _g
        out = []
        for p in _g.glob(os.path.join("assets", "i18n", "*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = (data or {}).get("_meta") or {}
                out.append({"lang": os.path.splitext(os.path.basename(p))[0],
                            "name": meta.get("name") or "",
                            "nativeName": meta.get("nativeName") or "",
                            "rtl": int(meta.get("rtl") or 0)})
            except Exception:
                continue
        out.sort(key=lambda x: x["lang"])
        return _ok(out)
    except Exception as e:
        return _err(e, 500)


@router.get("/i18n/{lang}")
def ui_i18n_get(request: Request, lang: str):
    g = _guard(request)
    if g:
        return g
    try:
        safe = str(lang).replace("/", "").replace("\\", "").replace("..", "")
        p = os.path.join("assets", "i18n", safe + ".json")
        if not os.path.exists(p):
            return _err(Exception("语言包不存在"), 404)
        with open(p, "r", encoding="utf-8") as f:
            return _ok(json.load(f))
    except Exception as e:
        return _err(e, 500)


@router.get("/logs/tail")
def ui_log_tail(request: Request, lines: int = 300, date: str = "",
                account: str = ""):
    g = _guard(request)
    if g:
        return g
    try:
        return _ok_svc(_svc().log_tail_service(lines=lines, date=date, account=account))
    except Exception as e:
        return _err(e, 500)


# ---------------- 全局配置 ----------------
def _cfg_ctrl():
    from web.controller import config_controller as cc
    return cc


@router.get("/setting")
def ui_get_setting(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        # [V3.0.8] 统一读 Entry: config.yaml 单一事实源(ConfigStore)
        from dao.config_store import ConfigStore
        return _ok(ConfigStore.instance().get_setting())
    except Exception as e:
        return _err(e, 500)


@router.post("/setting")
async def ui_save_setting(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        # [V3.0.8] 统一写 Entry: 经 ConfigStore 深合并+原子落盘
        # (避免与账号数据写入互相覆盖 config.yaml)
        # [V3.2.1] 落盘/热重载耗时操作放线程池, 避免阻塞事件循环(前端整站卡顿)
        from dao.config_store import ConfigStore
        await run_in_threadpool(ConfigStore.instance().update_setting, body)
        # 尝试热重载
        try:
            await run_in_threadpool(_svc().load_web_setting)
        except Exception:
            pass
        return _ok(msg="配置已保存并热重载")
    except Exception as e:
        return _err(e, 500)


# ---------------- 答题源(题库) ----------------
@router.get("/answersources")
def ui_answer_sources(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        # [V3.2.1] 读入口统一走 ConfigStore(单一事实源), 与写入保持一致
        from dao.config_store import ConfigStore
        st = ConfigStore.instance().get_setting() or {}
        ans = (st.get("answerSetting", {}) or {})
        return _ok({"sources": ans.get("sources", []),
                    "tokenCheck": ans.get("tokenCheck", 0),
                    "localCacheEnable": ans.get("localCacheEnable", 0),
                    "order": ans.get("order", ""),
                    "externalTokens": ans.get("externalTokens", {}),
                    "externalGetUrl": ans.get("externalGetUrl", "")})
    except Exception as e:
        return _err(e, 500)


@router.post("/answersources")
async def ui_save_answer_sources(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        ans = {}
        if "sources" in body:
            srcs = []
            for s in body.get("sources") or []:
                srcs.append({k: s.get(k, "") for k in
                             ("name", "type", "enable", "token",
                              "aiType", "model", "url")})
            ans["sources"] = srcs
        for k in ("tokenCheck", "localCacheEnable", "order"):
            if k in body:
                ans[k] = body[k]
        # [逆向适配] 外部题库13家 token + 「题库TOKEN获取地址」
        if isinstance(body.get("externalTokens"), dict):
            ans["externalTokens"] = {str(k): str(v)
                                     for k, v in body["externalTokens"].items() if v}
        if "externalGetUrl" in body:
            ans["externalGetUrl"] = str(body["externalGetUrl"] or "")
        # [V3.2.1] 统一写入口: 走 ConfigStore(内存+锁+原子写),
        # 不再直写文件(旧 cc._write_yaml 无锁非原子, 会与账号写入互相覆盖)
        from dao.config_store import ConfigStore
        await run_in_threadpool(
            ConfigStore.instance().update_setting,
            {"answerSetting": ans})
        try:
            await run_in_threadpool(_svc().load_web_setting)
        except Exception:
            pass
        return _ok(msg="答题源已保存")
    except Exception as e:
        return _err(e, 500)


# ---------------- 主题背景图(上传/读取) ----------------
@router.post("/bg/upload")
async def ui_bg_upload(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        b64 = str(body.get("dataUrl", ""))
        if "," not in b64:
            return _err("dataUrl无效")
        head, raw = b64.split(",", 1)
        ext = "png"
        if "jpeg" in head or "jpg" in head:
            ext = "jpg"
        elif "webp" in head:
            ext = "webp"
        os.makedirs(BG_DIR, exist_ok=True)
        import base64 as _b64
        raw_bytes = _b64.b64decode(raw)
        # [2026-10-24] Pillow优化: WebP统一编码(体积小兼容好) + 超宽1920缩放(加载性能)
        out_path = os.path.join(BG_DIR, "ui_bg.webp")
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(raw_bytes))
            img = img.convert("RGB")
            w, h = img.size
            if w > 1920:
                img = img.resize((1920, int(h * 1920 / w)), Image.LANCZOS)
            img.save(out_path, "WEBP", quality=86, method=4)
            # 清理旧格式残留
            for _ext in ("png", "jpg", "jpeg"):
                _old = os.path.join(BG_DIR, f"ui_bg.{_ext}")
                if os.path.isfile(_old):
                    try:
                        os.remove(_old)
                    except Exception:
                        pass
            return _ok({"path": f"/ui/api/bg/file?v={int(time.time())}",
                        "format": "webp"})
        except Exception:
            # Pillow失败则原样保存(兼容兜底)
            p = os.path.join(BG_DIR, f"ui_bg.{ext}")
            with open(p, "wb") as f:
                f.write(raw_bytes)
            return _ok({"path": f"/ui/api/bg/file?v={int(time.time())}"})
    except Exception as e:
        return _err(e, 500)


@router.get("/bg/file")
def ui_bg_file(request: Request):
    g = _guard(request)
    if g:
        return g
    for ext in ("webp", "png", "jpg", "jpeg"):
        p = os.path.join(BG_DIR, f"ui_bg.{ext}")
        if os.path.isfile(p):
            return FileResponse(p)
    return _err("无背景图", 404)


# ---------------- [赞助/赞赏] 微信赞赏码(GUI 开屏横幅 + 赞赏码展示 + 配置) ----------------
SPONSOR_QR_NAME = "微信赞赏码.png"


def _sponsor_bases():
    """赞赏码候选目录: BG_DIR > _MEIPASS/assets(内置) > exe目录/assets > cwd/assets"""
    bases = [BG_DIR]
    try:
        import sys as _sys
        _mp = getattr(_sys, "_MEIPASS", "")
        if _mp:
            bases.append(os.path.join(_mp, "assets"))
        bases.append(os.path.join(os.path.dirname(
            os.path.abspath(_sys.executable)), "assets"))
    except Exception:
        pass
    try:
        bases.append(os.path.join(os.getcwd(), "assets"))
    except Exception:
        pass
    return bases


def _sponsor_qr_path():
    """赞赏码路径: 优先用户上传 ui_sponsor_qr.*, 否则内置微信赞赏码(含 exe 内置 _MEIPASS)"""
    bases = _sponsor_bases()
    for b in bases:
        for ext in ("webp", "png", "jpg", "jpeg"):
            p = os.path.join(b, f"ui_sponsor_qr.{ext}")
            if os.path.isfile(p):
                return p
    for b in bases:
        p = os.path.join(b, SPONSOR_QR_NAME)
        if os.path.isfile(p):
            return p
    return ""


@router.get("/sponsor")
def ui_sponsor_info(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        from dao.config_store import ConfigStore
        st = ConfigStore.instance().get_setting() or {}
        bsset = st.get("basicSetting", st.get("basic_setting", {})) or {}
        sw = int(bsset.get("sponsorSw", bsset.get("sponsor_sw", 1)) or 0)
        text = str(bsset.get("sponsorText", bsset.get("sponsor_text", "")) or "")
        p = _sponsor_qr_path()
        return _ok({"enabled": sw == 1, "text": text, "hasQr": bool(p),
                    "qrUrl": ("/ui/api/sponsor/qr?v=%d" % int(time.time())) if p else ""})
    except Exception as e:
        return _err(e, 500)


@router.get("/sponsor/qr")
def ui_sponsor_qr(request: Request):
    g = _guard(request)
    if g:
        return g
    p = _sponsor_qr_path()
    if p:
        return FileResponse(p)
    return _err("无赞赏码", 404)


@router.post("/sponsor/qr")
async def ui_sponsor_qr_upload(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        b64 = str(body.get("dataUrl", ""))
        if "," not in b64:
            return _err("dataUrl无效")
        _head, raw = b64.split(",", 1)
        import base64 as _b64
        raw_bytes = _b64.b64decode(raw)
        os.makedirs(BG_DIR, exist_ok=True)
        out_path = os.path.join(BG_DIR, "ui_sponsor_qr.webp")
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(raw_bytes)).convert("RGB")
            img.save(out_path, "WEBP", quality=90, method=4)
            for _ext in ("png", "jpg", "jpeg"):
                _old = os.path.join(BG_DIR, f"ui_sponsor_qr.{_ext}")
                if os.path.isfile(_old):
                    try:
                        os.remove(_old)
                    except Exception:
                        pass
        except Exception:
            with open(os.path.join(BG_DIR, "ui_sponsor_qr.png"), "wb") as f:
                f.write(raw_bytes)
        return _ok({"path": "/ui/api/sponsor/qr?v=%d" % int(time.time())})
    except Exception as e:
        return _err(e, 500)


# ---------------- 公告/版本 ----------------
@router.get("/about")
def ui_about(request: Request):
    g = _guard(request)
    if g:
        return g
    ver = "?"
    try:
        from web.server import APP_VERSION as _v
        ver = _v
    except Exception:
        pass
    ann = ""
    try:
        cand = os.path.join(_BASE, "assets", "announcement.txt")
        if os.path.isfile(cand):
            ann = io.open(cand, encoding="utf-8",
                          errors="ignore").read()[:4000]
    except Exception:
        pass
    return _ok({"version": ver, "announcement": ann})


# ---------------- [V3.2.2] 通知测试(飞书) ----------------
@router.post("/notify/feishu/test")
async def ui_feishu_test(request: Request):
    g = _guard(request)
    if g:
        return g
    try:
        body = await request.json()
        wh = str(body.get("webhook", "") or "").strip()
        sec = str(body.get("secret", "") or "").strip()
        if not wh:
            return _err("webhook 不能为空")
        from utils.feishu_utils import send_feishu
        ok = await run_in_threadpool(
            send_feishu, wh, "Yatori 通知自检",
            "这是一条测试消息，收到即配置成功。", sec)
        return _ok({"ok": bool(ok)},
                   msg="测试消息已发送" if ok else "发送失败(请检查地址/密钥)")
    except Exception as e:
        return _err(e, 500)


# ---------------- 静态页面(React dist) ----------------
def mount_ui(app):
    """挂载 /ui 静态资源(SPA: 任意路径回退index.html)
    注意: /ui/api 路由必须先注册, 否则会被SPA通配路由吞掉(返回index.html)"""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    # 先注册API桥路由(优先匹配)
    app.include_router(router)

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/{full_path:path}", include_in_schema=False)
    def _ui_index(full_path: str = ""):
        if full_path.startswith("api/"):
            return JSONResponse({"code": 404, "msg": "unknown ui api"}, status_code=404)
        idx = os.path.join(UI_DIST, "index.html")
        if not os.path.isfile(idx):
            return HTMLResponse(
                "<h1>Yatori UI 尚未构建</h1><p>请先执行 web-ui 目录 "
                "npm run build 并复制 dist 到 web/static/ui</p>",
                status_code=200)
        # 优先返回静态文件, 否则SPA回退
        if full_path:
            fp = os.path.join(UI_DIST, full_path)
            if os.path.isfile(fp):
                return FileResponse(fp)
            # assets 子路径
            fp2 = os.path.join(UI_DIST, "assets", full_path)
            if os.path.isfile(fp2):
                return FileResponse(fp2)
        return FileResponse(idx)
