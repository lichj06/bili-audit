#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 B 站公开数据：热门榜视频的 stat + 评论。

只用公开接口，不需要登录，不触碰任何需要授权的数据。
带限速（默认每次请求间隔 0.6–1.3s），避免给 B 站造成负担。

产出（**原始数据只写进 data/raw-local/**，不进 git）
------------------------------------------------
  data/raw-local/videos.jsonl    每视频一行：bvid/aid/真标题/真 UP/stat 全字段
  data/raw-local/comments.jsonl  每条评论一行：aid/文本/点赞数/时间/uid_hash
  data/raw-local/fetch_log.jsonl 每次请求的结果码（**旧版把 code 丢了**，见下）

  然后运行 `python3 analysis/anonymize.py` 生成可发布的匿名数据。

已知接口缺陷（实测，2026-09-23）
------------------------------
① 评论分页**不生效**：`x/v2/reply/main` 的 `pn` 参数无效 ——
   pn=1/2/3 返回完全相同的 rpid（实测 314719551921 / 318314835872）。
   所以本采集器**只取第 1 页**，并在每页结果与上一页完全相同时提前停止，
   不再把同一页重复写多遍（旧版写 3 遍 → 1086 行里 90% 是同一页的复制）。
② 返回码会被丢掉：旧版 `except: break` 把接口的 code/message 扔了，
   于是报告里「约 60–80 次请求后限流」这句话**没有任何日志支撑**。
   现在每次请求都写进 fetch_log.jsonl。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bili.api import comments, popular, video_info  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw-local")


def sleep_polite(lo: float = 0.6, hi: float = 1.3) -> None:
    time.sleep(random.uniform(lo, hi))


def collect(pages: int = 3, comment_pages: int = 1, per_page: int = 20,
            limit: int = 0) -> None:
    os.makedirs(RAW, exist_ok=True)
    log_path = os.path.join(RAW, "fetch_log.jsonl")
    log = open(log_path, "a", encoding="utf-8")

    def note(kind: str, ok: bool, code=None, msg=None, n=0, detail="") -> None:
        log.write(json.dumps({
            "ts": int(time.time()), "kind": kind, "ok": ok,
            "code": code, "message": msg, "n": n, "detail": detail,
        }, ensure_ascii=False) + "\n")
        log.flush()

    # ① 收集视频列表
    seeds: list[dict] = []
    seen = set()
    for pn in range(1, pages + 1):
        try:
            lst = popular(ps=per_page, pn=pn)
            note("popular", True, 0, None, len(lst), f"pn={pn}")
        except Exception as exc:  # noqa: BLE001
            note("popular", False, None, str(exc), 0, f"pn={pn}")
            print(f"  热门榜第 {pn} 页失败: {exc}")
            continue
        for item in lst:
            bv = item.get("bvid")
            if bv and bv not in seen:
                seen.add(bv)
                seeds.append({"bvid": bv, "aid": item.get("aid"),
                              "title": item.get("title", "")})
        print(f"  热门榜第 {pn} 页 → 累计 {len(seeds)} 个视频")
        sleep_polite()

    if limit:
        seeds = seeds[:limit]

    # ② 逐视频取详情 + 评论
    vpath = os.path.join(RAW, "videos.jsonl")
    cpath = os.path.join(RAW, "comments.jsonl")
    with open(vpath, "w", encoding="utf-8") as fv, open(cpath, "w", encoding="utf-8") as fc:
        for i, s in enumerate(seeds, 1):
            try:
                info = video_info(s["bvid"])
                note("view", True, 0, None, 1, s["bvid"])
            except Exception as exc:  # noqa: BLE001
                note("view", False, None, str(exc), 0, s["bvid"])
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

            # 评论：只取第 1 页（pn 无效），并与已有内容按 rpid 去重
            got, seen_rpid = 0, set()
            stop_reason = ""
            for pn in range(1, max(1, comment_pages) + 1):
                try:
                    c = comments(info["aid"], pn=pn, ps=20, sort=2)
                except Exception as exc:  # noqa: BLE001
                    stop_reason = f"请求异常: {exc}"
                    note("reply", False, None, str(exc), 0, f"aid={info['aid']} pn={pn}")
                    break
                code = c.get("code")
                note("reply", code == 0, code, None, len(c.get("replies") or []),
                     f"aid={info['aid']} pn={pn}")
                if code != 0:
                    stop_reason = f"接口返回 code={code}（0 条）"
                    break
                page = c.get("replies") or []
                if pn > 1 and page and page[0].get("rpid") in seen_rpid:
                    stop_reason = "第 %d 页与第 1 页重复（pn 参数无效）" % pn
                    break
                for r in page:
                    rpid = r.get("rpid")
                    if rpid in seen_rpid:
                        continue
                    seen_rpid.add(rpid)
                    content = ((r.get("content") or {}).get("message") or "").strip()
                    if not content:
                        continue
                    uid = str((r.get("member") or {}).get("mid") or "")
                    fc.write(json.dumps({
                        "aid": info["aid"], "bvid": info["bvid"], "rpid": rpid,
                        "content": content,
                        "like": r.get("like", 0), "rcount": r.get("rcount", 0),
                        "ctime": r.get("ctime"),
                        # ⚠️ 无盐 sha1(mid)[:12] 可被一次公开 API 反查回 mid。
                        # 这个字段**只在 raw-local**，发布版不允许出现。
                        "uid_hash": hashlib.sha1(uid.encode()).hexdigest()[:12] if uid else "",
                        "uname_len": len(((r.get("member") or {}).get("uname") or "")),
                        "level": ((r.get("member") or {}).get("level_info") or {}).get("current_level"),
                    }, ensure_ascii=False) + "\n")
                    got += 1
                if not page:
                    stop_reason = "本页 0 条"
                    break
                if pn >= max(1, comment_pages):
                    break
                fc.flush()
                sleep_polite()
            if stop_reason:
                print(f"      ↳ 停止翻页：{stop_reason}")
            fc.flush()
            print(f"  [{i}/{len(seeds)}] {s['bvid']}  view={rec['view']:>9}  "
                  f"评论 {got} 条（唯一 rpid）  {str(rec['title'])[:26]}")

    log.close()
    print(f"\n原始数据 → {vpath}\n          {cpath}\n请求日志 → {log_path}")
    print("下一步：python3 analysis/anonymize.py   # 生成可发布的匿名数据")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3, help="热门榜页数（每页 20）")
    ap.add_argument("--comment-pages", type=int, default=1,
                    help="每个视频取几页评论（**实测 pn 无效，多取只会拿到同一页**，默认 1）")
    ap.add_argument("--limit", type=int, default=0, help="最多采集多少个视频（0=不限）")
    args = ap.parse_args()
    collect(args.pages, args.comment_pages, limit=args.limit)


if __name__ == "__main__":
    main()
