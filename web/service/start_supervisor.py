# -*- coding: utf-8 -*-
"""[V3.2.5] 账号启动监督器(自动启动来源的实现与打点)。

职责: 在"启动来源"统一收口函数 start_brush_service 之上, 提供自动启动机制,
并让每一次自动启动都带上明确来源标签, 便于与手动启动区分排查。

已实现机制(均经 start_brush_service 触发, 日志自动带 [启动来源: X]):
  1) 守护自动重启 : 刷课线程异常崩溃(非正常完成/非用户停止)后自动拉起
  2) 巡检自动恢复 : 巡检发现"期望运行却掉线"时自动恢复
  3) 定时任务     : 到达 assets/state/auto_schedule.json 中的定时时刻
  4) 服务重启拉起 : 进程重启后自动恢复上次处于运行(期望)状态的账号

安全语义(关键, 防止"刷完还无限重启"):
  · 正常完成 / 用户主动停止  -> 清除"期望运行", 绝不重启
  · 仅"异常崩溃"或"掉线"     -> 进入自动恢复, 且带指数退避 + 有界重试, 超限放弃
  · 手动/API/脚本启动         -> 标记为"期望运行", 使崩溃后能被守护重启

期望运行状态持久化到 assets/state/desired_run.json, 供开机拉起使用。
所有自动触发均写日志并打 [启动来源] 标签; 可用 grep "启动来源" 过滤。
"""
import json
import os
import threading
import time
from typing import Dict, Optional

from web.service import start_source as S

_LOCK = threading.Lock()
_RECS: Dict[str, dict] = {}          # uid -> rec
_FIRED: Dict[str, str] = {}          # schedule 去重: f"{uid}|{at}" -> date
_STARTED = False
_THREAD: Optional[threading.Thread] = None
_BOOT_DONE = False

_STATE_DIR = os.path.join("assets", "state")
_STATE_FILE = os.path.join(_STATE_DIR, "desired_run.json")
_SCHEDULE_FILE = os.path.join(_STATE_DIR, "auto_schedule.json")

# ---- 配置默认(与 config.BasicSetting 对应; 读不到时回退这里) ----
_DEF_FLAGS = {
    "master": True,       # auto_supervisor_sw 总开关
    "restart": True,      # auto_restart_sw 守护自动重启
    "patrol": True,       # patrol_recover_sw 巡检自动恢复
    "boot": True,         # boot_relaunch_sw 服务重启拉起
    "interval": 60,       # patrol_interval_sec 巡检周期(秒)
    "max_retry": 6,       # auto_start_retry_max 单账号连续自动重启上限
}


# ============ 期望运行状态读写 ============

def _ensure_dir():
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
    except Exception:
        pass


def _load():
    """启动时从磁盘恢复"期望运行"集合。"""
    try:
        if not os.path.exists(_STATE_FILE):
            return
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                uid = str(it.get("uid") or "")
                if not uid:
                    continue
                _RECS[uid] = {
                    "uid": uid,
                    "account": str(it.get("account") or ""),
                    "desired": bool(it.get("desired", True)),
                    "source": str(it.get("source") or ""),
                    "retries": 0,
                    "next_ts": 0.0,
                    "last_crash": False,
                    "updated": time.time(),
                }
    except Exception:
        pass


def _save():
    """持久化"期望运行"集合(只存 desired=True 的, 其余自动清洗)。"""
    try:
        _ensure_dir()
        out = []
        for r in _RECS.values():
            if r.get("desired"):
                out.append({"uid": r["uid"], "account": r.get("account", ""),
                            "desired": True, "source": r.get("source", "")})
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _STATE_FILE)
    except Exception:
        pass


# ============ 对外: 标记期望态 ============

def mark_desired(uid: str, account: str, source: str):
    """标记账号为"期望运行"。手动/API/脚本启动成功后调用。

    自动来源(守护/巡检/定时/开机)不会重置重试计数, 避免退避失效。
    """
    uid = str(uid or "").strip()
    if not uid:
        return
    with _LOCK:
        rec = _RECS.get(uid)
        if rec is None:
            rec = {"uid": uid, "account": str(account or ""),
                   "desired": True, "source": source, "retries": 0,
                   "next_ts": 0.0, "last_crash": False,
                   "updated": time.time()}
            _RECS[uid] = rec
        rec["desired"] = True
        rec["account"] = str(account or rec.get("account") or "")
        rec["source"] = source
        rec["last_crash"] = False
        if not S.is_auto(source):
            # 手动启动: 视为一次全新会话, 重置重试与退避
            rec["retries"] = 0
            rec["next_ts"] = 0.0
        rec["updated"] = time.time()
        _save()


