"""Validate the complete skill/resource graph in a relocated source tree."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .common import read_json, relative, StudioError, sha256


def check(root):
    root = Path(root).resolve()
    errors = []
    try:
        manifest = read_json(root / "studio-kit.json")
        plugin = read_json(root / ".codex-plugin/plugin.json")
        if plugin.get("skills") != "./skills/" or plugin.get("name") != manifest.get(
            "name"
        ):
            errors.append("plugin name/skills disagree with studio-kit.json")
        if plugin.get("version") != manifest.get("version"):
            errors.append("plugin version disagrees with package")
        names = set()
        for skill in manifest["skills"]:
            if skill["name"] in names:
                errors.append("duplicate skill name: " + skill["name"])
            names.add(skill["name"])
            path = relative(root, skill["path"])
            if not path.is_file():
                errors.append("missing skill: " + skill["path"])
                continue
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n") or len(text.split("---", 2)) != 3:
                errors.append("missing frontmatter: " + skill["path"])
                continue
            front = text.split("---", 2)[1]
            if not re.search(
                r"^name: " + re.escape(skill["name"]) + r"$", front, re.M
            ) or not re.search(r"^description: .+", front, re.M):
                errors.append("invalid skill metadata: " + skill["path"])
        if len(names) != 10:
            errors.append("expected ten distinct studio entrypoints")
        for name in manifest["resources"]:
            if not relative(root, name).is_file():
                errors.append("missing resource: " + name)
        for path in root.rglob("*.md"):
            if any(
                part in {".git", ".venv", "artifacts"}
                for part in path.relative_to(root).parts
            ):
                continue
            for link in re.findall(
                r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")
            ):
                if urlsplit(link).scheme or link.startswith("#"):
                    continue
                target = (path.parent / unquote(link.split("#")[0])).resolve()
                if not target.is_relative_to(root) or not target.exists():
                    errors.append(
                        f"{path.relative_to(root)}: missing/escaping link {link}"
                    )
        for path in (root / "templates").glob("*.json"):
            read_json(path)
        lock = read_json(root / "upstream-lock.json")
        for source in lock["sources"]:
            if not re.fullmatch(r"[a-f0-9]{40}", source["revision"]):
                errors.append(
                    "upstream revision is not pinned: " + source["repository"]
                )
            for item in source.get("files", []):
                p = relative(root, item["local"])
                if not p.is_file() or sha256(p) != item["sha256"]:
                    errors.append(
                        "upstream adapted file hash mismatch: " + item["local"]
                    )
    except (StudioError, KeyError, TypeError, OSError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors}
