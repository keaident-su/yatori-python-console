# -*- coding: utf-8 -*-
"""
启动逻辑 - 对应 Go 项目的 logic/Lunch.go
包含：配置检查、IP代理检查、Web模式切换、并发刷课执行
"""
import os
import sys
import threading
from typing import List

import yaml

from config.config import (
    JSONDataForConfig, Setting, User, CoursesCustom,
    read_config, get_user_input, str_to_int
)
from utils.log import (
    log_init, log_print, string_to_log_level,
    INFO, BoldRed, Red, Yellow, Green, BoldGreen, Default
)
from utils import ip_proxy as proxy_utils
from utils.announcement import show_announcement


def file_exists(file_name: str) -> bool:
    """检查文件是否存在"""
    return os.path.isfile(file_name)


def lunch():
    """
    主启动逻辑 - 对应 Go 的 Lunch()
    1. 检查/生成配置文件
    2. 读取配置
    3. 初始化日志
    4. 配置校验
    5. IP 代理检查
    6. Web 模式判断
    7. 并发刷课
    """

    # 1. 检查 config.yaml 是否存在
    if not file_exists("./config.yaml"):
        log_print(INFO, BoldRed, """
程序未检测到config.yaml配置文件，

如果你用的配置文件生成器你确定你文件放对位置了？
以及请不要放个config（1）.yaml，config（2）.yaml这样子的的文件，要的是config.yaml。

如果使用的是控制台配置生成器的同学可以忽略此条信息。
""")
        _generate_config()

    # 2. 读取配置文件
    config_data = read_config("./config.yaml")

    # 2.5 性能策略注入(全速开关/档位→环境变量, 供 parallel 惰性读取) + 运行期微调器启动
    try:
        _bs = config_data.setting.basic_setting
        os.environ["YATORI_FULL_CPU"] = "1" if _bs.full_cpu_mode == 1 else "0"
        os.environ["YATORI_PERF_GEAR"] = str(
            _bs.performance_gear or "aggressive")
        from logic.core import perf_tuner
        perf_tuner.start()
        from logic.core.parallel import perf_summary
        log_print(INFO, perf_summary())
    except Exception:
        pass

    # 3. 初始化日志配置
    bs = config_data.setting.basic_setting
    log_init(
        level=string_to_log_level(bs.log_level),
        log_file_sw=(bs.log_out_file_sw == 1),
        color_log=(bs.color_log == 1),
        log_dir=os.path.join("assets", "logs")
    )

    # 4. 配置文件检查
    _config_json_check(config_data)

    # 4.5 多答题源初始化 + 启动时 token 有效性自检(输出检查结果)
    from logic.core.answer_engine import run_startup_token_check
    run_startup_token_check(config_data.setting)

    # 5. 检查代理 IP
    _check_proxy_ip()

    # 6. Web 模式
    if config_data.setting.basic_setting.web_model == 1:
        _start_web_service(
            config_data.setting.basic_setting.web_port,
            auto_open_browser=(
                config_data.setting.basic_setting.auto_open_browser == 1))
    else:
        # 7. 并发刷课
        brush_block(config_data)

    log_print(INFO, Red, "Yatori --- ", "所有任务执行完毕")


