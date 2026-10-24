"""用霞鹜文楷（LXGW WenKai, SIL OFL 1.1）提取今文字（楷书）字形轮廓。

输入：字表（TSV: 字<TAB>拼音<TAB>码位）
输出：data/kai.json { 字: "path d" }
"""
import json, os, re, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", ".cache")
OUT = CACHE
FONT = "/tmp/hanzi/LXGWWenKai-Regular.ttf"
CANVAS, PAD = 1000, 78
UPEM = 1000

def num(v):
    s = f"{v:.0f}"
    return "0" if s in ("-0", "") else s

def tidy(d):
    d = re.sub(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", lambda m: num(float(m.group(0))), d)
    return re.sub(r"\s+", " ", d).strip()

def main():
    chars = [ln.split("\t")[0].strip() for ln in open(os.path.join(CACHE, "chars.tsv"), encoding="utf-8") if ln.strip()]
    f = TTFont(FONT, lazy=True)
    gs = f.getGlyphSet(); cmap = f.getBestCmap()
    out, missing = {}, []
    for ch in chars:
        g = cmap.get(ord(ch))
        if not g:
            missing.append(ch); continue
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        if not bp.bounds:
            missing.append(ch); continue
        x0, y0, x1, y1 = bp.bounds
        w, h = x1 - x0, y1 - y0
        scale = (CANVAS - 2 * PAD) / max(w, h)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # 字体坐标系 y 向上，SVG y 向下；先翻转再缩放居中
        tx = CANVAS / 2 - cx * scale
        ty = CANVAS / 2 + cy * scale
        sp = SVGPathPen(gs, ntos=num)
        gs[g].draw(TransformPen(sp, (scale, 0, 0, -scale, tx, ty)))
        out[ch] = tidy(sp.getCommands())
    json.dump(out, open(os.path.join(CACHE, "kai.json"), "w"), ensure_ascii=False)
    print(f"kai glyphs={len(out)} missing={len(missing)} bytes={os.path.getsize(os.path.join(CACHE,'kai.json'))}")
    if missing:
        print("missing sample:", "".join(missing[:100]))

if __name__ == "__main__":
    main()
