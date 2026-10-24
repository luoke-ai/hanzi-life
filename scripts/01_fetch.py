"""下载 Commons 字形 SVG -> 归一化到 1000x1000 -> 存为紧凑 path 数据。

策略：低并发（2）+ 429 退避 + 缓存断点续传 + 按优先级（常用字先来）增量输出。
输出：.cache/glyphs_raw.json  { 字: { oracle|bronze|seal|clerical: "d" } }
"""
import json, os, re, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

import svgelements as se

BASE = "/tmp/hanzi"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
CACHE = os.path.join(HERE, "..", ".cache")
RAW = os.path.join(HERE, "..", ".cache", "glyphs_raw.json")
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "HanziLife/1.0 (https://github.com/luoke-ai/hanzi-life; static site data build)"}
CANVAS, PAD = 1000, 78
os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def api(params, tries=6):
    params.update(format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(3 + 4 * i)
    raise RuntimeError("commons api failed: " + url)


def file_urls(names):
    out = {}
    for i in range(0, len(names), 50):
        batch = names[i:i + 50]
        d = api({"action": "query", "prop": "imageinfo", "iiprop": "url|size",
                 "titles": "|".join("File:" + n for n in batch)})
        for pg in d.get("query", {}).get("pages", {}).values():
            ii = pg.get("imageinfo")
            if ii and "url" in ii[0]:
                out[pg["title"].replace("File:", "")] = ii[0]["url"]
        time.sleep(0.3)
    return out


def num(v):
    s = f"{v:.1f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def tidy(d):
    d = re.sub(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", lambda m: num(float(m.group(0))), d)
    return re.sub(r"\s+", " ", d).strip()


def normalize(svg_path):
    s = se.SVG.parse(svg_path)
    bbs = []
    for e in s.elements():
        if not isinstance(e, se.Path):
            continue
        b = e.bbox()
        if b is not None and b[2] > b[0] and b[3] > b[1]:
            bbs.append((e, b))
    if not bbs:
        return None
    x0 = min(b[0] for _, b in bbs); y0 = min(b[1] for _, b in bbs)
    x1 = max(b[2] for _, b in bbs); y1 = max(b[3] for _, b in bbs)
    w, h = x1 - x0, y1 - y0
    scale = (CANVAS - 2 * PAD) / max(w, h)
    tx = (CANVAS - w * scale) / 2 - x0 * scale
    ty = (CANVAS - h * scale) / 2 - y0 * scale
    parts = []
    for p, _ in bbs:
        d = (p * se.Matrix(scale, 0, 0, scale, tx, ty)).d()
        if d:
            parts.append(tidy(d))
    return " ".join(parts) if parts else None


def fetch_one(name, url):
    local = os.path.join(CACHE, name)
    if not os.path.exists(local) or os.path.getsize(local) < 80:
        for attempt in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                    data = r.read()
                if len(data) >= 80:
                    open(local, "wb").write(data)
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    ra = e.headers.get("Retry-After")
                    time.sleep(float(ra) if ra else 3 + attempt * 3)
                elif e.code == 404:
                    return name, None
                else:
                    time.sleep(2 + attempt * 2)
            except Exception:
                time.sleep(2 + attempt * 2)
        else:
            return name, None
    try:
        return name, normalize(local)
    except Exception:
        return name, None


def main():
    sel = json.load(open(f"{BASE}/selection.json"))
    keep = set(json.load(open(f"{BASE}/keep.json"))["chars"])
    meta = {}
    for ln in open(os.path.join(CACHE, "chars.tsv"), encoding="utf-8"):
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 4:
            meta[p[0]] = int(p[3]) if p[3].isdigit() else 9999
    need = {ch: v for ch, v in sel.items() if ch in keep}
    # 优先级：常用字（TGHZ 序号小）优先，其次有更多阶段的字
    order = sorted(need, key=lambda c: (meta.get(c, 9999), -len(need[c])))
    files = {}
    for ch in order:
        for stage, info in need[ch].items():
            files.setdefault(info["file"].replace("File:", ""), None)
    names = list(files)
    print(f"chars={len(need)} files={len(names)}", flush=True)

    done = json.load(open(RAW)) if os.path.exists(RAW) else {}
    have = set()
    for rec in done.values():
        pass
    # 已下载的缓存文件名 -> 直接归一化
    cached = {n for n in names if os.path.exists(os.path.join(CACHE, n)) and os.path.getsize(os.path.join(CACHE, n)) >= 80}
    print(f"cached={len(cached)}", flush=True)

    todo = [n for n in names if n not in cached]
    urls = file_urls(todo) if todo else {}
    print("urls", len(urls), flush=True)

    resolved = {}
    for n in cached:
        try:
            d = normalize(os.path.join(CACHE, n))
            if d:
                resolved[n] = d
        except Exception:
            pass
    print("resolved from cache", len(resolved), flush=True)

    def work(name):
        url = urls.get(name)
        if not url:
            return name, None
        pass
        return fetch_one(name, url)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (name, d) in enumerate(pool.map(work, list(urls)), 1):
            if d:
                resolved[name] = d
            if i % 50 == 0:
                build(need, resolved)
                print(f"  {i}/{len(urls)} ok={len(resolved)} {time.time()-t0:.0f}s", flush=True)
    build(need, resolved)
    print(f"DONE files={len(resolved)}/{len(names)} chars={len(json.load(open(RAW)))} "
          f"time={time.time()-t0:.0f}s", flush=True)


def build(need, resolved):
    result = {}
    for ch, stages in need.items():
        rec = {}
        for stage, info in stages.items():
            d = resolved.get(info["file"].replace("File:", ""))
            if d:
                rec[stage] = d
        if rec:
            result[ch] = rec
    json.dump(result, open(RAW, "w"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
