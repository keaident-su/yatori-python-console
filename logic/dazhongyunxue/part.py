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
from config.config import course_allowed  # [V3.1.3] 统一课程过滤
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
            # [V3.2.1] 浏览器启动: 优先 Playwright 内置 chromium(安装包已含),
            # 内置缺失时回退系统 Chrome(旧实现仅 channel="chrome",
            # 未装 Chrome 的机器会直接报错 → 用户感受“启动不了”)
            browser = None
            _e1 = _e2 = None
            try:
                browser = p.chromium.launch(headless=headless)
            except Exception as _ex1:
                _e1 = _ex1
                try:
                    browser = p.chromium.launch(headless=headless,
                                                channel="chrome")
                except Exception as _ex2:
                    _e2 = _ex2
            if browser is None:
                log("未检测到可用浏览器(内置Chromium与系统Chrome均不可用)，"
                    "请安装 Google Chrome 后重试")
                log("浏览器启动失败: %s / %s" % (str(_e1)[:80], str(_e2)[:80]))
                return None
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
        # [V3.2.3] 附 traceback 摘要便于定位(如 playwright/driver 版本不匹配/state 类型)
        import traceback as _tb
        _tail = " | ".join(_tb.format_exc().splitlines()[-2:])[:220]
        log(f"登录异常: {str(e)[:100]}")
        log(f"登录异常trace: {_tail}")
        return None


def _load_setting():
    """加载全局配置(供 resolve_base 读取 dzyx_base_url; 失败返回None)"""
    try:
        from web.service.user_service import load_web_setting
        return load_web_setting()
    except Exception:
        try:
            from config.config import read_config
            return read_config("config.yaml").setting
        except Exception:
            return None


def user_login_operation(users: List[User]) -> List[DzyxCache]:
    caches: List[DzyxCache] = []
    for u in users:
        try:
            log = _log_f(u)
            base = dzyx_api.resolve_base(setting=_load_setting(), user=u)
            state = dzyx_api.load_state(u.account)
            if not isinstance(state, dict):
                state = None
            cookies = dzyx_api.cookies_from_state(state) if state else {}
            cache = DzyxCache(u.account, getattr(u, "password", ""), base,
                              cookies, state or {})
            # 校验登录态有效性
            valid = False
            if cookies:
                try:
                    lst = cache.client.study_list()
                    valid = isinstance(lst, list)
                except Exception:
                    valid = False
            if not valid:
                # [V3.2.1] 优先纯协议登录(无需浏览器): 明文密码→DES 密文→滑块+login.gson
                plain = ""
                try:
                    plain = str(getattr(getattr(u, "courses_custom", None),
                                        "password", "") or
                                getattr(u, "password", "") or "")
                except Exception:
                    plain = str(getattr(u, "password", "") or "")
                _pc_ok = False
                if plain:
                    _ct = None
                    try:
                        from logic.dazhongyunxue import cipher as _cipher
                        _ct = _cipher.encrypt_password(plain)
                    except Exception:
                        _ct = None
                    if _ct:
                        try:
                            from logic.dazhongyunxue import protocol as _pcp
                            _pc = _pcp.login_protocol(
                                base, str(u.account), _ct, log=log)
                        except Exception:
                            _pc = {}
                        if _pc:
                            state = {"cookies": [{"name": k, "value": v}
                                                 for k, v in _pc.items()]}
                            dzyx_api.save_state(u.account, state)
                            cache = DzyxCache(u.account, plain, base,
                                              dict(_pc), state)
                            _pc_ok = True
                            log("登录成功(纯协议·无需浏览器)")
                if not _pc_ok:
                    log("纯协议登录未通过, 回退浏览器登录...")
                    headless = _headless_flag()
                    state = _playwright_login(u, base, headless, log)
                if not state:
                    log("登录态获取失败, 跳过该账号"
                        "(请确认: ①平台地址是否填对(如 zyk 专业课站需填完整地址) "
                        "②本机是否已安装 Google Chrome ③账密是否正确)")
                    continue
                dzyx_api.save_state(u.account, state)
                cache = DzyxCache(u.account, getattr(u, "password", ""), base,
                                  dzyx_api.cookies_from_state(state),
                                  state if isinstance(state, dict) else {})
            caches.append(cache)
            log(f"登录态就绪({base})")
        except Exception as _e:
            # [V3.2.3] 单账号异常不得中断其他账号, 并落 traceback 便于定位
            import traceback as _tb
            try:
                _lf = _log_f(u)
                _lf(f"登录异常已跳过: {type(_e).__name__}: {str(_e)[:140]}")
                _lf("异常trace: " + " | ".join(
                    _tb.format_exc().splitlines()[-3:])[:260])
            except Exception:
                pass
            continue
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
    _by_acc = {str(getattr(x, "account", "")): x for x in (accounts or [])}
    for cache in caches:
        _u = _by_acc.get(str(cache.account))
        if _u is None:
            continue  # 登录失败账号不在 caches 列时跳过错配
        t = threading.Thread(target=_brush_account,
                             args=(setting, _u, cache), daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.3)
    for t in threads:
        t.join()


