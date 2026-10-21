# -*- coding: utf-8 -*-
"""大众云学(yxlearning)平台主模块(2026-10-22 逆向+适配)

路线: 浏览器自动化(playwright 系统Chrome) + 只读接口纯协议。
视频为百家云 ev1 加密流(wasm 浏览器内解密), 进度由百家云服务端回调平台,
故自动化只需保证真实播放+页面存活+弹题隐藏(与参照油猴脚本同思路)。

平台接口契约(对齐 launcher/brush_block):
  filter_account / user_login_operation / run_brush_operation / web_course_list
"""
import json
import random
import threading
import time
from typing import List, Optional

from config.config import User, Setting, JSONDataForConfig
from utils.log import log_print, INFO, Green, Red, Yellow, Default, Purple

from logic.dazhongyunxue import api as dzyx_api
from logic.dazhongyunxue import slider as dzyx_slider

PLATFORM_KEY = "DZYX"


class DzyxCache:
    """登录态缓存(对齐其他平台 cache 对象用法)"""

    def __init__(self, account: str, password: str, base: str,
                 cookies: dict, state: dict):
        self.account = account
        self.password = password
        self.base = base
        self.cookie_dict = cookies or {}
        self.state = state or {}
        self.client = dzyx_api.DzyxClient(base, self.cookie_dict)


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return [u for u in (config_data.users or [])
            if (u.account_type or "").upper() == PLATFORM_KEY]


def _log_f(user: User):
    acct = str(getattr(user, "account", ""))

    def _f(msg):
        log_print(INFO, "[大众云学]", "[", Green, acct, Default, "] ",
                  Yellow, str(msg))
    return _f


# ================= 登录 =================

