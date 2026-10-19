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

# 程序版本号(与 web/server.py APP_VERSION 保持一致)
APP_VERSION = "2.0.9.1"

# 路径解析：兼容 PyInstaller 打包(冻结)环境与源码开发环境
if getattr(sys, "frozen", False):
    # 打包后：exe 可执行文件所在目录即“主程序目录”，
    # config.yaml、assets(日志/人脸) 都应放在这里，与 main.py 同目录的语义保持一致
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    # 打包内置的只读资源(logo.txt、tls dll 等)解压到临时目录 sys._MEIPASS
    RES_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
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

    # 4. 启动主逻辑
    from logic.launcher import lunch
    lunch()


if __name__ == "__main__":
    # PyInstaller 打包(Windows spawn)下必须最先调用 freeze_support()，
    # 否则 multiprocessing/ProcessPoolExecutor 的子进程会把整个主程序再执行一遍，
    # 造成进程无限裂变/卡死。
    import multiprocessing
    multiprocessing.freeze_support()
    main()
