# -*- coding: utf-8 -*-
"""GitHub Releases 在线更新检测（纯 Python，不依赖 Qt）。

查询 GitHub 最新正式版 Release，把 tag / 名称 / 更新说明 / 下载链接返回给界面层；
网络失败、被限流、解析失败一律抛异常，由界面层静默降级，不影响灯控主流程。
"""

import json
import re
import urllib.request

REPO_OWNER = "kcsvip"
REPO_NAME = "x99-console"
API_URL = "https://api.github.com/repos/%s/%s/releases/latest" % (REPO_OWNER, REPO_NAME)
RELEASES_URL = "https://github.com/%s/%s/releases" % (REPO_OWNER, REPO_NAME)
USER_AGENT = "x99-console-update-check"

_TAG_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_version(text):
    """把 'v1.6.2' / '1.6.3-beta' 解析成 (1, 6, 2)；解析不出返回 None。"""
    m = _TAG_RE.search(text or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_newer(latest_tag, current):
    """latest_tag 是否比 current 新；版本号都解析不出来时保守返回 False。"""
    a, b = parse_version(latest_tag), parse_version(current)
    if not a or not b:
        return False
    return a > b


def fetch_latest(timeout=5):
    """拉取最新正式版 Release。

    返回 dict：tag / name / url / body / prerelease / assets。
    网络或解析问题抛异常，由调用方兜底。
    """
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))

    assets = []
    for a in data.get("assets") or []:
        assets.append({
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": a.get("size") or 0,
        })

    return {
        "tag": data.get("tag_name") or "",
        "name": data.get("name") or data.get("tag_name") or "",
        "url": data.get("html_url") or RELEASES_URL,
        "body": data.get("body") or "",
        "prerelease": bool(data.get("prerelease")),
        "assets": assets,
    }
