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

    # 首次运行：自动创建所需目录（配置在同目录，日志与人脸在 assets 内）
    os.makedirs(os.path.join("assets", "sound"), exist_ok=True)
    os.makedirs(os.path.join("assets", "faces"), exist_ok=True)
    os.makedirs(os.path.join("assets", "fsces"), exist_ok=True)
    os.makedirs(os.path.join("assets", "logs"), exist_ok=True)


def main():
    """主函数"""
    # 1. 初始化
    init_console()

    # 2. 打印 LOGO
    from config.config import read_logo
    print(read_logo())

    # 2.5 打印 CPU 拓扑与调度策略（多核/异构自适应，便于跨环境确认生效）
    from logic.core.cpu_topology import TOPOLOGY_DESC, SCHEDULE_STRATEGY
    print(f"[CPU拓扑] {TOPOLOGY_DESC} | 调度策略: {SCHEDULE_STRATEGY}")

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
