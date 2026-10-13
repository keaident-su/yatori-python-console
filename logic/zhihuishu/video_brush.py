# -*- coding: utf-8 -*-
"""v233: 防假完成复核引擎 (基于v207, 两处修复)
修复1: 节点击改用 JS li.click() 直点 + 坐标CDP兜底
修复2: 完成判定 cur >= dur-1 (播到片尾最后1秒)
支持: ZHS_ONLY=7.1 仅刷指定节(验证模式); 不设=全量续刷
"""
import importlib
import sys
import os
import io
import json
import asyncio
import time
import functools as _ft
import shutil

LOGF = os.environ.get("ZHS_LOG", r"d:\yatori-go-console-main\_zhs_v210.txt")
NO_GREEN = set()  # v230: 播放完成但未即时变绿的节(本会话暂停重刷)

_f = io.open(LOGF, "w", encoding="utf-8")
sys.stdout = _f
sys.stderr = _f
print = _ft.partial(print, flush=True)

BASE = r"d:\yatori-go-console-main\yatori-python-console"
sys.path.insert(0, BASE)
os.chdir(BASE)
nodriver = importlib.import_module("nodriver")
cdp_input = importlib.import_module("nodriver.cdp.input_")
LB = importlib.import_module("logic.zhihuishu.login_browser")

URL4E = os.environ.get(
    "ZHS_URL",
    "https://studyvideoh5.zhihuishu.com/stuStudy?recruitAndCourseId=4e5b5850435e4859454a58585a405a4458")
UDD = os.environ.get("ZHS_PROFILE", os.path.join(
    os.environ.get("TEMP", r"C:\Temp"), "yatori-zhs-cap164"))
PROG = os.environ.get(
    "ZHS_PROGRESS", r"d:\yatori-go-console-main\_zhs_progress.json")
ONLY = (os.environ.get("ZHS_ONLY", "") or "").strip()
ACC_LOGIN = os.environ.get("ZHS_ACC", "18286610553")
PWD_LOGIN = os.environ.get("ZHS_PWD", "XWTxwt1902")

TOC_JS = """
(() => {
  const out = [];
  for (const li of document.querySelectorAll('li.clearfix.video, li[class*="video"]')) {
    const t = (li.innerText || '').replace(/\\s+/g,' ').trim();
    const m = t.match(/^(\\d+\\.\\d+)/); if (!m) continue;
    const pm = t.match(/(\\d+)%/);
    out.push({no: m[1], pct: pm ? parseInt(pm[1]) : null, title: t.slice(0, 50)});
  }
  return JSON.stringify(out);
})()
"""

STATE_JS = """
(() => {
  const v = document.querySelector('video');
  const txt = document.body.innerText || '';
  const sp = document.querySelector('.speedBox span');
  let top = '';
  try {
    const el = document.querySelector('.video-study .title, .box-content .title, .catalogue_title, [class*="chapter-name"], .current_play');
    if (el) top = (el.innerText||'').replace(/\\s+/g,' ').slice(0,60);
    if (!top) {
      const m = txt.match(/第[一二三四五六七八九十]+章[^\\n]{0,40}/);
      if (m) top = m[0].slice(0,60);
    }
  } catch (e) {}
  return JSON.stringify({
    dur: v ? Math.round(v.duration||0) : 0, cur: v ? Math.round(v.currentTime) : -1,
    rate: v ? v.playbackRate : null, paused: v ? v.paused : true,
    aiQuiz: (function(){
      if (!txt.includes('AI\u52a9\u6559\u5c0f\u667a\u7ed9\u4f60\u51fa\u9898')) return false;
      for (var _el of document.querySelectorAll('li.topic-item, [class*="topic-item"]')) {
        var _r = _el.getBoundingClientRect();
        if (_r.width > 100 && _r.height > 0) return true;
      }
      for (var _el2 of document.querySelectorAll('.el-dialog__wrapper, .el-dialog')) {
        var _r2 = _el2.getBoundingClientRect();
        if (_r2.width > 200 && _r2.height > 200) return true;
      }
      return false;
    })(),
    speedTxt: sp ? sp.innerText : null,
    srcHash: v && (v.currentSrc || v.src) ? String(v.currentSrc || v.src).split('/').pop().slice(0, 18) : 'none',
    srcFull: v ? String(v.currentSrc || v.src || '') : '',
    top: top
  });
})()
"""

