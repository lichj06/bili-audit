#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享数据管道：读取原始数据 → 去重 → 计算指标 / 稳健 z 分数 / 分位数。

为什么单独抽出来
----------------
`analyze.py` 和 `make_figures.py` 必须用**同一套**分位数与偏离度算法，
否则报告表里的中位数和 SVG 图里的中位数会打架（旧版就是这样：26.53% vs 27.8%）。

三条纪律
--------
① 评论按【内容】去重后再算任何指标 —— x/v2/reply/main 的 pn 参数无效，
   同一页会被重复写入（见 README「已知缺陷」）。
② z 分数**保留符号**：(x − median) / (1.4826 × MAD)。
   旧版取绝对值，导致「投币比偏低」永远判不出来。
③ 只有明确方向的指标才用单侧阈值，方向写在 flag 名字里。
"""

from __future__ import annotations

import json
import os
import re
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
REPORT = os.path.join(ROOT, "report")

Q_PAT = re.compile(r"[?？]")
Q3_PAT = re.compile(r"[?？]{3,}")

# 指标 → 方向：high = 只有偏高才可疑；low = 只有偏低才可疑；both = 双侧
METRIC_DIRECTION = {
    "r_like_view": "high",     # 点赞/播放 异常高
    "r_coin_like": "low",      # 投币/点赞 异常低（投币贵，刷不动 → 注水形态）
    "dup_prefix8": "high",     # 前 8 字重复度 异常高（模板化）
    "r_fav_like": "both",
    "r_share_view": "both",
    "r_reply_view": "both",
    "r_danmaku_view": "both",
    "q_rate": "both",
    "q3_rate": "both",
}


# ── 读取 ────────────────────────────────────────────────────────────────
def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def dedup_comments(comments: list[dict]) -> tuple[list[dict], dict]:
    """按 (aid, 文本) 去重。

    实测：`x/v2/reply/main` 的 `pn` 参数不生效（pn=1/2/3 返回同一批 rpid），
    所以 1086 行里绝大多数是同一页被抄了多遍。去重是**先于一切指标**的一步，
    不去重的话「重复率」测的是采集器的 bug，不是评论区的形态。
    """
    seen = set()
    out = []
    for c in comments:
        key = (c.get("aid"), (c.get("content") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    per_video: dict = defaultdict(lambda: {"raw": 0, "uniq": 0})
    for c in comments:
        per_video[c.get("aid")]["raw"] += 1
    for c in out:
        per_video[c.get("aid")]["uniq"] += 1
    return out, dict(per_video)


# ── 统计工具（analyze 与 make_figures 共用）────────────────────────────
def percentile(values: list[float], p: float) -> float:
    """线性插值分位数，等价于 statistics.quantiles(method="inclusive")。

    旧版 make_figures.q() 取 `v[int(len(v)*p)]`（不插值）→ 与 analyze 报告的
    中位数打架。两处必须调同一个函数。
    """
    if not values:
        return 0.0
    v = sorted(values)
    if len(v) == 1:
        return float(v[0])
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return float(v[lo] + (v[hi] - v[lo]) * (k - lo))


def median(values: list[float]) -> float:
    return float(st.median(values)) if values else 0.0


def mad(values: list[float]) -> float:
    if not values:
        return 0.0
    med = st.median(values)
    return float(st.median([abs(v - med) for v in values]))


def robust_z(values: list[float], x: float) -> float:
    """**有符号**稳健 z 分数：(x − median) / (1.4826 × MAD)。MAD=0 或样本 <4 时返回 0。

    有符号是必须的：旧版返回绝对值，于是 `z_coin_like >= 3.0` 这种
    「偏低」判据永远不成立（实测该指标最大 |z| = 2.84）。
    """
    if len(values) < 4:
        return 0.0
    m = mad(values)
    if m <= 1e-12:
        return 0.0
    return (x - st.median(values)) / (1.4826 * m)


def safe_div(a, b) -> float:
    try:
        return float(a) / float(b) if b else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


# ── 数据源选择 ─────────────────────────────────────────────────────────
RAW_DIR = os.path.join(DATA, "raw-local")


def load_comments_for_analysis() -> tuple[list[dict], str]:
    """优先用原始评论（能算文本指标）；没有则用发布版的逐视频派生指标。

    返回 (记录, 数据源说明)。两种来源算出的指标必须一致 —— 见 README「一键验证」。
    """
    raw = os.path.join(RAW_DIR, "comments.jsonl")
    if os.path.exists(raw):
        recs = load_jsonl(raw)
        if recs and any("content" in r for r in recs):
            return recs, "data/raw-local/comments.jsonl（原始评论，本机留档）"
    pub = load_jsonl(os.path.join(DATA, "comments.jsonl"))
    if pub and all("n_texts_unique" in r for r in pub):
        return pub, "data/comments.jsonl（发布版逐视频派生指标）"
    return [], "无可用评论数据"


def metrics_from_derived(v: dict, d: dict) -> dict:
    """发布版评论指标 → 与 video_metrics() 同形的行（问号类指标缺失，置 None）。"""
    view = v.get("view") or 0
    like = v.get("like") or 0
    return {
        "bvid": v.get("bvid"), "aid": v.get("aid"),
        "view": view, "like": like, "coin": v.get("coin") or 0,
        "favorite": v.get("favorite") or 0, "share": v.get("share") or 0,
        "reply": v.get("reply") or 0, "danmaku": v.get("danmaku") or 0,
        "n_comments_sampled": d.get("n_texts_unique", 0),
        "r_like_view": safe_div(like, view),
        "r_coin_like": safe_div(v.get("coin"), like),
        "r_fav_like": safe_div(v.get("favorite"), like),
        "r_share_view": safe_div(v.get("share"), view),
        "r_reply_view": safe_div(v.get("reply"), view),
        "r_danmaku_view": safe_div(v.get("danmaku"), view),
        "uniq_texts": d.get("n_texts_unique", 0),
        "dup_exact": d.get("dup_exact", 0.0),
        "dup_prefix8": d.get("dup_prefix8", 0.0),
        "mean_level": d.get("level_mean"),
        "q_rate": None, "q3_rate": None, "q_per_1k_chars": None, "q_total": None,
    }


# ── 指标 ────────────────────────────────────────────────────────────────
def video_metrics(v: dict, cs: list[dict]) -> dict:
    """单个视频的互动比 + 评论文本特征 + 问号指数。cs 必须是**已去重**的评论。"""
    view = v.get("view") or 0
    like = v.get("like") or 0
    coin = v.get("coin") or 0
    fav = v.get("favorite") or 0
    share = v.get("share") or 0
    reply = v.get("reply") or 0
    danmaku = v.get("danmaku") or 0

    texts = [(c.get("content") or "").strip() for c in cs]
    texts = [t for t in texts if t]
    n = len(texts)
    q_hit = sum(1 for t in texts if Q_PAT.search(t))
    q3_hit = sum(1 for t in texts if Q3_PAT.search(t))
    q_total = sum(len(Q_PAT.findall(t)) for t in texts)
    chars = sum(len(t) for t in texts)
    levels = [c.get("level") for c in cs if isinstance(c.get("level"), int)]

    return {
        "bvid": v.get("bvid"), "aid": v.get("aid"),
        "view": view, "like": like, "coin": coin, "favorite": fav,
        "share": share, "reply": reply, "danmaku": danmaku,
        "n_comments_sampled": n,
        # ── 互动比 ──
        "r_like_view": safe_div(like, view),
        "r_coin_like": safe_div(coin, like),
        "r_fav_like": safe_div(fav, like),
        "r_share_view": safe_div(share, view),
        "r_reply_view": safe_div(reply, view),
        "r_danmaku_view": safe_div(danmaku, view),
        # ── 评论文本特征（在去重后的集合上算）──
        "uniq_texts": n,
        "dup_exact": 1 - safe_div(len(set(texts)), n),
        "dup_prefix8": 1 - safe_div(len({t[:8] for t in texts}), n),
        "mean_level": st.mean(levels) if levels else None,
        # ── 问号指数 ──
        "q_rate": safe_div(q_hit, n),
        "q3_rate": safe_div(q3_hit, n),
        "q_per_1k_chars": safe_div(q_total * 1000, chars),
        "q_total": q_total,
    }


def analyse(videos: list[dict], comments: list[dict], min_comments: int = 10,
            source: str = "") -> dict:
    """videos 含评论不足 min_comments 条（去重后）的会被跳过。

    comments 可以是两种形状：
      · 原始评论（每行一条，有 content）→ 去重后算全部指标
      · 发布版派生指标（每行一个视频，有 n_texts_unique）→ 只用已算好的重复度，
        问号类指标缺数据，行里置 None（不编数）

    默认 10 而不是 20：本批数据去重后每个视频只有 18–21 条唯一评论，
    阈值取 20 会把 18 个视频砍到 10 个。取 10 时结果与 18 完全相同（见 README）。
    """
    derived = bool(comments) and all("n_texts_unique" in c for c in comments) \
        and not any("content" in c for c in comments)

    if derived:
        by_video = {c.get("aid"): c for c in comments}
        n_raw = sum(c.get("n_rows_raw") or 0 for c in comments)
        n_uniq = sum(c.get("n_texts_unique") or 0 for c in comments)
        n_uniq_text = None
    else:
        comments, per_video = dedup_comments(comments)
        tmp: dict = defaultdict(list)
        for c in comments:
            tmp[c.get("aid")].append(c)
        by_video = tmp
        n_raw = sum(p["raw"] for p in per_video.values())
        n_uniq = len(comments)
        n_uniq_text = len({c.get("content") for c in comments})

    rows, skipped = [], 0
    for v in videos:
        cs = by_video.get(v.get("aid"))
        if not cs:
            skipped += 1
            continue
        if derived:
            if (cs.get("n_texts_unique") or 0) < min_comments:
                skipped += 1
                continue
            rows.append(metrics_from_derived(v, cs))
        else:
            if len(cs) < min_comments:
                skipped += 1
                continue
            rows.append(video_metrics(v, cs))

    # ── 有符号稳健偏离度 ──
    for k in METRIC_DIRECTION:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        for r in rows:
            r[f"z_{k}"] = round(robust_z(vals, r[k]), 2) if isinstance(r.get(k), (int, float)) else 0.0

    # ── 方向性标记（3.0 阈值，单侧；方向见 METRIC_DIRECTION）──
    flags = {"flag_like_high": ("z_r_like_view", "high"),
             "flag_coin_low": ("z_r_coin_like", "low"),
             "flag_dup_high": ("z_dup_prefix8", "high")}
    for r in rows:
        r["flag_like_high"] = r["z_r_like_view"] >= 3.0
        r["flag_coin_low"] = r["z_r_coin_like"] <= -3.0
        r["flag_dup_high"] = r["z_dup_prefix8"] >= 3.0
        r["n_flags"] = sum([r["flag_like_high"], r["flag_coin_low"], r["flag_dup_high"]])
        r["q_index"] = round(r["q_rate"] * 100, 1) if isinstance(r.get("q_rate"), (int, float)) else None

    # 可达性诊断：某个标记若在**本批数据里根本不可能为真**，报告必须说明，
    # 不能只写「0 个触发」——那会被读成「数据正常」。
    diag = {}
    for name, (zkey, direction) in flags.items():
        zs = [r[zkey] for r in rows] or [0.0]
        extreme = max(zs) if direction == "high" else min(zs)
        metric = zkey.lstrip("z_")
        if metric == "r_like_view":
            metric = "r_like_view"
        diag[name] = {
            "metric": metric.replace("z_", ""), "direction": direction, "threshold": 3.0,
            "extreme_z": round(extreme, 2),
            "reachable": bool(extreme >= 3.0) if direction == "high" else bool(extreme <= -3.0),
            "mad_zero": mad([r[metric] for r in rows if isinstance(r.get(metric), (int, float))]) <= 1e-12,
        }

    return {
        "rows": rows,
        "n_videos": len(rows),
        "n_videos_sampled": len(videos),
        "n_skipped_low_comment": skipped,
        "n_comments_raw": n_raw,
        "n_comments_unique": n_uniq,
        "n_comments_unique_text": n_uniq_text,
        "n_videos_zero_comment": sum(1 for v in videos if not by_video.get(v.get("aid"))),
        "min_comments": min_comments,
        "comment_source": source or ("发布版派生指标" if derived else "原始评论"),
        "dedup_rule": "按 (aid, 评论文本) 精确去重 —— 同一视频内完全相同的文本只计一次",
        "flag_rule": ("稳健 z =(x−median)/(1.4826×MAD)，阈值 |z|≥3；"
                      "方向：点赞率取高尾、投币比取低尾、前8字重复率取高尾"),
        "flag_diagnostics": diag,
    }
