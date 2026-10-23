# -*- coding: utf-8 -*-
"""
日志模块 - 对应 Go 项目的 yatori-go-core/utils/log + LogModel.go
支持彩色控制台日志 + 文件日志输出
"""
import os
import re
import sys
import functools
import logging
import threading
from datetime import datetime
from typing import Any

# ============ 日志等级 ============
DEBUG = "DEBUG"
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"

# ============ ANSI 颜色代码 ============
Reset = "\033[0m"
Bold = "\033[1m"

Red = "\033[31m"
Green = "\033[32m"
Yellow = "\033[33m"
Blue = "\033[34m"
Purple = "\033[35m"
Cyan = "\033[36m"
White = "\033[37m"
Default = "\033[39m"
DarkGray = "\033[90m"

BoldRed = "\033[1;31m"
BoldGreen = "\033[1;32m"
BoldYellow = "\033[1;33m"
BoldBlue = "\033[1;34m"

# ============ 全局配置 ============
_current_level: str = INFO
_color_enabled: bool = True
_file_logger: logging.Logger = None
_log_file_sw: bool = False

_LEVEL_PRIORITY = {DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3}

# ============ 账号日志上下文 (threading.local, 每线程独立) ============
# 刷课线程开头 set_log_account(账号, 备注)，线程内所有日志自动带前缀并存账号独立文件
_account_ctx = threading.local()


def set_log_account(account: str, remark: str = ""):
    """绑定当前线程的日志账号上下文(刷课线程开头调用)

    绑定后: 日志行加 [账号|备注] 前缀(控制台+全局文件),
    同时写入独立文件 assets/logs/accounts/{账号}_{备注}/{日期}.log。
    """
    _account_ctx.account = str(account or "")
    _account_ctx.remark = str(remark or "")


def clear_log_account():
    """解除当前线程的账号上下文(线程结束/账号任务完成时调用)"""
    _account_ctx.account = ""
    _account_ctx.remark = ""


def _get_log_account_raw() -> tuple:
    """返回当前线程账号上下文 (account, remark)；无上下文返回 ("", "")"""
    return (getattr(_account_ctx, "account", ""),
            getattr(_account_ctx, "remark", ""))


def with_log_account(account: str, remark: str = ""):
    """返回包装器: 在被包装函数执行期间绑定账号日志上下文

    用法(包装已有函数传入线程):
        threading.Thread(
            target=with_log_account(user.account, user.remark_name)(_user_block),
            args=(setting, user, cache))
    效果: 函数执行期间日志自动带 [账号|备注] 前缀并写入账号独立文件;
    函数结束(含异常)时自动清除上下文。
    """
    def _deco(fn):
        @functools.wraps(fn)
        def _wrapper(*args, **kwargs):
            set_log_account(account, remark)
            try:
                return fn(*args, **kwargs)
            finally:
                clear_log_account()
        return _wrapper
    return _deco


def _account_prefix() -> str:
    """当前线程的日志前缀 '[账号|备注] '(无上下文返回空串)"""
    acc, remark = _get_log_account_raw()
    if not acc:
        return ""
    return f"[{acc}|{remark}] " if remark else f"[{acc}] "


# ============ 跨天自动切换的日志 Handler ============
# 2026-09-30: 修复"系统时间过0点后仍写旧日志文件"的bug。
# 每次 emit 检查日期, 跨天自动切到 {新日期}.log; 单日超 max_bytes 仍按旧规则轮转。

class _DailyRotatingHandler(logging.Handler):
    """全局日志文件 handler: {log_dir}/{日期}.log

    - 跨天自动切换新文件(0点后第一条日志即写新日期文件)
    - 单日超 100MB 轮转 {日期}.log.1 ~ .5(与旧 RotatingFileHandler 行为一致)
    """

    def __init__(self, log_dir: str, max_bytes: int = 100 * 1024 * 1024,
                 backup_count: int = 5):
        logging.Handler.__init__(self)
        self._log_dir = log_dir
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._current_date = None
        self._current_path = None
        self._stream = None
        self._written = 0

    def _open_for(self, date_str: str):
        path = os.path.join(self._log_dir, f"{date_str}.log")
        os.makedirs(self._log_dir, exist_ok=True)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        self._stream = open(path, "a", encoding="utf-8", errors="replace")
        self._current_path = path
        self._current_date = date_str
        self._written = size

    def _close_file(self):
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _ensure_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._stream is None or today != self._current_date:
            self._close_file()
            self._open_for(today)

    def _rotate(self):
        self._close_file()
        base = self._current_path
        for i in range(self._backup_count - 1, 0, -1):
            src = f"{base}.{i}"
            if os.path.exists(src):
                try:
                    os.replace(src, f"{base}.{i + 1}")
                except OSError:
                    pass
        try:
            os.replace(base, f"{base}.1")
        except OSError:
            pass
        self._open_for(self._current_date or
                       datetime.now().strftime("%Y-%m-%d"))

    def emit(self, record):
        try:
            data = self.format(record) + "\n"
            n = len(data.encode("utf-8", errors="replace"))
            with self.lock:
                self._ensure_today()
                if (self._max_bytes > 0 and self._written > 0
                        and self._written + n > self._max_bytes):
                    self._rotate()
                if self._stream is not None:
                    self._stream.write(data)
                    self._stream.flush()
                    self._written += n
        except Exception:
            self.handleError(record)

    def close(self):
        with self.lock:
            self._close_file()
        logging.Handler.close(self)