CLICK_JS = """
(() => {
  const KEY = window.__zhsTargetNo || '';
  for (const li of document.querySelectorAll('li.clearfix.video, li[class*="video"]')) {
    const t = (li.innerText || '').replace(/\\s+/g,' ').trim();
    const m = t.match(/^(\\d+\\.\\d+)/);
    if (!m || m[1] !== KEY) continue;
    try { li.scrollIntoView({block: 'center'}); } catch (e) {}
    try {
      const inner = li.querySelector('.catalogue_title3') || li.querySelector('span') || li;
      inner.click();
      return 'js-clicked-inner';
    } catch (e) { return 'click-err:' + e; }
  }
  return 'notfound';
})()
"""

SCROLL_JS = """
(() => {
  const KEY = window.__zhsTargetNo || '';
  for (const li of document.querySelectorAll('li.clearfix.video, li[class*="video"]')) {
    const t = (li.innerText || '').replace(/\\s+/g,' ').trim();
    const m = t.match(/^(\\d+\\.\\d+)/);
    if (!m || m[1] !== KEY) continue;
    try { li.scrollIntoView({block: 'center'}); } catch (e) {}
    try {
      let el = li.parentElement;
      while (el && el !== document.body) {
        if (el.scrollHeight > el.clientHeight + 20) {
          const lr = li.getBoundingClientRect();
          const er = el.getBoundingClientRect();
          el.scrollTop += Math.round((lr.top + lr.height/2) - (er.top + er.height/2));
          break;
        }
        el = el.parentElement;
      }
    } catch (e) {}
    return 'scrolled';
  }
  return 'notfound';
})()
"""

POS_JS = """
(() => {
  const KEY = window.__zhsTargetNo || '';
  for (const li of document.querySelectorAll('li.clearfix.video, li[class*="video"]')) {
    const t = (li.innerText || '').replace(/\\s+/g,' ').trim();
    const m = t.match(/^(\\d+\\.\\d+)/);
    if (!m || m[1] !== KEY) continue;
    const tgt = li.querySelector('.catalogue_title') || li.querySelector('span.catalogue_title3') || li;
    const r = tgt.getBoundingClientRect();
    const x = Math.round(r.x + r.width/2);
    const y = Math.round(r.y + r.height/2);
    let hit = 'null';
    try {
      const el = document.elementFromPoint(x, y);
      if (el) {
        if (li.contains(el)) { hit = 'li'; }
        else {
          const oli = el.closest('li');
          hit = oli ? 'other-li:' + ((oli.innerText||'').replace(/\\s+/g,' ').trim().slice(0,16)) : el.tagName;
        }
      }
    } catch (e) { hit = 'err'; }
    return JSON.stringify({x: x, y: y,
                           vis: r.top >= 0 && r.bottom <= ((window.innerHeight||1000) + 30),
                           hit: hit});
  }
  return '';
})()
"""

QUIZ_CLOSE_JS = """
(() => {
  let fb = null;
  for (const el of document.querySelectorAll('div,span,button,a')) {
    if ((el.innerText||'').trim() === '\u5173\u95ed') {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        if (el.children.length === 0) return JSON.stringify({x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)});
        if (!fb) fb = {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)};
      }
    }
  }
  return fb ? JSON.stringify(fb) : '';
})()
"""

