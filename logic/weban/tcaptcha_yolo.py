# -*- coding: utf-8 -*-
"""[V3.2.4] TCaptcha word_click 识别增强: 进程隔离调用 crack-tcaptcha

背景: 现有 detect_points(OpenCV 模板匹配) 单次识别率约 50%(靠重试);
      crackTCaptcha(https://github.com/hailan09/crackTCaptcha) 的 YOLO+Siamese
      ONNX 模型(随 wheel 打包, ~44MB) 对 word_click 一次通过。

合规: 以其 CLI 独立子进程方式调用(不链接进主程序), 规避 GPL-3.0 传染;
      独立 venv(tools/tcaptcha_venv)安装, 不污染主项目依赖;
      未安装/失败时调用方自动回退现有 OpenCV 流程。

安装(仅首次):
  python -m venv tools/tcaptcha_venv
  tools/tcaptcha_venv/Scripts/pip install "crack-tcaptcha[word-click]" -i https://pypi.tuna.tsinghua.edu.cn/simple
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional


def _cli_path() -> str:
    """定位独立 venv 中的 crack-tcaptcha CLI(跨平台)"""
    base = os.path.dirname(os.path.abspath(__file__))
    roots = [
        os.path.join(base, "..", "..", ".."),  # 项目根
        os.path.join(base, "..", ".."),        # yatori-python-console
    ]
    names = (
        os.path.join("tools", "tcaptcha_venv",
                     "Scripts", "crack-tcaptcha.exe"),
        os.path.join("tools", "tcaptcha_venv", "bin", "crack-tcaptcha"),
    )
    for r in roots:
        for n in names:
            p = os.path.normpath(os.path.join(r, n))
            if os.path.isfile(p):
                return p
    return ""


def available() -> bool:
    return bool(_cli_path())


def extract_appid_from_page(pg) -> str:
    """从已打开的 Playwright 页面提取 TCaptcha appId(考试场景为动态值)。

    来源优先级: window 对象上的 tcaptcha 配置 -> 内联脚本正则。
    失败返回空串(调用方保持固定默认 appId 或跳过)。
    """
    try:
        v = pg.evaluate("""() => {
            try {
                var w = window;
                for (var k in w) {
                    try {
                        var o = w[k];
                        if (!o || typeof o !== 'object') continue;
                        var a = o.appId || o.appid
                              || (o.captchaCfg && o.captchaCfg.appid)
                              || (o.cfg && o.cfg.appid);
                        if (a && /^[0-9]{6,12}$/.test(String(a))) return String(a);
                    } catch (e2) {}
                }
            } catch (e1) {}
            try {
                var txt = document.documentElement.outerHTML || '';
                var m = txt.match(/appid['\"]?\\s*[:=]\\s*['\"]?([0-9]{6,12})/i);
                if (m) return m[1];
            } catch (e3) {}
            return '';
        }""")
        return str(v or "").strip()
    except Exception:
        return ""


def _parse_json_out(out: str) -> Optional[dict]:
    for ln in reversed((out or "").splitlines()):
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            return json.loads(ln)
        except Exception:
            continue
    return None


def solve_word_click(app_id: str, entry_url: str = "", log: Any = None,
                     timeout: float = 120.0, retries: int = 2) -> Optional[dict]:
    """子进程求解 TCaptcha(自动按难度分流, 当前主打磨 word_click)。

    :return: {"ticket": "tr03...", "randstr": "@xx"} 或 None(未安装/失败)
    """
    exe = _cli_path()
    if not exe or not app_id:
        return None
    cmd = [exe, "solve", "--appid", str(app_id),
           "--retries", str(max(1, int(retries or 1))), "--json"]
    if entry_url:
        cmd += ["--entry-url", str(entry_url)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace")
        out = (proc.stdout or "").strip()
        obj = _parse_json_out(out)
        if obj and obj.get("ok") and obj.get("ticket"):
            if log is not None:
                try:
                    log.info(f"TCaptcha(YOLO子进程) 求解成功 "
                             f"randstr={obj.get('randstr', '')}")
                except Exception:
                    pass
            return {"ticket": obj["ticket"], "randstr": obj.get("randstr", "")}
        if log is not None:
            try:
                log.warning(f"TCaptcha(YOLO子进程) 失败 rc={proc.returncode} "
                            f"out={(out or (proc.stderr or ''))[:120]}")
            except Exception:
                pass
    except Exception as e:
        if log is not None:
            try:
                log.warning(f"TCaptcha(YOLO子进程) 异常: {str(e)[:100]}")
            except Exception:
                pass
    return None
