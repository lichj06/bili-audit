#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一分析：把「注水检测」和「问号指数」放进同一个框架 —— 互动数据的分布形状。

框架
----
两类问题本质是同一个问题的两面：

    注水（假互动）  分布过于【规则/突变】：点赞率高但投币率极低、评论高度模板化
    问号（真共鸣）  分布有【结构】：短促、密集、情绪集中、语义多样

两者都用同一批采到的数据算，都不做"判定"，只做【相对群体分布的偏离度】。

三个纪律
--------
① 只描述指标偏离群体分布的程度，**不下"这个视频注水了"的结论**
② 用稳健统计（中位数 + MAD），避免少数极端值污染阈值
③ 所有指标都给出计算方式，可复现、可反驳
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "report")

Q_PAT = re.compile(r"[?？]")
Q3_PAT = re.compile(r"[?？]{3,}")


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def safe_div(a, b) -> float:
    try:
        return float(a) / float(b) if b else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def mad_z(values: list[float], x: float) -> float:
    """稳健 z 分数：|x − median| / (1.4826 × MAD)。MAD 为 0 时返回 0。"""
    if len(values) < 4:
        return 0.0
    med = st.median(values)
    mad = st.median([abs(v - med) for v in values])
    if mad <= 1e-12:
        return 0.0
    return abs(x - med) / (1.4826 * mad)


def analyse(videos: list[dict], comments: list[dict], min_comments: int = 20) -> dict:
    by_video: dict[int, list[dict]] = defaultdict(list)
    for c in comments:
        by_video[c["aid"]].append(c)

    rows = []
    skipped = 0
    for v in videos:
        # 只保留评论样本足够的视频 —— 评论太少的视频会让 q_rate 等比例指标失去意义
        if len(by_video.get(v.get("aid"), [])) < min_comments:
            skipped += 1
            continue
        aid = v.get("aid")
        cs = by_video.get(aid, [])
        view = v.get("view") or 0
        like = v.get("like") or 0
        coin = v.get("coin") or 0
        fav = v.get("favorite") or 0
        share = v.get("share") or 0
        reply = v.get("reply") or 0
        danmaku = v.get("danmaku") or 0

        texts = [c["content"] for c in cs]
        n = len(texts)
        # 评论重复度：完全重复率 + 前 8 字重复率（水军模板的典型特征）
        exact = 1 - len(set(texts)) / n if n else 0.0
        prefix = 1 - len({t[:8] for t in texts}) / n if n else 0.0
        # 问号指数
        q_hit = sum(1 for t in texts if Q_PAT.search(t))
        q3_hit = sum(1 for t in texts if Q3_PAT.search(t))
        q_total = sum(len(Q_PAT.findall(t)) for t in texts)
        chars = sum(len(t) for t in texts)
        # 评论者特征
        levels = [c.get("level") for c in cs if isinstance(c.get("level"), int)]
        uids = [c.get("uid_hash") for c in cs if c.get("uid_hash")]

        rows.append({
            "bvid": v.get("bvid"), "aid": aid, "title": v.get("title"),
            "tname": v.get("tname"), "duration": v.get("duration"),
            "view": view, "like": like, "coin": coin, "favorite": fav,
            "share": share, "reply": reply, "danmaku": danmaku,
            "n_comments_sampled": n,
            # ── 互动比（注水检测的输入）──
            "r_like_view": safe_div(like, view),
            "r_coin_like": safe_div(coin, like),
            "r_fav_like": safe_div(fav, like),
            "r_share_view": safe_div(share, view),
            "r_reply_view": safe_div(reply, view),
            "r_danmaku_view": safe_div(danmaku, view),
            # ── 评论文本特征 ──
            "dup_exact": exact, "dup_prefix8": prefix,
            "uniq_uids": len(set(uids)), "uid_concentration": 1 - safe_div(len(set(uids)), len(uids)),
            "mean_level": st.mean(levels) if levels else None,
            # ── 问号指数 ──
            "q_rate": safe_div(q_hit, n),
            "q3_rate": safe_div(q3_hit, n),
            "q_per_1k_chars": safe_div(q_total * 1000, chars),
            "q_total": q_total,
        })

    # ── 稳健偏离度 ──
    metric_keys = ["r_like_view", "r_coin_like", "r_fav_like", "r_share_view",
                   "r_reply_view", "r_danmaku_view", "dup_prefix8", "q_rate", "q3_rate"]
    for k in metric_keys:
        vals = [r[k] for r in rows if isinstance(r[k], (int, float))]
        for r in rows:
            r[f"z_{k}"] = round(mad_z(vals, r[k]), 2) if isinstance(r[k], (int, float)) else 0.0

    # 注水风险：只用"便宜可刷"的指标偏离 + 评论模板化
    # 逻辑：播放/点赞可以廉价刷，投币/收藏成本高；若点赞异常高而投币比异常低 → 值得核对
    for r in rows:
        r["flag_like_high"] = r["z_r_like_view"] >= 3.0
        r["flag_coin_low"] = r["z_r_coin_like"] >= 3.0
        r["flag_template"] = r["z_dup_prefix8"] >= 3.0
        r["n_flags"] = sum([r["flag_like_high"], r["flag_coin_low"], r["flag_template"]])
        r["q_index"] = round(r["q_rate"] * 100, 1)

    return {"rows": rows, "n_videos": len(rows), "n_comments": len(comments),
            "n_skipped_low_comment": skipped, "min_comments": min_comments}