QUIZ_OPT_JS = """
(() => {
  for (const el of document.querySelectorAll('li.topic-item, [class*="topic-item"]')) {
    const r = el.getBoundingClientRect();
    if (r.width > 100 && r.height > 0) {
      var t = el.querySelector('span, p, label, div');
      var tr = t ? t.getBoundingClientRect() : r;
      var x = Math.round((tr.width > 20) ? tr.x + tr.width/2 : r.x + r.width/2);
      var y = Math.round((tr.height > 10) ? tr.y + tr.height/2 : r.y + r.height/2);
      return JSON.stringify({x: x, y: y});
    }
  }
  return '';
})()
"""

SPEEDBOX_JS = """
(() => {
  const el = document.querySelector('.speedBox');
  if (!el) return '';
  const r = el.getBoundingClientRect();
  if (r.width <= 0) return '';
  return JSON.stringify({x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)});
})()
"""

SPEED15_JS = """
(() => {
  const el = document.querySelector('.speedTab15, [rate="1.5"]');
  if (!el) return '';
  const r = el.getBoundingClientRect();
  if (r.width <= 0) return '';
  return JSON.stringify({x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)});
})()
"""


def wprog(d):
    try:
        d["ts"] = time.time()
        d["tsStr"] = time.strftime("%H:%M:%S")
        io.open(PROG, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


async def mclick(tab, x, y):
    try:
        await tab.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=int(x), y=int(y)))
        await asyncio.sleep(0.2)
        await tab.send(cdp_input.dispatch_mouse_event(type_="mousePressed", x=int(x), y=int(y), button=cdp_input.MouseButton.LEFT, click_count=1))
        await asyncio.sleep(0.08)
        await tab.send(cdp_input.dispatch_mouse_event(type_="mouseReleased", x=int(x), y=int(y), button=cdp_input.MouseButton.LEFT, click_count=1))
    except Exception as e:
        print("   [mclick容忍]", str(e)[:80])


async def st(tab):
    try:
        return json.loads(str(await tab.evaluate(STATE_JS)))
    except Exception:
        return {}


async def read_toc(tab):
    try:
        return json.loads(str(await tab.evaluate(TOC_JS)))
    except Exception:
        return []


async def ensure_login(tab, acc, pwd):
    """检测登录页并自动登录(复用login_browser内部逻辑: 填表+过石块); 返回True=已登录"""
    try:
        url = str(await LB._eval(tab, 'location.href'))
    except Exception:
        return False
    if 'login.' not in url:
        return True
    print("[v210] 检测到登录页, 自动登录中...")
    for _ in range(5):
        try:
            js = LB._FILL_JS.replace('__USER__', json.dumps(
                acc)).replace('__PASS__', json.dumps(pwd))
            r = await LB._eval(tab, js)
            print("[v210] 填表:", r)
            if r == 'filled':
                break
        except Exception as e:
            print("[v210] 填表异常:", str(e)[:80])
        await asyncio.sleep(2)
    await asyncio.sleep(0.4)
    try:
        r = await LB._eval(tab, LB._CLICK_JS)
        print("[v210] 点登录:", r)
    except Exception as e:
        print("[v210] 点登录异常:", str(e)[:80])
        return False
    await asyncio.sleep(1)
    state = None
    try:
        for _ in range(20):
            await asyncio.sleep(0.5)
            state = await LB._eval(tab, LB._YIDUN_STATE_JS)
            if state and state.get('hasPopup'):
                if state.get('bgImgReady') and state.get('jigsawReady'):
                    break
                continue
        if state and state.get('hasPopup'):
            print("[v210] 出现过石块, 尝试自动通过...")
            for attempt in range(1, 6):
                ok = await LB._solve_once(tab, state, "", attempt)
                if ok:
                    print("[v210] 石块通过(第%d次)" % attempt)
                    break
                try:
                    await LB._eval(tab, LB._REFRESH_JS)
                except Exception:
                    pass
                await asyncio.sleep(2.2)
                state = await LB._eval(tab, LB._YIDUN_STATE_JS)
                if not state or not state.get('hasPopup'):
                    break
    except Exception as e:
        print("[v210] 石块处理异常:", str(e)[:100])
    await asyncio.sleep(1.5)
    for _ in range(16):
        try:
            url = str(await LB._eval(tab, 'location.href'))
            if 'login.' not in url:
                break
        except Exception:
            pass
        await asyncio.sleep(0.5)
    try:
        url = str(await LB._eval(tab, 'location.href'))
    except Exception:
        url = ''
    ok_login = 'login.' not in url
    print("[v210] 登录结果: %s | url=%s" %
          ("成功" if ok_login else "未完成", url[:100]))
    return ok_login


