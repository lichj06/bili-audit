#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一分析：把「注水检测」和「问号指数」放进同一个框架 —— 互动数据的分布形状。

框架
----
    注水（假互动）  分布过于【规则/突变】：点赞率高而投币比低、评论高度模板化
    问号（真共鸣）  分布有【结构】：短促、密集、情绪集中

两者都用同一批数据算，都不做"判定"，只做【相对群体分布的偏离度】。

隐私
----
输出里**不出现**标题、UP 名、uid —— 只用稳定 id（v01…v45）。
id↔真标题的对照表在 data/raw-local/，不进 git。
统计逻辑全在 analysis/pipeline.py，与 make_figures.py 共用（分位数必须同源）。

三个纪律
--------
① 只描述指标偏离群体分布的程度，**不下"这个视频注水了"的结论**
② 用稳健统计（中位数 + MAD），且 z 分数**保留符号**（旧版取绝对值 → 方向判据失效）
③ 所有指标都给出计算方式，可复现、可反驳
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import (  # noqa: E402
    DATA, REPORT, analyse, load_comments_for_analysis, load_jsonl, median, percentile,
)

RATIOS = [
    ("r_like_view", "点赞 / 播放"),
    ("r_coin_like", "投币 / 点赞"),
    ("r_fav_like", "收藏 / 点赞"),
    ("r_reply_view", "评论 / 播放"),
]
FLAG_LABEL = {"flag_like_high": "点赞率异常高", "flag_coin_low": "投币比异常低",
              "flag_dup_high": "前8字重复率异常高"}
ID_PREFIX = {"vid": "v", "user": "u"}


def stable_ids(videos: list[dict]) -> dict:
    """按 data/videos.jsonl 的行序给每个 aid 一个稳定匿名 id：v01…v45。

    同时给出 owner 的匿名 id（u01…）。真值只落在 data/raw-local/。
    """
    vmap, umap = {}, {}
    for i, v in enumerate(videos, 1):
        vmap[v.get("aid")] = f"v{i:02d}"
        mid = v.get("owner_mid")
        if mid is not None and mid not in umap:
            umap[mid] = f"u{len(umap) + 1:02d}"
    return {"video": vmap, "owner": umap}