def report_markdown(res: dict) -> str:
    rows = res["rows"]
    if not rows:
        return "# 没有数据\n"
    rows_sorted = sorted(rows, key=lambda r: -r["q_index"])
    L = []
    L.append("# B 站互动数据形态观察\n")
    L.append(f"**样本**：{res['n_videos']} 个热门视频 · {res['n_comments']} 条评论\n")

    L.append("## 一、问号指数排行（评论中含 `?`/`？` 的比例）\n")
    L.append("| # | 问号指数 | 含？？？的比例 | 标题 |")
    L.append("|---|---|---|---|")
    for i, r in enumerate(rows_sorted[:15], 1):
        L.append(f"| {i} | **{r['q_index']}%** | {r['q3_rate'] * 100:.1f}% | {str(r['title'])[:38]} |")

    L.append("\n## 二、互动比分布\n")
    L.append("| 视频 | 播放 | 点赞率 | 投币/点赞 | 收藏/点赞 | 评论/播放 |")
    L.append("|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -x["view"])[:15]:
        L.append(f"| {str(r['title'])[:26]} | {r['view']:,} | {r['r_like_view'] * 100:.2f}% | "
                 f"{r['r_coin_like'] * 100:.1f}% | {r['r_fav_like'] * 100:.1f}% | {r['r_reply_view'] * 1000:.2f}‰ |")

    flagged = sorted([r for r in rows if r["n_flags"] > 0], key=lambda x: -x["n_flags"])
    L.append(f"\n## 三、指标偏离群体分布的视频（{len(flagged)} 个）\n")
    L.append("> ⚠️ 偏离 ≠ 注水。这里只报告「指标与同批样本的中位数偏离超过 3×MAD」，"
             "不构成任何指控。真实爆款、分区差异、活动推广都会造成同样的偏离。\n")
    if flagged:
        L.append("| 视频 | 标记数 | 触发项 |")
        L.append("|---|---|---|")
        for r in flagged:
            tags = []
            if r["flag_like_high"]:
                tags.append("点赞率异常高")
            if r["flag_coin_low"]:
                tags.append("投币比异常低")
            if r["flag_template"]:
                tags.append("评论模板化")
            L.append(f"| {str(r['title'])[:30]} | {r['n_flags']} | {' / '.join(tags)} |")
    else:
        L.append("（本批样本中没有视频触发阈值）")

    L.append("\n## 四、样本分布\n")
    by_t = Counter(r["tname"] for r in rows if r["tname"])
    L.append("| 分区 | 视频数 |")
    L.append("|---|---|")
    for t, c in by_t.most_common(10):
        L.append(f"| {t} | {c} |")
    return "\n".join(L) + "\n"


def main() -> None:
    videos = load_jsonl(os.path.join(DATA, "videos.jsonl"))
    comments = load_jsonl(os.path.join(DATA, "comments.jsonl"))
    if not videos:
        print("没有采集到数据，请先运行 bili/collect.py")
        return
    res = analyse(videos, comments)
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(DATA, "analysis.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    md = report_markdown(res)
    open(os.path.join(OUT, "数据观察.md"), "w", encoding="utf-8").write(md)

    rows = res["rows"]
    print(f"视频 {res['n_videos']} 个 · 评论 {res['n_comments']} 条\n")
    print("── 问号指数 Top 8 ──")
    for r in sorted(rows, key=lambda x: -x["q_index"])[:8]:
        print(f"  {r['q_index']:5.1f}%  {str(r['title'])[:42]}")
    print("\n── 互动比中位数 ──")
    for k, name in [("r_like_view", "点赞/播放"), ("r_coin_like", "投币/点赞"),
                    ("r_fav_like", "收藏/点赞"), ("r_reply_view", "评论/播放")]:
        v = [r[k] for r in rows]
        print(f"  {name:10} 中位 {st.median(v) * 100:.2f}%   区间 {min(v) * 100:.2f}% – {max(v) * 100:.2f}%")
    print("\n── 偏离群体分布的视频 ──")
    fl = [r for r in rows if r["n_flags"] > 0]
    for r in sorted(fl, key=lambda x: -x["n_flags"])[:8]:
        tags = [t for t, f in (("点赞率异常高", r["flag_like_high"]), ("投币比异常低", r["flag_coin_low"]),
                               ("评论模板化", r["flag_template"])) if f]
        print(f"  [{r['n_flags']}] {' / '.join(tags):24} {str(r['title'])[:34]}")
    if not fl:
        print("  （无）")
    print(f"\n报告 → {os.path.join(OUT, '数据观察.md')}")


if __name__ == "__main__":
    main()
