"""Validate the complete skill/resource graph in a relocated source tree."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .common import read_json, relative, StudioError, sha256


# The base catalogue by name. The count alone cannot prove these are present,
# because any other well-formed skill would reach the same number.
REQUIRED_SKILLS = {
    name: f"skills/{name}/SKILL.md"
    for name in (
        "studio-director", "studio-game-design", "studio-art-direction", "studio-blender",
        "studio-meshy", "studio-terrain", "studio-animation", "studio-audio", "studio-godot",
        "studio-playtest", "studio-gym", "studio-review",
    )
}


# YAML 1.2's double-quoted escapes, with the hex lengths it requires.
_DOUBLE_QUOTED = (
    r'"(?:[^"\\]|\\(?:[0abtnvfre "/\\N_LP\t]'
    r'|x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}))*"'
)


def _valid_yaml_scalar(text):
    """A one-line YAML scalar that parses as the whole string, without a YAML library.

    A plain scalar ends at ": " or " #" and cannot start with an indicator. A double-quoted one must close at its
    last character with every inner quote escaped; a single-quoted one escapes
    an inner quote by doubling it.
    """
    if text.startswith('"'):
        return re.fullmatch(_DOUBLE_QUOTED, text) is not None
    if text.startswith("'"):
        return re.fullmatch(r"'(?:[^']|'')*'", text) is not None
    if text[0] in "-?:,[]{}#&*!|>%@`":
        return False
    return ": " not in text and " #" not in text and not text.endswith(":")


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
        claude_path = root / ".claude-plugin/plugin.json"
        if claude_path.is_file():
            claude = read_json(claude_path)
            if not isinstance(claude, dict):
                raise StudioError("Claude plugin manifest must be an object")
            if claude.get("name") != manifest.get("name") or claude.get("version") != manifest.get("version"):
                errors.append("Claude plugin name/version disagree with package")
            if claude.get("skills", "./skills/") not in ("./skills/", ["./skills/"]):
                errors.append("Claude plugin must load the shared skills directory")
        marketplace_path = root / ".claude-plugin/marketplace.json"
        if marketplace_path.is_file():
            marketplace = read_json(marketplace_path)
            if not isinstance(marketplace, dict):
                raise StudioError("Claude marketplace must be an object")
            if marketplace.get("name") != manifest.get("name") + "-marketplace":
                errors.append("Claude marketplace name disagrees with package")
            owner = marketplace.get("owner")
            if not isinstance(owner, dict) or not isinstance(owner.get("name"), str) or not owner["name"].strip():
                errors.append("Claude marketplace owner must have a nonempty name")
            plugins = marketplace.get("plugins")
            if not isinstance(plugins, list) or any(
                not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip()
                for entry in plugins
            ):
                raise StudioError("Claude marketplace plugins must be a list of named objects")
            matching = [entry for entry in plugins if entry["name"] == manifest.get("name")]
            if len(matching) != 1:
                errors.append("Claude marketplace must contain exactly one shared-kit plugin")
            else:
                entry = matching[0]
                try:
                    source = relative(root, entry.get("source"))
                    if source != root:
                        errors.append("Claude marketplace plugin source must resolve to the shared package root")
                except (StudioError, ValueError):
                    errors.append("Claude marketplace plugin source must resolve to the shared package root")
                if "version" in entry and entry["version"] != manifest.get("version"):
                    errors.append("Claude marketplace plugin version disagrees with package")
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
                continue
            # A YAML plain scalar ends at ": " or " #", so hosts that parse the
            # frontmatter as YAML would refuse or truncate such a description.
            description = re.search(r"^description: (.+)$", front, re.M).group(1).rstrip()
            if not _valid_yaml_scalar(description):
                errors.append("description is not a valid one-line YAML scalar: " + skill["path"])
        for name, path in REQUIRED_SKILLS.items():
            if name not in names:
                errors.append("missing required skill declaration: " + name)
            elif any(skill["name"] == name and skill["path"] != path for skill in manifest["skills"]):
                errors.append(name + " must use its canonical skill path")
        tripo_path = "skills/studio-tripo/SKILL.md"
        tripo_reference = "skills/studio-tripo/references/provider-workflow.md"
        has_tripo = "studio-tripo" in names
        expected_count = 13 if has_tripo else 12
        if len(names) != expected_count:
            errors.append(f"expected {expected_count} distinct studio entrypoints")
        if has_tripo:
            if any(skill["name"] == "studio-tripo" and skill["path"] != tripo_path
                   for skill in manifest["skills"]):
                errors.append("studio-tripo must use its canonical skill path")
            if tripo_reference not in manifest["resources"]:
                errors.append("studio-tripo workflow must be declared as a resource")
        elif (root / "skills/studio-tripo").exists() or any(
            skill["path"].startswith("skills/studio-tripo/")
            for skill in manifest["skills"]
        ) or tripo_reference in manifest["resources"]:
            errors.append("studio-tripo files/resources require its skill declaration")
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
