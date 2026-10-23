"""Find, fetch and track openly licensed assets and textures.

Every fetched or added file lands in one project ledger with its source page,
licence, author, retrieval date, download URL and SHA-256, so a library can be
rebuilt byte for byte, credits can be generated, and each entry can be pasted
into an asset record's `provenance.base` or `provenance.texture_bases`.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .common import StudioError, outside_package, read_json, relative, safe_id, sha256, write_json
from .records import BASE_LICENCES, normalise_licence

CATALOG = Path(__file__).resolve().parents[1] / "skills/studio-assets/references/sources.json"
DEFAULT_LIBRARY = "assets/third_party"
LEDGER_NAME = "ledger.json"
# Named so a site owner can group our requests (Poly Haven's API terms ask for
# this) and browser-like so plain CDNs do not treat the helper as a bad bot.
USER_AGENT = ("Mozilla/5.0 (compatible; game-studio-kit-assets/1; "
              "+https://github.com/GanglyPuma22/game-studio-kit)")
POLYHAVEN_MAPS = ("Diffuse", "nor_gl", "Rough", "AO", "Displacement", "arm")

# Replaced in tests; no test reaches the network.
_urlopen = urllib.request.urlopen


def catalog(kind=None):
    data = read_json(CATALOG)
    sources = data["sources"]
    if kind:
        sources = [s for s in sources if kind in s["kinds"]]
    return {"ok": True, "checked_at": data["checked_at"], "checked_from": data["checked_from"],
            "route_meanings": data["route_meanings"], "sources": sources}


def _source(source_id):
    for s in read_json(CATALOG)["sources"]:
        if s["id"] == source_id:
            return s
    raise StudioError("Unknown source " + repr(source_id) + "; see `studio assets sources`")


def _https(url):
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme != "https":
        raise StudioError("Asset URLs must use HTTPS")
    return url


def _request(url, referer=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.8"}
    if referer:
        headers["Referer"] = _https(referer)
    return urllib.request.Request(_https(url), headers=headers)


def _get_json(url):
    try:
        with _urlopen(_request(url), timeout=60) as response:
            return json.loads(response.read(32 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise StudioError(f"Source answered HTTP {exc.code} for {urllib.parse.urlsplit(url).netloc}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise StudioError("Source unreachable or returned invalid JSON: "
                          + urllib.parse.urlsplit(url).netloc) from exc


def _dest(root, lib, *parts):
    """A download target, checked as a whole against the project root.

    Every intermediate folder is resolved, so a symlinked source or asset
    folder that points outside the project (or into the kit) is refused
    before anything is written.
    """
    name = Path(lib.relative_to(root), *parts).as_posix()
    target = relative(root, name)
    if not target.is_relative_to(lib):
        raise StudioError("Download target escapes the library folder")
    return outside_package(target, "Asset download")


def _download(url, target, max_bytes, referer=None, md5=None):
    """Stream to a temporary file beside the target, then rename it into place."""
    tmp, got = _stage(url, target, max_bytes, referer, md5)
    os.replace(tmp, target)
    return got


def _commit(staged):
    """Replace every target only once all of a fetch's files arrived intact."""
    for tmp, target in staged:
        os.replace(tmp, target)


def _discard(staged):
    for tmp, _ in staged:
        Path(tmp).unlink(missing_ok=True)


def _stage(url, target, max_bytes, referer=None, md5=None):
    """Download to a temporary file beside the target; the caller renames it."""
    max_bytes = max_bytes or 1024 * 1024 * 1024
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    digest, check, size, kept = hashlib.sha256(), hashlib.md5(), 0, None
    try:
        with os.fdopen(fd, "wb") as out, _urlopen(_request(url, referer), timeout=120) as response:
            kind = (response.headers.get("Content-Type") or "").lower()
            if kind.startswith("text/html"):
                raise StudioError("Download returned a web page, not a file: "
                                  + urllib.parse.urlsplit(url).netloc
                                  + " (a login wall, challenge or missing referer)")
            declared = response.headers.get("Content-Length")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise StudioError(f"Download exceeded --max-mb ({max_bytes // (1024 * 1024)} MB)")
                digest.update(chunk)
                check.update(chunk)
                out.write(chunk)
            if declared and size != int(declared):
                raise StudioError("Incomplete download; nothing was kept")
        if md5 and check.hexdigest() != md5:
            raise StudioError("Downloaded file does not match the source's md5; nothing was kept")
        kept = tmp
    except urllib.error.HTTPError as exc:
        raise StudioError(f"Source answered HTTP {exc.code} for {urllib.parse.urlsplit(url).netloc}")
    except urllib.error.URLError as exc:
        raise StudioError("Source unreachable: " + urllib.parse.urlsplit(url).netloc) from exc
    finally:
        if kept is None:
            Path(tmp).unlink(missing_ok=True)
    return kept, {"sha256": digest.hexdigest(), "bytes": size}


