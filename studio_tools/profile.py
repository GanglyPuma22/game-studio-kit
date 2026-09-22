"""Project-owned launch and playtest profiles: the wrapper script, as a file.

Six wrapper scripts around one project were the same thirty lines with a
different worktree and a different set of feature flags: verify a list of asset
hashes, offer a `--check` that verifies without launching, then call
`playtest start` with a fixed scene, session, renderer, resolution and a long
passthrough list. Three more read a project's accepted arguments, appended an
output path and the candidate's content digest, and called `launch` or
`bench cleanroom`. None of that is project logic an agent should be writing in
Python; all of it is a declaration about how this project is played.

A profile is that declaration. The kit already owns the pieces it was made of:
`manifest.verify` is the asset-hash check, `launch`/`playtest start` are the
launch, and `artifacts/candidate.json` is where the content digest lives. This
module only resolves one file into the arguments those commands already take,
and it keeps the one rule the wrappers had no way to keep: the passthrough
values never reach a receipt.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import uuid

from .common import StudioError, digest, read_json, relative, safe_id
from .config import app_path
from .evidence import inventory

PROFILE_KIND = "launch-profile"
SCHEMA_VERSION = 1
COMMANDS = ("launch", "playtest")

# Exactly the fields each command's parser takes, under the names it uses. An
# unknown field is refused rather than ignored: a misspelled `passthrough`
# would otherwise silently launch the game without the flags it exists for.
SHARED_FIELDS = {
    "script": str,
    "results": list,
    "scrub_env": list,
    "passthrough": list,
    "identity_manifest": str,
    "feature_flags": list,
}
COMMAND_FIELDS = {
    "launch": {"mode": str, "timeout": (int, float), "scope": str, **SHARED_FIELDS},
    "playtest": {
        "session": str, "scene": str, "rendering_method": str, "resolution": str,
        "max_minutes": (int, float), **SHARED_FIELDS,
    },
}
LIST_FIELDS = ("results", "scrub_env", "passthrough", "feature_flags")
# Free-text keys a profile may carry for whoever reads it; never resolved.
COMMENT_FIELDS = ("$comment", "description")

LABEL = "{label}"
CONTENT_DIGEST = "{content_digest}"
PROJECT = "{project}"
PLACEHOLDERS = (LABEL, CONTENT_DIGEST, PROJECT)
CANDIDATE_RECORD = "artifacts/candidate.json"


def _profile_path(root, path):
    """The profile file, which belongs to the project it describes.

    Recorded project-relative in the receipt, so the profile has to be inside
    the project; a profile kept somewhere else could not be named in a receipt
    without naming a host path.
    """
    root = Path(root).resolve()
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise StudioError(
                "A launch profile belongs to the project it describes; "
                "name it with a project-relative path"
            )
        return resolved
    return relative(root, str(candidate).replace("\\", "/"))


def load(root, path):
    """Read and fully validate one profile; return (record, file record).

    The bytes are read once, so the recorded hash and the resolved fields can
    never describe two different files.
    """
    profile_path = _profile_path(root, path)
    try:
        raw = profile_path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"Cannot read JSON record: {profile_path.name}") from exc
    if not isinstance(record, dict) or record.get("kind") != PROFILE_KIND:
        raise StudioError(f'Expected a {PROFILE_KIND} record')
    if record.get("schema_version") != SCHEMA_VERSION:
        raise StudioError(f"Launch profile schema_version must be {SCHEMA_VERSION}")
    command = record.get("command")
    if command not in COMMANDS:
        raise StudioError('Launch profile command must be "launch" or "playtest"')
    allowed = COMMAND_FIELDS[command]
    for name, value in record.items():
        if name in ("schema_version", "kind", "command") or name in COMMENT_FIELDS:
            continue
        if name not in allowed:
            other = next((c for c in COMMANDS if name in COMMAND_FIELDS[c]), None)
            raise StudioError(
                f'Launch profile field "{name}" is not a {command} field'
                + (f"; it belongs to {other}" if other else "")
            )
        if not isinstance(value, allowed[name]) or isinstance(value, bool):
            raise StudioError(f'Launch profile field "{name}" has the wrong type')
        if name in LIST_FIELDS and not all(isinstance(item, str) and item for item in value):
            raise StudioError(f'Launch profile field "{name}" must be a list of nonempty strings')
        if allowed[name] is str and not value.strip():
            raise StudioError(f'Launch profile field "{name}" must be a nonempty string')
    file_record = {
        "path": Path(profile_path).resolve().relative_to(Path(root).resolve()).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return record, file_record


def candidate_digests(root):
    """The candidate record's stored content digest and the project's actual one.

    A stored digest is a claim about files, and the files move. Substituting
    one into a launch without re-reading the project would hand the engine, and
    then whatever reads its output, the identity of a build that no longer
    exists -- which is precisely the confusion the digest was added to prevent.
    Both numbers are computed the same way `new_candidate` computes the stored
    one, so they are comparable rather than merely similar.
    """
    path = Path(root) / CANDIDATE_RECORD
    if not path.is_file():
        raise StudioError(
            f"This profile substitutes {CONTENT_DIGEST}, which comes from "
            f"{CANDIDATE_RECORD}; run `studio candidate new` first"
        )
    record = read_json(path)
    stored = record.get("content_digest") if isinstance(record, dict) else None
    if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
        raise StudioError(
            f"{CANDIDATE_RECORD} has no content_digest of 64 lowercase hexadecimal "
            f"characters, so {CONTENT_DIGEST} has nothing to substitute; "
            "run `studio candidate new`"
        )
    return stored, digest(inventory(root))


def substitute(values, *, root, label, project=None, content_digest=None):
    """Replace the three declared placeholders in a passthrough list.

    Literal replacement, not `str.format`: a passthrough argument may legally
    contain braces of its own, so only the three declared tokens are touched.

    `project` is the host-mapped spelling of the project root -- the same one
    the launcher hands the engine through `--path`. A Windows engine driven
    from WSL cannot open `/home/...`, so substituting the raw root would have
    produced a passthrough path the game could not read while the engine's own
    `--path` beside it was translated.
    """
    replacements = ((LABEL, label),
                    (PROJECT, project if project is not None else str(Path(root).resolve())),
                    (CONTENT_DIGEST, content_digest))
    resolved = []
    for item in values:
        for token, value in replacements:
            if value is not None:
                item = item.replace(token, value)
        resolved.append(item)
    return resolved


def _identity(root, record, config):
    """Verify the profile's identity manifest, or report that it declared none."""
    from .manifest import verify

    declared = record.get("identity_manifest")
    if not declared:
        return {"declared": False, "verdict": "not_declared", "ok": True}
    result = verify(root, relative(root, declared), config=config)
    return {
        "declared": True,
        "manifest": declared,
        "verdict": result["verdict"],
        "totals": result["totals"],
        "receipt": Path(result["receipt"]).resolve().relative_to(Path(root).resolve()).as_posix(),
        "ok": result["verdict"] == "match",
    }