def _brush_account(setting: Setting, user: User, cache: DzyxCache) -> None:
    log = _log_f(type("_U", (), {"account": cache.account})())
    try:
        lst = cache.client.study_list()
    except Exception as e:
        log(f"学习列表拉取失败: {str(e)[:60]}")
        return
    todo = [x for x in lst
            if int(x.get("studyStatus", 0) or 0) != 2
            and int(x.get("applyStatus", 0) or 0) == 1]
    # [V3.1.3] 统一课程过滤(班级名即课程名): 只刷/排除 生效
    try:
        _cc = getattr(user, "courses_custom", None)
        if _cc is not None:
            todo = [x for x in todo
                    if course_allowed(_cc, str((x.get("classEntity") or {})
                                               .get("className", "")))]
    except Exception:
        pass
    if not todo:
        log("全部班级已完成, 无需学习")
        return
    # 2026-10-22: 纯协议主路线(实测: cv.gson心跳=平台计时, 随机pid即回"正常计时!",
    #   1倍速真实节奏, 全程requests无浏览器)。浏览器版保留为兼容回退。
    from logic.dazhongyunxue import protocol as dzyx_proto
    log(f"待学习班级 {len(todo)} 个, 纯协议模式启动")
    for item in todo:
        my_class_id = item.get("myClassId", "")
        cname = ((item.get("classEntity") or {}).get("className")
                 or my_class_id[:8])
        log(f"【{cname}】纯协议学习开始")
        try:
            res = dzyx_proto.run_protocol_study(
                cache.client, my_class_id,
                log=lambda m: log(m), interval=20, max_hours=10.0)
            if res.get("done"):
                log(f"【{cname}】✅课程完成!")
            elif res.get("need_browser"):
                # [V3.2.1] 纯协议计时被拒 -> 回退浏览器真实播放(保证能刷)
                log(f"【{cname}】纯协议未生效, 回退浏览器播放...")
                _browser_fallback_study(cache, item, log)
            else:
                log(f"【{cname}】阶段结束, 进度{res.get('courseRate', 0):.2f}%")
        except Exception as e:
            log(f"【{cname}】纯协议异常: {str(e)[:80]}")
        time.sleep(random.uniform(3, 8))
    log("账号刷课流程结束")


