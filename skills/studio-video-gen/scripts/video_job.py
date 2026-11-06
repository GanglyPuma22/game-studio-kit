#!/usr/bin/env python3
"""Mechanical runner for paid video and image generation (Runway, OpenRouter).

It does no creative work. It reads a jobs file, prices every job, refuses to
spend past a cap or without a recorded approval, claims a record entry before
each POST, polls every accepted task in parallel and archives the outputs.

  python video_job.py estimate JOBS.json
  python video_job.py balance  --provider runway [--key-file FILE]
  python video_job.py submit   JOBS.json --out DIR --approval "go grab test, cap $3" [--only a,b] [--key-file FILE]
  python video_job.py resume   DIR [--key-file FILE]

Jobs file:
  {"provider": "runway", "cap_usd": 3.0,
   "jobs": [{"name": "grab_pillars", "endpoint": "video_to_video",
             "body": {"model": "seedance2_5", "promptVideo": "@file:inputs/grab.mp4", ...},
             "ref_seconds": 6, "out_seconds": 6}]}

A string "@file:<path>" anywhere in a body becomes a data: URI of that file
(path relative to the jobs file). Standard library only. The key is read from
RUNWAYML_API_SECRET or OPENROUTER_API_KEY, or from a KEY=VALUE file, and is
never printed, logged or written to the record.
"""
import argparse, base64, json, math, os, sys, threading, time, urllib.error, urllib.request

PROVIDERS = {
    "runway": {"api": "https://api.dev.runwayml.com/v1", "env": "RUNWAYML_API_SECRET"},
    "openrouter": {"api": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY"},
}
RUNWAY_VERSION = "2024-11-06"
DATA_URI_LIMIT = 5 * 1024 * 1024  # Runway rejects inline media above about 5 MB
PROMPT_LIMITS = {"aleph2": 1000}  # characters
RATES_CHECKED = "2026-11-02"  # https://docs.dev.runwayml.com/guides/pricing/ ; re-check before each approval ask


def runway_credits(job):
    """Credits ($0.01 each) from the published per-second rates, rounded up per task."""
    if "est_credits" in job:
        return int(job["est_credits"])
    model = job["body"].get("model", "")
    out_s = float(job.get("out_seconds") or job["body"].get("duration") or 0)
    ref_s = float(job.get("ref_seconds") or 0)
    if model.startswith("seedance"):
        return max(80, math.ceil(30 * out_s + 15 * ref_s))
    if model.startswith("aleph"):
        return max(56, math.ceil(28 * (ref_s or out_s)))
    if model.startswith("kling"):
        return math.ceil(9.4 * (ref_s or out_s) * 2)
    if model.startswith("gen4_image"):
        return 8
    raise SystemExit("no rate for model %r: give the job an est_credits from the current price page" % model)


def estimate_usd(provider, job):
    if provider == "runway":
        return runway_credits(job) / 100.0
    if "est_usd" not in job:
        raise SystemExit("job %s: OpenRouter jobs need est_usd (price page x seconds, x2 with a video reference)"
                         % job["name"])
    return float(job["est_usd"])


def read_key(provider, key_file=None):
    env = PROVIDERS[provider]["env"]
    value = os.environ.get(env, "").strip()
    if not value and key_file and os.path.isfile(key_file):
        with open(key_file, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                if line.startswith(env + "="):
                    value = line.split("=", 1)[1].strip().strip("'\"")
    if not value:
        raise SystemExit("credential_missing: set %s or pass --key-file" % env)
    return value


def http(method, url, key=None, provider="runway", body=None, raw=False):
    """One HTTP call. Returns (status, parsed JSON or bytes). Errors are returned, not raised."""
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if key:
        req.add_header("Authorization", "Bearer " + key)
        if provider == "runway":
            req.add_header("X-Runway-Version", RUNWAY_VERSION)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:2000]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, {"error": "%s: %s" % (type(e).__name__, e)}


def data_uri(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) > DATA_URI_LIMIT:
        raise SystemExit("%s is %.1f MB; inline media must stay under 5 MB (re-encode or host it)"
                         % (path, len(data) / 1e6))
    if data[4:8] == b"ftyp":
        mime = "video/mp4"
    elif data.startswith(b"\x89PNG"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8"):
        mime = "image/jpeg"  # go by bytes: image models often save JPEG data as .png
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise SystemExit("unknown media type: " + path)
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())


def resolve(value, base):
    if isinstance(value, str) and value.startswith("@file:"):
        return data_uri(os.path.join(base, value[6:]))
    if isinstance(value, list):
        return [resolve(v, base) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, base) for k, v in value.items()}
    return value


