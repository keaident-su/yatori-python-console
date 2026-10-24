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
        # (account, remark) -> {date, path, stream, written}
        self._streams = {}

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
        handler.setFormatter(StandardFormatter())
        _file_logger.addHandler(handler)

        # 账号独立日志 handler: {log_dir}/accounts/{账号}_{备注}/{日期}.log
        # (仅在刷课线程绑定了账号上下文时生效)
        acc_handler = _AccountFileHandler(log_dir)
        acc_handler.setFormatter(StandardFormatter())
        _file_logger.addHandler(acc_handler)

        # [V3.0.10] 历史日志一次性原位转换为标准格式(后台线程, 不阻塞启动)
        try:
            start_legacy_migration_async(log_dir)
        except Exception:
            pass


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


# ============ [2026-10-24 V3.0.10] 标准日志格式(用户规范) ============
# 格式: [ISO8601毫秒+时区] [LEVEL] [模块] [线程] [账号] 消息
# 多行(堆栈/详情)每行缩进4空格; \t 转义为 \\t; 文件纯文本, 终端可选彩色。
def _iso_ts(created: float = None) -> str:
    """ISO 8601 带毫秒带时区"""
    try:
        dt = (datetime.fromtimestamp(created) if created is not None
              else datetime.now()).astimezone()
        return dt.isoformat(timespec="milliseconds")
    except Exception:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000")


def _thread_name() -> str:
    try:
        import threading as _th
        return _th.current_thread().name or "main"
    except Exception:
        return "main"


def _module_name() -> str:
    """[自动推导] 调用者模块路径(跳过 utils.log 与 logging 内部帧)"""
    try:
        import inspect as _ins
        f = _ins.currentframe()
        while f is not None:
            name = f.f_globals.get("__name__", "")
            if (name and name != __name__
                    and not name.startswith("logging")
                    and not name.startswith("importlib")
                    and not name.startswith("concurrent")):
                return name
            f = f.f_back
    except Exception:
        pass
    return "system"


def _esc_tab(s) -> str:
    return str(s).replace("\t", "\\t")


def build_standard_lines(ts, level, module, tid, account, text) -> str:
    """单行主条目 + 多行附属(每行4空格缩进); 级别统一 WARN 写法"""
    lvl = str(level).upper()
    if lvl == "WARNING":
        lvl = "WARN"
    body = "" if text is None else str(text)
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    head = (f"[{ts}] [{lvl}] [{module or 'system'}] "
            f"[{tid or 'main'}] [{account or '-'}] {_esc_tab(lines[0])}")
    if len(lines) == 1:
        return head
    tail = "\n".join("    " + _esc_tab(ln) for ln in lines[1:])
    return head + "\n" + tail


class StandardFormatter(logging.Formatter):
    """[V3.0.10] 四通道统一标准格式(纯文本, 无 ANSI)"""

    def format(self, record):
        try:
            ts = _iso_ts(record.created)
        except Exception:
            ts = _iso_ts()
        module = getattr(record, "ymodule", None) or record.name or "system"
        if module == "yatori_file_logger":
            module = "system"
        tid = getattr(record, "ythread", None) or record.threadName or "main"
        try:
            acc, _ = _get_log_account_raw()
        except Exception:
            acc = ""
        try:
            text = record.getMessage()
        except Exception:
            text = f"{record.msg} {record.args or ''}"
        if record.exc_info:
            try:
                text = text + "\n" + self.formatException(record.exc_info)
            except Exception:
                pass
        return build_standard_lines(ts, record.levelname, module, tid,
                                    acc, text)


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

    # [V3.0.10] 标准格式: [ISO时间] [LEVEL] [模块] [线程] [账号] 消息
    module = _module_name()
    tid = _thread_name()
    try:
        acc, _rem = _get_log_account_raw()
    except Exception:
        acc = ""
    ts = _iso_ts()
    level_up = str(level).upper()
    if level_up == "WARNING":
        level_up = "WARN"
    base_prefix = (f"[{ts}] [{level_up}] [{module}] [{tid}] "
                   f"[{acc or '-'}] ")
    body_lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    console_text = "\n".join(
        [base_prefix + _esc_tab(body_lines[0])]
        + ["    " + _esc_tab(x) for x in body_lines[1:]])
    # 终端彩色(仅 isatty; 重定向/文件/无终端自动无色 -> 跨设备可读)
    try:
        _isatty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    except Exception:
        _isatty = False
    if _color_enabled and _isatty:
        if level_up in ("ERROR", "FATAL", "BOLD_RED"):
            console_text = f"{Red}{console_text}{Reset}"
        elif level_up in ("WARN", "WARNING"):
            console_text = f"{Yellow}{console_text}{Reset}"

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

    # 写入文件日志(去除ANSI; StandardFormatter 统一加时间/级别/模块/线程/账号,
    # 账号独立文件由 _AccountFileHandler 按账号上下文分流)
    if _log_file_sw and _file_logger:
        try:
            if level_up in ("ERROR", "FATAL", "BOLD_RED"):
                _lv = logging.ERROR
            elif level_up in ("WARN", "WARNING"):
                _lv = logging.WARNING
            elif level_up == "DEBUG":
                _lv = logging.DEBUG
            else:
                _lv = logging.INFO
            _file_logger.log(_lv, _strip_ansi(raw_text),
                             extra={"ymodule": module, "ythread": tid})
        except Exception:
            pass