def _generate_config():
    """交互式生成配置文件"""
    set_config = JSONDataForConfig()

    # 基本设置默认值
    set_config.setting.basic_setting.completion_tone = 1
    set_config.setting.basic_setting.color_log = 1
    set_config.setting.basic_setting.log_out_file_sw = 1
    set_config.setting.basic_setting.log_level = "INFO"
    set_config.setting.basic_setting.log_model = 0
    set_config.setting.ai_setting.ai_type = "TONGYI"
    set_config.setting.api_que_setting.url = "http://localhost:8083"

    # 用户交互输入
    account_type = get_user_input("请输入平台类型 (如 YINGHUA)(全大写): ")
    url = get_user_input("请输入平台的URL链接 (可留空): ")
    account = get_user_input("请输入账号: ")
    password = get_user_input("请输入密码: ")
    video_model = get_user_input("请输入刷视频模式 (0-不刷, 1-普通模式, 2-暴力模式, 3-去红模式): ")
    auto_exam = get_user_input("是否自动考试? (0-不考试, 1-AI考试, 2-外部题库对接考试): ")
    exam_auto_submit = get_user_input("考完试是否自动提交试卷? (0-否, 1-是): ")
    include_courses = get_user_input("请输入需要包含的课程名称，多个用(英文逗号)分隔(可留空): ")
    exclude_courses = get_user_input("请输入需要排除的课程名称，多个用(英文逗号)分隔(可留空): ")

    def clean_string_slice(s: str) -> List[str]:
        if not s:
            return []
        return [p.strip() for p in s.split(",") if p.strip()]

    user = User(
        account_type=account_type,
        url=url,
        account=account,
        password=password,
        courses_custom=CoursesCustom(
            video_model=str_to_int(video_model),
            auto_exam=str_to_int(auto_exam),
            exam_auto_submit=str_to_int(exam_auto_submit),
            include_courses=clean_string_slice(include_courses),
            exclude_courses=clean_string_slice(exclude_courses),
        ),
    )
    set_config.users.append(user)

    # 写入 YAML 文件
    data = _config_to_yaml_dict(set_config)
    with open("./config.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def _config_to_yaml_dict(config: JSONDataForConfig) -> dict:
    """将配置转为可 YAML 序列化的字典"""
    users = []
    for u in config.users:
        user_dict = {
            "accountType": u.account_type,
            "url": u.url,
            "account": u.account,
            "password": u.password,
            "coursesCustom": {
                "videoModel": u.courses_custom.video_model,
                "autoExam": u.courses_custom.auto_exam,
                "examAutoSubmit": u.courses_custom.exam_auto_submit,
                "includeCourses": u.courses_custom.include_courses,
                "excludeCourses": u.courses_custom.exclude_courses,
            }
        }
        users.append(user_dict)

    return {
        "setting": {
            "basicSetting": {
                "completionTone": config.setting.basic_setting.completion_tone,
                "colorLog": config.setting.basic_setting.color_log,
                "logOutFileSw": config.setting.basic_setting.log_out_file_sw,
                "logLevel": config.setting.basic_setting.log_level,
                "logModel": config.setting.basic_setting.log_model,
            },
            "aiSetting": {
                "aiType": config.setting.ai_setting.ai_type,
            },
            "apiQueSetting": {
                "url": config.setting.api_que_setting.url,
            },
            "answerSetting": {
                "tokenCheck": 1,
                "localCacheEnable": 1,
                "localCachePath": "questions_answers.json",
                "order": "",
                "sources": [],
            },
        },
        "users": users,
    }


def _config_json_check(config_data: JSONDataForConfig):
    """配置文件检测检验"""
    if len(config_data.users) == 0:
        log_print(INFO, BoldRed, "请先在config文件中配置好相应账号")
        sys.exit(0)

    for i, user in enumerate(config_data.users):
        if user.account_type in ("YINGHUA", "HQKJ"):
            if not user.url.startswith("http"):
                log_print(INFO, BoldRed,
                          f"账号{user.account}未配置正确url，请先在config文件中配置好相应账号信息")
                sys.exit(0)
            # 截取基础 URL
            parts = user.url.split("/")
            if len(parts) >= 3:
                config_data.users[i].url = "/".join(parts[:3])

        if user.is_proxy == 1:
            proxy_utils.IS_PROXY_FLAG = True


def _check_proxy_ip():
    """检查代理 IP 可用性"""
    if not proxy_utils.IS_PROXY_FLAG:
        return

    log_print(INFO, Yellow, "正在开启IP池代理...")
    log_print(INFO, Yellow, "正在检查IP池IP可用性...")

    ip_list, err = proxy_utils.ip_files_reader("./ip.txt")
    if err:
        log_print(INFO, BoldRed, "IP代理池文件ip.txt读取失败，请确认文件格式或者内容是否正确")
        sys.exit(0)

    for ip in ip_list:
        passed, state, error = proxy_utils.check_proxy_ip(ip)
        if not passed:
            log_print(INFO, f" [{ip}] ", BoldRed,
                      f"该IP代理不可用，错误信息：{error}")
            continue
        log_print(INFO, f" [{ip}] ", Green, f"检测通过，状态：{state}")
        proxy_utils.IP_PROXY_POOL.append(ip)

    log_print(INFO, BoldGreen, "IP检查完毕")

    if len(proxy_utils.IP_PROXY_POOL) == 0:
        log_print(INFO, BoldRed,
                  "无可用IP代理池，若要继续使用请先检查IP代理池文件内的IP可用性，或者在配置文件关闭IP代理功能")
        sys.exit(0)


def _pick_free_port(start_port: int, max_tries: int = 100) -> int:
    """从 start_port 开始向下寻找空闲端口

    用于支持程序多开: 多个实例可以同时在各自端口上监听。
    注意: 探测时不设置 SO_REUSEADDR —— Windows 下它允许重复绑定，
    只有直接 bind 才能真正判断端口是否被其它实例占用。
    """
    import socket as _socket
    for offset in range(max_tries):
        port = start_port + offset
        if port > 65535:
            break
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return start_port


def _open_browser(url: str):
    """打开系统默认浏览器(无桌面环境/失败时静默)"""
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def _ensure_self_signed_cert(cert_cfg: str, key_cfg: str):
    """准备 HTTPS 证书: 配置路径优先; 否则 openssl 生成自签并持久化

    返回 (cert_path, key_path); 失败返回 (None, None)(调用方回退HTTP)。
    自签证书首次访问时浏览器/客户端需手动信任。
    """
    if cert_cfg and key_cfg and os.path.isfile(cert_cfg) \
            and os.path.isfile(key_cfg):
        return cert_cfg, key_cfg
    d = os.path.join("assets", "web_ssl")
    cert = os.path.join(d, "server.crt")
    key = os.path.join(d, "server.key")
    if os.path.isfile(cert) and os.path.isfile(key):
        return cert, key
    try:
        import shutil
        import subprocess
        exe = shutil.which("openssl")
        if not exe:
            for c in (r"C:\Program Files\Git\usr\bin\openssl.exe",
                      r"C:\Program Files\Git\mingw64\bin\openssl.exe",
                      "/usr/bin/openssl", "/usr/local/bin/openssl"):
                if os.path.isfile(c):
                    exe = c
                    break
        if not exe:
            raise FileNotFoundError("未找到 openssl")
        os.makedirs(d, exist_ok=True)
        subprocess.run(
            [exe, "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", key, "-out", cert, "-days", "3650", "-nodes",
             "-subj", "/CN=Yatori-Console"],
            check=True, capture_output=True, timeout=60)
        log_print(INFO, Green,
                  f"已自动生成自签HTTPS证书: {cert} "
                  f"(首次访问需在浏览器中手动信任)")
        return cert, key
    except Exception as e:
        log_print(INFO, Red,
                  f"自动生成自签证书失败({e}); 请安装 openssl 或在配置中指定 webSslCert/webSslKey")
        return None, None


def _start_web_service(web_port: int = 8080,
                       auto_open_browser: bool = True):
    """启动 Web 服务 - 支持多开

    端口从配置 basicSetting.webPort 读取(默认8080)；若端口已被占用
    (通常是已有一个实例在运行)，自动顺延到下一个空闲端口，
    第二个实例不会再因端口冲突而直接退出。
    """
    from dao.database import sqlite_init
    from global_state import global_var  # noqa: F401

    # 初始化数据库(多实例可共用同一 yatori.db, WAL+busy_timeout 保证并发安全)
    sqlite_init()

    # 启动 FastAPI(前端/Web 功能因严重问题已移除; 发布版不含 web 模块时友好提示)
    try:
        import uvicorn
        from web.server import create_app
    except ImportError:
        log_print(INFO, Red,
                  "前端(Web)功能因严重问题已移除, 当前版本不支持 Web 模式; "
                  "请将 config.yaml 的 webModel 设为 0 使用控制台模式")
        return

    # 通信加密密钥初始化(config 优先 → assets/web_secret.txt → 自动生成)
    # 必须在 create_app 之前: 认证/加密模块会读取密钥并缓存, 提前统一来源
    try:
        from web.service.user_service import load_web_setting
        _bs = load_web_setting().basic_setting
    except Exception:
        _bs = None
    try:
        from web.crypto_channel import get_web_secret
        _sec = get_web_secret(getattr(_bs, "web_secret", "") or "")
        log_print(INFO, Green,
                  "通信加密已启用(AES-256-GCM); 前后端可同密钥加密传输")
    except Exception as _e:
        log_print(INFO, Red, f"通信加密初始化失败: {_e}")

    app = create_app()

    try:
        base_port = int(web_port)
    except (TypeError, ValueError):
        base_port = 8080
    if not (0 < base_port <= 65535):
        base_port = 8080

    # HTTPS 证书准备(webSsl=1 时; 未配置证书则自动生成自签并持久化)
    ssl_kw = {}
    if _bs is not None and getattr(_bs, "web_ssl", 0) == 1:
        _cert, _key = _ensure_self_signed_cert(
            getattr(_bs, "web_ssl_cert", ""),
            getattr(_bs, "web_ssl_key", ""))
        if _cert and _key:
            ssl_kw = {"ssl_certfile": _cert, "ssl_keyfile": _key}
        else:
            log_print(INFO, Red, "HTTPS 启用失败(无证书且无法自动生成), 已回退 HTTP")

    # 端口占用自动顺延 + 启动重试, 避免多开时第二个实例直接崩溃退出
    for _ in range(50):
        port = _pick_free_port(base_port)
        if port != base_port:
            log_print(INFO, Yellow,
                      f"端口 {base_port} 已被占用(可能已有多开实例在运行)，"
                      f"已自动改用空闲端口 {port} 启动")
        _scheme = "https" if ssl_kw else "http"
        log_print(INFO, Green,
                  f"Web服务已启动: {_scheme}://127.0.0.1:{port} "
                  f"(局域网访问: {_scheme}://<本机IP>:{port})")
        try:
            from web import auth as _auth
            _entry = _auth.secret_entry()
            log_print(INFO, Green,
                      f"管理界面入口(秘密路径,勿外传): "
                      f"{_scheme}://<本机IP>:{port}/{_entry}/ "
                      f"(访问口令 = webSecret；默认路径已隐藏)")
        except Exception:
            pass
        if auto_open_browser:
            try:
                from web import auth as _auth2
                _web_url = (f"{_scheme}://127.0.0.1:{port}/"
                            f"{_auth2.secret_entry()}/")
            except Exception:
                _web_url = f"{_scheme}://127.0.0.1:{port}/"
            threading.Timer(1.5, _open_browser, args=(_web_url,)).start()
            log_print(INFO, Green,
                      f"正在打开浏览器界面: {_web_url}  (如未自动打开请手动访问)")
        try:
            _run_uvicorn(app, port, ssl_kw,
                         getattr(_bs, "web_ssl_cert", "") if _bs else "",
                         getattr(_bs, "web_ssl_key", "") if _bs else "")
            return
        except (OSError, SystemExit) as e:
            log_print(INFO, Yellow,
                      f"端口 {port} 启动失败({e})，正在尝试下一个端口...")
            base_port = port + 1


def _run_uvicorn(app, port: int, ssl_kw: dict,
                 cfg_cert: str = "", cfg_key: str = ""):
    """启动 uvicorn; HTTPS 时挂载多证书 SNI(按访问域名自动选择证书)

    uvicorn 内部会在 serve→load 阶段创建 SSLContext(单证书),
    这里在 load 完成后注入 SNI 回调: 客户端用哪个域名访问,
    就自动匹配证书库中对应的证书; 未匹配到时用默认证书。
    """
    import uvicorn
    # uvicorn 访问/错误日志接入全局日志文件(一条不漏, 跨天自动切换)
    # 与业务日志同一 assets/logs/{日期}.log
    from utils.log import build_uvicorn_log_config
    _log_cfg = build_uvicorn_log_config(os.path.join("assets", "logs"))
    if not ssl_kw:
        uvicorn.run(app, host="0.0.0.0", port=port, log_config=_log_cfg)
        return
    config = uvicorn.Config(app, host="0.0.0.0", port=port, **ssl_kw,
                            log_config=_log_cfg)
    try:
        from web import cert_manager
        # 预加载(幂等): serve 时会跳过已 load, ssl context 就绪后挂载 SNI 回调
        config.load()
        _sctx = getattr(config, "ssl", None)
        if _sctx is not None:
            n = cert_manager.attach_sni(_sctx, cfg_cert, cfg_key)
            if n >= 1:
                log_print(INFO, Green,
                          f"多证书已启用: {n} 张证书按访问域名自动匹配(SNI)")
    except Exception as _e:
        log_print(INFO, Yellow, f"多证书 SNI 初始化跳过: {_e}")
    server = uvicorn.Server(config)
    server.run()


def brush_block(config_data: JSONDataForConfig):
    """
    刷课执行块 - 对应 Go 的 brushBlock()
    使用 threading 实现多平台并发
    """
    from logic.xuexitong import part as xxt
    from logic.yinghua import part as yinghua
    from logic.enaea import part as enaea
    from logic.cqie import part as cqie
    from logic.ketangx import part as ketangx
    from logic.icve import part as icve
    from logic.qingshuxuetang import part as qsxt
    from logic.welearn import part as welearn
    from logic.haiqikeji import part as hqkj
    from logic.weban import part as weban
    from logic.zhihuishu import part as zhihuishu
    from logic.dazhongyunxue import part as dzyx

    # 统一登录模块
    platforms = [
        ("YINGHUA", yinghua),
        ("ENAEA", enaea),
        ("CQIE", cqie),
        ("XUEXITONG", xxt),
        ("KETANGX", ketangx),
        ("WELEARN", welearn),
        ("ICVE", icve),
        ("QSXT", qsxt),
        ("HQKJ", hqkj),
        ("WEBAN", weban),
        ("ZHIHUISHU", zhihuishu),
        ("DZYX", dzyx),
    ]

    platform_data = []
    for name, mod in platforms:
        accounts = mod.filter_account(config_data)
        caches = mod.user_login_operation(accounts)
        platform_data.append(
            (name, mod, config_data.setting, accounts, caches))

    # 统一刷课 - 并发执行
    threads = []
    for name, mod, setting, accounts, caches in platform_data:
        t = threading.Thread(
            target=mod.run_brush_operation,
            args=(setting, accounts, caches),
            daemon=True,
        )
        threads.append(t)
        t.start()

    # 等待所有平台完成
    for t in threads:
        t.join()


_GUI_LOCK_FH = None


def _acquire_gui_single_lock() -> bool:
    """[2026-10-24] GUI单实例锁: 防止双开导致端口顺延/双窗口混乱
    (历史上双实例同时跑 -> 一个绑8080一个绑8081, 用户看到错乱界面).
    返回 True=获锁(首个实例), False=已有实例在运行."""
    global _GUI_LOCK_FH
    import os as _os
    lock_path = _os.path.join("assets", ".gui.lock")
    try:
        _os.makedirs(_os.path.dirname(lock_path), exist_ok=True)
        fh = open(lock_path, "a+")
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(_os.getpid()))
            fh.flush()
        except Exception:
            pass
        _GUI_LOCK_FH = fh  # 持有引用, 进程存活期间保持锁
        return True
    except Exception:
        return False