def mark_undesired(uid: str = "", account: str = ""):
    """清除"期望运行"(用户主动停止 / 任务正常完成)。"""
    uid = str(uid or "").strip()
    account = str(account or "").strip()
    with _LOCK:
        targets = []
        if uid and uid in _RECS:
            targets.append(uid)
        elif account:
            for u, r in _RECS.items():
                if r.get("account") == account:
                    targets.append(u)
        for u in targets:
            _RECS[u]["desired"] = False
            _RECS[u]["updated"] = time.time()
        if targets:
            _save()


def on_exit(uid: str, account: str, crashed: bool):
    """刷课线程结束回调(由各 Activity._brush_loop 的 finally 调用)。

    :param crashed: True=异常崩溃(可自动重启); False=正常完成/用户停止(清除期望)
    """
    uid = str(uid or "").strip()
    account = str(account or "").strip()
    if not uid:
        return
    with _LOCK:
        rec = _RECS.get(uid)
        if rec is None:
            return
        if crashed and rec.get("desired"):
            # 仅"期望运行"账号在崩溃时才安排重启; 退避由巡检触发时统一计算
            rec["last_crash"] = True
            rec["next_ts"] = 0.0  # 立即进入下一次巡检判定
            rec["updated"] = time.time()
        else:
            # 正常完成或用户停止 -> 不再自动拉起
            rec["desired"] = False
            rec["updated"] = time.time()
        _save()


# ============ 配置读取 ============

