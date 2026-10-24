"""通过 GitHub Git Data API 发布静态站点（git push 不可达时的替代路径）。

增量上传：本地计算 git blob sha1，只上传与远端最新提交不同的文件。

用法：GITHUB_TOKEN=xxx python3 scripts/deploy_api.py "提交说明"
"""
import base64, hashlib, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "luoke-ai/hanzi-life"
BRANCH = "main"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
SKIP_DIRS = {".git", ".cache", "node_modules", ".venv", "__pycache__"}


def req(method, path, payload=None, tries=5):
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
            with urllib.request.urlopen(r, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503):
                time.sleep(2 + i * 4)
                continue
            raise RuntimeError(f"{method} {path} -> {e.code} {body}")
    raise RuntimeError(f"{method} {path} failed after retries")


def git_sha(path):
    """git blob sha1"""
    raw = open(path, "rb").read()
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(raw))
    h.update(raw)
    return h.hexdigest(), raw


def collect():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn == ".DS_Store" or fn.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            out.append((rel, full))
    out.sort()
    return out


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "更新站点"
    files = collect()
    local = {}
    for rel, full in files:
        local[rel] = git_sha(full)

    # 读取远端最新提交树
    remote = {}
    parent = None
    try:
        ref = req("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
        parent = ref["object"]["sha"]
        commit = req("GET", f"/repos/{REPO}/git/commits/{parent}")
        tree = req("GET", f"/repos/{REPO}/git/trees/{commit['tree']['sha']}?recursive=1")
        for e in tree.get("tree", []):
            if e["type"] == "blob":
                remote[e["path"]] = e["sha"]
    except RuntimeError as e:
        print("no existing ref, first deploy:", e)

    changed = [(rel, full) for rel, full in files if remote.get(rel) != local[rel][0]]
    deleted = [p for p in remote if p not in local]
    print(f"files={len(files)} changed={len(changed)} deleted={len(deleted)}", flush=True)

    def upload(item):
        rel, full = item
        sha, raw = local[rel]
        blob = req("POST", f"/repos/{REPO}/git/blobs",
                   {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        return rel, blob["sha"], len(raw)

    entries = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (rel, sha, size) in enumerate(pool.map(upload, changed), 1):
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
            if i % 25 == 0:
                print(f"  blobs {i}/{len(changed)} {time.time()-t0:.0f}s", flush=True)

    for p in deleted:
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": None})

    if not entries:
        print("nothing to update")
        return

    payload = {"tree": entries}
    if parent:
        payload["base_tree"] = req("GET", f"/repos/{REPO}/git/commits/{parent}")["tree"]["sha"]
    tree = req("POST", f"/repos/{REPO}/git/trees", payload)

    commit_payload = {"message": msg, "tree": tree["sha"]}
    if parent:
        commit_payload["parents"] = [parent]
    commit = req("POST", f"/repos/{REPO}/git/commits", commit_payload)

    if parent:
        req("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": True})
    else:
        req("POST", f"/repos/{REPO}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    print("deployed", commit["sha"], flush=True)


if __name__ == "__main__":
    main()
