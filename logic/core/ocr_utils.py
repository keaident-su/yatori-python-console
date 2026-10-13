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
    - GPU 自适应: 平台自适应选后端(Windows→DirectML / macOS→CoreML /
      Linux→CUDA 等), 注入 rapidocr 内部 ORT 会话; 探针验证失败自动回落 CPU
"""
import threading
from typing import Any, List, Optional

_engine: Any = None
_engine_kind: str = ""          # "rapidocr" | "ddddocr" | ""
_engine_providers: List[str] = []   # 实际生效的 ORT 执行后端
_init_lock = threading.Lock()
_warned = False
_gpu_logged = False


def _gpu_providers():
    """当前可用的 GPU 执行后端(平台自适应单一事实源, 空=仅 CPU)"""
    try:
        from logic.core.gpu_accel import detect, pick_ort_providers
        if not detect().get("has_gpu"):
            return []
        return list(pick_ort_providers() or [])
    except Exception:
        return []


def _construct_rapidocr(providers=None):
    """构造 RapidOCR 引擎; providers 非空时注入到其内部 ORT 会话

    做法: 临时替换 rapidocr.utils 模块内的 InferenceSession 符号,
    使 rapidocr 自建的三个会话(det/rec/cls)都使用我们选定的执行后端。
    与 rapidocr 版本解耦(1.2.x 等), 构造完立即还原; 任何异常均不抛出。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    if not providers:
        try:
            return RapidOCR()
        except Exception:
            return None
    try:
        from rapidocr_onnxruntime import utils as _rr_utils
        avail = set()
        try:
            import onnxruntime as _ort
            avail = set(_ort.get_available_providers())
        except Exception:
            pass
        use = [p for p in providers if p in avail]
        if not use:
            return RapidOCR()
        _orig = _rr_utils.InferenceSession

        class _GpuSession(_orig):
            """把 rapidocr 的 providers 换成我们的 GPU 后端(保留其 CPU 配置)"""

            def __init__(self, path_or_bytes, sess_options=None,
                         providers=None, **kwargs):
                cpu_entries = []
                for item in (providers or []):
                    name = (item[0] if isinstance(item, (list, tuple)) and item
                            else item)
                    if name == "CPUExecutionProvider":
                        cpu_entries.append(item)
                if not cpu_entries:
                    cpu_entries = ["CPUExecutionProvider"]
                merged = [(p, {"device_id": 0})
                          for p in use] + cpu_entries
                try:
                    super().__init__(path_or_bytes, sess_options=sess_options,
                                     providers=merged, **kwargs)
                except Exception:
                    # 注入失败(如后端不可用): 退回 rapidocr 原始 providers
                    super().__init__(path_or_bytes, sess_options=sess_options,
                                     providers=providers, **kwargs)

        _rr_utils.InferenceSession = _GpuSession
        try:
            return RapidOCR()
        finally:
            _rr_utils.InferenceSession = _orig
    except Exception:
        try:
            return RapidOCR()
        except Exception:
            return None


def _probe_engine(eng) -> bool:
    """最小图真实推理一次, 验证会话可用

    防"会话假可用": 例如 CUDA provider 缺 cuDNN 时建会话成功但推理崩溃。
    """
    try:
        import io
        import numpy as np
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(
            np.full((24, 80, 3), 255, dtype=np.uint8)).save(buf, "PNG")
        eng(buf.getvalue())
        return True
    except Exception:
        return False


def _real_providers(eng) -> list:
    """从引擎内部会话读取真实生效的执行后端(用于日志/验证, 避免声明与实际不符)

    注: rapidocr 不同子模块存会话的属性名不同(rec=session, det/cls=infer),
    两种都尝试。
    """
    out = []
    for attr in ("text_detector", "text_recognizer", "text_cls"):
        obj = getattr(eng, attr, None)
        if obj is None:
            continue
        holder = None
        for hattr in ("session", "infer"):
            cand = getattr(obj, hattr, None)
            if cand is not None:
                holder = cand
                break
        raw = getattr(holder, "session", None) if holder is not None else None
        if raw is None and hasattr(holder, "get_providers"):
            raw = holder
        try:
            names = raw.get_providers() if raw is not None else []
        except Exception:
            names = []
        for p in names:
            if p not in out:
                out.append(p)
    return out


def _try_init_rapidocr():
    """初始化 rapidocr 引擎, 返回 (engine, 实际生效的 GPU 后端列表)

    按平台后端优先级逐档尝试([p1,p2] → [p2] → CPU), 每档均以最小图探针验证,
    验证失败自动降档(防"会话假可用"); 任何异常均不抛出。
    """
    providers = _gpu_providers()
    for i in range(len(providers)):
        subset = providers[i:]
        eng = _construct_rapidocr(subset)
        if eng is not None and _probe_engine(eng):
            real = _real_providers(eng)
            return eng, (real or subset)
    eng = _construct_rapidocr(None)
    if eng is None:
        return None, []
    return eng, _real_providers(eng)


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
    global _engine, _engine_kind, _engine_providers
    if _engine is not None:
        return _engine
    with _init_lock:
        if _engine is not None:
            return _engine
        eng, used = _try_init_rapidocr()
        if eng is not None:
            _engine = eng
            _engine_kind = "rapidocr"
            _engine_providers = list(used)
            _log_gpu_once(_engine_providers)
            return _engine
        eng = _try_init_ddddocr()
        if eng is not None:
            _engine = eng
            _engine_kind = "ddddocr"
            _engine_providers = []
            _log_gpu_once(_engine_providers)
            return _engine
    return None


def active_providers() -> list:
    """当前 OCR 引擎实际使用的执行后端(便于日志/排查确认 GPU 是否生效)"""
    return list(_engine_providers)


def _log_gpu_once(providers=None):
    """首次启用 OCR 时打印一次硬件加速状态(便于用户确认 GPU 是否生效)"""
    global _gpu_logged
    try:
        if _gpu_logged:
            return
        _gpu_logged = True
        from logic.core.gpu_accel import summary
        s = summary()
        if s:
            print(f"[OCR] {s}")
        if providers is None:
            return
        gpu_on = [p for p in providers if p != "CPUExecutionProvider"]
        if gpu_on:
            print(f"[OCR] 推理后端: {', '.join(providers)}  — GPU 加速已生效")
        elif providers:
            print("[OCR] 推理后端: CPU（未启用 GPU）")
    except Exception:
        pass


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
