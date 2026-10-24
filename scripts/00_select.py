"""挑选字形文件：按阶段优先级为一字选一体，并输出待下载清单。"""
import json, pickle, re, collections, os

BASE = "/tmp/hanzi"
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
E = pickle.load(open(f"{BASE}/enum_all.pkl", "rb"))

CJK = lambda s: len(s) == 1 and (
    "\u3400" <= s <= "\u4dbf" or "\u4e00" <= s <= "\u9fff" or "\U00020000" <= s <= "\U0002ffff"
)

# 阶段 -> (候选族, 优先级顺序)
STAGES = {
    "oracle": ["oracle", "oracle-shang", "oracle-2", "oracle-3", "oracle-4", "oracle-5"],
    "bronze": ["bronze", "bronze-shang", "bronze-warring", "bronze-spring", "bronze-2", "bronze-3", "bronze-4"],
    "seal":   ["seal", "bigseal", "bigseal-2"],
    "clerical": ["clerical", "clerical-han", "clerical-han-2", "clerical-2", "clerical-han-variant", "hanjian", "silk"],
}

def parse(files):
    """文件名 '字-族.svg' -> {字: {族: 文件名}}，同族保留第一个。"""
    out = collections.defaultdict(dict)
    for f in files:
        n = f.replace("File:", "").rsplit(".", 1)[0]
        if n.startswith("ACC-") or n.startswith("Calligraphy"):
            continue
        m = re.match(r"^(.+?)-([a-z0-9\-]+)$", n)
        if not m:
            continue
        ch, fam = m.group(1), m.group(2)
        if not CJK(ch):
            continue
        out[ch].setdefault(fam, f)
    return out

parsed = {k: parse(v) for k, v in E.items()}
chars = set()
for v in parsed.values():
    chars |= set(v)
# 只保留确实带某个古文字体的字
sel = {}
for ch in sorted(chars):
    picked = {}
    for stage, fams in STAGES.items():
        for fam in fams:
            src = None
            for k in parsed:
                if fam in parsed[k].get(ch, {}):
                    src = parsed[k][ch][fam]
                    break
            if src:
                picked[stage] = {"fam": fam, "file": src}
                break
    if picked:
        sel[ch] = picked
print("chars with ancient glyph:", len(sel))
cnt = collections.Counter()
for ch, p in sel.items():
    for s in p:
        cnt[s] += 1
print("stage coverage:", dict(cnt))
json.dump(sel, open(f"{BASE}/selection.json", "w"), ensure_ascii=False)