def _paths(root, library):
    # The whole library, ledger included, must sit outside the installed kit.
    lib = outside_package(relative(root, library or DEFAULT_LIBRARY), "Asset library")
    return lib, outside_package(lib / LEDGER_NAME, "Asset ledger")


def _load_ledger(ledger):
    if not ledger.is_file():
        return {"schema_version": 1, "kind": "asset-ledger", "assets": []}
    data = read_json(ledger)
    if data.get("kind") != "asset-ledger" or not isinstance(data.get("assets"), list):
        raise StudioError("Not an asset ledger: " + ledger.name)
    return data


def _checked_licence(licence, attribution):
    value = normalise_licence(licence)
    if value not in BASE_LICENCES:
        raise StudioError("Licence " + repr(licence) + " is not reusable; allowed: "
                          + ", ".join(sorted(BASE_LICENCES))
                          + ". NonCommercial, NoDerivatives, ShareAlike, GPL and unclear licences are refused")
    if value.startswith("CC-BY") and not (attribution or "").strip():
        raise StudioError("A CC-BY licence needs --attribution with the exact credit text")
    return value


def _today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _compatible(ledger_path, asset_id, page, licence):
    """Refuse, before anything is downloaded, an id already holding another rights record."""
    for old in _load_ledger(ledger_path)["assets"]:
        if old["asset_id"] == asset_id and (old["page_url"], old["licence"]) != (page, licence):
            # One entry carries one rights record; never let a second
            # page's licence or attribution overwrite the first one's.
            raise StudioError("Ledger already has " + asset_id + " from " + old["page_url"]
                              + " under " + old["licence"] + "; pass a distinct --id")


def _record(root, ledger_path, entry):
    _compatible(ledger_path, entry["asset_id"], entry["page_url"], entry["licence"])
    ledger = _load_ledger(ledger_path)
    # Another resolution, map set or variant of the same asset adds files;
    # files fetched earlier stay recorded so verify and restore still cover them.
    # Older files keep their place and come first, so restore replays
    # extraction in the order the fetches happened.
    fetched = entry["files"]
    new_paths = {f["path"] for f in fetched}
    for old in ledger["assets"]:
        if old["asset_id"] == entry["asset_id"]:
            entry["files"] = [f for f in old["files"] if f["path"] not in new_paths] + fetched
    ledger["assets"] = [a for a in ledger["assets"] if a["asset_id"] != entry["asset_id"]]
    ledger["assets"].append(entry)
    ledger["assets"].sort(key=lambda a: a["asset_id"])
    write_json(ledger_path, ledger)
    first = fetched[0]
    return {
        "ok": True,
        "asset_id": entry["asset_id"],
        "licence": entry["licence"],
        "files": fetched,
        "ledger": ledger_path.relative_to(root).as_posix(),
        # Paste into an asset record; validate-record checks the same rules.
        "provenance": {
            "source_url": entry["page_url"], "licence": entry["licence"], "author": entry["author"],
            "attribution": entry["attribution"], "retrieved_at": entry["retrieved_at"],
            "file": {"path": first["path"], "sha256": first["sha256"]},
        },
    }


def _entry(source, asset_id, title, page, licence, author, attribution, refetchable, files, extra=None):
    entry = {
        "asset_id": asset_id, "source": source, "title": title, "page_url": _https(page),
        "licence": licence, "author": author or "", "attribution": attribution or None,
        "retrieved_at": _today(), "retrieved_on": platform.node() or "unknown host",
        "refetchable": refetchable, "files": files,
    }
    for f in files:
        # Download settings live on each file: a later fetch into the same
        # entry must not change how an earlier file is restored.
        f["refetchable"] = refetchable
    entry.update(extra or {})
    return entry


