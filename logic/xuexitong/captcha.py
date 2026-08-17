# -*- coding: utf-8 -*-
"""超星 cx_captcha 滑块验证码处理
对应 Go aggregation/xuexitong/XueXiTongSliderAction.go + captcha_retry.go
纯标准库实现：PNG解码(zlib+struct) + NCC归一化互相关模板匹配，零第三方依赖
流程: get/conf(服务器时间) → get/verification/image(token+双图) →
      下载双图 → NCC识别偏移 → check/verification/result → validate
"""
import hashlib
import json
import math
import random
import re
import struct
import time
import uuid as _uuid_mod
import zlib

from logic.xuexitong import api as xxt_api
from utils.log import log_print, INFO, Green, Yellow, Red, Default

# 优先用PIL解码(支持JPEG/PNG)；无PIL时回退纯标准库PNG解码
# 超星滑块背景图为JPEG，裁剪图为PNG，生产环境必须安装Pillow
try:
    from PIL import Image as _PILImage
    import io as _io
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ============ PNG 解码（纯标准库，支持 8位 color_type 0/2/3/4/6） ============

def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_gray_alpha(data: bytes):
    """解码 PNG 为 (灰度矩阵, alpha矩阵)
    支持 8位 color_type 0/2/3/4/6；无alpha通道时alpha全255
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是有效的PNG数据")
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    palette = b""
    idat = bytearray()
    n = len(data)
    while pos + 8 <= n:
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = \
                struct.unpack(">IIBBBBB", chunk[:13])
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if bit_depth != 8 or interlace != 0:
        raise ValueError(
            f"不支持的PNG: bit_depth={bit_depth} interlace={interlace}")
    ch_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in ch_map:
        raise ValueError(f"不支持的PNG color_type={color_type}")
    ch = ch_map[color_type]
    stride = width * ch
    raw = zlib.decompress(bytes(idat))

    # 反滤波 + 灰度化 + alpha提取
    rows = []
    alpha_rows = []
    prev = bytearray(stride)
    off = 0
    for _y in range(height):
        f = raw[off]
        off += 1
        line = bytearray(raw[off:off + stride])
        off += stride
        if f == 1:  # Sub
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:  # Average
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:  # Paeth
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                up_left = prev[i - ch] if i >= ch else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        prev = line

        row = [0.0] * width
        arow = [255] * width
        if color_type == 0:  # 灰度
            for x in range(width):
                row[x] = float(line[x])
        elif color_type == 2:  # RGB
            for x in range(width):
                i = x * 3
                row[x] = (0.299 * line[i] + 0.587 * line[i + 1]
                          + 0.114 * line[i + 2])
        elif color_type == 3:  # 调色板
            for x in range(width):
                i = line[x] * 3
                if i + 2 < len(palette):
                    row[x] = (0.299 * palette[i] + 0.587 * palette[i + 1]
                              + 0.114 * palette[i + 2])
        elif color_type == 4:  # 灰度+alpha
            for x in range(width):
                i = x * 2
                row[x] = float(line[i])
                arow[x] = line[i + 1]
        else:  # color_type == 6: RGBA
            for x in range(width):
                i = x * 4
                row[x] = (0.299 * line[i] + 0.587 * line[i + 1]
                          + 0.114 * line[i + 2])
                arow[x] = line[i + 3]
        rows.append(row)
        alpha_rows.append(arow)
    return rows, alpha_rows


def _downsample2(m):
    """2倍降采样（2x2块均值），降低纯Python NCC计算量"""
    h = len(m)
    w = len(m[0])
    h2, w2 = h // 2, w // 2
    return [[(m[y * 2][x * 2] + m[y * 2][x * 2 + 1]
              + m[y * 2 + 1][x * 2] + m[y * 2 + 1][x * 2 + 1]) * 0.25
             for x in range(w2)] for y in range(h2)]


def _downsample2_mask(m):
    """2倍降采样alpha掩码（2x2块均值≥128记1）"""
    h = len(m)
    w = len(m[0])
    h2, w2 = h // 2, w // 2
    return [[1 if (m[y * 2][x * 2] + m[y * 2][x * 2 + 1]
                   + m[y * 2 + 1][x * 2] + m[y * 2 + 1][x * 2 + 1]) >= 512 else 0
             for x in range(w2)] for y in range(h2)]


# ============ alpha掩码NCC归一化互相关模板匹配 ============
# 关键修正: 裁剪图透明区域必须从NCC中剔除 —— 若置黑参与计算，深色背景
# (如暗色海水)会与透明黑块高相关，产生错误峰值(选中诱饵缺口)，
# 导致服务器报 verification error

def _ncc_match_masked(src, tpl, mask):
    """带掩码的归一化互相关匹配，返回 (best_x, best_score)
    仅模板中不透明像素参与计算
    """
    h1, w1 = len(src), len(src[0])
    h2, w2 = len(tpl), len(tpl[0])
    if h2 > h1 or w2 > w1:
        raise ValueError("裁剪图大于背景图，无法匹配")

    # 模板统计量(仅掩码内)为常数，预计算一次
    num = 0
    tpl_sum = 0.0
    tpl_sum2 = 0.0
    for j in range(h2):
        trow = tpl[j]
        mrow = mask[j]
        for i in range(w2):
            if mrow[i]:
                num += 1
                v = trow[i]
                tpl_sum += v
                tpl_sum2 += v * v
    if num == 0:
        raise ValueError("裁剪图无有效像素")
    mean_b = tpl_sum / num
    tpl_var_term = tpl_sum2 - num * mean_b * mean_b

    best_x = 0
    best_score = -2.0
    for y in range(h1 - h2 + 1):
        for x in range(w1 - w2 + 1):
            sum_src = 0.0
            sum_src2 = 0.0
            sum_mul = 0.0
            for j in range(h2):
                srow = src[y + j]
                trow = tpl[j]
                mrow = mask[j]
                for i in range(w2):
                    if mrow[i]:
                        a = srow[x + i]
                        b = trow[i]
                        sum_src += a
                        sum_src2 += a * a
                        sum_mul += a * b
            mean_a = sum_src / num
            numerator = sum_mul - num * mean_a * mean_b
            denom_v = (sum_src2 - num * mean_a * mean_a) * tpl_var_term
            if denom_v <= 0:
                continue
            score = numerator / math.sqrt(denom_v + 1e-9)
            if score > best_score:
                best_score = score
                best_x = x
    return best_x, best_score


def detect_slide_offset(bg_png: bytes, cut_png: bytes) -> int:
    """计算滑块偏移量 - 对应 Go DetectSlideOffset (结果 -5)
    alpha掩码NCC + 2倍降采样，偏移换算回全分辨率
    """
    bg, _bg_a = _decode_image_gray_alpha(bg_png)
    cut, cut_a = _decode_image_gray_alpha(cut_png)
    bg2 = _downsample2(bg)
    cut2 = _downsample2(cut)
    mask2 = _downsample2_mask(cut_a)
    best_x, _score = _ncc_match_masked(bg2, cut2, mask2)
    return best_x * 2 - 5


def _decode_image_gray_alpha(data: bytes):
    """图片解码为 (灰度矩阵, alpha矩阵)：有PIL用PIL(支持JPEG)，否则回退纯Python PNG"""
    if _HAS_PIL:
        with _PILImage.open(_io.BytesIO(data)) as img:
            rgba = img.convert("RGBA")
        w, h = rgba.size
        px = rgba.load()
        rows = []
        alpha_rows = []
        for y in range(h):
            row = [0.0] * w
            arow = [255] * w
            for x in range(w):
                r, g, b, a = px[x, y]
                row[x] = 0.299 * r + 0.587 * g + 0.114 * b
                arow[x] = a
            rows.append(row)
            alpha_rows.append(arow)
        return rows, alpha_rows
    return _decode_png_gray_alpha(data)


# ============ 滑块验证编排（对应 Go XueXiTSlider.Pass + captcha_retry.go） ============

# 偏移修正探测表: 第N次重试使用 delta[N-1]，x_submit = x_detect + delta
# 超星滑块容差有限，通过多候选探测确定服务器接受的修正量
_OFFSET_DELTAS = [0, -2, 2, -5, 5]


def _pass_slider_once(cache, captcha_id: str, referer: str,
                      offset_delta: int = 0) -> str:
    """完整过一次滑块，成功返回 validate 凭证"""
    # 第一步: 拉取配置(服务器时间t)
    conf_body = xxt_api.cx_captcha_conf_api(cache, captcha_id, retry=3)
    m = re.search(r'"t":(\d+).*?"captchaId":"([^"]+)"', conf_body or "")
    if not m:
        raise RuntimeError(
            f"滑块配置响应异常: {(conf_body or '')[:200]}")
    server_time = m.group(1)

    # 动态iv: 官方前端JS iv=md5(captchaId+"slide"+当前毫秒+uuid)，
    # image接口上报后服务器记录，check时必须传同一iv，否则 verification error
    iv = hashlib.md5(
        (captcha_id + "slide" + str(int(time.time() * 1000))
         + str(_uuid_mod.uuid4())).encode()).hexdigest()

    # 第二步: 拉取验证码图片信息(token/背景图/裁剪图)
    img_body = xxt_api.cx_captcha_img_api(
        cache, captcha_id, server_time, referer, iv=iv, retry=3)
    m2 = re.search(r'cx_captcha_function\((\{.*\})\)', img_body or "")
    if not m2:
        raise RuntimeError(
            f"滑块图片响应缺少JSON: {(img_body or '')[:200]}")
    obj = json.loads(m2.group(1))
    token = obj.get("token", "")
    vo = obj.get("imageVerificationVo") or {}
    shade_url = vo.get("shadeImage", "")
    cutout_url = vo.get("cutoutImage", "")
    if not token or not shade_url or not cutout_url:
        raise RuntimeError("滑块图片响应缺少token/图片字段")

    # 第三步: 下载双图 → 识别偏移 → 提交校验
    shade = xxt_api.pull_cx_slider_img_api(cache, shade_url, retry=5)
    cutout = xxt_api.pull_cx_slider_img_api(cache, cutout_url, retry=5)
    x = detect_slide_offset(shade, cutout) + offset_delta
    # 拟人延时: 真人滑动从拉图到提交至少间隔数百毫秒，立即提交易触发风控
    time.sleep(random.uniform(0.8, 1.8))
    pass_body = xxt_api.pass_cx_slider_api(
        cache, captcha_id, token, x, iv=iv, referer=referer, retry=3)
    m3 = re.search(r'cx_captcha_function\((\{.*\})\)', pass_body or "")
    if not m3:
        raise RuntimeError(
            f"滑块校验响应缺少JSON: {(pass_body or '')[:200]}")
    pobj = json.loads(m3.group(1))
    if pobj.get("result") is True:
        extra = pobj.get("extraData")
        if extra is None:
            raise RuntimeError("滑块校验响应缺少 extraData")
        # extraData 是字符串，需要二次解析（对齐Go）
        extra_obj = json.loads(extra) if isinstance(extra, str) else extra
        validate = extra_obj.get("validate") if isinstance(
            extra_obj, dict) else None
        if not validate:
            raise RuntimeError("滑块校验响应缺少 validate")
        return validate
    raise RuntimeError(f"滑块校验未通过: {(pass_body or '')[:200]}")


def pass_cx_slider_captcha(cache, captcha_id: str, referer: str,
                           attempts: int = 5, log_tag: str = "") -> str:
    """对应 Go captcha_retry.go passSliderCaptcha (defaultCaptchaAttempts=5)
    失败或 validate 为空都重试，全部失败抛出 RuntimeError
    """
    last_err = "未知错误"
    for i in range(1, attempts + 1):
        try:
            delta = _OFFSET_DELTAS[(i - 1) % len(_OFFSET_DELTAS)]
            validate = _pass_slider_once(
                cache, captcha_id, referer, offset_delta=delta)
            if validate:
                if log_tag:
                    log_print(INFO, log_tag, Green,
                              f"滑块验证通过(第{i}次尝试)")
                return validate
            last_err = "validate为空"
        except Exception as e:
            last_err = str(e)
        if log_tag:
            log_print(INFO, log_tag, Yellow,
                      f"滑块验证第{i}/{attempts}次失败: {last_err}")
    raise RuntimeError(f"滑块验证{attempts}次均失败: {last_err}")
