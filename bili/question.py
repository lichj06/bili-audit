#!/usr/bin/env python3
"""问号指数 —— 评论区与弹幕的「问号密度」测量器

设计约束（来自 2026-09-23 的隐私事故教训）：
  · 只输出聚合统计，**不保存评论文本、不保存任何用户标识**
  · 因此这个工具可以直接公开发布，不依赖 data/raw-local/
  · 请求带限速；遇到风控（-352）退避重试，不硬冲

用法:
  python3 -m bili.question BV1xxxxxxxxx
  python3 -m bili.question BV1xxx BV2yyy --comment-pages 2 --danmaku-segments 3
  python3 -m bili.question BV1xxx --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request

from . import api

UA = api.HEADERS.get("User-Agent", "Mozilla/5.0")
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

# wbi 签名用的固定置换表（B 站公开的 web 端算法）
_MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _mixin_key(img_key: str, sub_key: str) -> str:
    return "".join((img_key + sub_key)[i] for i in _MIXIN_TAB)[:32]


def _wbi_keys() -> tuple[str, str]:
    """未登录也能拿到 wbi key（nav 返回 -101 但 data.wbi_img 仍在）。"""
    d = json.loads(api._get("https://api.bilibili.com/x/web-interface/nav", timeout=15))
    wi = (d.get("data") or {}).get("wbi_img") or {}
    if not wi:
        raise RuntimeError("拿不到 wbi_img（风控或接口变更）")
    ik = wi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sk = wi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    return ik, sk


def _signed(path: str, params: dict, keys: tuple[str, str]) -> str:
    p = dict(params)
    p["wts"] = int(time.time())
    p = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in sorted(p.items())}
    q = urllib.parse.urlencode(p)
    p["w_rid"] = hashlib.md5((q + _mixin_key(*keys)).encode()).hexdigest()
    return f"https://api.bilibili.com{path}?" + urllib.parse.urlencode(p)


def _get_json(url: str, timeout: int = 20, retries: int = 3) -> dict:
    """带退避的请求：风控（-352）就等一等再试，不硬冲。"""
    last = None
    for i in range(retries):
        try:
            raw = api._get(url, timeout=timeout)
            d = json.loads(raw)
        except Exception as e:                       # 网络层
            last = e
            time.sleep(2.0 * (i + 1))
            continue
        code = d.get("code")
        if code == 0:
            return d
        last = RuntimeError(f"code={code} message={d.get('message')}")
        if code in (-352, -412, -509):               # 风控 / 限流
            time.sleep(3.0 * (i + 1))
            continue
        break
    raise RuntimeError(f"请求失败: {url[:80]} … {last}")


# ----------------------------------------------------------------- 抓取
def fetch_comments(aid: int, pages: int = 3, per_page: int = 20, sleep: float = 2.0) -> list[str]:
    """抓评论正文（只用于当场统计，不落盘）。分页用 cursor.next，不是 pn。"""
    keys = _wbi_keys()
    out: list[str] = []
    nxt = 1
    for _ in range(max(1, pages)):
        url = _signed("/x/v2/reply/wbi/main",
                      {"oid": aid, "type": 1, "mode": 3, "ps": per_page,
                       "pn": nxt, "web_location": 1315875}, keys)
        d = _get_json(url)
        data = d.get("data") or {}
        for r in (data.get("replies") or []):
            msg = r.get("content", {}).get("message")
            if msg:
                out.append(msg)
        cur = data.get("cursor") or {}
        if cur.get("is_end"):
            break
        nxt = cur.get("next") or (nxt + 1)
        time.sleep(sleep)
    return out


def fetch_danmaku(cid: int, segments: int = 3, sleep: float = 1.0) -> list[str]:
    """抓弹幕正文。seg.so 是 protobuf，复用 repo 里已有的解析器。"""
    out: list[str] = []
    for seg in range(1, max(1, segments) + 1):
        try:
            raw = api.danmaku_raw(cid, seg)
        except Exception:
            break
        if not raw:
            break
        dms = api.parse_danmaku(raw)
        if not dms:
            break
        out += [str(d.get("content", "")) for d in dms]
        time.sleep(sleep)
    return out


# ----------------------------------------------------------------- 统计
_Q = ("?", "？")
_E = ("!", "！")


def q_metrics(texts: list[str]) -> dict:
    """问号 + 感叹号密度指标。全部是聚合值，不含任何原文或用户标识。

    按个数分档（1 / 2 / 3+），所以「单个问号」和「单个感叹号」各自单独计入，
    不会被 ≥3 那一档吞掉。
    """
    n = len(texts)
    if n == 0:
        return {"n": 0}

    def cnt(t: str, chars: tuple) -> int:
        return sum(t.count(c) for c in chars)

    wq = we = both = 0
    q = [0, 0, 0]          # 1 个 / 2 个 / 3+ 个
    e = [0, 0, 0]
    pure_q = pure_e = pure_mix = 0
    total_q = total_e = 0
    for t in texts:
        a, b = cnt(t, _Q), cnt(t, _E)
        total_q += a
        total_e += b
        if a:
            wq += 1
            q[min(a, 3) - 1] += 1
        if b:
            we += 1
            e[min(b, 3) - 1] += 1
        if a and b:
            both += 1
        s = t.strip()
        if not s:
            continue
        if all(c in _Q for c in s):
            pure_q += 1
        elif all(c in _E for c in s):
            pure_e += 1
        elif all(c in _Q + _E for c in s):
            pure_mix += 1

    r = lambda x: round(x / n, 4)
    return {
        "n": n,
        # 覆盖度
        "含问号比例": r(wq),
        "含感叹号比例": r(we),
        "问叹同时出现比例": r(both),
        # 按个数分档（1 个单独计入）
        "问号1个": r(q[0]), "问号2个": r(q[1]), "问号3个以上": r(q[2]),
        "感叹1个": r(e[0]), "感叹2个": r(e[1]), "感叹3个以上": r(e[2]),
        # 纯符号条（整条只有符号）
        "纯问号": r(pure_q), "纯感叹号": r(pure_e), "纯问叹混合": r(pure_mix),
        # 强度
        "平均每条问号数": round(total_q / n, 3),
        "平均每条感叹号数": round(total_e / n, 3),
    }


def measure(bvid: str, comment_pages: int = 3, danmaku_segments: int = 3) -> dict:
    v = api.video_info(bvid)
    aid, cid = v["aid"], v["cid"]
    stat = v.get("stat") or {}
    cs = fetch_comments(aid, comment_pages)
    ds = fetch_danmaku(cid, danmaku_segments)
    return {
        "bvid": bvid,
        "title": v.get("title"),
        "owner": (v.get("owner") or {}).get("name"),
        "tname": v.get("tname"),
        "views": stat.get("view"), "likes": stat.get("like"),
        "replies_total": stat.get("reply"), "danmaku_total": stat.get("danmaku"),
        "评论问号": q_metrics(cs),
        "弹幕问号": q_metrics(ds),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="问号指数：评论区与弹幕的问号密度")
    ap.add_argument("bvids", nargs="+")
    ap.add_argument("--comment-pages", type=int, default=3)
    ap.add_argument("--danmaku-segments", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    results = []
    for bv in a.bvids:
        try:
            r = measure(bv, a.comment_pages, a.danmaku_segments)
        except Exception as e:
            print(f"[失败] {bv}: {e}", file=sys.stderr)
            continue
        results.append(r)
        print(f"\n=== {r['title'][:44]}  ({r['bvid']})")
        print(f"    分区 {r['tname']} | UP {r['owner']}")
        print(f"    播放 {r['views']} 点赞 {r['likes']} 评论总数 {r['replies_total']} 弹幕总数 {r['danmaku_total']}")
        for k in ("评论问号", "弹幕问号"):
            m = r[k]
            if not m.get("n"):
                print(f"    {k}  没抓到样本")
                continue
            p = lambda x: f"{m[x]:.2%}"
            print(f"    {k}  样本 {m['n']}")
            print(f"        含问号 {p('含问号比例')}  含感叹号 {p('含感叹号比例')}"
                  f"  问叹同时 {p('问叹同时出现比例')}")
            print(f"        问号 1个 {p('问号1个')} · 2个 {p('问号2个')} · 3+个 {p('问号3个以上')}")
            print(f"        感叹 1个 {p('感叹1个')} · 2个 {p('感叹2个')} · 3+个 {p('感叹3个以上')}")
            print(f"        纯问号 {p('纯问号')}  纯感叹号 {p('纯感叹号')}"
                  f"  纯问叹混合 {p('纯问叹混合')}")
            print(f"        均每条 问号 {m['平均每条问号数']}  感叹号 {m['平均每条感叹号数']}")
        time.sleep(1.5)

    if a.json:
        json.dump(results, open(a.json, "w"), ensure_ascii=False, indent=2)
        print(f"\n已写入 {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
