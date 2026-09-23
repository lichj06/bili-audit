#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 SVG 图表（零依赖）。"""
import json, os, statistics as st
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
DATA=os.path.join(ROOT,"data"); OUT=os.path.join(ROOT,"report","figures")
C_TEXT,C_AXIS="#24292f","#d0d7de"; C1,C2,C3="#0969da","#1a7f37","#cf222e"
W=780
def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def bar(title, rows, fname, xmax=100.0, xlabel="%", labw=210):
    n=len(rows); rh=min(42,max(28,(560)//max(1,n))); H=44+40+rh*n
    bw=W-labw-90; p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#fff"/>',
        f'<text x="16" y="28" font-size="16" font-weight="600" fill="{C_TEXT}">{esc(title)}</text>']
    for g in range(5):
        x=labw+bw*g/4; p.append(f'<line x1="{x:.0f}" y1="44" x2="{x:.0f}" y2="{44+rh*n}" stroke="{C_AXIS}"/>')
        p.append(f'<text x="{x:.0f}" y="{44+rh*n+20}" font-size="11" fill="#57606a" text-anchor="middle">{int(xmax*g/4)}</text>')
    for i,(lab,v,col) in enumerate(rows):
        y=44+i*rh; w=max(1,bw*min(v,xmax)/xmax)
        p.append(f'<text x="{labw-10}" y="{y+rh/2+5:.0f}" font-size="12.5" fill="{C_TEXT}" text-anchor="end">{esc(lab)[:34]}</text>')
        p.append(f'<rect x="{labw}" y="{y+rh*0.2:.0f}" width="{w:.0f}" height="{rh*0.6:.0f}" rx="3" fill="{col}"/>')
        p.append(f'<text x="{labw+w+8:.0f}" y="{y+rh/2+5:.0f}" font-size="12.5" font-weight="600" fill="{C_TEXT}">{v:.1f}{xlabel}</text>')
    p.append(f'<text x="{W-20}" y="{H-8}" font-size="11" fill="#57606a" text-anchor="end">数据与代码开源 · 样本来自 B 站热门榜公开数据</text></svg>')
    open(os.path.join(OUT,fname),"w",encoding="utf-8").write("\n".join(p))
def box(title, series, fname, ymax):
    """series: [(name, [min,q1,med,q3,max], color)]"""
    H=340; pl,pr,pt,pb=90,30,46,60; ph=H-pt-pb; pw=W-pl-pr
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
       f'<rect width="{W}" height="{H}" fill="#fff"/>',
       f'<text x="16" y="28" font-size="16" font-weight="600" fill="{C_TEXT}">{esc(title)}</text>']
    for g in range(5):
        y=pt+ph*(1-g/4); p.append(f'<line x1="{pl}" y1="{y:.0f}" x2="{W-pr}" y2="{y:.0f}" stroke="{C_AXIS}"/>')
        p.append(f'<text x="{pl-8}" y="{y+4:.0f}" font-size="11" fill="#57606a" text-anchor="end">{ymax*g/4:.0f}</text>')
    for i,(name,vals,col) in enumerate(series):
        cx=pl+pw*(i+0.5)/len(series)
        def Y(v): return pt+ph*(1-min(v,ymax)/ymax)
        p.append(f'<line x1="{cx:.0f}" y1="{Y(vals[0]):.0f}" x2="{cx:.0f}" y2="{Y(vals[4]):.0f}" stroke="{col}" stroke-width="1.5"/>')
        p.append(f'<rect x="{cx-34:.0f}" y="{Y(vals[3]):.0f}" width="68" height="{max(2,Y(vals[1])-Y(vals[3])):.0f}" fill="{col}" opacity="0.28" stroke="{col}"/>')
        p.append(f'<line x1="{cx-34:.0f}" y1="{Y(vals[2]):.0f}" x2="{cx+34:.0f}" y2="{Y(vals[2]):.0f}" stroke="{col}" stroke-width="3"/>')
        p.append(f'<text x="{cx:.0f}" y="{H-pb+22}" font-size="12.5" fill="{C_TEXT}" text-anchor="middle">{esc(name)}</text>')
        p.append(f'<text x="{cx:.0f}" y="{Y(vals[2])-9:.0f}" font-size="12" font-weight="600" fill="{col}" text-anchor="middle">{vals[2]:.1f}</text>')
    p.append(f'<text x="{W-20}" y="{H-8}" font-size="11" fill="#57606a" text-anchor="end">中位线 / 箱=IQR / 须=极值</text></svg>')
    open(os.path.join(OUT,fname),"w",encoding="utf-8").write("\n".join(p))
res=json.load(open(os.path.join(DATA,"analysis.json"),encoding="utf-8"))
rows=res["rows"]
def q(v,p):
    v=sorted(v); i=min(len(v)-1,int(len(v)*p)); return v[i]
# 图1 问号指数 Top12
top=sorted(rows,key=lambda r:-r["q_index"])[:12]
bar(f"图1 · 问号指数排行（评论中含 ?/？ 的比例）· n={len(rows)} 个视频",
    [(r["title"][:32], r["q_index"], C1) for r in top], "fig1_question.svg", 30, "%")
# 图2 互动比四分位
def five(key,scale=100.0):
    v=sorted(r[key]*scale for r in rows); return [v[0],q(v,.25),q(v,.5),q(v,.75),v[-1]]
box("图2 · 互动比分布（%）—— 正常视频之间的差异就有 10–100 倍",
    [("点赞/播放",five("r_like_view"),C1),("投币/点赞",five("r_coin_like"),C2),
     ("收藏/点赞",five("r_fav_like"),C3),("评论/播放",five("r_reply_view"),"#bf8700")],
    "fig2_ratios.svg", 120)
# 图3 问号 vs 互动
bar("图3 · 含「？？？」（3 个以上）的评论占比", [(r["title"][:32], r["q3_rate"]*100, C3)
    for r in sorted(rows,key=lambda r:-r["q3_rate"])[:10]], "fig3_q3.svg", 15, "%")
print("生成:"); [print("  report/figures/"+f) for f in sorted(os.listdir(OUT))]
