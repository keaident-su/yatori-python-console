# -*- coding: utf-8 -*-
"""[V3.2.5] 账号启动来源标签统一定义。

目标(对应需求): 账号一旦启动, 能从日志一眼判断这次启动是
"手动"还是"自动", 以及具体触发方式; 文案统一、清晰、可 grep。

分类口径(TIDE 控制台式排查):
  手动类
    - GUI手动        : 桌面 GUI(pywebview) 单账号点"启动"
    - Web前端手动    : 浏览器 Web UI 单账号点"启动"
    - GUI批量        : 桌面 GUI "一键启动全部空闲"
    - Web批量        : 浏览器 Web UI "一键启动全部空闲"
    - API手动        : 直接调用 /api/v1/startBrush 等 HTTP 接口(含第三方/运维脚本)
  自动类(由启动监督器 start_supervisor 触发)
    - 守护自动重启   : 运行线程异常崩溃后自动拉起
    - 巡检自动恢复   : 巡检发现"本应运行却掉线"时自动恢复
    - 定时任务       : 到达配置的定时启动时刻
    - 服务重启拉起   : 进程重启后自动恢复上次运行中的账号
    - 夜间恢复       : 夜间休息结束, 任务由暂停转为继续(非新起线程, 仅打点)
    - 批量脚本       : 外部批量/恢复脚本(可经 ?source= 自报)

统一日志标签格式(含排查信息):
    [启动来源: Web前端手动][接口: /ui/api/task/start][IP: 1.2.3.4]
"""

SOURCE_UNKNOWN = "未标注"

# ---- 手动类 ----
SRC_GUI = "GUI手动"
SRC_WEB = "Web前端手动"
SRC_GUI_BATCH = "GUI批量"
SRC_WEB_BATCH = "Web批量"
SRC_API = "API手动"

# ---- 自动类 ----
SRC_DAEMON_RESTART = "守护自动重启"
SRC_PATROL = "巡检自动恢复"
SRC_SCHEDULE = "定时任务"
SRC_BOOT = "服务重启拉起"
SRC_NIGHT = "夜间恢复"
SRC_SCRIPT = "批量脚本"

ALL_SOURCES = (
    SRC_GUI, SRC_WEB, SRC_GUI_BATCH, SRC_WEB_BATCH, SRC_API,
    SRC_DAEMON_RESTART, SRC_PATROL, SRC_SCHEDULE, SRC_BOOT,
    SRC_NIGHT, SRC_SCRIPT,
)

# 自动类来源集合: 启动监督器据此判定, 且 mark_desired 时不重置重试计数
AUTO_SOURCES = frozenset({
    SRC_DAEMON_RESTART, SRC_PATROL, SRC_SCHEDULE, SRC_BOOT, SRC_NIGHT,
})


def is_auto(source: str) -> bool:
    """是否为自动启动来源(守护/巡检/定时/开机/夜间)。"""
    return (source or "").strip() in AUTO_SOURCES


def fmt_tag(source: str, iface: str = "", ip: str = "") -> str:
    """格式化统一来源标签。

    :param source: 来源文案(空则回退"未标注")
    :param iface:  触发接口路径(可选, 如 /ui/api/task/start)
    :param ip:     客户端 IP(可选)
    :return: 如 "[启动来源: X][接口: /a][IP: 1.2.3.4]"；无附加信息时只含来源段
    """
    parts = ["[启动来源: %s]" % (str(source or "").strip() or SOURCE_UNKNOWN)]
    if iface:
        parts.append("[接口: %s]" % iface)
    if ip:
        parts.append("[IP: %s]" % ip)
    return "".join(parts)
