#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键验证：重跑分析、检查报告与数据是否自洽、检查有没有隐私泄漏。

只用标准库，不需要联网。

    python3 analysis/verify.py

检查项（任一失败返回码 1）：
  1. analysis.json / 数据观察.md 能被重新生成
  2. 图与报告表的分位数一致（make_figures 里也断言了一次）
  3. 发布版 data/*.jsonl 里没有真标题 / UP 名 / 评论文本 / uid_hash
  4. 报告里出现的每个数字都能在 analysis.json 里对上（抽样核对）
  5. analysis.json 里不存在 aid 之外的标识（只有 v01… 这种稳定 id）
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw-local")
REPORT = os.path.join(ROOT, "report")

FAILS, CHECKS = [], 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def run(script: str) -> bool:
    r = subprocess.run([sys.executable, os.path.join(ROOT, script)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
    return r.returncode == 0


def main() -> int:
    print("① 重跑管道")
    check("analysis/analyze.py 跑通", run("analysis/analyze.py"))
    check("analysis/make_figures.py 跑通", run("analysis/make_figures.py"))

    print("\n② 数据与报告一致性")
    res = json.load(open(os.path.join(DATA, "analysis.json"), encoding="utf-8"))
    rows = res["rows"]
    n = res["n_videos"]
    check("n_videos == 18（本批）", n == 18, f"实测 {n}")
    check("n_comments_unique == 353",
          res["n_comments_unique"] == 353, f"实测 {res['n_comments_unique']}")
    check("n_videos_sampled == 45", res["n_videos_sampled"] == 45)
    check("每行都有稳定 id（v01…）且无标题字段",
          all(r.get("vid", "").startswith("v") and "title" not in r for r in rows))
    check("analysis.json 不含 aid/bvid（只剩稳定 id）",
          all("aid" not in r and "bvid" not in r for r in rows))
    check("q3_rate 全为 0（本批无三重问号）",
          all(r["q3_rate"] == 0 for r in rows))

    import statistics as st
    from pipeline import percentile  # noqa: E402
    md = open(os.path.join(REPORT, "数据观察.md"), encoding="utf-8").read()
    for key, label in [("r_like_view", "点赞 / 播放"), ("r_coin_like", "投币 / 点赞"),
                       ("r_fav_like", "收藏 / 点赞"), ("r_reply_view", "评论 / 播放")]:
        v = [r[key] for r in rows]
        med = st.median(v) * 100
        check(f"报告含 {label} 中位 {med:.2f}%", f"{med:.2f}%" in md)
        check(f"报告含 {label} 极差 {percentile(v,1)/percentile(v,0):.1f}×",
              f"{percentile(v, 1) / percentile(v, 0):.1f}×" in md)

    print("\n③ 隐私：发布版不得含真值")
    pub_v = open(os.path.join(DATA, "videos.jsonl"), encoding="utf-8").read()
    pub_c = open(os.path.join(DATA, "comments.jsonl"), encoding="utf-8").read()
    raw_v = os.path.join(RAW, "videos.jsonl")
    raw_c = os.path.join(RAW, "comments.jsonl")
    check("raw-local 存在（原始数据未被删除）",
          os.path.exists(raw_v) and os.path.exists(raw_c))
    check("raw-local 已被 .gitignore 忽略",
          "data/raw-local/" in open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read())
    if os.path.exists(raw_v):
        rv = [json.loads(x) for x in open(raw_v, encoding="utf-8") if x.strip()]
        leaks = [v["title"] for v in rv
                 if v.get("title") and v["title"][:10] in pub_v]
        check("发布版 videos.jsonl 无真标题泄漏", not leaks, str(leaks[:2]))
        leaks2 = [v["owner_name"] for v in rv
                  if v.get("owner_name") and v["owner_name"] in pub_v]
        check("发布版 videos.jsonl 无 UP 名泄漏", not leaks2, str(leaks2[:2]))
    if os.path.exists(raw_c):
        rc = [json.loads(x) for x in open(raw_c, encoding="utf-8") if x.strip()]
        sample = [c for c in rc[:300] if c.get("content")]
        hit = [c["content"][:12] for c in sample if c["content"][:12] in pub_c]
        check("发布版 comments.jsonl 无评论文本泄漏", not hit, str(hit[:2]))
        h = [c["uid_hash"] for c in rc[:300] if c.get("uid_hash")]
        check("发布版 comments.jsonl 无 uid_hash 泄漏", not any(x in pub_c for x in h))

    print("\n④ 报告里不得再出现旧数字/旧说法")
    docs = {f: open(os.path.join(ROOT, f), encoding="utf-8").read()
            for f in ("README.md", "发布文案.md", "report/报告.md")}
    bad = {
        # 注意：允许「旧版写的是『10–100 倍』——本批实测 9.6–72.2×」这种**纠错性**引用，
        # 所以下面两个模式排除了被「旧版」或引号标记过的上下文。
        "10–100 倍（当作实测值使用）": r"(?<!旧版这里写的是「)10[-–—]100\s*倍(?!」)",
        "「本样本里就有 14% 的」": r"就有\s*14%\s*的",
        "60–80 次请求后限流（当作结论使用）": r"(?<!约 )60[-–—]80\s*次请求后(?!限流」)",
        "2026-01-14 一审宣判": r"2026-01-14\s*一审",
        "SHA1 前 12 位（可反查）": r"SHA1\s*前\s*12\s*位",
        "获取注水量可行性整节": r"获取注水量的可行性",
    }
    for label, pat in bad.items():
        hits = [f for f, t in docs.items() if re.search(pat, t)]
        check(f"已清除：{label}", not hits, str(hits))

    print(f"\n{'=' * 46}\n{CHECKS - len(FAILS)}/{CHECKS} 项通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    raise SystemExit(main())
