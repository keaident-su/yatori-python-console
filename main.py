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

# 项目根目录（main.py 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

    # 切换工作目录到项目根目录，确保所有相对路径正确
    os.chdir(BASE_DIR)

    # 确保必要目录存在
    os.makedirs("./assets/sound", exist_ok=True)
    os.makedirs("./assets/log", exist_ok=True)


def main():
    """主函数"""
    # 1. 初始化
    init_console()

    # 2. 打印 LOGO
    from config.config import read_logo
    print(read_logo())

    # 3. 显示公告
    from utils.announcement import show_announcement
    show_announcement()

    # 4. 启动主逻辑
    from logic.launcher import lunch
    lunch()


if __name__ == "__main__":
    main()