def _browser_fallback_study(cache: DzyxCache, item: dict, log) -> None:
    """[V3.2.1] 浏览器回退刷课(纯协议被服务端拒绝计时时使用)

    启动策略与 _playwright_login 一致: 内置 chromium 优先, 回退系统 Chrome。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"浏览器回退不可用(playwright缺失): {str(e)[:60]}")
        return
    try:
        with sync_playwright() as p:
            browser = None
            _e1 = _e2 = None
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as _ex1:
                _e1 = _ex1
                try:
                    browser = p.chromium.launch(
                        headless=True, channel="chrome")
                except Exception as _ex2:
                    _e2 = _ex2
            if browser is None:
                log("浏览器回退失败: 内置Chromium与系统Chrome均不可用"
                    f" ({str(_e1)[:50]}/{str(_e2)[:50]})")
                return
            ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                      ignore_https_errors=True)
            try:
                ctx.add_cookies([{"name": str(k), "value": str(v),
                                  "url": cache.base}
                                 for k, v in (cache.cookie_dict or {}).items()])
            except Exception:
                pass
            try:
                _study_one_class(ctx, cache, item, log)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log(f"浏览器回退异常: {str(e)[:80]}")


def _study_one_class(ctx, cache: DzyxCache, item: dict, log) -> None:
    my_class_id = item.get("myClassId", "")
    cname = ((item.get("classEntity") or {}).get("className")
             or item.get("lastCourseName") or my_class_id[:8])
    log(f"【{cname}】开始学习")
    page = ctx.new_page()
    try:
        page.goto(cache.base + "/learning/index?myClassId=" + my_class_id,
                  timeout=60000, wait_until="domcontentloaded")
        # 2026-10-22: 目录异步渲染, 轮询等 .videoLi 出现(最多20秒)
        n = 0
        for _ in range(20):
            page.wait_for_timeout(1000)
            n = page.locator(".videoLi").count()
            if n:
                break
        log(f"【{cname}】目录 {n} 讲")
        for i in range(n):
            row = page.locator(".videoLi").nth(i)
            title = (row.inner_text() or "").strip().split("\n")[0][:30]
            # 已完成讲跳过(行内有"已完成"/100%标记)
            rowtxt = row.inner_text() or ""
            if "已完成" in rowtxt or "100%" in rowtxt:
                continue
            # JS直点(绕过遮挡/可操作性检查), 失败回退 locator.click
            clicked = page.evaluate("""(idx) => {
                const rows = document.querySelectorAll('.videoLi');
                if (rows[idx]) { rows[idx].scrollIntoView({block:'center'}); rows[idx].click(); return true; }
                return false;
            }""", i)
            if not clicked:
                try:
                    row.click(timeout=5000)
                except Exception:
                    log(f"【{cname}】{title} 点击失败, 跳过")
                    continue
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
        mid = str(x.get("myClassId", ""))
        # [V3.2.1] 任务点真实化: 用 my-class 的讲列表统计"已完成讲数/总讲数"
        # (旧实现 jobCount 写死 100, 进度页显示"任务点 30/100"语义不清)
        _jc, _jf = 100, int(round(speed))
        try:
            from logic.dazhongyunxue import protocol as _p
            _plans = _p.fetch_video_plans(cache.client, mid)
            if _plans:
                _jc = len(_plans)
                _jf = sum(1 for p in _plans
                          if int(p.get("duration") or 0) > 0
                          and int(p.get("watched") or 0)
                          >= int(p.get("duration") or 0) - 2)
        except Exception:
            pass
        out.append({
            "courseId": mid,
            "courseName": ce.get("className", ""),
            "teacher": "",
            "jobFinishCount": _jf,
            "jobCount": _jc,
            "jobRate": round(speed, 1),
            "quizFinishCount": None,
            "quizCount": None,
            "overallScore": x.get("score"),
            "hasProgress": True,
            "statusText": {0: "未开始", 1: "学习中", 2: "已完成"}.get(
                status, "未知"),
        })
    return out


def web_course_detail_stat(cache: DzyxCache, user: User,
                           course_id: str) -> dict:
    """[V3.2.1] 课程详情统计: 返回讲(任务点)清单。

    DZYX 无独立的作业/考试接口(平台侧作业/考试未开放协议), 故 work* 用
    "视频讲"充当任务点清单, exam* 置 None(前端显示 --)。
    """
    plans = []
    try:
        from logic.dazhongyunxue import protocol as _p
        plans = _p.fetch_video_plans(
            cache.client, str(course_id)) or []
    except Exception:
        plans = []
    items = []
    fin = 0
    for p in plans:
        dur = int(p.get("duration") or 0)
        w = int(p.get("watched") or 0)
        done = dur > 0 and w >= dur - 2
        if done:
            fin += 1
        items.append({
            "name": p.get("name") or "视频",
            "status": "已完成" if done else ("学习中" if w > 0 else "未开始"),
            "deadline": "",
            "ongoing": (not done),
            "score": None,
            "progress": round(min(100.0, (w / dur * 100.0)) if dur else 0, 1),
        })
    return {"supported": True,
            "workFinish": fin if plans else None,
            "workCount": len(plans) if plans else None,
            "examFinish": None, "examCount": None,
            "workList": items, "examList": [],
            "workOngoing": sum(1 for i in items if i["ongoing"]),
            "examOngoing": 0}



# [V3.2.3] 可重做巡检接入: 大众云学(考试发现层; 重考接口未逆向 -> 只发现不执行)
def _retake_scan_dzyx(cache, user, log):
    from logic.core import retake_scanner as _rs
    items = []
    try:
        lst = cache.client.study_list() or []
    except Exception:
        lst = []
    cc = user.courses_custom
    for it in lst:
        mid = str(it.get("myClassId", "") or "")
        if not mid:
            continue
        cname = ((it.get("classEntity") or {}).get("className")
                 or it.get("lastCourseName") or mid[:8])
        try:
            if not course_allowed(cc, str(cname)):
                continue
        except Exception:
            pass
        try:
            mc = cache.client.my_class(mid) or {}
        except Exception:
            mc = {}
        cid = mc.get("classExamId")
        if not cid:
            continue
        passed = mc.get("isPass")
        ok = passed in (1, True, "1")
        items.append(_rs.RetakeItem(
            "DZYX", str(cname), "考试", "结课考试",
            status=("已通过" if ok else "未通过/可重考"),
            expired=False, remaining=(0 if ok else -1),
            note="大众云学重考接口未逆向, 仅发现"))
    return items


try:
    from logic.core import retake_scanner as _rs2
    _rs2.register("DZYX", _retake_scan_dzyx, None)
except Exception:
    pass
