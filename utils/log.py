# -*- coding: utf-8 -*-
"""
日志模块 - 对应 Go 项目的 yatori-go-core/utils/log + LogModel.go
支持彩色控制台日志 + 文件日志输出
"""
import os
import sys
import logging
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
             color_log: bool = True, log_dir: str = "./assets/log"):
    """
    初始化日志系统
    :param level: 日志等级 (DEBUG/INFO/WARNING/ERROR)
    :param log_file_sw: 是否输出日志文件
    :param color_log: 是否启用彩色日志
    :param log_dir: 日志文件目录
    """
    global _current_level, _color_enabled, _file_logger, _log_file_sw

    _current_level = level.upper()
    _color_enabled = (color_log is True) or (color_log == 1)
    _log_file_sw = (log_file_sw is True) or (log_file_sw == 1)

    # 控制台编码加固: 防 Windows 重定向(GBK)下生僻字符/emoji 打印崩溃
    setup_stdio_encoding()

    if _log_file_sw:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(
            log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")

        _file_logger = logging.getLogger("yatori_file_logger")
        _file_logger.setLevel(logging.DEBUG)
        _file_logger.handlers.clear()

        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _file_logger.addHandler(handler)


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

    # 构建带时间戳的控制台输出
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_tag = f"[{level}]"

    if _color_enabled:
        console_text = f"{DarkGray}{timestamp}{Reset} {level_tag} {raw_text}"
    else:
        console_text = f"{timestamp} {level_tag} {_strip_ansi(raw_text)}"

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
    if _log_file_sw and _file_logger:
        plain_text = f"{level_tag} {_strip_ansi(raw_text)}"
        _file_logger.info(plain_text)


def model_print(is_sw: bool, level: str, *args: Any):
    """
    条件打印 - 对应 Go 的 ModelPrint()
    只在 is_sw 为 True 时打印
    """
    if is_sw:
        log_print(level, *args)