def search(source, query, kind=None, limit=10):
    q = urllib.parse.quote(query)
    if source == "polyhaven":
        t = {"textures": "textures", "models": "models", "hdris": "hdris"}.get(kind or "textures")
        if t is None:
            raise StudioError("polyhaven kinds are textures, models and hdris")
        data = _get_json(f"https://api.polyhaven.com/search?q={q}&t={t}")
        hits = [{"id": r["slug"], "page_url": "https://polyhaven.com/a/" + r["slug"]}
                for r in data.get("results", [])[:limit]]
    elif source == "ambientcg":
        kinds = {"textures": "Material", "models": "3DModel", "hdris": "HDRI", "decals": "Decal"}
        t = kinds.get(kind or "textures")
        if t is None:
            raise StudioError("ambientcg kinds are " + ", ".join(kinds))
        data = _get_json(f"https://ambientcg.com/api/v2/full_json?q={q}&type={t}&limit={int(limit)}"
                         "&include=downloadData")
        hits = []
        for a in data.get("foundAssets", [])[:limit]:
            zips = a.get("downloadFolders", {}).get("default", {}).get(
                "downloadFiletypeCategories", {}).get("zip", {}).get("downloads", [])
            hits.append({"id": a["assetId"], "page_url": "https://ambientcg.com/a/" + a["assetId"],
                         "variants": [z["attribute"] for z in zips]})
    else:
        raise StudioError("search covers polyhaven and ambientcg; for other sources browse the site "
                          "(see `studio assets sources`) and fetch with --source url")
    return {"ok": True, "source": source, "query": query, "results": hits}


def fetch_polyhaven(root, library, asset, resolution="1k", fmt="jpg", maps=None, max_bytes=None):
    safe_id(asset)
    lib, ledger = _paths(root, library)
    _compatible(ledger, "polyhaven/" + asset, "https://polyhaven.com/a/" + asset, "CC0-1.0")
    info = _get_json("https://api.polyhaven.com/info/" + asset)
    files = _get_json("https://api.polyhaven.com/files/" + asset)
    kind = {0: "hdris", 1: "textures", 2: "models"}.get(info.get("type"))
    wanted = []  # (relative name, url, md5)
    if kind == "hdris":
        item = files.get("hdri", {}).get(resolution, {}).get(fmt if fmt in ("hdr", "exr") else "hdr")
        if not item:
            raise StudioError("No HDRI at that resolution/format")
        wanted.append((Path(item["url"]).name, item["url"], item.get("md5")))
    elif kind == "models":
        item = files.get("gltf", {}).get(resolution, {}).get("gltf")
        if not item:
            raise StudioError("No glTF at that resolution; available: " + ", ".join(files.get("gltf", {})))
        wanted.append((Path(item["url"]).name, item["url"], item.get("md5")))
        for name, inc in sorted(item.get("include", {}).items()):
            wanted.append((name, inc["url"], inc.get("md5")))
    elif kind == "textures":
        for m in maps or POLYHAVEN_MAPS:
            item = files.get(m, {}).get(resolution, {}).get(fmt)
            if item:
                wanted.append((Path(item["url"]).name, item["url"], item.get("md5")))
        if not wanted:
            raise StudioError("No maps at that resolution/format; maps offered: "
                              + ", ".join(k for k in files if k not in ("blend", "gltf", "mtlx", "usd", "fbx")))
    else:
        raise StudioError("Unknown Poly Haven asset type")
    recorded, staged = [], []
    try:
        for name, url, md5 in wanted:
            target = _dest(root, lib, "polyhaven", asset, resolution, name)
            tmp, got = _stage(url, target, max_bytes, md5=md5)
            staged.append((tmp, target))
            recorded.append({"path": target.relative_to(root).as_posix(), "url": url, **got})
    except BaseException:
        _discard(staged)
        raise
    _commit(staged)
    return _record(root, ledger, _entry(
        "polyhaven", "polyhaven/" + asset, info.get("name", asset), "https://polyhaven.com/a/" + asset,
        "CC0-1.0", ", ".join(info.get("authors", {})), None, True, recorded,
        {"kind": kind, "resolution": resolution}))


