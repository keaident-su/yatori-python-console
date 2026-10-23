# -*- coding: utf-8 -*-
"""
Yatori Python Console - 主入口文件
对应 Go 项目的 main.go

启动流程：
1. 初始化控制台
2. 打印 LOGO
3. 显示公告
4. 启动主逻辑
"""
import sys
import os


def _ensure_stdio():
    """[2026-10-24] windowed GUI(pythonw / PyInstaller console=False)下
    sys.stdout/stderr 为 None, 任何 print 都会 AttributeError 崩溃;
    统一重定向到 assets/logs/gui_console.log(无黑框但日志保留)。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    _f = None
    try:
        _base = (os.path.dirname(os.path.abspath(sys.executable))
                 if getattr(sys, "frozen", False)
                 else os.path.dirname(os.path.abspath(__file__)))
        _dir = os.path.join(_base, "assets", "logs")
        os.makedirs(_dir, exist_ok=True)
        _f = open(os.path.join(_dir, "gui_console.log"), "a",
                  encoding="utf-8", buffering=1)
    except Exception:
        import io as _io
        _f = _io.StringIO()
    if sys.stdout is None:
        sys.stdout = _f
    if sys.stderr is None:
        sys.stderr = _f
    # 标准输出兜底文本包装(部分库直接调 sys.stdout.buffer)
    try:
        if not hasattr(sys.stdout, "buffer"):
            class _W:
                def __init__(self, f):
                    self._f = f
                    self.buffer = f

                def write(self, x):
                    try:
                        self._f.write(x)
                    except Exception:
                        pass

                def flush(self):
                    try:
                        self._f.flush()
                    except Exception:
                        pass
            sys.stdout = _W(sys.stdout)
            sys.stderr = _W(sys.stderr)
    except Exception:
        pass


# 程序版本号(与 web/server.py APP_VERSION 保持一致)
APP_VERSION = "3.0.3"

# 路径解析：兼容 PyInstaller 打包(冻结)环境与源码开发环境
if getattr(sys, "frozen", False):
    # 打包后：只读资源(logo/tls dll/内置静态页)在 sys._MEIPASS
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(
        os.path.abspath(sys.executable)))
    if sys.platform == "win32":
        # Windows: exe 所在目录即数据目录(config.yaml/assets/日志), 与历史习惯一致
        BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    else:
        # [2026-10-24] Linux: 程序安装目录(/opt)只读不可写!
        # 数据(config.yaml/assets/日志/背景图)统一放用户目录(标准 XDG 约定),
        # 避免新装系统上 PermissionError 崩溃
        BASE_DIR = os.path.join(os.path.expanduser("~"),
                                ".local", "share", "yatori")
        try:
            os.makedirs(BASE_DIR, exist_ok=True)
        except Exception:
            pass
else:
    # 源码运行：项目根目录（main.py 所在目录）
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = BASE_DIR

# 将项目根目录添加到 Python 路径
sys.path.insert(0, BASE_DIR)


def init_console():
    """
    初始化控制台 - 对应 Go 的 YatoriConsoleInit()
    Windows 下设置虚拟终端以支持 ANSI 颜色
    """
    if sys.platform == "win32":
        # [2026-10-24] windowed打包(console=False)下带 --console 启动时
        # 动态附加一个新控制台窗口, 保留原CLI能力
        if getattr(sys, "frozen", False) and "--console" in sys.argv:
            try:
                import ctypes as _ct
                if _ct.windll.kernel32.GetConsoleWindow() == 0:
                    _ct.windll.kernel32.AllocConsole()
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8",
                                      errors="ignore", buffering=1)
                    sys.stderr = sys.stdout
                    sys.stdin = open("CONIN$", "r", encoding="utf-8",
                                     errors="ignore")
            except Exception:
                pass
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # 启用虚拟终端处理
            kernel32.SetConsoleMode(
                kernel32.GetStdHandle(-11),  # STD_OUTPUT_HANDLE
                7  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
        except Exception:
            pass

    # 控制台输出编码加固(Windows重定向GBK/跨平台兜底),
    # 需在 LOGO 打印之前生效(logo 含非 ASCII 字符)
    try:
        from utils.log import setup_stdio_encoding
        setup_stdio_encoding()
    except Exception:
        pass

    # 切换工作目录到主程序(exe/main.py)所在目录，确保所有相对路径正确
    os.chdir(BASE_DIR)

    # 反调试/反附加守护(Windows; Cython 原生编译之上的动态分析屏障)
    try:
        from utils.anti_debug import start_anti_debug_guard
        start_anti_debug_guard()
    except Exception:
        pass

    # 首次运行：自动创建所需目录（配置在同目录，日志与人脸在 assets 内）
    os.makedirs(os.path.join("assets", "sound"), exist_ok=True)
    os.makedirs(os.path.join("assets", "faces"), exist_ok=True)
    os.makedirs(os.path.join("assets", "fsces"), exist_ok=True)
    os.makedirs(os.path.join("assets", "logs"), exist_ok=True)


def _verify_build_integrity():
    """启动完整性自校验(仅打包环境; 清单由 build_protected.py 生成)"""
    try:
        from _integrity_data import MANIFEST
    except ImportError:
        return   # 开发态/旧包无清单
    try:
        from utils.integrity import verify_integrity
        if not verify_integrity(MANIFEST):
            print("[Security] integrity check failed")
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass


def main():
    """主函数"""
    # 0. stdio守护(windowed下stdout为None, 必须最先兜底)
    _ensure_stdio()
    # 0.1 统一工作目录=数据目录(打包版资源相对路径全部落此; 防只读目录崩溃)
    try:
        os.chdir(BASE_DIR)
    except Exception:
        pass
    # 1. 初始化
    init_console()

    # 1.2 性能策略早期注入(必须在任何 logic.* 业务 import 之前, 供 parallel 惰性读取)
    #     来源: config.yaml → basicSetting.fullCpuMode / performanceGear
    try:
        import yaml as _yaml
        _cfg_path = os.path.join(BASE_DIR, "config.yaml")
        if os.path.exists(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _bs = (((_yaml.safe_load(_f) or {}).get("setting") or {})
                       .get("basicSetting") or {})
            os.environ["YATORI_FULL_CPU"] = (
                "1" if int(_bs.get("fullCpuMode", 0) or 0) == 1 else "0")
            os.environ["YATORI_PERF_GEAR"] = str(
                _bs.get("performanceGear", "aggressive") or "aggressive")
    except Exception:
        pass

    # 1.5 完整性自校验(原生扩展防篡改; 打包环境生效)
    _verify_build_integrity()

    # 2. 打印 LOGO
    from config.config import read_logo
    print(read_logo())

    # 2.0 开屏赞助提示(2026-10-20: 开源项目求赞助, 赞赏码见 assets/微信赞赏码.png)
    try:
        from utils.sponsor import print_sponsor_banner
        print_sponsor_banner()
    except Exception:
        pass

    # 2.1 打印版本号(便于部署后确认)
    print(f"[版本] {APP_VERSION}")

    # 2.5 打印 CPU 拓扑与调度策略（多核/异构自适应，便于跨环境确认生效）
    from logic.core.cpu_topology import TOPOLOGY_DESC, SCHEDULE_STRATEGY
    print(f"[CPU拓扑] {TOPOLOGY_DESC} | 调度策略: {SCHEDULE_STRATEGY}")

    # 2.55 打印 CPU 型号识别与配置加载结果(cpus/ 目录自动匹配)
    try:
        from logic.core.cpu_profile import startup_banner
        print(f"[CPU配置] {startup_banner()}")
    except Exception:
        pass

    # 2.6 打印平台与能力画像（多系统/多架构适配排查用）
    try:
        from utils.platform_info import platform_summary
        print(f"[平台] {platform_summary()}")
    except Exception:
        pass

    # 3. 显示公告
    from utils.announcement import show_announcement
    show_announcement()

    # 4. 启动主逻辑(2026-10-23: 默认桌面GUI; --console 进入原控制台/webMode菜单)
    if "--console" in sys.argv:
        from logic.launcher import lunch
        lunch()
    else:
        try:
            from logic.launcher import run_gui
            run_gui()
        except Exception as _ge:
            print(f"[GUI] 桌面窗口启动失败({_ge}), 回退控制台模式")
            from logic.launcher import lunch
            lunch()


if __name__ == "__main__":
    # PyInstaller 打包(Windows spawn)下必须最先调用 freeze_support()，
    # 否则 multiprocessing/ProcessPoolExecutor 的子进程会把整个主程序再执行一遍，
    # 造成进程无限裂变/卡死。
    import multiprocessing
    multiprocessing.freeze_support()
    main()