def check_job(job, base):
    """Offline checks that would otherwise cost a rejected round trip."""
    problems = []
    body = job.get("body", {})
    text = body.get("promptText") or body.get("prompt") or ""
    limit = PROMPT_LIMITS.get(body.get("model", ""))
    if limit and len(text) > limit:
        problems.append("prompt is %d chars, %s takes %d" % (len(text), body["model"], limit))

    def walk(v):
        if isinstance(v, str) and v.startswith("@file:"):
            p = os.path.join(base, v[6:])
            if not os.path.isfile(p):
                problems.append("missing file " + v[6:])
            elif os.path.getsize(p) > DATA_URI_LIMIT:
                problems.append("%s over 5 MB" % v[6:])
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
    walk(body)
    return problems


def load(path):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    if spec.get("provider") not in PROVIDERS:
        raise SystemExit("provider must be one of " + ", ".join(PROVIDERS))
    if not isinstance(spec.get("cap_usd"), (int, float)) or spec["cap_usd"] <= 0:
        raise SystemExit("the jobs file needs a positive cap_usd")
    names = [j["name"] for j in spec["jobs"]]
    if len(names) != len(set(names)):
        raise SystemExit("job names must be unique")
    return spec


def cmd_estimate(a):
    spec = load(a.jobs)
    base = os.path.dirname(os.path.abspath(a.jobs))
    total, bad = 0.0, False
    for job in spec["jobs"]:
        usd = estimate_usd(spec["provider"], job)
        total += usd
        problems = check_job(job, base)
        bad = bad or bool(problems)
        print("%-24s $%6.2f  %s" % (job["name"], usd, "; ".join(problems) or "ok"))
    print("TOTAL $%.2f of cap $%.2f (rates checked %s)" % (total, spec["cap_usd"], RATES_CHECKED))
    if total > spec["cap_usd"] or bad:
        sys.exit(1)


def balance(provider, key):
    if provider == "runway":
        status, r = http("GET", PROVIDERS["runway"]["api"] + "/organization", key)
        return r.get("creditBalance") if status == 200 else None
    status, r = http("GET", PROVIDERS["openrouter"]["api"] + "/credits", key, provider)
    d = r.get("data", {}) if status == 200 else {}
    return None if not d else round(d.get("total_credits", 0) - d.get("total_usage", 0), 4)


def cmd_balance(a):
    print(json.dumps({"provider": a.provider, "balance": balance(a.provider, read_key(a.provider, a.key_file)),
                      "read_only": True}))


