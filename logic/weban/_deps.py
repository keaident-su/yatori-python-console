# -*- coding: utf-8 -*-
"""
安全微伴依赖惰性加载层

原 SDK 在模块顶层 import nodriver/opencv(验证码) 等重依赖,
直接顶层引入会导致未使用安全微伴的部署环境(如仅用学习通)也无法启动。
本模块将其改为惰性加载: 仅在真正需要验证码能力时导入,
并给出清晰的依赖缺失提示。其余纯 HTTP 功能不受影响。
"""


def is_non_interactive() -> bool:
    """判断是否处于无交互环境(容器/非TTY/管道)

    移植自 SDK captcha.is_non_interactive, 不含任何重依赖。
    """
    import os
    import sys
    env = os.environ.get("ENVIRONMENT", "").strip().lower()
    if env in ("docker", "container"):
        return True
    try:
        if not sys.stdin.isatty():
            return True
    except (AttributeError, ValueError):
        return True
    return False


def is_android() -> bool:
    """判断是否运行在 Android 环境(含 Termux) - 转发全局平台探测(单一事实源)"""
    from utils.platform_info import is_android as _is_android
    return _is_android()


def load_captcha_module():
    """惰性加载验证码模块(nodriver/opencv 依赖)

    :return: logic.weban.captcha 模块
    :raises RuntimeError: 依赖缺失时给出可操作的安装提示
    """
    try:
        from logic.weban import captcha as captcha_module
        return captcha_module
    except ImportError as e:
        raise RuntimeError(
            "安全微伴验证码依赖缺失(nodriver/opencv-python), "
            f"请执行 pip install -r requirements.txt 后重试: {e}"
        ) from e