def _playwright_login(user: User, base: str, headless: bool, log) -> Optional[dict]:
    """滑块登录(实测链: 填表→登录→滑块→拖→完成→再登录)"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"playwright 不可用: {e}")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, channel="chrome")
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                ignore_https_errors=True)
            page = ctx.new_page()
            page.goto(base + "/login", timeout=60000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            acc = page.query_selector('input[name="account"]')
            pwd = page.query_selector('input[name="password"]')
            if not acc or not pwd:
                log("登录页结构异常(无账号/密码框)")
                browser.close()
                return None
            acc.fill(str(user.account))
            pwd.fill(str(getattr(user.courses_custom, "password", "")
                         or user.password or ""))
            for _ in range(6):
                page.evaluate("""() => {
                    const b = Array.from(document.querySelectorAll('button'))
                        .find(e => (e.textContent||'').trim() === '登录'
                                   && e.offsetParent !== null);
                    if (b) b.click();
                }""")
                page.wait_for_timeout(3000)
                if "login" not in page.url:
                    break
                if not dzyx_slider.solve_slider(page, log):
                    continue
                page.wait_for_timeout(1500)
            ok = "login" not in page.url
            state = ctx.storage_state() if ok else None
            browser.close()
            if ok:
                log("登录成功(滑块已通过)")
                return state
            log("登录失败(滑块或账密)")
            return None
    except Exception as e:
        log(f"登录异常: {str(e)[:80]}")
        return None


def user_login_operation(users: List[User]) -> List[DzyxCache]:
    caches: List[DzyxCache] = []
    for u in users:
        log = _log_f(u)
        base = dzyx_api.resolve_base()
        state = dzyx_api.load_state(u.account)
        cookies = dzyx_api.cookies_from_state(state) if state else {}
        cache = DzyxCache(u.account, getattr(u, "password", ""), base,
                          cookies, state)
        # 校验登录态有效性
        valid = False
        if cookies:
            try:
                lst = cache.client.study_list()
                valid = isinstance(lst, list)
            except Exception:
                valid = False
        if not valid:
            headless = _headless_flag()
            state = _playwright_login(u, base, headless, log)
            if not state:
                log("登录态获取失败, 跳过该账号")
                continue
            dzyx_api.save_state(u.account, state)
            cache = DzyxCache(u.account, getattr(u, "password", ""), base,
                              dzyx_api.cookies_from_state(state), state)
        caches.append(cache)
        log("登录态就绪")
    return caches


def _headless_flag() -> bool:
    return os_env_bool("YATORI_DZYX_HEADLESS", True)


def os_env_bool(name: str, default: bool) -> bool:
    import os
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


# ================= 刷课主循环 =================

def run_brush_operation(setting: Setting, accounts: List[User],
                        caches: List[DzyxCache]) -> None:
    if not caches:
        return
    threads = []
    for cache in caches:
        t = threading.Thread(target=_brush_account,
                             args=(setting, cache), daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.3)
    for t in threads:
        t.join()


def _brush_account(setting: Setting, cache: DzyxCache) -> None:
    log = _log_f(type("_U", (), {"account": cache.account})())
    try:
        lst = cache.client.study_list()
    except Exception as e:
        log(f"学习列表拉取失败: {str(e)[:60]}")
        return
    todo = [x for x in lst
            if int(x.get("studyStatus", 0) or 0) != 2
            and int(x.get("applyStatus", 0) or 0) == 1]
    if not todo:
        log("全部班级已完成, 无需学习")
        return
    log(f"待学习班级 {len(todo)} 个, 启动浏览器逐个刷课")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"playwright 不可用: {e}")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=_headless_flag(),
                                    channel="chrome")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  ignore_https_errors=True,
                                  storage_state=cache.state)
        for item in todo:
            try:
                _study_one_class(ctx, cache, item, log)
            except Exception as e:
                log(f"班级学习异常: {str(e)[:80]}")
            time.sleep(random.uniform(3, 8))
        browser.close()
    log("账号刷课流程结束")


def _study_one_class(ctx, cache: DzyxCache, item: dict, log) -> None:
    my_class_id = item.get("myClassId", "")
    cname = ((item.get("classEntity") or {}).get("className")
             or item.get("lastCourseName") or my_class_id[:8])
    log(f"【{cname}】开始学习")
    page = ctx.new_page()
    try:
        page.goto(cache.base + "/learning/index?myClassId=" + my_class_id,
                  timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        n = page.locator(".videoLi").count()
        log(f"【{cname}】目录 {n} 讲")
        for i in range(n):
            row = page.locator(".videoLi").nth(i)
            title = (row.inner_text() or "").strip().split("\n")[0][:30]
            # 已完成讲跳过(行内有"已完成"/100%标记)
            rowtxt = row.inner_text() or ""
            if "已完成" in rowtxt or "100%" in rowtxt:
                continue
            row.click(timeout=8000)
            page.wait_for_timeout(random.uniform(5, 8))
            ok_play = page.evaluate("""() => {
                const v = document.querySelector('video');
                if (v) v.muted = true;
                const bj = window.baiJiaYunPlayer;
                if (!bj) return false;
                try {
                    if (bj.setMuted) bj.setMuted(true);
                    if (bj.play) bj.play();
                    return true;
                } catch (e) { return false; }
            }""")
            if not ok_play:
                log(f"【{cname}】{title} 播放器未就绪, 跳过")
                continue
            log(f"【{cname}】播放: {title}")
            _wait_video_done(page, log, cname)
            time.sleep(random.uniform(2, 5))
        log(f"【{cname}】全部讲处理完毕")
    finally:
        try:
            page.close()
        except Exception:
            pass


def _wait_video_done(page, log, cname: str,
                     max_minutes: int = 90) -> None:
    """等待单讲播完: 弹题隐藏+暂停恢复+进度到顶"""
    t0 = time.time()
    while time.time() - t0 < max_minutes * 60:
        page.wait_for_timeout(5000)
        st = page.evaluate("""() => {
            const bj = window.baiJiaYunPlayer;
            if (!bj) return null;
            let dur = 0;
            try { dur = bj.duration || (bj.getDuration ? bj.getDuration() : 0); } catch (e) {}
            // 弹题隐藏(百家云视频内 quiz)
            try {
                const w = document.querySelector('.bplayer-question-wrap');
                if (w && getComputedStyle(w).display !== 'none') {
                    w.style.setProperty('display', 'none', 'important');
                }
            } catch (e) {}
            // 暂停自愈
            try { if (bj.paused && bj.play) bj.play(); } catch (e) {}
            return {t: bj.currentTime || 0, dur: dur || 0, paused: !!bj.paused};
        }""")
        if not st:
            return
        if st.get("dur") and st.get("t", 0) >= st["dur"] - 2:
            log(f"【{cname}】本讲播完({int(st['t'])}s)")
            return
    log(f"【{cname}】单讲超时保护退出")


# ================= Web 查课 =================

def web_course_list(cache: DzyxCache, user: User) -> List[dict]:
    try:
        lst = cache.client.study_list()
    except Exception:
        return []
    out = []
    for x in lst or []:
        ce = x.get("classEntity") or {}
        speed = float(x.get("studySpeed", 0) or 0)
        status = int(x.get("studyStatus", 0) or 0)
        out.append({
            "courseId": str(x.get("myClassId", "")),
            "courseName": ce.get("className", ""),
            "teacher": "",
            "jobFinishCount": int(speed),
            "jobCount": 100,
            "jobRate": round(speed, 1),
            "quizFinishCount": None,
            "quizCount": None,
            "overallScore": x.get("score"),
            "hasProgress": True,
            "statusText": {0: "未开始", 1: "学习中", 2: "已完成"}.get(
                status, "未知"),
        })
    return out