async def kick_play(tab):
    try:
        await tab.evaluate("(() => {const v=document.querySelector('video'); if(v){v.muted=true; v.play().catch(()=>{});} return true;})()")
    except Exception:
        pass
    await mclick(tab, 640, 400)
    await asyncio.sleep(1.2)
    try:
        await tab.evaluate("(() => {const v=document.querySelector('video'); if(v&&v.paused){v.play().catch(()=>{});} return true;})()")
    except Exception:
        pass


async def handle_quiz(tab):
    try:
        ro = await tab.evaluate(QUIZ_OPT_JS)
        if str(ro).startswith("{"):
            pos = json.loads(str(ro))
            await mclick(tab, pos["x"], pos["y"])
            await asyncio.sleep(1.2)
        rc = await tab.evaluate(QUIZ_CLOSE_JS)
        if str(rc).startswith("{"):
            pos = json.loads(str(rc))
            await mclick(tab, pos["x"], pos["y"])
            await asyncio.sleep(1.0)
        # v232: JS直点兜底(坐标点击无效时; 对Vue按钮有效)
        try:
            await tab.evaluate("""
(() => {
  for (const el of document.querySelectorAll('li.topic-item, [class*="topic-item"]')) {
    const r = el.getBoundingClientRect();
    if (r.width > 100 && r.height > 0) { try { el.click(); } catch(e){} break; }
  }
  return true;
})()
""")
            await asyncio.sleep(0.8)
            await tab.evaluate("""
(() => {
  for (const el of document.querySelectorAll('div,span,button,a')) {
    if ((el.innerText||'').trim() === '\u5173\u95ed' && el.children.length === 0) {
      try { el.click(); } catch(e){}
      return true;
    }
  }
  for (const el of document.querySelectorAll('div,span,button')) {
    if ((el.innerText||'').trim() === '\u5173\u95ed') {
      try { el.click(); } catch(e){}
      return true;
    }
  }
  return false;
})()
""")
            await asyncio.sleep(0.5)
        except Exception:
            pass
        # ESC 兜底(部分弹窗支持)
        try:
            await tab.send(cdp_input.dispatch_key_event(type_="rawKeyDown", windows_virtual_key_code=27))
            await tab.send(cdp_input.dispatch_key_event(type_="keyUp", windows_virtual_key_code=27))
            await asyncio.sleep(0.5)
        except Exception:
            pass
        await tab.evaluate("(() => {const v=document.querySelector('video'); if(v&&v.paused){v.play().catch(()=>{});} return true;})()")
        return True
    except Exception as e:
        print("  [弹题处理异常]", e)
        return False


async def set_speed_15(tab):
    for attempt in range(3):
        try:
            await tab.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=640, y=400))
            await asyncio.sleep(1.0)
            r = await tab.evaluate(SPEEDBOX_JS)
            if not str(r).startswith("{"):
                await mclick(tab, 640, 400)
                await asyncio.sleep(1.0)
                r = await tab.evaluate(SPEEDBOX_JS)
            if not str(r).startswith("{"):
                continue
            sp = json.loads(str(r))
            await mclick(tab, sp["x"], sp["y"])
            await asyncio.sleep(0.8)
            r15 = await tab.evaluate(SPEED15_JS)
            if not str(r15).startswith("{"):
                continue
            t15 = json.loads(str(r15))
            await mclick(tab, t15["x"], t15["y"])
            await asyncio.sleep(2.5)
            await kick_play(tab)
            await asyncio.sleep(6)
            s = await st(tab)
            print("   [1.5x] 尝试%d: rate=%s spTxt=%s dur=%s" % (
                attempt + 1, s.get("rate"), s.get("speedTxt"), s.get("dur")))
            if s.get("rate") == 1.5:
                return True
        except Exception as e:
            print("   [1.5x] 异常:", e)
    return False


