# -*- coding: utf-8 -*-
"""
配置控制器 - 后端基础设置读写 + 在线测试
  GET  /configGet   读取可编辑设置(已排除 webModel/webPort/webSecret/webSsl* 等 web 相关项)
  POST /configSave  白名单写入 config.yaml, 并热更新(无需重启)
  POST /sourceTest  答题源真实查询测试(题库/AI 通用)
  POST /emailTest   邮件发送测试
"""
import os
import re
import time

import yaml
from fastapi import APIRouter, Request

from entity.vo import Response

router = APIRouter()

CONFIG_PATH = "./config.yaml"

# 允许前端编辑的基础设置白名单(排除 web 相关: webModel/webPort/webSecret/webSsl/webSslCert/webSslKey/autoOpenBrowser 不在内)
BASIC_KEYS = [
    "completionTone", "colorLog", "logOutFileSw", "logLevel", "logModel",
    "ocrImageQuestion", "noticePrefix", "browserPath", "cdpHost", "cdpPort",
    "fullCpuMode", "performanceGear",
    # 2026-10-23修复: 后加字段漏白名单导致前端保存被静默丢弃
    #   (studyCountCap关闭后仍按30跑 / dzyxBaseUrl无法保存)
    "dzyxBaseUrl", "studyCountCap",
]
EMAIL_KEYS = ["sw", "SMTPHost", "SMTPPort", "userName", "password"]
AI_KEYS = ["aiType", "aiUrl", "model", "API_KEY"]
SHOWDOC_KEYS = ["sw", "url"]
APIQUE_KEYS = ["url"]
# 答题源支持的键
SOURCE_KEYS = ["name", "type", "enable", "token", "aiType", "model", "url"]
ANSWER_META_KEYS = ["tokenCheck",
                    "localCacheEnable", "localCachePath", "order"]


def _read_yaml() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _write_yaml(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False,
                       default_flow_style=False)


def _pick(d: dict, keys: list) -> dict:
    out = {}
    for k in keys:
        if isinstance(d, dict) and k in d:
            out[k] = d[k]
    return out


# 需要强制转 int 的字段(避免前端字符串写入 yaml 后影响运行时解析)
_INT_BASIC = {"completionTone", "colorLog", "logOutFileSw", "logModel",
              "ocrImageQuestion", "cdpPort", "studyCountCap"}
_INT_EMAIL = {"sw", "SMTPPort"}
_INT_META = {"tokenCheck", "localCacheEnable"}


def _to_int(v):
    """宽松转 int: '1'/'0'/1/True/'' 等统一转换, 失败回退 0"""
    if isinstance(v, bool):
        return 1 if v else 0
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


@router.get("/configGet")
async def config_get():
    """读取当前后端设置(供前端配置页回显)"""
    data = _read_yaml()
    st = data.get("setting", {}) or {}
    ans = st.get("answerSetting", {}) or {}
    out = {
        "basicSetting": _pick(st.get("basicSetting", {}) or {}, BASIC_KEYS),
        "emailInform": _pick(st.get("emailInform", {}) or {}, EMAIL_KEYS),
        "aiSetting": _pick(st.get("aiSetting", {}) or {}, AI_KEYS),
        "showdocInform": _pick(st.get("showdocInform", {}) or {}, SHOWDOC_KEYS),
        "apiQueSetting": _pick(st.get("apiQueSetting", {}) or {}, APIQUE_KEYS),
        "answerSetting": {
            **_pick(ans, ANSWER_META_KEYS),
            "sources": [
                _pick(s, SOURCE_KEYS) for s in (ans.get("sources") or [])
                if isinstance(s, dict)
            ],
        },
    }
    return Response(code=200, message="读取配置成功", data=out).to_dict()