def model_print(is_sw: bool, level: str, *args: Any):
    """
    条件打印 - 对应 Go 的 ModelPrint()
    只在 is_sw 为 True 时打印
    """
    if is_sw:
        log_print(level, *args)


# ============ uvicorn 日志接入(access log 落盘) ============

class _UiPollFilter(logging.Filter):
    """[2026-10-24] GUI高频轮询路径不落盘: 日志中心tail/状态轮询等会把
    access日志刷屏淹没业务日志, 此类请求直接丢弃(控制台仍可见)."""
    _SKIP = ("/ui/api/logs/tail", "/ui/api/ping", "/ui/api/accounts",
             "/ui/api/rtstatus", "/ui/api/task/status", "/favicon")

    def filter(self, record):
        try:
            msg = str(record.msg)
            args = record.args or ()
            text = msg % args if args else msg
            return not any(k in str(text) for k in self._SKIP)
        except Exception:
            return True


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
            "file_plain": {"()": "utils.log.StandardFormatter"},
            # [V3.0.10] uvicorn 文件通道也用统一标准格式(纯文本)
            "access_file": {
                "()": "utils.log.StandardFormatter",
            },
        },
        "filters": {
            "ui_poll": {"()": "utils.log._UiPollFilter"},
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
                "log_dir": log_dir + "/access",
                "formatter": "access_file",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default", "file"], "level": "INFO",
                        "propagate": False},
            "uvicorn.error": {"handlers": ["default", "file"],
                              "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access", "file_access"],
                               "level": "INFO", "propagate": False,
                               "filters": ["ui_poll"]},
        },
    }

# ============ [V3.0.10] 历史日志格式转换(原位, 一次性) ============
import glob as _glob_log
import re as _re_log

# 旧格式行: "2026-10-24 21:05:02 [INFO] 正文"
_LEGACY_LINE_RE = _re_log.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?\s+\[([A-Za-z_]+)\]\s?(.*)$")
# 旧正文开头的账号前缀 "[19885639522|备注]" 或 "[19885639522]"(账号>=6位数字)
_ACC_PREFIX_RE = _re_log.compile(r"^\[(\d{6,20})(?:\|([^\]]*))?\]\s*(.*)$")
# 已是新格式的行(幂等跳过)
_NEW_LINE_RE = _re_log.compile(
    r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[^\]]*\]\s+\[[A-Z_]+\]")


def _convert_legacy_text(old_line: str) -> str:
    """旧行 -> 标准格式行; 非主条目行 -> 4空格缩进附属行"""
    m = _LEGACY_LINE_RE.match(old_line)
    if not m:
        return "    " + old_line.replace("\t", "\\t")
    y, mo, d, hh, mm, ss, ms, lvl, rest = m.groups()
    ms3 = (ms or "000").ljust(3, "0")[:3]
    iso = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}.{ms3}+08:00"
    lvl_norm = lvl.upper()
    if lvl_norm in ("WARNING",):
        lvl_norm = "WARN"
    acc = ""
    am = _ACC_PREFIX_RE.match(rest)
    if am:
        acc = am.group(1)
        rest = am.group(3)
    return (f"[{iso}] [{lvl_norm}] [legacy] [-] [{acc or '-'}] "
            f"{rest.replace(chr(9), chr(92) + 't')}")


def _migrate_one_file(path: str) -> bool:
    """单文件原位转换(tmp -> os.replace, 中断不破坏原文件)"""
    tmp = path + ".fmttmp"
    try:
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False
        changed = False
        with open(path, "r", encoding="utf-8", errors="replace") as fr, \
                open(tmp, "w", encoding="utf-8", errors="replace") as fw:
            for ln in fr:
                line = ln.rstrip("\r\n")
                if not line:
                    fw.write("\n")
                    continue
                if _NEW_LINE_RE.match(line) or line.startswith("    "):
                    fw.write(line + "\n")
                else:
                    fw.write(_convert_legacy_text(line) + "\n")
                    changed = True
        if changed:
            os.replace(tmp, path)
        else:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return changed
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def migrate_legacy_logs(log_dir: str = "./assets/logs") -> dict:
    """[V3.0.10] 一次性把旧格式日志原位转换为标准格式(标记文件防重跑)"""
    stats = {"files": 0, "ok": 0}
    marker = os.path.join(log_dir, ".logfmt_v10.done")
    try:
        if os.path.exists(marker):
            return stats
        open(marker, "w", encoding="utf-8").write(_iso_ts())
    except Exception:
        return stats
    pats = [os.path.join(log_dir, "*.log"),
            os.path.join(log_dir, "*.log.[1-9]"),
            os.path.join(log_dir, "access", "*.log"),
            os.path.join(log_dir, "accounts", "*", "*.log")]
    for pat in pats:
        for p in _glob_log.glob(pat):
            stats["files"] += 1
            if _migrate_one_file(p):
                stats["ok"] += 1
    return stats


def start_legacy_migration_async(log_dir: str = "./assets/logs") -> None:
    """后台线程执行历史日志转换(不阻塞启动)"""
    try:
        import threading as _th2

        def _run():
            try:
                r = migrate_legacy_logs(log_dir)
                if r.get("ok"):
                    print(f"[logfmt] 历史日志已转换为标准格式: "
                          f"{r['ok']}/{r['files']} 个文件")
            except Exception:
                pass

        _th2.Thread(target=_run, name="logfmt-migrate", daemon=True).start()
    except Exception:
        pass
