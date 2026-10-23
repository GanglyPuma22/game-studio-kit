#!/usr/bin/env python3
"""Service host side: stage a gated Hugging Face model for one runtime
without sending the account token there.

    stage_hf.py RECIPE_JSON OUT_JSON

Reads the host's own Hugging Face login (HF_TOKEN, else the file in
HF_TOKEN_PATH, else ~/.cache/huggingface/token; the file may hold the bare
token or an env-style HF_TOKEN=... line), lists the model at the
recipe's pinned revision, keeps the files the recipe includes, and writes
OUT_JSON (mode 600) with, per file, its SHA-256 and either the bytes inline
(small files) or the short-lived download link the hub hands out. Each link
is checked to work without the token. The token is never printed or written.
OUT_JSON is a set of capabilities: copy it only to the job's runtime, never
into results, and treat it as expired after the run.
"""
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HUB = "https://huggingface.co"


def token_from_file(text):
    """A bare token, or the HF_TOKEN line of an env file (export, quotes allowed)."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    for l in lines:
        k, sep, v = l.removeprefix("export ").partition("=")
        if sep and k.strip() in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
            return v.strip().strip("'\"")
    return lines[0] if len(lines) == 1 and "=" not in lines[0] else ""


def token():
    t = os.environ.get("HF_TOKEN", "").strip()
    if not t:
        path = Path(os.environ.get("HF_TOKEN_PATH", Path.home() / ".cache" / "huggingface" / "token"))
        t = token_from_file(path.read_text()) if path.is_file() else ""
    if not t:
        sys.exit("no Hugging Face login on this host (HF_TOKEN, HF_TOKEN_PATH or ~/.cache/huggingface/token)")
    return t


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url, tok=None, follow=True, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=dict(headers or {}))
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        return opener.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        if not follow and e.code in (301, 302, 303, 307, 308):
            return e
        if e.code in (401, 403):
            sys.exit(f"{url.split('?')[0]}: HTTP {e.code}. Is the model's licence accepted on its page for this account?")
        raise


def main(recipe_path, out_path):
    recipe = json.loads(Path(recipe_path).read_text())
    model = recipe["model"]
    repo, rev = model["repo"], model["revision"]
    tok = token()
    tree = json.load(get(f"{HUB}/api/models/{repo}/tree/{rev}?recursive=true", tok))
    keep = [e for e in tree if e.get("type") == "file"
            and any(e["path"] == inc or (inc.endswith("/") and e["path"].startswith(inc)) for inc in model["include"])]
    if model.get("expect_files") and len(keep) != model["expect_files"]:
        sys.exit(f"{repo}@{rev}: {len(keep)} files match the recipe, expected {model['expect_files']}")
    files = []
    for e in keep:
        path = e["path"]
        url = f"{HUB}/{repo}/resolve/{rev}/{urllib.parse.quote(path)}"
        if e.get("lfs"):
            r = get(url, tok, follow=False)
            link = r.headers.get("Location", "")
            if not link.startswith("https://"):
                sys.exit(f"{path}: the hub gave no absolute download link")
            # The link must work on its own (no token on the runtime).
            probe = get(link, headers={"Range": "bytes=0-0"})
            if probe.status not in (200, 206):
                sys.exit(f"{path}: download link refused without the token (HTTP {probe.status})")
            files.append({"path": path, "sha256": e["lfs"]["oid"], "size": e["lfs"]["size"], "url": link})
        else:
            data = get(url, tok).read()
            files.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                          "inline_b64": base64.b64encode(data).decode()})
    out = Path(out_path)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"repo": repo, "revision": rev, "files": files}, f)
    print(f"staged {repo}@{rev[:12]}: {len(files)} files, {sum(x['size'] for x in files)} bytes (links expire; not for results)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
