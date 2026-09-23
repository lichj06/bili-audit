#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 B 站公开数据：热门榜视频的 stat + 评论文本。

只用公开接口，不需要登录，不触碰任何需要授权的数据。
带限速（默认每次请求间隔 0.8s），避免给 B 站造成负担。

产出：
  data/videos.jsonl    每个视频一行：bvid/aid/title/分区/时长/发布日期/stat 全部字段
  data/comments.jsonl  每条评论一行：aid/评论内容/点赞数/回复数/发布时间/用户 id 哈希
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bili.api import video_info, popular, comments  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")


def sleep_polite(lo: float = 0.6, hi: float = 1.3) -> None:
    time.sleep(random.uniform(lo, hi))


def collect(pages: int = 3, comment_pages: int = 2, per_page: int = 20, limit: int = 0) -> None:
    os.makedirs(DATA, exist_ok=True)
    # ① 收集视频列表
    seeds: list[dict] = []
    seen = set()
    for pn in range(1, pages + 1):
        try:
            lst = popular(ps=per_page, pn=pn)
        except Exception as exc:  # noqa: BLE001
            print(f"  热门榜第 {pn} 页失败: {exc}")
            continue
        for item in lst:
            bv = item.get("bvid")
            if bv and bv not in seen:
                seen.add(bv)
                seeds.append({"bvid": bv, "aid": item.get("aid"), "title": item.get("title", "")})
        print(f"  热门榜第 {pn} 页 → 累计 {len(seeds)} 个视频")
        sleep_polite()

    if limit:
        seeds = seeds[:limit]

    # ② 逐视频取详情 + 评论
    vpath = os.path.join(DATA, "videos.jsonl")
    cpath = os.path.join(DATA, "comments.jsonl")
    with open(vpath, "w", encoding="utf-8") as fv, open(cpath, "w", encoding="utf-8") as fc:
        for i, s in enumerate(seeds, 1):
            try:
                info = video_info(s["bvid"])
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i}/{len(seeds)}] {s['bvid']} 详情失败: {exc}")
                continue
            stat = info.get("stat") or {}
            owner = info.get("owner") or {}
            rec = {
                "bvid": info.get("bvid"), "aid": info.get("aid"),
                "title": info.get("title"), "tname": info.get("tname"),
                "duration": info.get("duration"), "pubdate": info.get("pubdate"),
                "desc_len": len(info.get("desc") or ""),
                "owner_mid": owner.get("mid"), "owner_name": owner.get("name"),
                "view": stat.get("view"), "like": stat.get("like"), "coin": stat.get("coin"),
                "favorite": stat.get("favorite"), "share": stat.get("share"),
                "reply": stat.get("reply"), "danmaku": stat.get("danmaku"),
                "now_rank": stat.get("now_rank"), "his_rank": stat.get("his_rank"),
            }
            fv.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fv.flush()
            sleep_polite()

            got = 0
            for pn in range(1, comment_pages + 1):
                try:
                    c = comments(info["aid"], pn=pn, ps=20, sort=2)
                except Exception:  # noqa: BLE001
                    break
                for r in c.get("replies") or []:
                    content = ((r.get("content") or {}).get("message") or "").strip()
                    if not content:
                        continue
                    uid = str((r.get("member") or {}).get("mid") or "")
                    fc.write(json.dumps({
                        "aid": info["aid"], "bvid": info["bvid"],
                        "content": content,
                        "like": r.get("like", 0), "rcount": r.get("rcount", 0),
                        "ctime": r.get("ctime"),
                        "uid_hash": hashlib.sha1(uid.encode()).hexdigest()[:12] if uid else "",
                        "uname_len": len(((r.get("member") or {}).get("uname") or "")),
                        "level": ((r.get("member") or {}).get("level_info") or {}).get("current_level"),
                    }, ensure_ascii=False) + "\n")
                    got += 1
                fc.flush()
                sleep_polite()
            print(f"  [{i}/{len(seeds)}] {s['bvid']}  view={rec['view']:>9}  评论取到 {got} 条  {str(rec['title'])[:26]}")

    print(f"\n视频 → {vpath}\n评论 → {cpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3, help="热门榜页数（每页 20）")
    ap.add_argument("--comment-pages", type=int, default=2, help="每个视频取几页评论（每页 20）")
    ap.add_argument("--limit", type=int, default=0, help="最多采集多少个视频（0=不限）")
    args = ap.parse_args()
    collect(args.pages, args.comment_pages, limit=args.limit)


if __name__ == "__main__":
    main()