def run_gui():
    """桌面GUI模式(2026-10-23): pywebview独立窗口 + 后台uvicorn服务
    默认启动方式(双击exe即GUI); --console 进入原控制台/webMode菜单。
    复用 web_mode_block 的全部服务能力(加密通道/端口顺延/认证), 窗口加载 /ui 页面。
    """
    import threading
    import time as _time

    # [2026-10-24] GUI单实例保护: 已有实例在跑则提示并退出
    if not _acquire_gui_single_lock():
        log_print(INFO, Red,
                  "检测到 Yatori 已在运行中（单实例保护），本实例退出；"
                  "如界面异常请先在任务管理器结束旧进程后重试")
        try:
            if sys.platform == "win32":
                import ctypes as _ct2
                _ct2.windll.user32.MessageBoxW(
                    0, "Yatori 刷课系统已在运行中，请勿重复启动。\n"
                       "（如旧窗口异常，请先结束旧进程再启动）",
                    "Yatori", 0x40)
        except Exception:
            pass
        return

    from dao.database import sqlite_init
    sqlite_init()

    try:
        import uvicorn  # noqa: F401
        from web.server import create_app
    except ImportError:
        log_print(INFO, Red, "Web组件缺失, 回退控制台模式")
        from logic.launcher import lunch
        return lunch()

    try:
        from web.service.user_service import load_web_setting
        _bs = load_web_setting().basic_setting
    except Exception:
        _bs = None

    try:
        from web import ui_bridge
        _tk = ui_bridge.UI_TOKEN
    except Exception:
        _tk = ""

    app = create_app()
    try:
        base_port = int(getattr(_bs, "web_port", 8080) or 8080)
    except (TypeError, ValueError):
        base_port = 8080
    port = _pick_free_port(base_port)
    if port != base_port:
        log_print(INFO, Yellow,
                  f"端口 {base_port} 已被占用, GUI服务改用空闲端口 {port}")

    def _serve():
        try:
            import uvicorn as _uv
            from utils.log import build_uvicorn_log_config
            _log_cfg = build_uvicorn_log_config(os.path.join("assets", "logs"))
            _uv.run(app, host="127.0.0.1", port=port, log_config=_log_cfg)
        except Exception as _e:
            log_print(INFO, Red, f"GUI后端服务异常: {_e}")

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    # 等待服务就绪(最多15秒)
    import urllib.request as _ur
    _ready = False
    for _i in range(80):
        try:
            with _ur.urlopen(f"http://127.0.0.1:{port}/ui", timeout=1):
                _ready = True
                break
        except Exception:
            _time.sleep(0.25)
    if not _ready:
        log_print(INFO, Red, "GUI后端服务启动超时, 回退控制台模式")
        from logic.launcher import lunch
        return lunch()

    url = f"http://127.0.0.1:{port}/ui?token={_tk}"
    log_print(INFO, Green, f"桌面窗口加载: {url}")
    # [2026-10-24] Linux WebKit2GTK 兼容(窗口有壳无内容/黑屏的已知主因):
    #  VM/无GPU环境下 DMABUF 渲染器会黑屏, 强制软渲染保证页面可见
    if sys.platform != "win32":
        import os as _os3
        _os3.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
        _os3.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
    try:
        import webview
        _win = webview.create_window(
            f"Yatori 刷课系统 V{__import__('web.server', fromlist=['APP_VERSION']).APP_VERSION}",
            url, width=1280, height=840, min_size=(1024, 680))
        # [2026-10-24] 加载看门狗: 20s未触发loaded则自动重载一次
        # (治理 Linux WebKit 偶发"有壳无内容")
        _load_flag = {"ok": False}
        try:
            _win.events.loaded += lambda: _load_flag.update(ok=True)
        except Exception:
            _load_flag["ok"] = True

        def _load_watchdog():
            _time.sleep(20)
            if not _load_flag.get("ok"):
                log_print(INFO, Red, "窗口20s未完成加载, 自动重载页面…")
                try:
                    _win.load_url(url)
                except Exception:
                    pass

        import threading as _thw
        _thw.Thread(target=_load_watchdog, daemon=True).start()
        # [2026-10-24] 窗口/任务栏图标(Windows必须.ico, PNG会触发Icon异常)
        _icon = os.path.join("assets", "app_icon.ico")
        webview.start(icon=_icon if os.path.isfile(_icon) else None)
    except Exception as _e:
        # 无WebView2/pywebview异常 → 退化为开浏览器
        log_print(INFO, Yellow, f"桌面窗口不可用({_e}), 改用浏览器打开")
        try:
            import webbrowser
            webbrowser.open(url)
            while True:
                _time.sleep(3600)
        except Exception:
            from logic.launcher import lunch
            return lunch()
