"""通过 GitHub Git Data API 发布静态站点（当 git push 不可达时使用）。

用法：GITHUB_TOKEN=xxx python3 scripts/deploy_api.py
"""
import base64, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "luoke-ai/hanzi-life"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"


def req(method, path, payload=None, tries=4):
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    for i in range(tries):
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Authorization", "Bearer " + TOKEN)
        r.add_header("Accept", "application/vnd.github+json")
        r.add_header("User-Agent", "hanzi-life-deploy")
        if data:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503):
                time.sleep(2 + i * 3)
                continue
            raise RuntimeError(f"{method} {path} -> {e.code} {body}")
    raise RuntimeError(f"{method} {path} failed after retries")


def collect():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".cache", "node_modules", ".venv")]
        for fn in filenames:
            if fn in (".DS_Store",) or fn.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            out.append((rel, full))
    out.sort()
    return out


def main():
    files = collect()
    total = sum(os.path.getsize(p) for _, p in files)
    print(f"files={len(files)} bytes={total/1e6:.1f}MB", flush=True)

    def upload(item):
        rel, full = item
        raw = open(full, "rb").read()
        payload = {"content": base64.b64encode(raw).decode(), "encoding": "base64"}
        res = req("POST", f"/repos/{REPO}/git/blobs", payload)
        return rel, res["sha"], len(raw)

    entries = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for rel, sha, size in pool.map(upload, files):
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
            done += 1
            if done % 50 == 0:
                print(f"  blobs {done}/{len(files)} {time.time()-t0:.0f}s", flush=True)

    print("creating tree…", flush=True)
    tree = req("POST", f"/repos/{REPO}/git/trees", {"tree": entries})
    print("creating commit…", flush=True)
    commit = req("POST", f"/repos/{REPO}/git/commits", {
        "message": "汉字的一生：输入任意汉字，看甲骨文到楷书的五体演变",
        "tree": tree["sha"],
    })
    print("updating ref…", flush=True)
    try:
        req("POST", f"/repos/{REPO}/git/refs", {"ref": "refs/heads/main", "sha": commit["sha"]})
    except RuntimeError:
        req("PATCH", f"/repos/{REPO}/git/refs/heads/main", {"sha": commit["sha"], "force": True})
    print("deployed commit", commit["sha"], flush=True)


if __name__ == "__main__":
    main()
