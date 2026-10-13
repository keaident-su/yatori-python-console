# -*- coding: utf-8 -*-
"""智慧树全自动浏览器登录(网易易盾滑块)

复用 weban 的 HTTP 层与浏览器基建思路:
  1. nodriver 打开智慧树登录页(受控浏览器, 反检测)
  2. JS 注入: 填账号/密码 + 勾选协议 + 点登录(触发滑块)
  3. 等待易盾滑块 iframe 出现
  4. 从页面提取拼图块/背景图(优先 URL 下载, 兜底整页截图裁剪)
  5. OpenCV 模板匹配找缺口水平距离(Autovisor 算法)
  6. CDP 派发人类化鼠标轨迹拖动滑块(随机分段+抖动)
  7. 验证通过后导出 Cookie(dict) 供 requests 会话复用

对外接口:
  browser_login(username, password, headless=True) -> dict[str, str] | None

2026-09-28 注: 本文件曾因重构被移除, 现按运行期字节码快照(login_browser
cpython-313.pyc)完整重建, 关键行为(轨迹/事件参数/距离公式)与之前实测
一次通过的版本保持一致。
"""
from __future__ import annotations

import asyncio
import base64
import io as _io
import json
import os
import random
import tempfile
import threading
import time

try:
    import cv2
    import numpy as np
except ImportError:  # opencv 不可用时降级失败
    cv2 = None
    np = None

try:
    import nodriver
except ImportError:
    nodriver = None

_LOGIN_URL = ("https://passport.zhihuishu.com/login"
              "?service=https://onlineservice-api.zhihuishu.com/login/gologin")

# ---------- JS 模板 ----------
_FILL_JS = """
(() => {
  const setVal = (el, v) => {
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    s.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const mob = document.querySelector('input[name=mobile]');
  const pw = document.querySelector('input[type=password]');
  if (!mob || !pw) return 'no-input';
  setVal(mob, __USER__);
  setVal(pw, __PASS__);
  const cb = document.querySelector('.el-checkbox__original');
  if (cb && !cb.checked) {
    const lbl = document.querySelector('.el-checkbox');
    (lbl || cb).click();
  }
  return 'filled';
})()
"""

_CLICK_JS = """
(() => {
  const btn = Array.from(document.querySelectorAll('div, button'))
    .find(e => (e.innerText || '').trim() === '登录' && e.children.length === 0);
  if (!btn) return 'no-btn';
  btn.click();
  return 'clicked';
})()
"""

_YIDUN_STATE_JS = """
(() => {
  const pop = document.querySelector('.yidun_popup');
  const modal = document.querySelector('.yidun_modal');
  const control = document.querySelector('.yidun_control');
  const slider = document.querySelector('.yidun_slider');
  const img = document.querySelector('img.yidun_bg-img')
    || document.querySelector('img.yidun_bgimg')
    || document.querySelector('img[class*=bg]');
  const jigsaw = document.querySelector('img.yidun_jigsaw')
    || document.querySelector('.yidun_jigsaw');
  const rectOf = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  return {
    hasPopup: !!pop, hasModal: !!modal,
    modalRect: rectOf(modal), controlRect: rectOf(control), sliderRect: rectOf(slider),
    bgImg: img ? (img.src || '').slice(0, 200) : '', bgRect: rectOf(img),
    bgImgReady: !!(img && img.src && img.complete && img.naturalWidth > 0),
    jigsaw: jigsaw ? (jigsaw.src || '').slice(0, 200) : '',
    jigsawReady: !!(jigsaw && jigsaw.src && jigsaw.complete && jigsaw.naturalWidth > 0),
  };
})()
"""

_CANVAS_JS = """
(() => {
  const out = {bg: '', jigsaw: '', canvases: []};
  const tryCanvas = (c) => { try { return c.toDataURL('image/png'); } catch (e) { return ''; } };
  const push = (el) => {
    if (!el || el.tagName !== 'CANVAS') return;
    const d = tryCanvas(el);
    if (d) out.canvases.push({w: el.width, h: el.height, d: d.slice(0, 60)});
  };
  const ifr = document.querySelector('iframe.yidun_cover-frame, iframe[src*=yidun], iframe[src*=captcha]');
  if (ifr) {
    try {
      const doc = ifr.contentDocument;
      if (doc) {
        const cs = doc.querySelectorAll('canvas');
        cs.forEach(c => {
          const d = tryCanvas(c);
          if (d) out.canvases.push({w: c.width, h: c.height, d: d.slice(0, 60), inside: true});
        });
      }
    } catch (e) { out.err = String(e); }
  }
  out.hasIframe = !!ifr;
  return out;
})()
"""