@router.post("/configSave")
async def config_save(request: Request):
    """白名单保存配置(仅写回被允许的键, 不动 users/其他段), 保存后热更新"""
    body = await request.json()
    if not isinstance(body, dict):
        return Response(code=400, message="参数错误").to_dict()

    data = _read_yaml()
    st = data.setdefault("setting", {})

    # 基础设置
    saved_blocks = []
    if isinstance(body.get("basicSetting"), dict):
        bs = st.setdefault("basicSetting", {})
        for k in BASIC_KEYS:
            if k in body["basicSetting"]:
                v = body["basicSetting"][k]
                bs[k] = _to_int(v) if k in _INT_BASIC else v
        saved_blocks.append("basicSetting")
    # 邮件
    if isinstance(body.get("emailInform"), dict):
        ei = st.setdefault("emailInform", {})
        for k in EMAIL_KEYS:
            if k in body["emailInform"]:
                v = body["emailInform"][k]
                ei[k] = _to_int(v) if k in _INT_EMAIL else (
                    str(v) if k != "sw" else v)
        saved_blocks.append("emailInform")
    # AI(旧版单AI兼容段)
    if isinstance(body.get("aiSetting"), dict):
        ai = st.setdefault("aiSetting", {})
        for k in AI_KEYS:
            if k in body["aiSetting"]:
                ai[k] = str(body["aiSetting"][k])
        saved_blocks.append("aiSetting")
    # ShowDoc
    if isinstance(body.get("showdocInform"), dict):
        sd = st.setdefault("showdocInform", {})
        for k in SHOWDOC_KEYS:
            if k in body["showdocInform"]:
                v = body["showdocInform"][k]
                sd[k] = _to_int(v) if k == "sw" else str(v)
        saved_blocks.append("showdocInform")
    # 外部题库地址
    if isinstance(body.get("apiQueSetting"), dict):
        aq = st.setdefault("apiQueSetting", {})
        for k in APIQUE_KEYS:
            if k in body["apiQueSetting"]:
                aq[k] = str(body["apiQueSetting"][k])
        saved_blocks.append("apiQueSetting")
    # 多答题源
    if isinstance(body.get("answerSetting"), dict):
        a = st.setdefault("answerSetting", {})
        src = body["answerSetting"]
        for k in ANSWER_META_KEYS:
            if k in src:
                v = src[k]
                if k in _INT_META:
                    a[k] = _to_int(v)
                elif k == "order":
                    # 允许前端传逗号分隔字符串, 统一转列表落盘
                    if isinstance(v, str):
                        a[k] = [p.strip() for p in
                                re.split(r"[,，;；\n]+", v) if p.strip()]
                    elif isinstance(v, list):
                        a[k] = [str(p).strip() for p in v
                                if str(p or "").strip()]
                    else:
                        a[k] = v
                else:
                    a[k] = v
        if isinstance(src.get("sources"), list):
            cleaned = []
            for s in src["sources"]:
                if not isinstance(s, dict):
                    continue
                item = _pick(s, SOURCE_KEYS)
                if "enable" in item:
                    item["enable"] = _to_int(item["enable"])
                for sk in ("name", "type", "token", "aiType", "model", "url"):
                    if sk in item:
                        item[sk] = str(item[sk] or "").strip()
                cleaned.append(item)
            a["sources"] = cleaned
        saved_blocks.append("answerSetting")

    try:
        _write_yaml(data)
    except Exception as e:
        return Response(code=500, message=f"写入 config.yaml 失败: {e}").to_dict()

    # 热更新: 重新读取并注入答题引擎(与启动刷课同一通道, 无需重启)
    hot = "ok"
    try:
        from web.service.user_service import load_web_setting
        load_web_setting()
    except Exception as e:
        hot = f"配置已保存, 但热更新异常(重启后生效): {e}"
    return Response(code=200, message=f"已保存并实时生效({hot})",
                    data={"saved": saved_blocks, "hot": hot}).to_dict()


