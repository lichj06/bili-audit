#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 SVG 图表（零依赖）。

关键修复
--------
· 分位数改用 analysis/pipeline.percentile()（线性插值，等价 statistics.quantiles）。
  旧版用 `v[int(len(v)*p)]`（不插值）→ 图2 的中位数 27.8/19.6 与报告表的
  26.53/19.08 打架。现在两处调同一个函数，并在结尾自动交叉核对。
· 标题里的数字来自 analysis.json 实测值，不写死。旧版写死「10–100 倍」，
  实测极差只有 9.6×–72.2×。
· 不生成 fig3（q3_rate 在本批数据里恒为 0，图无信息量）。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from pipeline import median, percentile  # noqa: E402

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "report", "figures")
C_TEXT, C_AXIS = "#24292f", "#d0d7de"
C1, C2, C3 = "#0969da", "#1a7f37", "#cf222e"
W = 780


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar(title, rows, fname, xmax=100.0, xlabel="%", labw=210):
    n = len(rows)
    rh = min(42, max(28, 560 // max(1, n)))
    H = 44 + 40 + rh * n
    bw = W - labw - 90
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="16" y="28" font-size="16" font-weight="600" fill="{C_TEXT}">{esc(title)}</text>']
    for g in range(5):
        x = labw + bw * g / 4
        p.append(f'<line x1="{x:.0f}" y1="44" x2="{x:.0f}" y2="{44 + rh * n}" stroke="{C_AXIS}"/>')
        p.append(f'<text x="{x:.0f}" y="{44 + rh * n + 20}" font-size="11" '
                 f'fill="#57606a" text-anchor="middle">{xmax * g / 4:.0f}</text>')
    for i, (lab, v, col) in enumerate(rows):
        y = 44 + i * rh
        w = max(1, bw * min(v, xmax) / xmax)
        p.append(f'<text x="{labw - 10}" y="{y + rh / 2 + 5:.0f}" font-size="12.5" '
                 f'fill="{C_TEXT}" text-anchor="end">{esc(lab)[:34]}</text>')
        p.append(f'<rect x="{labw}" y="{y + rh * 0.2:.0f}" width="{w:.0f}" '
                 f'height="{rh * 0.6:.0f}" rx="3" fill="{col}"/>')
        p.append(f'<text x="{labw + w + 8:.0f}" y="{y + rh / 2 + 5:.0f}" font-size="12.5" '
                 f'font-weight="600" fill="{C_TEXT}">{v:.1f}{xlabel}</text>')
    p.append(f'<text x="{W - 20}" y="{H - 8}" font-size="11" fill="#57606a" text-anchor="end">'
             f'数据与代码开源 · 样本来自 B 站热门榜公开数据 · 视频以稳定 id 标注</text></svg>')
    open(os.path.join(OUT, fname), "w", encoding="utf-8").write("\n".join(p))


def box(title, series, fname, ymax):
    """series: [(name, [min,q1,med,q3,max], color)]"""
    H = 340
    pl, pr, pt, pb = 90, 30, 46, 60
    ph = H - pt - pb
    pw = W - pl - pr
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="16" y="28" font-size="16" font-weight="600" fill="{C_TEXT}">{esc(title)}</text>']
    for g in range(5):
        y = pt + ph * (1 - g / 4)
        p.append(f'<line x1="{pl}" y1="{y:.0f}" x2="{W - pr}" y2="{y:.0f}" stroke="{C_AXIS}"/>')
        p.append(f'<text x="{pl - 8}" y="{y + 4:.0f}" font-size="11" fill="#57606a" '
                 f'text-anchor="end">{ymax * g / 4:.0f}</text>')
    for i, (name, vals, col) in enumerate(series):
        cx = pl + pw * (i + 0.5) / len(series)
        Y = lambda v: pt + ph * (1 - min(v, ymax) / ymax)  # noqa: E731
        p.append(f'<line x1="{cx:.0f}" y1="{Y(vals[0]):.0f}" x2="{cx:.0f}" '
                 f'y2="{Y(vals[4]):.0f}" stroke="{col}" stroke-width="1.5"/>')
        p.append(f'<rect x="{cx - 34:.0f}" y="{Y(vals[3]):.0f}" width="68" '
                 f'height="{max(2, Y(vals[1]) - Y(vals[3])):.0f}" fill="{col}" '
                 f'opacity="0.28" stroke="{col}"/>')
        p.append(f'<line x1="{cx - 34:.0f}" y1="{Y(vals[2]):.0f}" x2="{cx + 34:.0f}" '
                 f'y2="{Y(vals[2]):.0f}" stroke="{col}" stroke-width="3"/>')
        p.append(f'<text x="{cx:.0f}" y="{H - pb + 22}" font-size="12.5" fill="{C_TEXT}" '
                 f'text-anchor="middle">{esc(name)}</text>')
        p.append(f'<text x="{cx:.0f}" y="{Y(vals[2]) - 9:.0f}" font-size="12" '
                 f'font-weight="600" fill="{col}" text-anchor="middle">{vals[2]:.2f}</text>')
    p.append(f'<text x="{W - 20}" y="{H - 8}" font-size="11" fill="#57606a" text-anchor="end">'
             f'中位线 / 箱=四分位距 / 须=极值 · 分位数与报告表同源</text></svg>')
    open(os.path.join(OUT, fname), "w", encoding="utf-8").write("\n".join(p))


def five(rows, key, scale=100.0):
    v = sorted(r[key] * scale for r in rows)
    return [percentile(v, 0.0), percentile(v, 0.25), percentile(v, 0.5),
            percentile(v, 0.75), percentile(v, 1.0)]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    res = json.load(open(os.path.join(DATA, "analysis.json"), encoding="utf-8"))
    rows = res["rows"]
    n = len(rows)

    # 图1 问号指数 Top12（标题用稳定 id，不再用真标题）
    top = sorted(rows, key=lambda r: -(r.get("q_index") or 0))[:12]
    if any(r.get("q_index") is not None for r in top):
        bar(f"图1 · 问号指数排行（评论中含 ?/？ 的比例）· n={n} 个视频",
            [(r["vid"], r["q_index"] or 0.0, C1) for r in top],
            "fig1_question.svg", 25, "%", labw=80)
    else:
        print("跳过图1：本数据源没有评论文本，问号指数不可算")

    # 图2 互动比四分位（标题数字由实测算出）
    ratios = [("点赞/播放", "r_like_view", C1), ("投币/点赞", "r_coin_like", C2),
              ("收藏/点赞", "r_fav_like", C3), ("评论/播放", "r_reply_view", "#bf8700")]
    five_ = [(name, five(rows, key), col) for name, key, col in ratios]
    spreads = [v[4] / v[0] for _, v, _ in five_ if v[0] > 0]
    lo, hi = min(spreads), max(spreads)
    box(f"图2 · 互动比分布（%）—— 本批样本内极差 {lo:.1f}× – {hi:.1f}×",
        five_, "fig2_ratios.svg", 120)

    # 交叉核对：图里的中位数必须与报告表一致（同一函数算的）
    for (name, key, _), (label, vals, _c) in zip(ratios, five_):
        table_med = median([r[key] for r in rows]) * 100
        assert abs(table_med - vals[2]) < 1e-9, \
            f"{name} 中位数不一致：报告 {table_med} vs 图 {vals[2]}"
    print("交叉核对：图2 中位数 == 报告表中位数（同一 percentile 函数）")

    # 图3 不再生成：q3_rate 在本批数据里恒为 0，图无信息量
    fig3 = os.path.join(OUT, "fig3_q3.svg")
    if os.path.exists(fig3):
        os.remove(fig3)
        print("已删除 fig3_q3.svg（q3_rate 全批为 0，原图只显示 0）")

    print("生成:")
    for f in sorted(os.listdir(OUT)):
        print("  report/figures/" + f)


if __name__ == "__main__":
    main()
