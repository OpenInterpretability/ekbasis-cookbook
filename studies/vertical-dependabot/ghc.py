"""GitHub REST through `gh api`, cached on disk (one file per URL). Respects the rate limit."""
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", "gh")
REG = os.path.join(ROOT, "cache", "reg")


def _path(d, key):
    return os.path.join(d, hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def gh(url, allow_404=True):
    p = _path(CACHE, url)
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except ValueError:
            os.remove(p)                     # a file cut by a killed run
    for attempt in range(30):
        r = subprocess.run(["gh", "api", "-X", "GET", url, "-H", "Accept: application/vnd.github+json"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            data = json.loads(r.stdout) if r.stdout.strip() else None
            break
        err = r.stderr + r.stdout
        if allow_404 and ("404" in err or "Not Found" in err or "422" in err or "451" in err or "409" in err):
            data = {"__error__": err[:300]}
            break
        if "rate limit" in err.lower() or "403" in err or "429" in err:
            time.sleep(300)                  # the hourly window: wait for it instead of failing
            continue
        time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"gh failed: {url}: {err[:300]}")
    _save(p, data)
    return data


def _save(p, data):
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, p)


def http_json(url):
    """Public registries (npm, PyPI): no account, cached."""
    p = _path(REG, url)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    data = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "study"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = {"__error__": "404"}
                break
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    if data is None:
        data = {"__error__": "unreachable"}
    _save(p, data)
    return data
