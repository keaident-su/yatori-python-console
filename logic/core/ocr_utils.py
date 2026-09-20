# -*- coding: utf-8 -*-
"""本地图片OCR工具 - 用于识别以图片形式给出的题目/选项文本

引擎优先级:
    1) rapidocr_onnxruntime (PaddleOCR 的 ONNX 移植, 精度高,
       wheel 内置模型, 离线可用, 无需下载) —— 首选
    2) ddddocr (轻量验证码识别, wheel 内置模型) —— 降级备选

设计要点:
    - 引擎懒加载 + 单例 + 线程安全, 避免拖慢启动
    - 重依赖(onnxruntime/numpy/PIL)仅在真正识别时导入
    - 缺库时优雅降级: 返回空串并仅提示一次
"""
import threading
from typing import Any, Optional

_engine: Any = None
_engine_kind: str = ""          # "rapidocr" | "ddddocr" | ""
_init_lock = threading.Lock()
_warned = False


def _try_init_rapidocr():
    """尝试初始化 rapidocr_onnxruntime 引擎, 失败返回 None"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    try:
        return RapidOCR()
    except Exception:
        return None


def _try_init_ddddocr():
    """尝试初始化 ddddocr 引擎, 失败返回 None"""
    try:
        import ddddocr
    except Exception:
        return None
    try:
        return ddddocr.DdddOcr(show_ad=False)
    except Exception:
        try:
            return ddddocr.DdddOcr()
        except Exception:
            return None


def _get_engine():
    """懒加载单例引擎(线程安全)"""
    global _engine, _engine_kind
    if _engine is not None:
        return _engine
    with _init_lock:
        if _engine is not None:
            return _engine
        eng = _try_init_rapidocr()
        if eng is not None:
            _engine = eng
            _engine_kind = "rapidocr"
            return _engine
        eng = _try_init_ddddocr()
        if eng is not None:
            _engine = eng
            _engine_kind = "ddddocr"
            return _engine
    return None


def ocr_available() -> bool:
    """是否安装了任一本地OCR依赖(不触发引擎加载)"""
    import importlib.util
    try:
        if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
            return True
        if importlib.util.find_spec("ddddocr") is not None:
            return True
    except Exception:
        return False
    return False


def warn_missing_once():
    """缺库时仅提示一次"""
    global _warned
    if _warned:
        return
    _warned = True
    try:
        from utils.log import log_print, INFO, Yellow, Default
        log_print(INFO, "[OCR]", "[", Yellow, "提示", Default, "] ",
                  Yellow, "未检测到本地OCR依赖(rapidocr-onnxruntime/ddddocr)，"
                          "图片形式的题目/选项将无法识别。"
                          "可执行 pip install rapidocr-onnxruntime 启用。")
    except Exception:
        pass


def _rapidocr_run(eng, img_bytes: bytes) -> str:
    result = None
    ok = False
    try:
        out = eng(img_bytes)
        ok = True
        result = out[0] if isinstance(out, (list, tuple)) and out else None
    except Exception:
        ok = False
    if not ok:
        # 部分版本不支持 bytes 入参, 回退为 ndarray
        try:
            import io
            import numpy as np
            from PIL import Image
            arr = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
            out = eng(arr)
            result = out[0] if isinstance(out, (list, tuple)) and out else None
        except Exception:
            result = None
    if not result:
        return ""
    lines = []
    for item in result:
        try:
            text = item[1]
        except Exception:
            text = ""
        if text:
            lines.append(str(text))
    return " ".join(lines).strip()


def _ddddocr_run(eng, img_bytes: bytes) -> str:
    try:
        text = eng.classification(img_bytes)
        return (text or "").strip()
    except Exception:
        return ""


def ocr_bytes(img_bytes: Optional[bytes]) -> str:
    """识别图片字节中的文字, 失败/无引擎时返回空串

    :param img_bytes: 图片原始字节
    :return: 识别出的文本(多行以空格连接)
    """
    if not img_bytes:
        return ""
    eng = _get_engine()
    if eng is None:
        warn_missing_once()
        return ""
    try:
        if _engine_kind == "rapidocr":
            return _rapidocr_run(eng, img_bytes)
        return _ddddocr_run(eng, img_bytes)
    except Exception:
        return ""


def current_engine() -> str:
    """返回当前已加载的引擎名称(未加载返回空串)"""
    return _engine_kind