def save(record, out):
    tmp = os.path.join(out, "record.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    os.replace(tmp, os.path.join(out, "record.json"))


LOCK = threading.Lock()
# States whose estimate counts against the cap: anything that reached, or may have reached, the provider.
SPENDING = ("CLAIMED", "ACCEPTED", "DONE", "FAILED", "SUBMISSION_UNKNOWN")


def submit_one(spec, job, base, record, out, key):
    provider = spec["provider"]
    entry = record["jobs"][job["name"]]
    usd = entry["est_usd"]
    reserved = sum(e["est_usd"] for e in record["jobs"].values() if e["state"] in SPENDING)
    if reserved + usd > record["cap_usd"] + 1e-9:
        entry["state"] = "SKIPPED_OVER_CAP"
        return None
    if provider == "runway":
        bal = balance(provider, key)
        entry["balance_before"] = bal
        held = sum(e["est_usd"] for e in record["jobs"].values() if e["state"] == "ACCEPTED") * 100
        if bal is not None and bal - held < usd * 100:
            entry["state"] = "SKIPPED_NO_CREDITS"
            return None
    body = resolve(job["body"], base)
    entry["state"] = "CLAIMED"  # written before the POST: a crash here is SUBMISSION_UNKNOWN, never a retry
    save(record, out)
    path = "/" + job.get("endpoint", "video_to_video") if provider == "runway" else "/" + job.get("endpoint", "videos")
    status, r = http("POST", PROVIDERS[provider]["api"] + path, key, provider, body)
    entry["http_status"] = status
    if status is None:
        entry["state"] = "SUBMISSION_UNKNOWN"
        entry["error"] = r.get("error")
    elif status not in (200, 201, 202) or "id" not in r:
        entry["state"] = "REJECTED"
        entry["error"] = r.get("error")
    else:
        entry["state"] = "ACCEPTED"
        entry["task"] = r["id"]
    save(record, out)
    return entry.get("task")


def observe(provider, name, entry, out, key, timeout=2400, every=15):
    api = PROVIDERS[provider]["api"]
    t0 = time.time()
    while True:
        if provider == "runway":
            status, p = http("GET", api + "/tasks/" + entry["task"], key)
            st = (p or {}).get("status")
            done, ok = st in ("SUCCEEDED", "FAILED", "CANCELLED"), st == "SUCCEEDED"
        else:
            status, p = http("GET", api + "/videos/" + entry["task"], key, provider)
            st = (p or {}).get("status")
            done, ok = st in ("completed", "failed", "cancelled", "expired"), st == "completed"
        if done:
            break
        if time.time() - t0 > timeout:
            with LOCK:
                entry["state"] = "ACCEPTED"  # still running: resume later, never resubmit
                entry["note"] = "observation timed out"
            return
        time.sleep(every)
    files = []
    if ok:
        if provider == "runway":
            urls = p.get("output") or []
        else:
            urls = [api + "/videos/%s/content?index=0" % entry["task"]]
        for i, url in enumerate(urls):
            auth = key if provider == "openrouter" else None
            status, data = http("GET", url, auth, provider, raw=True)
            if status == 200 and isinstance(data, bytes):
                ext = ".png" if data.startswith(b"\x89PNG") else ".jpg" if data.startswith(b"\xff\xd8") else ".mp4"
                dst = os.path.join(out, "%s%s%s" % (name, "" if i == 0 else "_%d" % i, ext))
                with open(dst + ".part", "wb") as f:
                    f.write(data)
                os.replace(dst + ".part", dst)
                files.append(os.path.basename(dst))
    with LOCK:
        entry["final"] = st
        entry["seconds"] = round(time.time() - t0)
        entry["files"] = files
        if provider == "openrouter":
            entry["cost_usd"] = float(((p or {}).get("usage") or {}).get("cost") or 0.0)
        entry["state"] = "DONE" if ok and files else ("ACCEPTED" if ok else "FAILED")
        if not ok:
            entry["error"] = p.get("failure") or p.get("failureCode") or p.get("error") or st


def observe_all(record, out, key):
    threads = []
    for name, e in record["jobs"].items():
        if e["state"] == "ACCEPTED" and e.get("task"):
            t = threading.Thread(target=observe, args=(record["provider"], name, e, out, key))
            threads.append(t)
            t.start()
    for t in threads:
        t.join()
    if record["provider"] == "runway":
        record["balance_end"] = balance("runway", key)
    save(record, out)


def summary(record):
    for name, e in record["jobs"].items():
        print("%-24s %-18s $%.2f %s" % (name, e["state"], e["est_usd"], ",".join(e.get("files", [])) or e.get("error") or ""))
    spent = sum(e["est_usd"] for e in record["jobs"].values() if e["state"] in SPENDING)
    print("ESTIMATED SPEND $%.2f of cap $%.2f" % (spent, record["cap_usd"]))


def cmd_submit(a):
    if not a.approval or not a.approval.strip():
        raise SystemExit("approval_missing: quote the person's own go message (with its cap) in --approval")
    spec = load(a.jobs)
    base = os.path.dirname(os.path.abspath(a.jobs))
    only = set(filter(None, (a.only or "").split(",")))
    jobs = [j for j in spec["jobs"] if not only or j["name"] in only]
    for job in jobs:
        problems = check_job(job, base)
        if problems:
            raise SystemExit("job %s: %s" % (job["name"], "; ".join(problems)))
    os.makedirs(a.out, exist_ok=True)
    if os.path.exists(os.path.join(a.out, "record.json")):
        raise SystemExit("%s already holds a record; use resume, or a fresh --out" % a.out)
    key = read_key(spec["provider"], a.key_file)
    record = {"provider": spec["provider"], "cap_usd": float(spec["cap_usd"]), "approval": a.approval.strip(),
              "jobs_file": os.path.abspath(a.jobs), "rates_checked": RATES_CHECKED,
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "jobs": {}}
    if spec["provider"] == "runway":
        record["balance_start"] = balance("runway", key)
    for job in jobs:
        record["jobs"][job["name"]] = {"state": "PLANNED", "est_usd": estimate_usd(spec["provider"], job),
                                       "endpoint": job.get("endpoint"), "model": job["body"].get("model")}
    save(record, a.out)
    for job in jobs:  # one after another, cap checked before each
        submit_one(spec, job, base, record, a.out, key)
    observe_all(record, a.out, key)
    summary(record)


def cmd_resume(a):
    with open(os.path.join(a.out, "record.json"), encoding="utf-8") as f:
        record = json.load(f)
    key = read_key(record["provider"], a.key_file)
    observe_all(record, a.out, key)
    summary(record)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("estimate"); p.add_argument("jobs"); p.set_defaults(fn=cmd_estimate)
    p = sub.add_parser("balance"); p.add_argument("--provider", choices=PROVIDERS, required=True)
    p.add_argument("--key-file"); p.set_defaults(fn=cmd_balance)
    p = sub.add_parser("submit"); p.add_argument("jobs"); p.add_argument("--out", required=True)
    p.add_argument("--approval", required=True); p.add_argument("--only"); p.add_argument("--key-file")
    p.set_defaults(fn=cmd_submit)
    p = sub.add_parser("resume"); p.add_argument("out"); p.add_argument("--key-file"); p.set_defaults(fn=cmd_resume)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