@router.post("/sourceTest")
async def source_test(request: Request):
    """答题源真实查询测试: 用一道固定题真实调用该源, 返回答案与耗时"""
    body = await request.json()
    if not isinstance(body, dict) or not body.get("type"):
        return Response(code=400, message="缺少答题源类型(type)").to_dict()

    s_type = str(body.get("type", "")).strip()
    name = str(body.get("name", "") or "").strip() or s_type
    token = str(body.get("token", "") or "").strip()
    url = str(body.get("url", "") or "").strip()
    model = str(body.get("model", "") or "").strip()
    ai_type = str(body.get("aiType", "") or "").strip()

    if s_type != "local" and not token:
        return Response(code=400, message="未填写 token, 无法测试").to_dict()

    try:
        from logic.core.answer_engine import AnswerSource
        src = AnswerSource(name=name, s_type=s_type, enable=1, token=token,
                           ai_type=ai_type, model=model, url=url)
        t0 = time.time()
        ans = src.query("中国历史上第一个统一的多民族封建国家是哪一个?",
                        ["A.夏朝", "B.商朝", "C.秦朝", "D.汉朝"], "单选题")
        dt = round(time.time() - t0, 2)
        if ans:
            return Response(code=200, message=f"测试通过, 耗时 {dt}s",
                            data={"answer": ans, "elapsed": dt}).to_dict()
        # 本地题库缓存: 无 token 概念, 查不到仅说明测试题不在缓存中
        if s_type == "local":
            cache_file = url or "questions_answers.json"
            exists = os.path.exists(cache_file)
            return Response(
                code=200,
                message=f"本地题库缓存正常({'缓存文件存在' if exists else '缓存文件尚未生成(首次答题后自动创建)'})"
                f"；测试题不在缓存中(属正常现象, 不影响刷课)",
                data={"answer": "", "elapsed": dt}).to_dict()
        # 无答案: 补一次 token/接口自检区分“连接正常但未收录”与“真失败”
        ok, msg = src.check()
        # 限流类失败(如 EveryAPI 滚动窗口)等待后重试一次
        if not ok and any(k in str(msg) for k in
                          ("太快", "并发", "限流", "429")):
            time.sleep(1.5)
            ok, msg = src.check()
        if ok:
            # 自检通过 = 源可正常连通使用; 未命中仅因测试题未被收录,
            # 不应按失败展示(刷课时会自动回退下一个源)
            return Response(
                code=200,
                message=f"连接正常({msg})；测试题未被该源收录"
                f"(属正常现象, 不影响刷课), 耗时 {dt}s",
                data={"answer": "", "elapsed": dt}).to_dict()
        return Response(code=400,
                        message=f"测试未通过, 耗时 {dt}s; 自检失败: {msg}",
                        data={"answer": "", "elapsed": dt}).to_dict()
    except Exception as e:
        return Response(code=400, message=f"测试异常: {e}").to_dict()


@router.post("/emailTest")
async def email_test(request: Request):
    """邮件发送测试(使用请求中的临时配置, 测完不影响已保存配置)"""
    body = await request.json()
    if not isinstance(body, dict):
        return Response(code=400, message="参数错误").to_dict()
    to = str(body.get("to", "") or "").strip()
    if not to:
        return Response(code=400, message="缺少收件地址(to)").to_dict()
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        host = str(body.get("SMTPHost", "") or "").strip()
        port = int(body.get("SMTPPort", 465) or 465)
        user = str(body.get("userName", "") or "").strip()
        pwd = str(body.get("password", "") or "")
        if not host or not user or not pwd:
            return Response(code=400, message="SMTP 配置不完整").to_dict()
        t0 = time.time()
        msg = MIMEText("这是一封来自 Yatori 的测试邮件, 收到即表示 SMTP 配置正确。",
                       "plain", "utf-8")
        msg["Subject"] = Header("Yatori 邮件测试", "utf-8")
        msg["From"] = user
        msg["To"] = to
        if port == 465:
            srv = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            srv = smtplib.SMTP(host, port, timeout=15)
            try:
                srv.starttls()
            except Exception:
                pass
        srv.login(user, pwd)
        srv.sendmail(user, [x.strip()
                     for x in to.split(",") if x.strip()], msg.as_string())
        srv.quit()
        dt = round(time.time() - t0, 2)
        return Response(code=200, message=f"测试邮件已发送({dt}s), 请查收").to_dict()
    except Exception as e:
        return Response(code=400, message=f"发送失败: {e}").to_dict()