async def wait_section_green(tab, no, max_wait=150):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        toc = await read_toc(tab)
        for x in toc:
            if x["no"] == no:
                p = x.get("pct")
                if p is None or p >= 100:
                    return True
                break
        await asyncio.sleep(15)
    return False


async def click_section(tab, no):
    """v222 闭环点击(修复频繁点击重置加载): 滚动 -> 命中校验 -> 点击1次 -> 30s渐进检测dur"""
    await tab.evaluate("window.__zhsTargetNo = '%s'; true" % no)
    for rnd in range(1):
        try:
            sr = await tab.evaluate(SCROLL_JS)
        except Exception as e:
            print("[v222] 滚动异常:", str(e)[:60])
            await asyncio.sleep(1)
            continue
        if str(sr) == "notfound":
            print("[v222] 目标节 %s 不在目录(rnd=%d)" % (no, rnd))
            await asyncio.sleep(1)
            continue
        await asyncio.sleep(0.8)
        try:
            rp = await tab.evaluate(POS_JS)
        except Exception as e:
            print("[v222] 测量异常:", str(e)[:60])
            await asyncio.sleep(1)
            continue
        if not str(rp).startswith("{"):
            print("[v222] 测量空(rnd=%d)" % rnd)
            await asyncio.sleep(1)
            continue
        pp = json.loads(str(rp))
        hit = pp.get("hit", "")
        print("[v222] rnd=%d 位置(%s,%s) vis=%s hit=%s" %
              (rnd, pp.get("x"), pp.get("y"), pp.get("vis"), hit))
        if not pp.get("vis") or hit != "li":
            await asyncio.sleep(0.6)
            continue
        await mclick(tab, pp["x"], pp["y"])
        # v224: 读平台完整src + 渐进激活(15s load -> 25s 清空复位+重设平台src -> 35s cache-buster)
        full_src = ""
        for w in range(10):
            await asyncio.sleep(5)
            s = await st(tab)
            d = s.get("dur") or 0
            fs = str(s.get("srcFull") or "")
            if fs and fs != "none" and not full_src:
                full_src = fs
                print("[v224] 平台完整src: %s" % fs[:170])
            print("[v224] 点击后%2ds: dur=%s cur=%s src=%s" %
                  ((w + 1) * 5, d, s.get("cur"), str(s.get("srcHash"))))
            if d > 0:
                return True
            if s.get("aiQuiz"):
                await handle_quiz(tab)
            if w == 2:
                try:
                    await tab.evaluate("(() => {const v=document.querySelector('video'); if(v){v.load(); v.muted=true; v.play().catch(()=>{});} return true;})()")
                    print("[v224] 15s: load()激活")
                except Exception:
                    pass
            if w == 4:
                try:
                    await tab.evaluate("(() => {const v=document.querySelector('video'); if(v){v.removeAttribute('src'); v.load();} return true;})()")
                    await asyncio.sleep(1)
                    _u = full_src or str((await st(tab)).get("srcFull") or "")
                    _r = await tab.evaluate(
                        "(() => {const v=document.querySelector('video'); if(!v) return 'nov'; v.src=%s; v.muted=true; v.load(); v.play().catch(()=>{}); return 'reset-ok';})()" % json.dumps(_u))
                    print("[v224] 25s: 清空复位+重设平台src:", str(_r)[:60])
                except Exception as e:
                    print("[v224] 25s重设异常:", str(e)[:60])
            if w == 6 and full_src:
                try:
                    _cb = full_src + \
                        ("&" if "?" in full_src else "?") + \
                        "_t=" + str(int(time.time()))
                    _r2 = await tab.evaluate(
                        "(() => {const v=document.querySelector('video'); if(!v) return 'nov'; v.src=%s; v.muted=true; v.load(); v.play().catch(()=>{}); return 'cb-ok';})()" % json.dumps(_cb))
                    print("[v224] 35s: cache-buster重设:", str(_r2)[:60])
                except Exception as e:
                    print("[v224] 35s重设异常:", str(e)[:60])
            if w == 8:
                try:
                    await tab.evaluate("(() => {const v=document.querySelector('video'); if(v&&v.paused){v.play().catch(()=>{});} return true;})()")
                    print("[v224] 45s: play补刀")
                except Exception:
                    pass
        print("[v224] 本轮50s未起播, 重试(rnd=%d)" % rnd)
    return False