def report_markdown(res: dict, ids: dict) -> str:
    rows = res["rows"]
    L = []
    if not rows:
        return "# 没有数据\n"
    vmap = ids["video"]
    vid = lambda r: vmap.get(r["aid"], "v??")  # noqa: E731
    counts = {r["aid"]: r["n_comments_sampled"] for r in rows}

    L.append("# B 站互动数据形态观察\n")
    L.append(f"**样本**：{res['n_videos_sampled']} 个热门视频中，"
             f"{res['n_videos']} 个取到评论（去重后 ≥{res['min_comments']} 条唯一评论）"
             f"· 唯一评论 {res['n_comments_unique']} 条"
             f"（原始写入 {res['n_comments_raw']} 行）\n")
    L.append(f"> 视频只用稳定 id（{vid(rows[0])} …）标注，真标题不入库。\n")

    L.append("## 一、问号指数排行（评论中含 `?`/`？` 的比例）\n")
    if not any(isinstance(r.get("q_index"), (int, float)) for r in rows):
        L.append("（本数据源没有评论文本 —— 问号指数不可算。"
                 "原始评论在 `data/raw-local/` 时才可算，见 README。）\n")
    else:
        L.append("| # | 视频 | 问号指数 | 含？？？的比例 | 唯一评论数 |")
        L.append("|---|---|---|---|---|")
        for i, r in enumerate(sorted(rows, key=lambda x: -(x.get("q_index") or 0))[:15], 1):
            L.append(f"| {i} | `{vid(r)}` | **{r['q_index']}%** | "
                     f"{(r.get('q3_rate') or 0) * 100:.1f}% | {counts[r['aid']]} |")

    L.append("\n## 二、互动比分布\n")
    L.append("| 视频 | 播放 | 点赞率 | 投币/点赞 | 收藏/点赞 | 评论/播放 |")
    L.append("|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -x["view"])[:15]:
        L.append(f"| `{vid(r)}` | {r['view']:,} | {r['r_like_view'] * 100:.2f}% | "
                 f"{r['r_coin_like'] * 100:.1f}% | {r['r_fav_like'] * 100:.1f}% | "
                 f"{r['r_reply_view'] * 1000:.2f}‰ |")

    L.append("\n## 三、互动比基线（中位数与极差）\n")
    L.append("| 指标 | 中位 | 区间 | 极差倍数 |")
    L.append("|---|---|---|---|")
    for k, name in RATIOS:
        v = [r[k] for r in rows]
        lo, hi = percentile(v, 0.0), percentile(v, 1.0)
        L.append(f"| {name} | **{median(v) * 100:.2f}%** | "
                 f"{lo * 100:.2f}% – {hi * 100:.2f}% | "
                 f"**{hi / lo:.1f}×** |" if lo else f"| {name} | — | — | — |")

    flagged = sorted([r for r in rows if r["n_flags"] > 0], key=lambda x: -x["n_flags"])
    L.append(f"\n## 四、指标偏离群体分布的视频（{len(flagged)} 个）\n")
    L.append("> ⚠️ 偏离 ≠ 注水。这里只报告「指标与同批样本的中位数偏离超过 3×MAD」，"
             "不构成任何指控。真实爆款、分区差异、活动推广都会造成同样的偏离。\n")
    L.append("各标记的可达性（本批数据里该标记**能否**为真）：\n")
    L.append("| 标记 | 方向 | 极端 z | 本批可达 |")
    L.append("|---|---|---|---|")
    for name, d in res["flag_diagnostics"].items():
        reach = "是" if d["reachable"] else ("否（MAD=0，无离散度）" if d["mad_zero"] else "否")
        L.append(f"| {FLAG_LABEL[name]} | {'高尾' if d['direction'] == 'high' else '低尾'} | "
                 f"{d['extreme_z']:+.2f} | {reach} |")
    L.append("")
    if flagged:
        L.append("| 视频 | 标记数 | 触发项 |")
        L.append("|---|---|---|")
        for r in flagged:
            tags = [FLAG_LABEL[k] for k in FLAG_LABEL if r[k]]
            L.append(f"| `{vid(r)}` | {r['n_flags']} | {' / '.join(tags)} |")
    else:
        L.append("（本批样本中没有视频触发阈值）")

    L.append("\n## 五、样本构成\n")
    L.append(f"- 热门榜取到 {res['n_videos_sampled']} 个视频")
    L.append(f"- 其中 {res['n_videos_zero_comment']} 个**一条评论都没取到**（接口返回 0 条，"
             f"原因未记录 —— 旧版采集器丢掉了返回码，见 README「已知缺陷」）")
    L.append(f"- 剩下 {res['n_videos']} 个进入统计（n={res['n_videos']}）")
    L.append(f"- 评论去重规则：{res['dedup_rule']}")
    L.append(f"- 标记规则：{res['flag_rule']}")
    return "\n".join(L) + "\n"


def _public(res: dict) -> dict:
    """写盘版：去掉 aid / bvid 等可直接指向具体视频的标识，只留稳定 id。

    aid/bvid 会出现在**本机**的 raw-local 里；发布版没有它们的必要
    （自检见 analysis/verify.py）。
    """
    out = dict(res)
    out["rows"] = [{k: v for k, v in r.items() if k not in ("aid", "bvid")}
                   for r in res["rows"]]
    return out


def main() -> None:
    videos = load_jsonl(os.path.join(DATA, "videos.jsonl"))
    comments, csource = load_comments_for_analysis()
    if not videos:
        print("没有采集到数据，请先运行 bili/collect.py")
        return
    ids = stable_ids(videos)
    res = analyse(videos, comments, source=csource)

    # 匿名化：行里不带 aid/标题/uid，只带稳定 id
    for r in res["rows"]:
        r["vid"] = ids["video"].get(r["aid"], "v??")
    res["id_map_note"] = ("id↔真标题对照表：data/raw-local/video_id_map.csv（不进 git）")

    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(DATA, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(_public(res), f, ensure_ascii=False, indent=1)
    with open(os.path.join(REPORT, "数据观察.md"), "w", encoding="utf-8") as f:
        f.write(report_markdown(res, ids))

    rows = res["rows"]
    print(f"评论来源：{csource}")
    print(f"视频 {res['n_videos']} 个（采样 {res['n_videos_sampled']}，"
          f"其中 {res['n_videos_zero_comment']} 个无评论）")
    print(f"评论 原始 {res['n_comments_raw']} 行 → 去重后 {res['n_comments_unique']} 条"
          f"（全局唯一文本 {res['n_comments_unique_text']} 条）\n")
    qrows = [r for r in rows if isinstance(r.get("q_index"), (int, float))]
    if qrows:
        print("── 问号指数 Top 8 ──")
        for r in sorted(qrows, key=lambda x: -x["q_index"])[:8]:
            print(f"  {r['q_index']:5.1f}%  {r['vid']}  (n={r['n_comments_sampled']})")
    else:
        print("── 问号指数：本数据源没有评论文本，该指标不可算（未编数）──")
    print("\n── 互动比中位数 ──")
    for k, name in RATIOS:
        v = [r[k] for r in rows]
        lo, hi = percentile(v, 0.0), percentile(v, 1.0)
        print(f"  {name:10} 中位 {median(v) * 100:6.2f}%   "
              f"区间 {lo * 100:6.2f}% – {hi * 100:7.2f}%   极差 {hi / lo:.1f}×")
    print("\n── 偏离群体分布的视频 ──")
    fl = [r for r in rows if r["n_flags"] > 0]
    for r in sorted(fl, key=lambda x: -x["n_flags"])[:8]:
        tags = [FLAG_LABEL[k] for k in FLAG_LABEL if r[k]]
        print(f"  [{r['n_flags']}] {' / '.join(tags):24} {r['vid']}  z_coin={r['z_r_coin_like']:+.2f}")
    if not fl:
        print("  （无）")
    print("\n── 标记可达性 ──")
    for name, d in res["flag_diagnostics"].items():
        print(f"  {FLAG_LABEL[name]:16} 极端 z={d['extreme_z']:+.2f}  "
              f"可达={'是' if d['reachable'] else '否'}"
              f"{'（MAD=0）' if d['mad_zero'] else ''}")
    print(f"\n报告 → {os.path.join(REPORT, '数据观察.md')}")


if __name__ == "__main__":
    main()
