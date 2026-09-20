# -*- coding: utf-8 -*-
"""设置 GitHub Release 附件的中文显示名(label)

用法: python set_asset_label.py <owner/repo> <tag> <asset名> <中文显示名>
环境: 需 GH_TOKEN (workflow 中使用 secrets.GITHUB_TOKEN)

说明: GitHub Release 附件真实文件名不支持非 ASCII 字符(GitHub 会将其
      sanitize), 因此实际文件名使用 ASCII, 通过 label 提供中文显示名。
"""
import json
import os
import sys
import time
import urllib.request


def api(url: str, method: str = "GET", data: dict = None):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=body, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if len(sys.argv) < 5:
        print("usage: set_asset_label.py <repo> <tag> <asset_name> <label>")
        return 1
    repo, tag, asset_name, label = sys.argv[1:5]

    # 附件可能尚未对 API 可见, 重试几次
    asset_id = None
    for _ in range(6):
        rel = api(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        for a in rel.get("assets", []):
            if a["name"] == asset_name:
                asset_id = a["id"]
                break
        if asset_id:
            break
        time.sleep(5)

    if not asset_id:
        print(f"[label] asset not found: {asset_name}")
        return 1

    try:
        api(f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
            method="PATCH", data={"label": label})
    except Exception as e:
        print(f"[label] 设置失败(不影响下载): {e}")
        return 0  # label 失败不阻塞流程

    print(f"[label] OK: {asset_name} -> {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
