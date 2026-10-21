# -*- coding: utf-8 -*-
"""大众云学 sliderValid 滑块求解器(2026-10-22 逆向实测)

协议(实测):
  POST {base}/train/common-slider/get-slider.gson
    data: havingfilenameKey=filename2&tokenKey=token2&location_y_Key=location_y_2
          &location_x_Key=location_x_2&checkSliderKey=checkSlider2
    resp.attribute: {shadow_width, shadow_height, slider(b64), bgImg(b64),
                     width, height, location_y}
  DOM: .slider-valid-bg-img(底图) / .slider-valid-sliderimg(滑块)
       .sliderContainer .slider(拖拽钮) / button.slider-valid-btn(点击完成验证)
  登录: POST {base}/train/login/login.gson (内联滑块校验, 拖完后需再点一次登录)

缺口X求解: 复用智慧树易盾 YidunSolver._detect_gap(Autovisor 边缘匹配),
  失败回退 ccorr_mask 模板匹配(实测 conf≈1.0)。
"""
import base64
import random
import time
from typing import Callable, Optional

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _decode_src(src: str) -> Optional[bytes]:
    """data:base64 → 原始字节(非data:前缀视为无效)"""
    if not src or not src.startswith("data:"):
        return None
    try:
        return base64.b64decode(src.split(",", 1)[1])
    except Exception:
        return None


def detect_gap_x(bg_bytes: bytes, fg_bytes: bytes) -> Optional[int]:
    """缺口左边缘x; 双算法: 易盾Autovisor优先, ccorr_mask兜底"""
    if cv2 is None:
        return None
    # ① 复用智慧树易盾缺口识别(Autovisor: 降噪+OTSU+Canny+matchTemplate)
    try:
        from logic.zhihuishu.yidun.yidun_solver import YidunSolver
        x = YidunSolver._detect_gap(bg_bytes, fg_bytes)
        if x and 5 < x < 300:
            return int(x)
    except Exception:
        pass
    # ② ccorr_mask 模板匹配(大众云学实测 conf≈1.0)
    try:
        bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
        fg = cv2.imdecode(np.frombuffer(fg_bytes, np.uint8),
                          cv2.IMREAD_UNCHANGED)
        if bg is None or fg is None:
            return None
        bgg = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
        if fg.ndim == 3 and fg.shape[2] == 4:
            fgg = cv2.cvtColor(fg[:, :, :3], cv2.COLOR_BGR2GRAY)
            mask = (fg[:, :, 3] > 50).astype(np.uint8) * 255
        else:
            fgg = cv2.cvtColor(fg, cv2.COLOR_BGR2GRAY)
            mask = None
        if mask is not None:
            r = cv2.matchTemplate(bgg, fgg, cv2.TM_CCORR_NORMED, mask=mask)
            r = np.nan_to_num(r)
            _, mv, _, ml = cv2.minMaxLoc(r)
            if mv > 0.9 and 5 < ml[0] < 300:
                return int(ml[0])
        r = cv2.matchTemplate(bgg, fgg, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(r)
        if 5 < ml[0] < 300:
            return int(ml[0])
    except Exception:
        pass
    return None


def _wait_slider_imgs(page, timeout: float = 8.0):
    """轮询等滑块图 src 为 data:(弹窗动画期 src 为空会取到页面URL)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = page.evaluate("""() => {
            const bg = document.querySelector('.slider-valid-bg-img');
            const sl = document.querySelector('.slider-valid-sliderimg');
            return {bg: bg ? bg.src : '', sl: sl ? sl.src : ''};
        }""")
        if r.get("bg", "").startswith("data:") and r.get("sl", "").startswith("data:"):
            return r
        page.wait_for_timeout(400)
    return None


def _human_drag(page, gap_x: int) -> bool:
    """拟人分段拖动滑块到 gap_x"""
    slider = page.query_selector('.sliderContainer .slider')
    if not slider:
        return False
    box = slider.bounding_box()
    if not box:
        return False
    sx = box["x"] + box["width"] / 2
    sy = box["y"] + box["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    steps = random.randint(18, 26)
    for i in range(1, steps + 1):
        page.mouse.move(sx + gap_x * i / steps + random.uniform(-0.4, 0.4),
                        sy + random.uniform(-0.6, 0.6))
        page.wait_for_timeout(random.randint(9, 26))
    page.mouse.move(sx + gap_x, sy)
    page.wait_for_timeout(random.randint(250, 500))
    page.mouse.up()
    page.wait_for_timeout(700)
    vbtn = page.query_selector('.slider-valid-btn')
    if vbtn:
        try:
            if vbtn.is_visible():
                vbtn.click()
                page.wait_for_timeout(1200)
                return True
        except Exception:
            pass
    return False


def solve_slider(page, log: Callable[[str], None] = lambda m: None,
                 max_attempts: int = 10) -> bool:
    """在当前已弹出滑块的页面上求解; 返回是否通过(调用方随后再点登录)"""
    for attempt in range(max_attempts):
        r = _wait_slider_imgs(page)
        if not r:
            log(f"滑块图未就绪(第{attempt + 1}次)")
            page.wait_for_timeout(800)
            continue
        bg = _decode_src(r["bg"])
        fg = _decode_src(r["sl"])
        if not bg:
            continue
        gx = detect_gap_x(bg, fg or b"") if fg else None
        if not gx:
            log(f"缺口识别失败(第{attempt + 1}次), 刷新滑块")
            try:
                page.query_selector('.refreshIcon').click()
                page.wait_for_timeout(1200)
            except Exception:
                pass
            continue
        log(f"缺口x={gx}, 拖动验证(第{attempt + 1}次)")
        _human_drag(page, gx)
        return True
    return False