_REFRESH_JS = """
(() => { const b = document.querySelector('.yidun_refresh');
          if (b) { b.click(); return 'refresh'; } return 'no'; })()
"""


# ---------- 基础工具 ----------
def _log(msg, err: bool = False):
    ts = time.strftime("%H:%M:%S")
    tag = "ERR" if err else "INFO"
    try:
        print(f"{ts} [{tag}] [智慧树][浏览器] {msg}", flush=True)
    except Exception:
        pass


async def _wait(ms: int):
    await asyncio.sleep(max(0, int(ms)) / 1000.0)


def _dsv_to_py(dsv):
    """nodriver DeepSerializedValue 递归转 Python 原生类型"""
    try:
        if dsv is None:
            return None
        v = getattr(dsv, "value", None)
        if v is None:
            return None
        if isinstance(v, list):
            return [_dsv_to_py(item) for item in v] if v and isinstance(v[0], list) else v
        return v
    except Exception:
        return None


def _norm(v):
    """递归规范化 nodriver 返回的 {type, value} / [[k,{...}]] 结构"""
    if isinstance(v, dict):
        keys = set(v.keys())
        if 'type' in keys and 'value' in keys:
            return _norm(v.get('value'))
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        if v and all(isinstance(x, list) and len(x) == 2
                     and isinstance(x[0], str) and isinstance(x[1], dict)
                     for x in v):
            return {x[0]: _norm(x[1]) for x in v}
        return [_norm(x) for x in v]
    return v


async def _eval(tab, js: str):
    """执行 JS 并转换为 Python 原生类型(nodriver RemoteObject 处理)"""
    try:
        raw = await tab.evaluate(js, return_by_value=True)
    except Exception:
        return None
    # 裸值(str/bool/int/list/dict)直接用; RemoteObject 取 .value
    v = getattr(raw, "value", raw)
    if v is None:
        dsv = getattr(raw, "deep_serialized_value", None)
        if dsv is not None:
            v = getattr(dsv, "value", None)
    return _norm(v)