def _flags() -> dict:
    """从程序目录 config.yaml 轻量读取自动启动相关开关(容错)。"""
    f = dict(_DEF_FLAGS)
    try:
        if os.path.exists("./config.yaml"):
            import yaml
            with open("./config.yaml", "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            st = (data.get("setting") or {})
            bs = st.get("basicSetting") or st.get("basic_setting") or {}
            if isinstance(bs, dict):
                def _gi(*keys, dflt):
                    for k in keys:
                        if k in bs and bs[k] is not None:
                            try:
                                return int(bs[k])
                            except Exception:
                                return dflt
                    return dflt
                f["master"] = _gi("autoSupervisorSw", "auto_supervisor_sw",
                                  dflt=1) == 1
                f["restart"] = _gi(
                    "autoRestartSw", "auto_restart_sw", dflt=1) == 1
                f["patrol"] = _gi("patrolRecoverSw", "patrol_recover_sw",
                                  dflt=1) == 1
                f["boot"] = _gi("bootRelaunchSw",
                                "boot_relaunch_sw", dflt=1) == 1
                f["interval"] = max(10, _gi("patrolIntervalSec", "patrol_interval_sec",
                                            dflt=60))
                f["max_retry"] = max(1, _gi("autoStartRetryMax", "auto_start_retry_max",
                                            dflt=6))
    except Exception:
        pass
    return f


# ============ 执行一次启动(经统一收口) ============

def _safe_start(uid: str, account: str, source: str):
    """调用 start_brush_service 触发一次启动; 返回 (ok, msg)。"""
    try:
        from web.service import user_service as US
        r = US.start_brush_service(uid, source=source)
        code = (r or {}).get("code")
        return (code == 200, str((r or {}).get("message") or (r or {}).get("msg") or ""))
    except Exception as e:
        return (False, "启动异常: %s" % e)


def _backoff(retries: int) -> float:
    """指数退避(秒): 15,30,60,120,240,480 上限 600。"""
    return float(min(600, 15 * (2 ** min(max(0, retries - 1), 5))))


def _is_running(uid: str) -> bool:
    try:
        from web.service.user_service import _is_account_running
        return bool(_is_account_running(uid))
    except Exception:
        return False


# ============ 定时任务 ============

def _load_schedule() -> list:
    try:
        if os.path.exists(_SCHEDULE_FILE):
            with open(_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, list):
                return [x for x in d if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _tick_schedule(flags: dict):
    """到点触发定时启动(每天每个时刻只触发一次)。"""
    sch = _load_schedule()
    if not sch:
        return
    now = time.localtime()
    hm = "%02d:%02d" % (now.tm_hour, now.tm_min)
    today = "%04d-%02d-%02d" % (now.tm_year, now.tm_mon, now.tm_mday)
    wd = now.tm_wday + 1  # 1=周一
    for it in sch:
        if not it.get("enabled", True):
            continue
        if str(it.get("at", "")) != hm:
            continue
        days = it.get("days")
        if isinstance(days, list) and days and wd not in days:
            continue
        uid = str(it.get("uid") or "")
        account = str(it.get("account") or "")
        if not uid and account:
            uid = _uid_by_account(account)
        if not uid:
            continue
        key = "%s|%s" % (uid, hm)
        if _FIRED.get(key) == today:
            continue
        _FIRED[key] = today
        ok, msg = _safe_start(uid, account, S.SRC_SCHEDULE)
        _log("[定时任务] 定时启动 %s -> %s %s" %
             (account or uid, "成功" if ok else "失败", "" if ok else msg))


def _uid_by_account(account: str) -> str:
    try:
        from web.dao import user_mapper
        from web.dao.db import get_session  # type: ignore
    except Exception:
        pass
    try:
        from web.service.user_service import get_session, user_mapper  # type: ignore
        s = get_session()
        try:
            u = user_mapper.query_user(s, account=account)
            return str(getattr(u, "uid", "") or "") if u else ""
        finally:
            s.close()
    except Exception:
        return ""


# ============ 主循环 ============

def _log(msg: str):
    try:
        from utils.log import log_print, INFO, Yellow
        log_print(INFO, "[监督器]", Yellow, msg)
    except Exception:
        pass


def _tick():
    flags = _flags()
    if not flags["master"]:
        return
    # 定时任务
    try:
        _tick_schedule(flags)
    except Exception:
        pass

    # 巡检 / 守护重启
    now = time.time()
    to_act = []
    with _LOCK:
        for uid, rec in _RECS.items():
            if not rec.get("desired"):
                continue
            if _is_running(uid):
                # 心跳: 正常运行, 重置重试计数
                rec["retries"] = 0
                rec["next_ts"] = 0.0
                rec["last_crash"] = False
                continue
            if now < rec.get("next_ts", 0):
                continue
            # 判定来源: 崩溃走守护重启(需 restart 开), 掉线走巡检恢复(需 patrol 开)
            if rec.get("last_crash"):
                if not flags["restart"]:
                    continue
                src = S.SRC_DAEMON_RESTART
            else:
                if not flags["patrol"]:
                    continue
                src = S.SRC_PATROL
            if rec.get("retries", 0) >= flags["max_retry"]:
                rec["desired"] = False
                rec["updated"] = now
                to_act.append((uid, rec.get("account", ""), None,
                               "放弃(连续%d次自动启动失败)" % rec.get("retries", 0)))
                continue
            rec["retries"] = rec.get("retries", 0) + 1
            rec["next_ts"] = now + _backoff(rec["retries"])
            rec["updated"] = now
            to_act.append((uid, rec.get("account", ""), src, None))
        if any(a[2] is None for a in to_act):
            _save()

    for uid, account, src, giveup in to_act:
        if giveup:
            _log("[自动恢复放弃] %s %s" % (account or uid, giveup))
            continue
        ok, msg = _safe_start(uid, account, src)
        _log("[%s] 自动拉起 %s -> %s %s" %
             (src, account or uid, "成功" if ok else "失败", "" if ok else msg))


def _loop():
    # 首轮稍等, 让主服务/DB/配置就绪
    time.sleep(8)
    while True:
        try:
            _tick()
        except Exception as e:
            _log("巡检tick异常: %s" % e)
        # 用较短基准睡, 但实睡眠按配置 interval(下一次循环再读, 便于即时改配置)
        try:
            interval = _flags().get("interval", 60)
        except Exception:
            interval = 60
        time.sleep(max(10, int(interval)))


# ============ 启动入口 ============

def ensure_started():
    """启动监督线程(幂等)。在 GUI / Web 服务就绪后调用。"""
    global _STARTED, _THREAD
    if _STARTED:
        return
    if not _flags()["master"]:
        _log("自动启动监督器未启用(配置 auto_supervisor_sw=0), 跳过")
        return
    with _LOCK:
        _load()
    _STARTED = True
    _THREAD = threading.Thread(
        target=_loop, name="start-supervisor", daemon=True)
    _THREAD.start()
    _log("自动启动监督器已启动(守护重启/巡检恢复/定时/开机拉起)")


def boot_relaunch():
    """服务重启后自动拉起上次"期望运行"的账号(来源: 服务重启拉起)。"""
    global _BOOT_DONE
    if _BOOT_DONE:
        return
    _BOOT_DONE = True
    flags = _flags()
    if not (flags["master"] and flags["boot"]):
        return
    with _LOCK:
        if not _RECS:
            _load()
        targets = [(u, r.get("account", "")) for u, r in _RECS.items()
                   if r.get("desired")]
    if not targets:
        return
    _log("[服务重启拉起] 待恢复 %d 个账号" % len(targets))

    def _worker():
        # 2026-10-30 风控加固: 原错峰 1.5s/账号(87个号≈2分钟全部上线),
        # 多账号同IP下等于瞬时登录风暴; 现按 YATORI_BOOT_STAGGER_SEC
        # 默认 10s/账号拉开(87个号≈15分钟分批上线, 可设小恢复旧行为)
        _gap = 10.0
        try:
            _gap = max(1.5, float(os.environ.get(
                "YATORI_BOOT_STAGGER_SEC", "10")))
        except (TypeError, ValueError):
            pass
        for i, (uid, account) in enumerate(targets):
            time.sleep(2 + i * _gap)  # 错峰, 避免瞬时登录风暴
            ok, msg = _safe_start(uid, account, S.SRC_BOOT)
            _log("[服务重启拉起] %s -> %s %s" %
                 (account or uid, "成功" if ok else "失败", "" if ok else msg))

    threading.Thread(target=_worker, name="boot-relaunch", daemon=True).start()