def fetch_ambientcg(root, library, asset, resolution="1K", fmt="JPG", max_bytes=None, extract=False):
    safe_id(asset)
    lib, ledger = _paths(root, library)
    _compatible(ledger, "ambientcg/" + asset, "https://ambientcg.com/a/" + asset, "CC0-1.0")
    data = _get_json(f"https://ambientcg.com/api/v2/full_json?id={asset}&include=downloadData")
    found = [a for a in data.get("foundAssets", []) if a.get("assetId") == asset]
    if not found:
        raise StudioError("ambientCG has no asset " + repr(asset))
    zips = found[0].get("downloadFolders", {}).get("default", {}).get(
        "downloadFiletypeCategories", {}).get("zip", {}).get("downloads", [])
    attribute = f"{resolution}-{fmt}"
    match = [z for z in zips if z.get("attribute") == attribute]
    if not match:
        raise StudioError("No " + attribute + " download; offered: " + ", ".join(z["attribute"] for z in zips))
    url = match[0]["fullDownloadPath"]
    target = _dest(root, lib, "ambientcg", asset, Path(match[0].get("fileName") or f"{asset}_{attribute}.zip").name)
    tmp, got = _stage(url, target, max_bytes)
    if extract:
        try:
            _extract(root, Path(tmp), target.parent, check_only=True)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    os.replace(tmp, target)
    record = {"path": target.relative_to(root).as_posix(), "url": url, **got}
    if extract:
        record["extracted_to"] = _extract(root, target)
    return _record(root, ledger, _entry(
        "ambientcg", "ambientcg/" + asset, found[0].get("displayName", asset),
        "https://ambientcg.com/a/" + asset, "CC0-1.0", "ambientCG (Lennart Demes)", None, True,
        [record], {"kind": found[0].get("dataType"), "resolution": attribute}))


def _site_licence(source, licence):
    """A site-wide CC0 source may omit --licence; a per-asset source may not."""
    if source and source != "url":
        s = _source(source)
        if s["licence_scope"] == "site":
            if licence and normalise_licence(licence) != s["licence"]:
                raise StudioError(s["name"] + " publishes everything as " + s["licence"]
                                  + "; a different --licence means the page and catalogue disagree, skip it")
            return s["licence"]
    if not licence:
        raise StudioError("--licence is required: copy it from the asset page")
    return licence


def fetch_url(root, library, url, page, licence, author, attribution=None, title=None, asset=None,
              source="url", referer=None, refetchable=True, extract=False, max_bytes=None):
    lib, ledger = _paths(root, library)
    licence = _checked_licence(_site_licence(source, licence), attribution)
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(_https(url)).path)).name
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    name = (query.get("dn") or [name])[0] or "download.bin"
    asset = safe_id(asset or Path(name).stem.replace(".", "-").replace(" ", "-")[:100])
    group = safe_id(source if source != "url" else "web")
    _compatible(ledger, f"{group}/{asset}", _https(page), licence)
    target = _dest(root, lib, group, asset, Path(name).name)
    tmp, got = _stage(url, target, max_bytes, referer=referer)
    files = [{"path": target.relative_to(root).as_posix(), "url": url, **got}]
    extra = {"referer": referer} if referer else {}
    if referer:
        files[0]["referer"] = referer
    if extract:
        try:
            # Checked while still staged, so a bad refresh keeps the old archive.
            _extract(root, Path(tmp), target.parent, check_only=True)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    os.replace(tmp, target)
    if extract:
        files[0]["extracted_to"] = _extract(root, target)
    return _record(root, ledger, _entry(group, f"{group}/{asset}", title or asset, page, licence, author,
                                        attribution, refetchable, files, extra))