class _AccountFileHandler(logging.Handler):
    """账号独立日志 handler: {log_dir}/accounts/{账号}_{备注}/{日期}.log

    - 每线程从上下文读取账号, 多账号并发时按账号分文件、各自独立流
    - 跨天自动切换 + 单日 100MB 轮转
    - 无线程账号上下文时静默跳过(不产生文件)
    """

    def __init__(self, log_dir: str, max_bytes: int = 100 * 1024 * 1024,
                 backup_count: int = 5):
        logging.Handler.__init__(self)
        self._log_dir = log_dir
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._streams = {}   # (account, remark) -> {date, path, stream, written}

    @staticmethod
    def _safe(name: str) -> str:
        """文件夹名安全化(去非法字符)"""
        s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "")).strip("._")
        return s or "unknown"

    def emit(self, record):
        try:
            acc, remark = _get_log_account_raw()
            if not acc:
                return
            data = self.format(record) + "\n"
            n = len(data.encode("utf-8", errors="replace"))
            key = (acc, remark)
            today = datetime.now().strftime("%Y-%m-%d")
            with self.lock:
                st = self._streams.get(key)
                if st is None or st["date"] != today or st["stream"] is None:
                    if st and st.get("stream"):
                        try:
                            st["stream"].close()
                        except Exception:
                            pass
                    dir_name = (self._safe(acc) + "_" + self._safe(remark)
                                if remark else self._safe(acc))
                    path = os.path.join(self._log_dir, "accounts",
                                        dir_name, f"{today}.log")
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    size = os.path.getsize(path) if os.path.exists(path) else 0
                    st = {"date": today, "path": path, "written": size,
                          "stream": open(path, "a", encoding="utf-8",
                                         errors="replace")}
                    self._streams[key] = st
                if (self._max_bytes > 0 and st["written"] > 0
                        and st["written"] + n > self._max_bytes):
                    st["stream"].close()
                    base = st["path"]
                    for i in range(self._backup_count - 1, 0, -1):
                        src = f"{base}.{i}"
                        if os.path.exists(src):
                            try:
                                os.replace(src, f"{base}.{i + 1}")
                            except OSError:
                                pass
                    try:
                        os.replace(base, f"{base}.1")
                    except OSError:
                        pass
                    st["stream"] = open(base, "a", encoding="utf-8",
                                        errors="replace")
                    st["written"] = 0
                st["stream"].write(data)
                st["stream"].flush()
                st["written"] += n
        except Exception:
            self.handleError(record)

    def close(self):
        with self.lock:
            for st in self._streams.values():
                try:
                    st["stream"].close()
                except Exception:
                    pass
            self._streams.clear()
        logging.Handler.close(self)


def setup_stdio_encoding():
    """控制台/重定向输出编码加固(跨平台安全)

    Windows 下 stdout 被重定向到文件/管道时会改用本地编码(如GBK),
    打印非GBK字符(emoji/生僻字等)会抛 UnicodeEncodeError;
    此处统一改为 errors=replace, 无法编码的字符替换为'?'而不崩溃。
    Linux/macOS 原生UTF-8无影响。可重复调用。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass


def log_init(level: str = "INFO", log_file_sw: bool = True,
             color_log: bool = True, log_dir: str = "./assets/logs"):
    """
    初始化日志系统
    :param level: 日志等级 (DEBUG/INFO/WARNING/ERROR)
    :param log_file_sw: 是否输出日志文件
    :param color_log: 是否启用彩色日志
    :param log_dir: 日志文件目录(全局文件 {日期}.log; 账号文件 accounts/{账号}_{备注}/{日期}.log)
    """
    global _current_level, _color_enabled, _file_logger, _log_file_sw

    _current_level = level.upper()
    _color_enabled = (color_log is True) or (color_log == 1)
    _log_file_sw = (log_file_sw is True) or (log_file_sw == 1)

    # 控制台编码加固: 防 Windows 重定向(GBK)下生僻字符/emoji 打印崩溃
    setup_stdio_encoding()

    if _log_file_sw:
        os.makedirs(log_dir, exist_ok=True)

        _file_logger = logging.getLogger("yatori_file_logger")
        _file_logger.setLevel(logging.DEBUG)
        # 防冒泡到 root(避免 lib 自带 handler 重复输出)
        _file_logger.propagate = False
        # 防重复添加 handler(重复 log_init 时)
        for _h in list(_file_logger.handlers):
            try:
                _h.close()
            except Exception:
                pass
        _file_logger.handlers.clear()

        # 全局日志 handler: {log_dir}/{日期}.log
        # 2026-09-30: 自研跨天切换 handler 替代 RotatingFileHandler,
        # 修复"系统时间过0点后仍写旧日志文件"的bug; 单日100MB轮转保留
        handler = _DailyRotatingHandler(log_dir)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _file_logger.addHandler(handler)

        # 账号独立日志 handler: {log_dir}/accounts/{账号}_{备注}/{日期}.log
        # (仅在刷课线程绑定了账号上下文时生效)
        acc_handler = _AccountFileHandler(log_dir)
        acc_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _file_logger.addHandler(acc_handler)


def string_to_log_level(s: str) -> str:
    """字符串转日志等级"""
    s = s.upper()
    if s in _LEVEL_PRIORITY:
        return s
    return INFO


def _should_log(level: str) -> bool:
    """判断是否应该输出该等级的日志"""
    return _LEVEL_PRIORITY.get(level, 1) >= _LEVEL_PRIORITY.get(_current_level, 1)


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码"""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', str(text))


