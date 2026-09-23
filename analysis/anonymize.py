#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匿名化：把采集到的原始数据分成「本机留档」和「可发布」两份。

为什么必须有这一步
------------------
原始采集数据里有：
  · 真实 UP 的 mid / 昵称（45 个，含公众人物）
  · 无盐 uid_hash = sha1(mid)[:12] —— 一次公开 API 就能反查回 mid
  · 1086 行评论原文（含对具体用户的指名指控）
发布这些内容与 README 的「不点名」声明直接冲突，所以：

    data/raw-local/   原文 + 真标题 + 真 UP 对照表   ← 只在用户本机，进 .gitignore
    data/videos.jsonl 匿名化后的视频 stat（owner 只剩 u01…）
    data/comments.jsonl 只留派生指标（每视频唯一文本数/重复率/长度/等级），无文本无 uid

用法
----
    python3 analysis/anonymize.py

幂等：可以反复跑。第一次跑会把 data/*.jsonl 的原件复制到 data/raw-local/，
之后 raw-local 里的原件不再被覆盖（避免把已匿名的数据当成原文）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import DATA, dedup_comments, load_jsonl, percentile, safe_div  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(DATA, "raw-local")


def archive_raw(name: str) -> str:
    """把 data/<name> 的原件留档到 data/raw-local/<name>，返回留档路径。

    已存在则不覆盖 —— 防止把匿名化后的文件误当原文。
    """
    os.makedirs(RAW, exist_ok=True)
    dst = os.path.join(RAW, name)
    src = os.path.join(DATA, name)
    if not os.path.exists(src):
        raise SystemExit(f"缺少 {src}，先运行 python3 bili/collect.py")
    if os.path.exists(dst):
        print(f"  留档已存在，跳过复制：{os.path.relpath(dst, ROOT)}")
    else:
        shutil.copy2(src, dst)
        print(f"  原文留档：{os.path.relpath(dst, ROOT)}")
    return dst


def build_video_map(videos: list[dict]) -> tuple[dict, dict]:
    vmap, umap = {}, {}
    for i, v in enumerate(videos, 1):
        vmap[v.get("aid")] = f"v{i:02d}"
        mid = v.get("owner_mid")
        if mid is not None and mid not in umap:
            umap[mid] = f"u{len(umap) + 1:02d}"
    return vmap, umap


def write_id_map(videos: list[dict], vmap: dict, umap: dict) -> None:
    """真标题/真 UP 的对照表 —— 只在 raw-local。"""
    path = os.path.join(RAW, "video_id_map.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("vid,owner_ref,owner_mid,owner_name,aid,bvid,title\n")
        for v in videos:
            f.write(",".join([
                vmap.get(v.get("aid"), ""), umap.get(v.get("owner_mid"), ""),
                str(v.get("owner_mid") or ""), _csv(v.get("owner_name")),
                str(v.get("aid") or ""), str(v.get("bvid") or ""), _csv(v.get("title")),
            ]) + "\n")
    print(f"  id 对照表：{os.path.relpath(path, ROOT)}（不进 git）")


def _csv(s) -> str:
    s = str(s if s is not None else "")
    return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s


def publish_videos(videos: list[dict], umap: dict) -> None:
    """发布版 videos.jsonl：去掉 title / owner_mid / owner_name，owner 只剩 u01…"""
    path = os.path.join(DATA, "videos.jsonl")
    tmp = path + ".tmp"
    keep = ["bvid", "aid", "duration", "pubdate", "desc_len", "owner_ref",
            "view", "like", "coin", "favorite", "share", "reply", "danmaku",
            "now_rank", "his_rank"]
    with open(tmp, "w", encoding="utf-8") as f:
        for v in videos:
            rec = {k: v.get(k) for k in keep if k != "owner_ref"}
            rec["owner_ref"] = umap.get(v.get("owner_mid"), "")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(f"  发布版视频表：{os.path.relpath(path, ROOT)}（{len(videos)} 行，无标题无 UP 名）")


def publish_comment_metrics(comments: list[dict]) -> None:
    """发布版 comments.jsonl：**每行一个视频的派生指标**，没有任何评论文本/uid。"""
    uniq, per_video = dedup_comments(comments)
    by: dict = {}
    for c in uniq:
        by.setdefault(c.get("aid"), []).append(c)

    path = os.path.join(DATA, "comments.jsonl")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for aid, cs in by.items():
            texts = [(c.get("content") or "").strip() for c in cs]
            texts = [t for t in texts if t]
            n = len(texts)
            lens = sorted(len(t) for t in texts)
            levels = [c.get("level") for c in cs if isinstance(c.get("level"), int)]
            likes = sorted(c.get("like") or 0 for c in cs)
            f.write(json.dumps({
                "aid": aid,
                "n_rows_raw": per_video.get(aid, {}).get("raw", 0),
                "n_texts_unique": n,
                "n_prefix8_unique": len({t[:8] for t in texts}),
                "dup_exact": round(1 - safe_div(len(set(texts)), n), 4),
                "dup_prefix8": round(1 - safe_div(len({t[:8] for t in texts}), n), 4),
                "len_chars_total": sum(lens),
                "len_chars_median": percentile(lens, 0.5),
                "len_chars_p90": percentile(lens, 0.9),
                "n_over_50_chars": sum(1 for x in lens if x > 50),
                "like_median": percentile(likes, 0.5),
                "like_max": likes[-1] if likes else 0,
                "level_mean": round(sum(levels) / len(levels), 2) if levels else None,
            }, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(f"  发布版评论指标：{os.path.relpath(path, ROOT)}"
          f"（{len(by)} 行派生指标，0 条原文，0 个 uid）")


def main() -> None:
    print("① 留档原件 → data/raw-local/")
    archive_raw("videos.jsonl")
    archive_raw("comments.jsonl")

    videos = load_jsonl(os.path.join(RAW, "videos.jsonl"))
    comments = load_jsonl(os.path.join(RAW, "comments.jsonl"))
    if not videos or not comments:
        raise SystemExit("data/raw-local/ 里的原件为空，无法继续")
    print(f"  原件：{len(videos)} 个视频 · {len(comments)} 行评论")

    print("② 生成 id 对照表")
    vmap, umap = build_video_map(videos)
    write_id_map(videos, vmap, umap)

    print("③ 写出发布版数据（匿名 + 只留派生指标）")
    publish_videos(videos, umap)
    publish_comment_metrics(comments)

    # 自检：发布版里不能出现真值
    ok = True
    text = open(os.path.join(DATA, "videos.jsonl"), encoding="utf-8").read()
    for v in videos:
        for field in ("owner_name", "owner_mid", "title", "tname"):
            val = v.get(field)
            if val in (None, ""):
                continue
            if str(val) in text:
                print(f"  ✗ 泄漏：videos.jsonl 里仍能搜到 {field}={val!r}")
                ok = False
    cm = open(os.path.join(DATA, "comments.jsonl"), encoding="utf-8").read()
    for c in comments[:200]:
        if (c.get("content") or "").strip() and c["content"][:12] in cm:
            print(f"  ✗ 泄漏：comments.jsonl 里仍能搜到评论文本 {c['content'][:20]!r}")
            ok = False
            break
    if c0 := comments[0].get("uid_hash"):
        if c0 in cm:
            print(f"  ✗ 泄漏：comments.jsonl 里仍有 uid_hash {c0}")
            ok = False
    print("  自检：" + ("通过（发布版无标题/UP/评论文本/uid）" if ok else "**未通过，见上**"))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