def add_file(root, library, file, page, licence, author, attribution=None, title=None, asset=None,
             source="manual", url=None):
    """Record a file a person downloaded (login walls, challenges)."""
    lib, ledger = _paths(root, library)
    licence = _checked_licence(_site_licence(source if source != "manual" else None, licence), attribution)
    path = relative(root, file)
    if not path.is_file():
        raise StudioError("Missing file: " + file)
    if not path.is_relative_to(lib):
        raise StudioError("Keep library files under " + lib.relative_to(root).as_posix())
    group = safe_id(source)
    asset = safe_id(asset or path.stem.replace(".", "-").replace(" ", "-")[:100])
    files = [{"path": path.relative_to(root).as_posix(), "url": _https(url) if url else None,
              "sha256": sha256(path), "bytes": path.stat().st_size}]
    return _record(root, ledger, _entry(group, f"{group}/{asset}", title or asset, page, licence, author,
                                        attribution, bool(url), files))


def _extract(root, archive, folder=None, check_only=False, limit=4 * 1024 * 1024 * 1024):
    if not zipfile.is_zipfile(archive):
        raise StudioError("--extract needs a zip archive")
    base = ((folder or archive.parent) / "extracted").relative_to(root).as_posix()
    dest = outside_package(relative(root, base), "Extraction")
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if sum(m.file_size for m in members) > limit:
            raise StudioError("Archive expands beyond 4 GB; refusing to extract")
        for m in members:
            # Rejects absolute, escaping and symlink-redirected names.
            outside_package(relative(root, base + "/" + (m.filename.rstrip("/") or ".")), "Extraction")
        if check_only:
            return base
        z.extractall(dest)
    return dest.relative_to(root).as_posix()


def verify(root, library, restore=False, max_bytes=None):
    lib, ledger_path = _paths(root, library)
    ledger = _load_ledger(ledger_path)
    report = {"ok": True, "checked": 0, "missing": [], "mismatched": [], "restored": [], "unrestorable": []}
    for entry in ledger["assets"]:
        for f in entry["files"]:
            report["checked"] += 1
            p = outside_package(relative(root, f["path"]), "Restored file")
            if p.is_file():
                if sha256(p) != f["sha256"]:
                    report["mismatched"].append(f["path"])
                continue
            if restore and f.get("refetchable", entry.get("refetchable")) and f.get("url"):
                got = _download(f["url"], p, max_bytes, referer=f.get("referer", entry.get("referer")))
                if got["sha256"] != f["sha256"]:
                    p.unlink()
                    report["mismatched"].append(f["path"] + " (source changed since it was recorded)")
                else:
                    report["restored"].append(f["path"])
            elif restore:
                report["unrestorable"].append(f["path"])
            else:
                report["missing"].append(f["path"])
        # Every archive that was unpacked into a now-missing folder is replayed.
        folders = {}
        for f in entry["files"]:
            if f.get("extracted_to"):
                folders.setdefault(f["extracted_to"], []).append(f)
        for folder, archives in sorted(folders.items()):
            if relative(root, folder).is_dir():
                continue
            intact = all(relative(root, f["path"]).is_file()
                         and sha256(relative(root, f["path"])) == f["sha256"] for f in archives)
            if restore and intact:
                for f in archives:
                    _extract(root, relative(root, f["path"]))
                report["restored"].append(folder)
            else:
                report["missing"].append(folder)
    report["ok"] = not (report["missing"] or report["mismatched"] or report["unrestorable"])
    return report


def credits(root, library, output):
    _, ledger_path = _paths(root, library)
    ledger = _load_ledger(ledger_path)
    required, courtesy = [], []
    for a in ledger["assets"]:
        if a["licence"].startswith("CC-BY"):
            required.append(f"- {a['attribution']} ({a['page_url']})")
        else:
            by = f" by {a['author']}" if a.get("author") else ""
            courtesy.append(f"- {a['title']}{by}, {a['licence']} ({a['page_url']})")
    lines = ["# Third-party asset credits", "",
             "Generated by `studio assets credits` from " + ledger_path.relative_to(root).as_posix() + ".", ""]
    lines += ["## Attribution required (CC-BY)", ""] + (required or ["- none"]) + [""]
    lines += ["## Public domain (CC0), credited as a courtesy", ""] + (courtesy or ["- none"]) + [""]
    target = outside_package(relative(root, output), "Credits output")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "output": output, "attribution_required": len(required), "cc0": len(courtesy)}
