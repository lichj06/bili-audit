#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站公开接口客户端（仅用公开数据，不需要登录）。

已验证可用（2026-09-23，容器内无 cookie）：
  · x/web-interface/view?bvid=     视频信息 + stat（view/like/coin/fav/share/reply/danmaku）
  · x/web-interface/popular        热门榜（批量取视频）
  · x/v2/reply?type=1&oid=         评论（JSON）
  · x/v2/dm/web/seg.so?oid=        弹幕（protobuf，需自解析）
"""
from __future__ import annotations
import json, time, urllib.request, urllib.parse, gzip, io, zlib

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com",
           "Accept-Language": "zh-CN,zh;q=0.9", "Accept-Encoding": "gzip"}


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def get_json(url: str, timeout: int = 20, retries: int = 2) -> dict:
    last = None
    for i in range(retries + 1):
        try:
            return json.loads(_get(url, timeout).decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def video_info(bvid: str) -> dict:
    d = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if d.get("code") != 0:
        raise RuntimeError(f"view 接口返回 code={d.get('code')} {d.get('message')}")
    return d["data"]


def popular(ps: int = 20, pn: int = 1) -> list[dict]:
    d = get_json(f"https://api.bilibili.com/x/web-interface/popular?ps={ps}&pn={pn}")
    return (d.get("data") or {}).get("list", []) if d.get("code") == 0 else []


def comments(aid: int, pn: int = 1, ps: int = 20, sort: int = 2) -> dict:
    # 【实测】旧端点 x/v2/reply 只返回 3 条；x/v2/reply/main 返回满 ps 条
    url = (f"https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}"
           f"&mode=3&ps={ps}&pn={pn}")
    d = get_json(url)
    if d.get("code") != 0:
        return {"count": 0, "replies": [], "code": d.get("code")}
    data = d.get("data") or {}
    return {"count": (data.get("page") or {}).get("count", 0),
            "replies": data.get("replies") or [], "code": 0}


def danmaku_raw(aid: int, segment: int = 1) -> bytes:
    return _get(f"https://api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid={aid}&segment_index={segment}")


# ── 极简 protobuf 解析（只解 DanmakuElem 需要的字段）────────────────
def _varint(buf: bytes, i: int):
    shift = val = 0
    while True:
        b = buf[i]; i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7


def _fields(buf: bytes):
    """返回 [(field_no, wire_type, value)]，value 为 int(bytes 型则为原始字节)。"""
    i, n, out = 0, len(buf), []
    while i < n:
        key, i = _varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 2:
            ln, i = _varint(buf, i)
            v = buf[i:i + ln]; i += ln
        elif wt == 5:
            v = buf[i:i + 4]; i += 4
        elif wt == 1:
            v = buf[i:i + 8]; i += 8
        else:
            break
        out.append((fn, wt, v))
    return out


def parse_danmaku(buf: bytes) -> list[dict]:
    """解析 DmSegMobileReply：field1 = repeated DanmakuElem。

    DanmakuElem: 1=id 2=progress(ms) 3=mode 4=fontsize 5=color
                 6=midHash 7=content 8=ctime 9=weight 10=pool
    """
    out = []
    for fn, wt, val in _fields(buf):
        if fn != 1 or wt != 2:
            continue
        rec = {}
        for f2, w2, v2 in _fields(val):
            if f2 == 1: rec["id"] = v2
            elif f2 == 2: rec["progress"] = v2
            elif f2 == 3: rec["mode"] = v2
            elif f2 == 6: rec["mid_hash"] = v2.decode("utf-8", "replace") if isinstance(v2, bytes) else str(v2)
            elif f2 == 7: rec["content"] = v2.decode("utf-8", "replace") if isinstance(v2, bytes) else str(v2)
            elif f2 == 8: rec["ctime"] = v2
        if rec.get("content"):
            out.append(rec)
    return out
