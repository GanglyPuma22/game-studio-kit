#!/usr/bin/env python3
"""A game's long-term avoid ledger: one JSON object per line, queried by tag and text.

The ledger is a .jsonl file, or a .md file whose entry lines start with "{"
(so a heading and a code fence can sit around them).

The ledger documents what was tried, why it failed and what it cost, so a new
move or shot can start from past lessons. It never forbids a retry; a retry
that works marks the old entry superseded.

Standard library only. The ledger file belongs to the game, never to the kit.

    avoid_ledger.py query LEDGER [--tag T ...] [--any] [--text WORDS] [--decision D7]
                              [--all-status] [--full] [--limit N]
    avoid_ledger.py add LEDGER --json '{...}'      (or --json - to read stdin)
    avoid_ledger.py set-status LEDGER ID STATUS [--note TEXT]
    avoid_ledger.py check LEDGER
    avoid_ledger.py tags LEDGER
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REQUIRED = ("id", "date", "tags", "tried", "failed", "impact")
OPTIONAL = ("lesson", "decision", "status", "evidence", "superseded_by", "note", "lane")
STATUSES = ("active", "superseded", "retired")
DECISIONS = ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "limits")
LANES = ("in-engine", "video", "both")
TAG = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class LedgerError(Exception):
    pass


def validate(entry, where="entry"):
    """Return a list of problems with one entry (empty when it is valid)."""
    problems = []
    if not isinstance(entry, dict):
        return [f"{where}: not a JSON object"]
    for key in REQUIRED:
        if key not in entry or entry[key] in ("", None, []):
            problems.append(f"{where}: missing {key}")
    for key in entry:
        if key not in REQUIRED + OPTIONAL:
            problems.append(f"{where}: unknown field {key}")
    if "id" in entry and not (isinstance(entry["id"], str) and ID.match(entry["id"])):
        problems.append(f"{where}: id must be letters, digits, '.', '_' or '-'")
    if "date" in entry:
        try:
            datetime.date.fromisoformat(str(entry["date"]))
        except ValueError:
            problems.append(f"{where}: date must be YYYY-MM-DD")
    tags = entry.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            problems.append(f"{where}: tags must be a list of lowercase words (a-z, 0-9, '_', '.', '-')")
    for key in ("tried", "failed", "impact", "lesson", "evidence", "note", "superseded_by"):
        if key in entry and not isinstance(entry[key], str):
            problems.append(f"{where}: {key} must be a string")
    if entry.get("status", "active") not in STATUSES:
        problems.append(f"{where}: status must be one of {', '.join(STATUSES)}")
    if "decision" in entry and entry["decision"] not in DECISIONS:
        problems.append(f"{where}: decision must be one of {', '.join(DECISIONS)}")
    if "lane" in entry and entry["lane"] not in LANES:
        problems.append(f"{where}: lane must be one of {', '.join(LANES)}")
    return problems


def is_markdown(path):
    return Path(path).suffix.lower() == ".md"


def _numbered_entries(path):
    """Yield (line number, raw line) for each entry line.

    A .jsonl ledger holds only entries and blank lines. A .md ledger may carry a
    heading, notes and a code fence; there an entry is any line starting with "{".
    """
    markdown = is_markdown(path)
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or (markdown and not line.lstrip().startswith("{")):
            continue
        yield number, line


def load(path):
    """Read every entry; raise LedgerError naming each bad line."""
    path = Path(path)
    if not path.exists():
        return []
    entries, problems, seen = [], [], set()
    for number, line in _numbered_entries(path):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append(f"line {number}: not JSON ({error.msg})")
            continue
        problems += validate(entry, f"line {number}")
        if isinstance(entry, dict) and entry.get("id") in seen:
            problems.append(f"line {number}: duplicate id {entry['id']}")
        if isinstance(entry, dict):
            seen.add(entry.get("id"))
        entries.append(entry)
    if problems:
        raise LedgerError("\n".join(problems))
    return entries


def matches(entry, tags=(), any_tag=False, words=(), decision=None, all_status=False):
    if not all_status and entry.get("status", "active") != "active":
        return False
    if decision and entry.get("decision") != decision:
        return False
    own = set(entry.get("tags", []))
    if tags:
        hits = [t in own for t in tags]
        if not (any(hits) if any_tag else all(hits)):
            return False
    if words:
        text = " ".join(str(entry.get(k, "")) for k in ("tried", "failed", "impact", "lesson", "note")).lower()
        text += " " + " ".join(own)
        if not all(w.lower() in text for w in words):
            return False
    return True


def brief(entry):
    """One line per entry: what to avoid and why, cheap enough to paste into a brief."""
    status = entry.get("status", "active")
    flag = "" if status == "active" else f" [{status}]"
    decision = f" {entry['decision']}" if entry.get("decision") else ""
    lesson = f" -> {entry['lesson']}" if entry.get("lesson") else ""
    return (f"{entry['id']}{flag}{decision} [{','.join(entry['tags'])}] "
            f"tried {entry['tried']}; failed: {entry['failed']}; cost: {entry['impact']}{lesson}")


def query(path, tags=(), any_tag=False, words=(), decision=None, all_status=False, limit=0):
    found = [e for e in load(path) if matches(e, tags, any_tag, words, decision, all_status)]
    found.sort(key=lambda e: str(e.get("date", "")), reverse=True)
    return found[:limit] if limit else found


def add(path, entry):
    entry = dict(entry)
    entry.setdefault("status", "active")
    entry.setdefault("date", datetime.date.today().isoformat())
    problems = validate(entry)
    existing = load(path)
    if any(e.get("id") == entry.get("id") for e in existing):
        problems.append(f"entry: duplicate id {entry.get('id')}")
    if problems:
        raise LedgerError("\n".join(problems))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    # In a Markdown ledger, keep new entries inside a closing code fence.
    end = len(lines)
    if is_markdown(path):
        while end and not lines[end - 1].strip():
            end -= 1
        if end and lines[end - 1].strip().startswith("```"):
            end -= 1
        else:
            end = len(lines)
    lines.insert(end, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entry


def set_status(path, entry_id, status, note=None, superseded_by=None):
    if status not in STATUSES:
        raise LedgerError(f"status must be one of {', '.join(STATUSES)}")
    load(path)  # refuse to rewrite a ledger that does not validate
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for number, line in _numbered_entries(path):
        entry = json.loads(line)
        if entry.get("id") != entry_id:
            continue
        entry["status"] = status
        if note:
            entry["note"] = note
        if superseded_by:
            entry["superseded_by"] = superseded_by
        lines[number - 1] = json.dumps(entry, ensure_ascii=False)
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return entry
    raise LedgerError(f"no entry {entry_id}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("query", help="print matching active entries, newest first, one line each")
    q.add_argument("ledger")
    q.add_argument("--tag", action="append", default=[], help="entry must carry this tag (repeat for more)")
    q.add_argument("--any", action="store_true", help="match entries carrying any of the tags, not all")
    q.add_argument("--text", default="", help="words that must all appear in the entry")
    q.add_argument("--decision", choices=DECISIONS)
    q.add_argument("--all-status", action="store_true", help="include superseded and retired entries")
    q.add_argument("--full", action="store_true", help="print whole JSON entries")
    q.add_argument("--limit", type=int, default=0)
    a = sub.add_parser("add", help="append one entry after validating it")
    a.add_argument("ledger")
    a.add_argument("--json", required=True, help="the entry as JSON, or - to read stdin")
    s = sub.add_parser("set-status", help="mark an entry superseded or retired (it stays in the file)")
    s.add_argument("ledger")
    s.add_argument("id")
    s.add_argument("status", choices=STATUSES)
    s.add_argument("--note")
    s.add_argument("--superseded-by")
    c = sub.add_parser("check", help="validate every line")
    c.add_argument("ledger")
    t = sub.add_parser("tags", help="list tags with counts of active entries")
    t.add_argument("ledger")
    args = parser.parse_args(argv)
    try:
        if args.command == "query":
            found = query(args.ledger, args.tag, args.any, args.text.split(), args.decision,
                          args.all_status, args.limit)
            for entry in found:
                print(json.dumps(entry, ensure_ascii=False) if args.full else brief(entry))
            if not found:
                print("no matching entries", file=sys.stderr)
        elif args.command == "add":
            raw = sys.stdin.read() if args.json == "-" else args.json
            print(brief(add(args.ledger, json.loads(raw))))
        elif args.command == "set-status":
            print(brief(set_status(args.ledger, args.id, args.status, args.note, args.superseded_by)))
        elif args.command == "check":
            entries = load(args.ledger)
            print(f"ok: {len(entries)} entries")
        elif args.command == "tags":
            counts = {}
            for entry in load(args.ledger):
                if entry.get("status", "active") == "active":
                    for tag in entry["tags"]:
                        counts[tag] = counts.get(tag, 0) + 1
            for tag, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"{tag} {count}")
    except (LedgerError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