def _fmt_dur(sec):
    sec = int(sec)
    if sec >= 3600:
        return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)
    return "%02d:%02d" % (sec // 60, sec % 60)


async def brush_auto(browser, sec_guess, toc, done_this_run):
    """v227: 刷新页面->激活"自动续播视频"(=待刷节)->1.5x->监控->变绿。
    返回 (done_this_run, ok)"""
    no = sec_guess["no"]
    title = sec_guess.get("title", "")
    print("\n[v227] ===== 轮次: 预期节 %s %s =====" % (no, title))
    try:
        tab = await browser.get(URL4E)
    except Exception as e:
        print("[v227] 刷新失败, 重试:", str(e)[:80])
        await asyncio.sleep(3)
        tab = await browser.get(URL4E)
    await asyncio.sleep(30)

    # v228: 点击流(点击动作本身会向服务端上报"开始学习", 可能推动进度与续播指向)
    try:
        okc = await click_section(tab, no)
        print("[v228] 点击目标节 %s: %s" % (no, "已起播" if okc else "未起播(继续激活流)"))
    except Exception as eC:
        print("[v228] 点击异常:", str(eC)[:80])
    sC = await st(tab)
    if (sC.get("dur") or 0) == 0:
        # 刷新一次: 若点击已更新服务端"开始学习", 本次自动续播可能指向目标节
        try:
            tab = await browser.get(URL4E)
            await asyncio.sleep(30)
        except Exception:
            pass

    for act in range(3):
        s = await st(tab)
        d = s.get("dur") or 0
        print("[v227] 状态%d: dur=%s cur=%s src=%s" % (act + 1, d, s.get("cur"), str(s.get("srcHash"))))
        if d > 0:
            break
        full = str(s.get("srcFull") or "")
        if not full:
            await asyncio.sleep(8)
            continue
        print("[v227] 激活视频(清空复位+重设):", full[:110])
        try:
            await tab.evaluate("(() => {const v=document.querySelector('video'); if(v){v.pause(); v.removeAttribute('src'); v.load();} return true;})()")
            await asyncio.sleep(1)
            _u = json.dumps(full)
            await tab.evaluate(
                "(() => {const v=document.querySelector('video'); if(!v) return 'nov'; v.src=%s; v.muted=true; v.load(); v.play().catch(()=>{}); return 'ok';})()" % _u)
        except Exception as e:
            print("[v227] 激活异常:", str(e)[:80])
        await asyncio.sleep(15)

    s = await st(tab)
    dur = s.get("dur") or 0
    if dur == 0:
        print("[v227] 激活失败(dur=0), 本轮放弃: %s" % no)
        return done_this_run, False

    dur_s = _fmt_dur(dur)
    rno = no
    for x in toc:
        tt = str(x.get("title") or "")
        if dur_s and dur_s in tt:
            rno = x["no"]
            break
    print("[v227] 时长%ss(%s) -> 匹配节: %s" % (dur, dur_s, rno))
    no = rno

    ok15 = await set_speed_15(tab)
    print("[v227] 1.5倍速:", "成功" if ok15 else "失败(以当前速度继续)")

    s = await st(tab)
    dur = s.get("dur") or 0
    rate = s.get("rate") or 1
    max_wait = int(dur / max(rate, 0.5)) + 900
    t0 = time.time()
    last_cur = -1
    stuck = 0
    finished = False
    wprog({"stage": "刷课中(自动续播)", "sections": toc, "cur": "%s" % no,
           "done_this_run": done_this_run})
    while time.time() - t0 < max_wait:
        await asyncio.sleep(5)
        s = await st(tab)
        cur, d2, pz, qz, rt = s.get("cur", -1), s.get("dur", 0), s.get("paused"), s.get("aiQuiz"), s.get("rate")
        print("  [%4ds] cur=%s/%s rate=%s paused=%s quiz=%s" % (int(time.time() - t0), cur, d2, rt, pz, qz))
        if qz:
            print("  >> 弹题! 点选+关闭")
            await handle_quiz(tab)
            # 不continue: 继续走 paused 恢复逻辑(防弹窗误报卡死)
        if pz and d2 and d2 > 0:
            await tab.evaluate("(() => {const v=document.querySelector('video'); if(v&&v.paused){v.play().catch(()=>{});} return true;})()")
        if rt and rt != 1.5 and ok15:
            print("  >> rate掉回%s, 重设1.5" % rt)
            await set_speed_15(tab)
        if cur == last_cur:
            stuck += 1
        else:
            stuck = 0
        last_cur = cur
        if stuck >= 18:
            print("  >> 卡死90s, 补刀")
            try:
                await tab.evaluate("(() => {const v=document.querySelector('video'); if(v&&v.paused){v.play().catch(()=>{});} return true;})()")
            except Exception:
                pass
            stuck = 0
        if d2 and d2 > 0 and cur >= d2 - 1:
            print("  >> cur>=dur-1 播放完成!")
            finished = True
            break
        if cur and d2:
            pct_now = int(min(100, cur * 100 / d2))
            wprog({"stage": "刷课中(监控)", "sections": toc, "cur": "%s" % no,
                   "cur_pct": pct_now, "cur_pos": "%s/%s" % (cur, d2), "rate": rt,
                   "done_this_run": done_this_run})
    if not finished:
        print("[v227] 超时退出监控")
    if finished:
        print("[v227] 重读目录确认变绿(最多2.5分钟)...")
        green = await wait_section_green(tab, no, 150)
        print("[v227] 变绿确认:", "√ 已变绿" if green else "? 服务端延迟(下次复核)")
        if green:
            done_this_run += 1
        else:
            NO_GREEN.add(no)
            print("[v230] 已完成但未即时变绿, 本会话暂不重刷: %s" % no)
        toc2 = await read_toc(tab)
        wprog({"stage": "节完成", "sections": toc2, "cur": "", "done_this_run": done_this_run,
               "last_done": no, "green": green})
    return done_this_run, True


async def main():
    print("[v221] ========== 修复版引擎启动 ==========")
    print("[v221] 修复: 清缓存+--disable-quic(视频卡loading根因) | 闭环点击 | cur>=dur-1 | ZHS_ONLY=%s" %
          (ONLY or "(全量)"))
    # v221: 启动前清媒体缓存(修"视频卡loading": 缓存损坏+QUIC黑洞双修复)
    try:
        _default = os.path.join(UDD, "Default")
        for _d in ("Cache", "Media Cache", "Code Cache", "GPUCache"):
            _full = os.path.join(_default, _d)
            if os.path.isdir(_full):
                shutil.rmtree(_full, ignore_errors=True)
        for _lk in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            _lf = os.path.join(UDD, _lk)
            if os.path.exists(_lf):
                try:
                    os.remove(_lf)
                except Exception:
                    pass
        print("[v221] 媒体缓存/锁 已清理")
    except Exception as _e:
        print("[v221] 清缓存异常(忽略):", str(_e)[:80])
    browser = await nodriver.start(user_data_dir=UDD, headless=False, lang="zh-CN", no_sandbox=True, browser_args=["--disable-quic"])
    try:
        tab = await browser.get(URL4E)
        print("[v210] 等30s目录渲染...")
        await asyncio.sleep(30)
        toc = await read_toc(tab)
        # ★ 登录检测: 目录空时尝试自动登录
        if not toc:
            print("[v210] 目录为空, 检查登录态...")
            ok = await ensure_login(tab, ACC_LOGIN, PWD_LOGIN)
            if ok:
                print("[v210] 登录处理完成, 重新打开课程页...")
                tab = await browser.get(URL4E)
                await asyncio.sleep(30)
                toc = await read_toc(tab)
            else:
                print("[v210] 登录未完成, 放弃本次运行")
                return
        print("[v210] 初始目录:", [(x["no"], x["pct"]) for x in toc])
        wprog({"stage": "初始化", "sections": toc,
              "cur": "", "log": ["v210启动(修复版)"]})

        pend = [x for x in toc if not (
            x.get("pct") is None or (x.get("pct") or 0) >= 100)]
        if ONLY:
            pend = [x for x in pend if x["no"] == ONLY]
            if not pend:
                pend = [x for x in toc if x["no"] == ONLY]
        print("[v210] 待刷节:", [x["no"] for x in pend])

        done_this_run = 0
        skip_set = set()
        fail_cnt = {}
        it = 0
        while it < 30:
            it += 1
            toc = await read_toc(tab)
            pend = [x for x in toc if not (x.get("pct") is None or (x.get("pct") or 0) >= 100) and x["no"] not in skip_set and x["no"] not in NO_GREEN]
            if ONLY:
                pend = [x for x in pend if x["no"] == ONLY]
                if not pend:
                    pend = [x for x in toc if x["no"] == ONLY]
            print("\n[v227] ===== 迭代%d | 待刷: %s =====" % (it, [x["no"] for x in pend]))
            wprog({"stage": "轮次%d" % it, "sections": toc, "cur": "", "done_this_run": done_this_run,
                   "pending": [x["no"] for x in pend]})
            if not pend:
                # v233: 目录空/无待刷 -> 先复核登录态与页面(防"假完成")
                _t2 = await read_toc(tab)
                if not _t2:
                    print("[v233] 目录为空, 检测登录态/页面...")
                    _okl2 = await ensure_login(tab, ACC_LOGIN, PWD_LOGIN)
                    if _okl2:
                        try:
                            tab = await browser.get(URL4E)
                            await asyncio.sleep(30)
                        except Exception:
                            pass
                        toc = await read_toc(tab)
                        pend = [x for x in toc if not (
                            x.get("pct") is None or (x.get("pct") or 0) >= 100)
                            and x["no"] not in skip_set
                            and x["no"] not in NO_GREEN]
                        if ONLY:
                            pend = [x for x in pend if x["no"] == ONLY]
                        print("[v233] 复核后待刷:", [x["no"] for x in pend])
                    if not pend:
                        print("[v233] 复核后仍无待刷节, 正常结束")
                        break
                else:
                    break
            sec = pend[0]
            no0 = sec["no"]
            done_this_run, ok = await brush_auto(browser, sec, toc, done_this_run)
            if not ok:
                fail_cnt[no0] = fail_cnt.get(no0, 0) + 1
                print("[v227] 节 %s 激活失败计数=%d" % (no0, fail_cnt[no0]))
                if fail_cnt[no0] >= 3:
                    print("[v227] 节 %s 连续失败3次, 加入跳过" % no0)
                    skip_set.add(no0)
                await asyncio.sleep(5)

        toc = await read_toc(tab)
        print("\n[v227] ========== 全部完成 ==========")
        print("[v227] 最终目录:", [(x["no"], x["pct"]) for x in toc])
        print("[v227] 跳过(激活失败):", sorted(skip_set))
        wprog({"stage": "全部完成", "sections": toc, "cur": "", "done_this_run": done_this_run,
               "skipped": sorted(skip_set)})

    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