def resolve(config, root, command, overrides, *, path, label=None, check=False):
    """Turn one profile plus the explicit CLI flags into command arguments.

    Returns a dict with either `refused` (an `identity_mismatch` verdict, or a
    `--check` report) or `arguments` and `receipt`. Explicit CLI flags win over
    the profile: the profile is the project's default way to play, not a lock.
    """
    root = Path(root).resolve()
    record, file_record = load(root, path)
    if record["command"] != command:
        raise StudioError(
            f'This profile is a {record["command"]} profile; run it with `studio {record["command"]}`'
        )
    # A label is resolved here rather than inside the launcher, because
    # `{label}` has to name the run directory the receipts are actually in.
    label = safe_id(label) if label else uuid.uuid4().hex
    identity = _identity(root, record, config)
    fields = {name: value for name, value in record.items() if name in COMMAND_FIELDS[command]}
    fields.pop("identity_manifest", None)
    feature_flags = fields.pop("feature_flags", [])
    for name, value in overrides.items():
        # Only a flag the caller actually typed overrides the profile: argparse
        # leaves everything else None, and an empty --result/--scrub-env list
        # is the parser's own default rather than a caller's choice.
        if value is not None and value != []:
            fields[name] = value
    passthrough = list(fields.pop("passthrough", [])) + list(feature_flags)
    # Resolved before the receipt is built, so a stale candidate refuses with
    # the profile named in the refusal like every other verdict here.
    stored = actual = None
    if any(CONTENT_DIGEST in item for item in passthrough):
        stored, actual = candidate_digests(root)
    passthrough = substitute(
        passthrough, root=root, label=label,
        # The same translation `launch` applies to `--path`, so a profile's
        # own paths and the engine's project root agree on one host spelling.
        project=app_path(config, root, "godot"),
        content_digest=stored,
    )
    if passthrough and passthrough[0] != "--":
        # Godot exposes only arguments after `--` through
        # OS.get_cmdline_user_args(), so the separator itself must reach it.
        passthrough = ["--", *passthrough]
    receipt = {
        "launch_profile": {
            "path": file_record["path"],
            "sha256": file_record["sha256"],
            "command": command,
            "identity_verdict": identity["verdict"],
            "identity_receipt": identity.get("receipt"),
        }
    }
    if stored is not None and stored != actual:
        return {"refused": {
            "schema_version": 1,
            "kind": "launch-profile-refusal",
            "verdict": "candidate_stale",
            "ok": False,
            "command": command,
            "launched": False,
            **receipt,
            "candidate": {
                "record": CANDIDATE_RECORD,
                "recorded_content_digest": stored,
                "current_content_digest": actual,
            },
            "failure": (
                f"This profile substitutes {CONTENT_DIGEST} from {CANDIDATE_RECORD}, "
                "but the project's files no longer hash to the digest that record "
                "stores; run `studio candidate new` before launching so the engine "
                "is handed the identity of the build it is actually running"
            ),
        }}
    if not identity["ok"]:
        return {"refused": {
            "schema_version": 1,
            "kind": "launch-profile-refusal",
            "verdict": "identity_mismatch",
            "ok": False,
            "command": command,
            "launched": False,
            **receipt,
            "identity": {
                key: identity[key] for key in ("manifest", "verdict", "totals", "receipt")
            },
            "failure": (
                "The identity manifest this profile declares did not verify, so "
                "nothing was launched; the items are listed in the identity receipt"
            ),
        }}
    if check:
        return {"refused": {
            "schema_version": 1,
            "kind": "launch-profile-check",
            "verdict": "checked",
            "ok": True,
            "command": command,
            "launched": False,
            **receipt,
            "identity": {
                key: identity[key] for key in ("declared", "verdict", "totals", "receipt")
                if key in identity
            },
            # Counts and field names only. A passthrough value is exactly what
            # `--check` must not print: it is the reason the receipts never
            # carry one either.
            "resolved_fields": sorted(fields),
            "passthrough_count": len(passthrough) - (1 if passthrough[:1] == ["--"] else 0),
        }}
    fields["passthrough"] = passthrough
    fields["label"] = label
    return {"arguments": fields, "receipt": receipt, "identity": identity}
