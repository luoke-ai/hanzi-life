"""把抓取结果整理成站点可用的分片数据。

输出：
  data/index.json        { version, chars, stages, count }   —— 极小的清单，首屏即用
  data/g/<bucket>.json   { 字: { p, st, rd, df, src, o,b,s,l,k } } —— 按码位取模分片，按需加载
"""
import json, os, re

BASE = "/tmp/hanzi"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
GDIR = os.path.join(OUT, "g")
BUCKETS = 512

STAGES = [
    {"key": "o", "script": "oracle", "name": "甲骨文", "era": "商",
     "span": "约前 1600 — 前 1046", "note": "契刻于龟甲兽骨，以刀代笔，线条瘦硬方折，象形意味最浓"},
    {"key": "b", "script": "bronze", "name": "金文", "era": "西周",
     "span": "约前 1046 — 前 771", "note": "铸刻于青铜礼器，笔画圆浑肥厚，常有团块状笔触"},
    {"key": "s", "script": "seal", "name": "小篆", "era": "秦",
     "span": "前 221 — 前 206", "note": "书同文，笔画匀圆等粗，结构对称，字形趋于方正"},
    {"key": "l", "script": "clerical", "name": "隶书", "era": "汉",
     "span": "前 206 — 220", "note": "「隶变」破圆为方，波磔舒展，蚕头燕尾，今文字由此定型"},
    {"key": "k", "script": "kaishu", "name": "楷书", "era": "魏晋至今",
     "span": "3 世纪 — 今", "note": "横平竖直，法度严谨，通行千年，为今日标准字形所本"},
]


def load_meta():
    """从 Unihan 提取拼音、笔画、部首、英文释义。"""
    meta = {}
    def rows(fn):
        for line in open(os.path.join(BASE, fn), encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) == 3:
                yield p
    for cp, field, val in rows("Unihan_Readings.txt"):
        ch = chr(int(cp[2:], 16))
        if field == "kTGHZ2013":
            idx, _, read = val.split()[0].partition(":")
            meta.setdefault(ch, {})["p"] = read
            meta[ch]["lvl"] = int(idx.split(".")[0])
        elif field == "kDefinition":
            meta.setdefault(ch, {})["df"] = val.strip()
    for cp, field, val in rows("Unihan_IRGSources.txt"):
        ch = chr(int(cp[2:], 16))
        if field == "kTotalStrokes":
            meta.setdefault(ch, {})["st"] = int(val.split()[0])
        elif field == "kRSUnicode":
            v = val.split()
            raw = (v[1] if len(v) > 1 else v[0]).split(".")[0]
            digits = re.match(r"\d+", raw)
            if digits:
                meta.setdefault(ch, {})["rd"] = int(digits.group(0))
    return meta


def clean_def(s, limit=58):
    if not s:
        return ""
    s = re.sub(r"\([^)]*\)", "", s).strip(" ;,.")
    s = re.sub(r"\s+", " ", s)
    return s[:limit].rstrip(" ;,.")


def main():
    os.makedirs(GDIR, exist_ok=True)
    meta = load_meta()
    ancient = json.load(open(os.path.join(OUT, "..", ".cache", "glyphs_raw.json"), encoding="utf-8"))
    kai = json.load(open(os.path.join(OUT, "..", ".cache", "kai.json"), encoding="utf-8"))
    sel = json.load(open(f"{BASE}/selection.json", encoding="utf-8"))

    def rank(ch):
        m = meta.get(ch, {})
        return (m.get("lvl", 99999), ord(ch))
    chars = sorted((ch for ch in kai if ch in ancient or ch in kai), key=rank)
    buckets = {}
    n_with_ancient = 0
    stage_counts = {s["key"]: 0 for s in STAGES}
    for ch in chars:
        rec = ancient.get(ch, {})
        row = {}
        m = meta.get(ch, {})
        if m.get("p"):
            row["p"] = m["p"]
        if m.get("st"):
            row["st"] = m["st"]
        if m.get("rd"):
            row["rd"] = m["rd"]
        if m.get("lvl"):
            row["lvl"] = m["lvl"]
        df = clean_def(m.get("df"))
        if df:
            row["df"] = df
        srcs = {}
        for s in STAGES:
            d = rec.get(s["script"])
            if d:
                row[s["key"]] = d
                stage_counts[s["key"]] += 1
                info = sel.get(ch, {}).get(s["script"])
                if info:
                    srcs[s["key"]] = info["file"].replace("File:", "").rsplit(".", 1)[0]
        kd = kai.get(ch)
        if kd:
            row["k"] = kd
        if srcs:
            row["src"] = srcs
        if any(s["key"] in row for s in STAGES[:4]):
            n_with_ancient += 1
        b = ord(ch) % BUCKETS
        buckets.setdefault(b, {})[ch] = row

    total_bytes = 0
    for b, data in buckets.items():
        p = os.path.join(GDIR, f"{b}.json")
        txt = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        open(p, "w", encoding="utf-8").write(txt)
        total_bytes += len(txt.encode())

    ancient_chars = "".join(ch for ch in chars if any(ancient.get(ch, {}).get(k) for k in ("oracle", "bronze", "seal", "clerical")))
    quad_chars = "".join(ch for ch in chars if all(ancient.get(ch, {}).get(k) for k in ("oracle", "bronze", "seal", "clerical")))
    oracle_chars = "".join(ch for ch in chars if ancient.get(ch, {}).get("oracle"))
    import time as _t
    index = {
        "version": str(int(_t.time())),
        "ancientChars": ancient_chars,
        "quadChars": quad_chars,
        "oracleChars": oracle_chars,
        "count": len(chars),
        "chars": "".join(chars),
        "stages": STAGES,
        "buckets": BUCKETS,
        "have": stage_counts,
        "ancient": n_with_ancient,
    }
    open(os.path.join(OUT, "index.json"), "w", encoding="utf-8").write(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")))

    print(f"chars={len(chars)} ancient={n_with_ancient} buckets={len(buckets)} "
          f"shard_bytes={total_bytes} index={os.path.getsize(os.path.join(OUT,'index.json'))}")
    print("stage coverage:", stage_counts)
    biggest = max(os.path.getsize(os.path.join(GDIR, f)) for f in os.listdir(GDIR))
    print("largest shard:", biggest)


if __name__ == "__main__":
    main()