def log_print(level: str, *args: Any):
    """
    打印日志 - 对应 Go 的 lg.Print()
    支持混合颜色代码和文本参数
    用法: log_print(INFO, "[", Green, "username", Default, "] ", "消息内容")
    """
    if not _should_log(level):
        return

    # 构建输出文本
    parts = []
    for arg in args:
        parts.append(str(arg))

    raw_text = "".join(parts)

    # 账号上下文前缀(刷课线程内自动带 [账号|备注] )
    prefix = _account_prefix()

    # 构建带时间戳的控制台输出
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_tag = f"[{level}]"

    if _color_enabled:
        if prefix:
            console_text = (f"{DarkGray}{timestamp}{Reset} {level_tag} "
                            f"{Cyan}{prefix}{Reset}{raw_text}")
        else:
            console_text = f"{DarkGray}{timestamp}{Reset} {level_tag} {raw_text}"
    else:
        console_text = f"{timestamp} {level_tag} {prefix}{_strip_ansi(raw_text)}"

    try:
        print(console_text, flush=True)
    except UnicodeEncodeError:
        # 兜底: 控制台编码无法表示的部分用'?'替代(不中断任务)
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            print(console_text.encode(enc, errors="replace")
                  .decode(enc, errors="replace"), flush=True)
        except Exception:
            pass

    # 写入文件日志（去除ANSI）
    # 全局文件带前缀; 账号独立文件由 _AccountFileHandler 按账号上下文自动分流
    if _log_file_sw and _file_logger:
        plain_text = f"{level_tag} {prefix}{_strip_ansi(raw_text)}"
        _file_logger.info(plain_text)


def model_print(is_sw: bool, level: str, *args: Any):
    """
    条件打印 - 对应 Go 的 ModelPrint()
    只在 is_sw 为 True 时打印
    """
    if is_sw:
        log_print(level, *args)


# ============ uvicorn 日志接入(access log 落盘) ============

def build_uvicorn_log_config(log_dir: str = "./assets/logs") -> dict:
    """构建 uvicorn 的 log_config: 访问日志与错误日志全部写入全局日志文件

    2026-09-30: 需求——保存诸如
        INFO: 127.0.0.1:50105 - "GET /api/v1/logTail?..." 200 OK
    的 uvicorn 访问日志(一条不漏, 存全局文件), 且同样支持跨天自动切换。

    实现: uvicorn / uvicorn.access / uvicorn.error 的 handler 指向
    全局日志文件(与业务日志同一 {日期}.log), access 保持原生格式;
    控制台也保留输出(沿用 uvicorn 默认 StreamHandler)。
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": None,
            },
            "file_plain": {"format": "%(asctime)s %(message)s"},
            # [2026-10-24] uvicorn.access 专用文件格式: AccessFormatter会把 record.args
            # 改写为3元组, 若与普通file handler共用标准Formatter会报
            # "not enough arguments for format string" 刷屏
            "access_file": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(asctime)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "()": "utils.log._DailyRotatingHandler",
                "log_dir": log_dir,
                "formatter": "file_plain",
            },
            "file_access": {
                "()": "utils.log._DailyRotatingHandler",
                "log_dir": log_dir,
                "formatter": "access_file",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default", "file"], "level": "INFO",
                        "propagate": False},
            "uvicorn.error": {"handlers": ["default", "file"],
                              "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access", "file_access"],
                               "level": "INFO", "propagate": False},
        },
    }
