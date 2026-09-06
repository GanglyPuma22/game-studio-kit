"""Execute a user-verified Gaea build recipe, never invent a graph API."""

from pathlib import Path
from ..common import StudioError, sha256, write_json
from ..config import require_executable, app_path
from ..processes import run


def build(config, recipe, root):
    root = Path(root)
    required = (
        "version",
        "entitlement_confirmed",
        "ui_build_verified",
        "graph",
        "graph_sha256",
        "arguments",
        "outputs",
        "variables",
    )
    if (
        any(k not in recipe for k in required)
        or recipe["entitlement_confirmed"] is not True
        or recipe["ui_build_verified"] is not True
    ):
        raise StudioError(
            "Gaea needs an entitled installation and a UI-verified graph/command recipe"
        )
    if not isinstance(recipe["variables"], dict) or {"graph", "output"}.intersection(
        recipe["variables"]
    ):
        raise StudioError(
            "Gaea variables must be an object; graph and output are reserved names"
        )
    graph = Path(recipe["graph"]).resolve()
    if not graph.is_file() or sha256(graph) != recipe["graph_sha256"]:
        raise StudioError("Gaea graph missing or changed since UI verification")
    if not isinstance(recipe["arguments"], list) or not recipe["outputs"]:
        raise StudioError("Gaea recipe needs argument array and expected output files")
    execution_mode = recipe.get("execution_mode", "native")
    if execution_mode not in ("native", "unattended"):
        raise StudioError("Gaea execution_mode must be native or unattended")
    if execution_mode == "unattended" and recipe.get("unattended_verified") is not True:
        raise StudioError("Gaea unattended execution needs separate host verification")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise StudioError(
            "Gaea build needs an empty output directory to prevent stale-output success"
        )
    substitutions = {
        "graph": app_path(config, graph, "gaea"),
        "output": app_path(config, root, "gaea"),
    }
    substitutions.update({str(k): str(v) for k, v in recipe["variables"].items()})
    try:
        args = [arg.format_map(substitutions) for arg in recipe["arguments"]]
    except (KeyError, ValueError):
        raise StudioError("Gaea recipe contains an undeclared substitution") from None
    result = run(
        [require_executable(config, "gaea"), *args],
        timeout=config["timeout"],
        log=root / "gaea-build.log",
        hide_window=execution_mode == "unattended",
    )
    from ..common import relative, file_record

    outputs = []
    for name in recipe["outputs"]:
        path = relative(root, name)
        if not path.is_file() or path.stat().st_size == 0:
            raise StudioError("Gaea expected output missing: " + name)
        outputs.append(file_record(root, path))
    record = {
        "schema_version": 1,
        "status": "built",
        "version": recipe["version"],
        "execution_mode": execution_mode,
        "unattended_verified": recipe.get("unattended_verified") is True,
        "graph_sha256": recipe["graph_sha256"],
        "variables": recipe["variables"],
        "outputs": outputs,
        "elapsed_seconds": result["elapsed_seconds"],
        "terrain_contract": "required",
        "visual_verdict": "not_run",
    }
    write_json(root / "gaea-result.json", record)
    return record