def _decode_dataurl(data_url):
    """data:image/...;base64,xxx -> numpy BGR 图"""
    try:
        b64 = data_url.split(",", 1)[1]
        buf = np.frombuffer(base64.b64decode(b64), np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None


async def _download_image(url: str):
    """下载图片 URL -> numpy BGR"""
    if not url or cv2 is None:
        return None
    try:
        import requests
        r = requests.get(url, timeout=10, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36")})
        arr = np.frombuffer(r.content, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None


# ---------- 缺口识别 (Autovisor 算法, 实测成功) ----------
def _gap_offset(bg_bgr, jig_bgr):
    """缺口定位: 移植自 Autovisor(实测3年方案)

    背景: 灰度→fastNlMeansDenoising降噪→OTSU二值化→Canny(500,900)
    拼图: 灰度→反色→THRESHOLD_BINARY_INV(240)→Canny(500,900)
    """
    if bg_bgr is None or jig_bgr is None or cv2 is None:
        return None
    try:
        bg = cv2.cvtColor(
            bg_bgr, cv2.COLOR_BGRA2BGR) if bg_bgr.ndim == 3 and bg_bgr.shape[2] == 4 else bg_bgr
        bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
        bg_dn = cv2.fastNlMeansDenoising(bg_gray, None, 10, 7, 21)
        _, bg_bin = cv2.threshold(bg_dn, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bg_edge = cv2.Canny(bg_bin, 500, 900, apertureSize=3)
        if jig_bgr.ndim == 3 and jig_bgr.shape[2] == 4:
            jg = cv2.cvtColor(jig_bgr, cv2.COLOR_BGRA2GRAY)
        else:
            jg = cv2.cvtColor(
                jig_bgr, cv2.COLOR_BGR2GRAY) if jig_bgr.ndim == 3 else jig_bgr
        ji = cv2.bitwise_not(jg)
        _, jb = cv2.threshold(ji, 240, 255, cv2.THRESH_BINARY_INV)
        je = cv2.Canny(jb, 500, 900, apertureSize=3)
        res = cv2.matchTemplate(bg_edge, je, cv2.TM_CCOEFF_NORMED)
        _, _, _, ml = cv2.minMaxLoc(res)
        return int(ml[0])
    except Exception:
        return None


# ---------- 轨迹与拖动 (行为与实测成功版一致) ----------
def _human_tracks(distance):
    """生成滑动轨迹(移植自 Autovisor gen_movelist): 随机分段+末步补齐

    返回 [(累计位移x, 停留ms), ...], 最后一项累计值恰为 distance。
    Autovisor 实测: 每步 uniform(1, 剩余/2), 无过冲回拉。
    """
    tracks = []
    sum_n = float(distance)
    cur = 0.0
    for _ in range(29):
        if sum_n <= 1.5:
            break
        seg = random.uniform(1, sum_n / 2)
        cur += seg
        sum_n -= seg
        tracks.append((round(cur, 3), random.randint(10, 40)))
    cur += sum_n
    tracks.append((round(cur, 3), random.randint(10, 40)))
    return tracks


async def _drag_slider(tab, slider_rect, distance):
    """CDP 鼠标事件按轨迹拖动滑块"""
    x0 = slider_rect[0] + slider_rect[2] / 2
    y0 = slider_rect[1] + slider_rect[3] / 2
    try:
        from nodriver import cdp
    except ImportError:
        from nodriver.core import cdp  # type: ignore
    mouse = cdp.input_.dispatch_mouse_event

    async def send(kind: str, x: float, y: float, buttons: int):
        await tab.send(mouse(
            type_=kind, x=x, y=y,
            button=cdp.input_.MouseButton.LEFT,
            buttons=buttons,
            click_count=1 if kind == 'mousePressed' else 0))

    await send('mouseMoved', x0, y0, 0)
    await _wait(random.randint(80, 200))
    await send('mousePressed', x0, y0, 1)
    await _wait(random.randint(60, 160))
    for frac, hold in _human_tracks(int(distance)):
        cur_x = x0 + max(0.0, frac)
        cur_y = y0 + random.uniform(-0.8, 0.8)
        await send('mouseMoved', cur_x, cur_y, 1)
        await _wait(hold)
    await _wait(random.randint(150, 400))
    await send('mouseReleased', x0 + distance, y0, 0)


# ---------- 截图裁剪兜底 ----------
async def _screenshot_crop(tab, state):
    """整页截图并从 bgRect/jigsaw 位置裁剪出背景图/拼图块"""
    if cv2 is None or np is None:
        return None, None
    try:
        shot = await tab.send(
            __import__('nodriver').cdp.page.capture_screenshot())
        data = getattr(shot, 'data', None)
        if not isinstance(data, str):
            return None, None
        raw = base64.b64decode(data)
        arr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None, None
        # 设备像素比补偿
        dpr = 1.0
        try:
            dpr = float(await _eval(tab, 'window.devicePixelRatio || 1') or 1)
        except Exception:
            pass

        def crop(rect):
            if not rect:
                return None
            x, y, w, h = [int(v * dpr) for v in rect]
            sub = img[max(0, y):y + h, max(0, x):x + w]
            return sub.copy() if sub.size else None

        bg = crop(state.get('bgRect'))
        # jigsaw rect 现场取(state 里未记录)
        jrect = await _eval(tab, """(() => {
          const j = document.querySelector('img.yidun_jigsaw');
          if (!j) return null;
          const r = j.getBoundingClientRect();
          return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
        })()""")
        jig = crop(jrect if isinstance(jrect, list) else None)
        return bg, jig
    except Exception:
        return None, None


async def _extract_canvas_images(tab):
    """尝试从易盾 iframe 内 canvas 提取背景图/拼图块 dataURL"""
    try:
        return await _eval(tab, _CANVAS_JS)
    except Exception:
        return None


# ---------- 单次滑块尝试 ----------
async def _solve_once(tab, state, debug_dir="", attempt=1):
    """一次滑块尝试: 取图 -> 识别 -> 拖动 -> 判断"""
    bg_rect = state.get('bgRect')
    slider_rect = state.get('sliderRect')
    if not bg_rect or not slider_rect:
        _log('未找到滑块元素', err=True)
        return False

    # 取图: 优先 URL 下载; 兜底截图裁剪
    bg_bgr = None
    jig_bgr = None
    bg_url = state.get('bgImg') or ''
    jig_url = state.get('jigsaw') or ''
    if bg_url:
        bg_bgr = await _download_image(bg_url)
    if jig_url:
        jig_bgr = await _download_image(jig_url)

    data = await _extract_canvas_images(tab)
    if isinstance(data, dict):
        _log(f"canvas探测: iframe={data.get('hasIframe')} "
             f"canvas数={len(data.get('canvases') or [])}")

    if bg_bgr is None or jig_bgr is None:
        shot_bg, shot_jig = await _screenshot_crop(tab, state)
        if bg_bgr is None:
            bg_bgr = shot_bg
        if jig_bgr is None:
            jig_bgr = shot_jig

    if bg_bgr is None:
        _log('无法获取滑块背景图', err=True)
        return False

    dist = None
    if jig_bgr is not None:
        off = _gap_offset(bg_bgr, jig_bgr)
        if off is not None:
            dist = off
    if dist is None:
        _log('缺口识别失败', err=True)
        return False

    # 缩放: 原图坐标 -> 显示坐标(宽差>4 时)
    disp_w = bg_rect[2]
    real_w = bg_bgr.shape[1] if bg_bgr.ndim >= 2 else 0
    if real_w and abs(disp_w - real_w) > 4:
        dist = int(dist * disp_w / real_w)
    _log(f'缺口距离: {dist}px (图宽{real_w} 显示{disp_w})')

    if debug_dir:
        try:
            os.makedirs(debug_dir, exist_ok=True)
            cv2.imwrite(f'{debug_dir}\\zs_bg_{attempt}.png', bg_bgr)
            if jig_bgr is not None:
                cv2.imwrite(f'{debug_dir}\\zs_jig_{attempt}.png', jig_bgr)
        except Exception:
            pass

    # 拖动
    drag_dist = max(10.0, float(dist) + 16.0)
    await _drag_slider(tab, slider_rect, drag_dist)
    await _wait(600)

    # 拖动后诊断
    try:
        after = await _eval(tab, _YIDUN_STATE_JS)
        ar = (after or {}).get('sliderRect')
        _log(f'拖动后滑块位置: {ar} (拖前 {slider_rect})')
        pop_txt = await _eval(tab, "(() => { const p = document.querySelector('.yidun_popup'); return p ? (p.innerText || '').replace(/\\s+/g, ' ').slice(0, 120) : '(弹窗已消失)'; })()")
        _log(f'弹窗文本: {pop_txt}')
    except Exception:
        pass

    await _wait(800)
    # 判定 1: 弹窗/背景图消失 = 通过
    for _ in range(10):
        try:
            gone = await _eval(tab, """(() => {
              const pop = document.querySelector('.yidun_popup');
              const bg = document.querySelector('.yidun_bgimg');
              const bgVisible = bg && bg.offsetParent !== null
                && getComputedStyle(bg).display !== 'none';
              return !pop || !bgVisible;
            })()""")
            if gone:
                _log('滑块验证通过 ✓ (弹窗消失)')
                return True
        except Exception:
            pass
        await _wait(300)

    # 判定 2: 成功/失败文案
    for _ in range(6):
        try:
            win = await _eval(tab, """(() => {
              const t = document.querySelector('.yidun_modal__title');
              const tips = document.querySelector('.yidun_tips, .yidun_tips__content, .yidun_tips__text');
              const p = document.querySelector('.yidun_popup');
              return {title: t ? t.innerText : '', tip: tips ? tips.innerText : '', pop: !!p};
            })()""")
            title = str((win or {}).get('title') or '')
            tip = str((win or {}).get('tip') or '')
            if '成功' in title or '通过' in title or '成功' in tip:
                _log(f'滑块验证成功 ✓ ({title or tip})')
                return True
            if any(k in tip for k in ('失败', '再试', '重试', '错误')):
                _log(f'验证失败: {tip}', err=True)
                return False
        except Exception:
            pass
        await _wait(300)
    _log('验证结果未明确, 按失败处理重试', err=True)
    return False


# ---------- Cookie 收集 ----------
async def _collect_cookies(browser):
    """收集浏览器全部 Cookie(含智慧树主域)"""
    merged = {}
    try:
        for c in await browser.cookies.get_all():
            name = getattr(c, 'name', '') or ''
            val = getattr(c, 'value', '') or ''
            if name:
                merged[name] = val
    except Exception as e:
        _log(f'Cookie 获取失败: {e}', err=True)
    return merged


# ---------- 主流程 ----------
async def _browser_login_async(username, password, headless=True,
                               debug_dir="", browser_path=""):
    if nodriver is None:
        _log('nodriver 不可用, 无法浏览器登录', err=True)
        return None
    udd = tempfile.mkdtemp(prefix='yatori-zhs-')
    args = ['--window-size=1280,900', '--mute-audio', '--disable-extensions',
            '--no-first-run', '--disable-infobars',
            '--disable-blink-features=AutomationControlled']
    if headless:
        args.append('--headless=new')
    _log(f'使用内置浏览器: {"headless" if headless else "有界面"}')
    _log('启动浏览器...')
    browser = None
    try:
        kwargs = {'user_data_dir': udd, 'browser_args': args}
        if browser_path:
            kwargs['browser_executable_path'] = browser_path
        browser = await nodriver.start(**kwargs)
        tab = await browser.get(_LOGIN_URL)
        await _wait(3500)

        # 填表(带重试)
        for _ in range(5):
            js = _FILL_JS.replace('__USER__', json.dumps(username)) \
                         .replace('__PASS__', json.dumps(password))
            r = await _eval(tab, js)
            _log(f'填表: {r}')
            if r == 'filled':
                break
            _log(f'填表重试: {r}')
            await _wait(2000)
        await _wait(400)

        # 点登录
        r = await _eval(tab, _CLICK_JS)
        _log(f'点登录: {r}')
        await _wait(900)

        # 等滑块弹窗 + 图就绪
        state = None
        for _ in range(20):
            await _wait(500)
            state = await _eval(tab, _YIDUN_STATE_JS)
            if state and state.get('hasPopup'):
                if state.get('bgImgReady') and state.get('jigsawReady'):
                    break
                continue
        if state and state.get('hasPopup') \
                and not (state.get('bgImgReady') and state.get('jigsawReady')):
            await _wait(1500)
            state = await _eval(tab, _YIDUN_STATE_JS)
        _log(f'滑块状态: {state}')

        if not state or not state.get('hasPopup'):
            # 未触发滑块: 可能免验证直接登录
            _log('未触发滑块, 直接完成登录')
            cookies = await _collect_cookies(browser)
            if cookies:
                return cookies
            _log('未出现滑块且无 Cookie', err=True)
            return None

        # 滑块尝试循环
        passed = False
        for attempt in range(1, 6):
            _log(f'滑块第 {attempt} 次尝试...')
            await _wait(800)
            ok = await _solve_once(tab, state, debug_dir, attempt)
            if ok:
                passed = True
                break
            # 点刷新 + 等待重载
            r = await _eval(tab, _REFRESH_JS)
            await _wait(2200)
            state = await _eval(tab, _YIDUN_STATE_JS)
            if not state or not state.get('hasPopup'):
                # 弹窗不再出现 → 可能已通过
                break
        del passed

        # 等待跳转 + 结果
        await _wait(1200)
        url = None
        for _ in range(16):
            url = await _eval(tab, 'location.href')
            if url and 'login.' not in str(url):
                break
            await _wait(500)
        _log(f'当前URL: {url}')

        page_text = await _eval(tab, '(() => document.body.innerText.slice(0,100))()')
        if page_text and '密码' in str(page_text):
            _log(f'页面提示: {str(page_text)[:80]}', err=True)

        await _wait(80)
        cookies = await _collect_cookies(browser)
        _log(f'Cookie 数量: {len(cookies)}')
        return cookies if cookies else None
    except Exception as e:
        _log(f'浏览器登录异常: {type(e).__name__}: {e}', err=True)
        return None
    finally:
        try:
            if browser is not None:
                await browser.stop()
        except Exception:
            pass


def browser_login(username, password, headless=True, debug_dir="",
                  browser_path=""):
    """对外入口: 全自动浏览器登录智慧树, 成功返回 cookies dict"""
    if not username or not password:
        return None
    result = {}

    def _runner():
        try:
            result['v'] = asyncio.run(_browser_login_async(
                username, password, headless=headless,
                debug_dir=debug_dir, browser_path=browser_path))
        except Exception as e:
            _log(f'登录线程异常: {e}', err=True)
            result['v'] = None

    # nodriver 在部分环境下需要独立事件循环; 但也支持直接 asyncio.run
    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    return result.get('v') or None
