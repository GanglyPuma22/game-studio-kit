"""Lay a character's texture coordinates out again so the layout can hold paint.

A template the game project copies into its own tools and runs with
`studio blender run`:

    python <KIT>/scripts/studio.py blender run --project <GAME> \
        --source source/body.blend --script tools/texture_relayout.py \
        --label body-relayout --result source/body-relayout.blend \
        --result artifacts/relayout/body.json --config <HOST> -- \
        --save source/body-relayout.blend --report artifacts/relayout/body.json

What it does, in order:

1. Welds each chosen mesh by position on a working copy, so the split
   vertices an exporter leaves along old seams do not become new seams.
2. Cuts the surface into charts by body part (the vertex group each face
   mostly follows, or the object when there are no groups), by material, and
   by the side the face looks toward, with normals smoothed over the surface
   first.
3. Merges small charts into the neighbour they share the longest border with,
   but never onto a chart that faces the other way or has another material:
   two materials are painted by different rules, and one stray face of the
   wrong one shows as a patch.
4. Unwraps along the chart borders (minimum stretch where this Blender has
   it, from 4.3; angle based before), gives every island the same scale, and
   packs all chosen objects into one map.
5. Writes the result to a new layer on the original meshes. Vertices, normals,
   weights and the old layer are untouched; the new layer becomes the one that
   renders.
6. Optionally carries an existing colour map across to the new layout.

The report holds island count, map use and surface per unit of layout before
and after (`studio blender inspect` measures the exported file the same way),
and two counts at the map size given by --size: `thin_triangles`, flattened
to under half a texel across, where a line drawn beside one floods it, and
`overlap_texels`, texels that lie under two faces.

Options after `--`:
    --save PATH          .blend to write (required; never the source)
    --report PATH        JSON report (required)
    --object NAME        mesh object to lay out; repeat. Default: every mesh
    --thin NAME          object or vertex group that is thin blades (a mane,
                         a cape): cut by raw normals and keep small charts
    --min-share F        charts under this share of the surface merge (0.004)
    --min-faces N        charts under this many triangles merge (60)
    --smooth N           normal smoothing passes (12)
    --margin F           gap between islands as a fraction of the map (0.004)
    --unwrap METHOD      auto (default), stretch or angle
    --size N             map width in texels the report counts against (2048)
    --layer NAME         name of the new layer ("relayout")
    --carry SRC --carry-out PNG
                         bake image SRC from the old layout to the new one,
                         at --size
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import numpy as np


def options():
    parser = argparse.ArgumentParser(prog="texture-relayout")
    parser.add_argument("--save", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--object", action="append", default=[])
    parser.add_argument("--thin", action="append", default=[])
    parser.add_argument("--min-share", type=float, default=0.004)
    parser.add_argument("--min-faces", type=int, default=60)
    parser.add_argument("--smooth", type=int, default=12)
    parser.add_argument("--margin", type=float, default=0.004)
    parser.add_argument("--layer", default="relayout")
    parser.add_argument("--unwrap", choices=("auto", "stretch", "angle"), default="auto")
    parser.add_argument("--carry")
    parser.add_argument("--carry-out")
    parser.add_argument("--size", type=int, default=2048)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


# ---------------------------------------------------------------------------
# Reading the meshes


def triangulate(obj):
    import bmesh

    work = bmesh.new()
    work.from_mesh(obj.data)
    bmesh.ops.triangulate(work, faces=[f for f in work.faces if len(f.verts) > 3])
    work.to_mesh(obj.data)
    work.free()
    obj.data.update()


def read(obj, part_base, thin_names, paints):
    """World positions, triangles, each triangle's part, paint and thinness."""
    mesh = obj.data
    count = len(mesh.vertices)
    points = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", points)
    world = np.array(obj.matrix_world, dtype=np.float64)
    points = points.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
    faces = np.empty(len(mesh.polygons) * 3, dtype=np.int64)
    mesh.polygons.foreach_get("vertices", faces)
    faces = faces.reshape(-1, 3)
    strongest = np.zeros(count, dtype=np.int64)
    for vertex in mesh.vertices:
        if vertex.groups:
            strongest[vertex.index] = 1 + max(vertex.groups, key=lambda g: g.weight).group
    corner = strongest[faces]
    part = np.where(corner[:, 1] == corner[:, 2], corner[:, 1], corner[:, 0])
    thin_groups = {1 + g.index for g in obj.vertex_groups if g.name in thin_names}
    thin = np.isin(part, list(thin_groups)) if thin_groups else np.zeros(len(faces), dtype=bool)
    if obj.name in thin_names:
        thin[:] = True
    names = ["(none)"] + [g.name for g in obj.vertex_groups]
    # What a face is painted as: its material, or the object when it has none.
    slot = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("material_index", slot)
    keys = [m.name if m else None for m in mesh.materials] or [None]
    ids = np.array([
        paints.setdefault(("material", k) if k else ("object", obj.name), len(paints)) for k in keys
    ])
    paint = ids[np.clip(slot, 0, len(ids) - 1)]
    return points, faces, part + part_base, thin, paint, [f"{obj.name}/{n}" for n in names]


def weld(points):
    span = float(np.ptp(points, axis=0).max()) or 1.0
    steps = np.round(points / (span * 1e-6)).astype(np.int64)
    _, first, inverse = np.unique(steps, axis=0, return_index=True, return_inverse=True)
    return points[first], np.asarray(inverse).reshape(-1)


# ---------------------------------------------------------------------------
# Charts


def face_pairs(faces):
    """Pairs of triangles that share an edge, with that edge."""
    owner = np.repeat(np.arange(len(faces)), 3)
    a = faces.reshape(-1)
    b = faces[:, (1, 2, 0)].reshape(-1)
    low, high = np.minimum(a, b), np.maximum(a, b)
    key = low * (int(faces.max()) + 1) + high
    order = np.argsort(key, kind="stable")
    key, owner, low, high = key[order], owner[order], low[order], high[order]
    start = np.r_[True, key[1:] != key[:-1]]
    size = np.diff(np.r_[np.flatnonzero(start), len(key)])
    first = np.flatnonzero(start)[size == 2]          # an edge of exactly two faces
    return np.stack([owner[first], owner[first + 1]], axis=1), np.stack([low[first], high[first]], axis=1)


def components(count, pairs, joined):
    parent = np.arange(count)

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for (a, b), keep in zip(pairs.tolist(), joined.tolist()):
        if keep:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    return np.array([find(i) for i in range(count)])


def charts(points, faces, part, thin, paint, smooth, min_share, min_faces):
    corner = points[faces]
    cross = np.cross(corner[:, 1] - corner[:, 0], corner[:, 2] - corner[:, 0])
    area = 0.5 * np.linalg.norm(cross, axis=1)
    unit = lambda v: v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-20)
    normal = unit(cross)
    centre = corner.mean(axis=1)
    pairs, edges = face_pairs(faces)
    length = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    # Smooth the normals over the surface so a pitted face follows its plate.
    facing = normal * area[:, None]
    for _ in range(smooth):
        total = facing.copy()
        np.add.at(total, pairs[:, 0], facing[pairs[:, 1]])
        np.add.at(total, pairs[:, 1], facing[pairs[:, 0]])
        facing = unit(total) * area[:, None]
    facing = unit(facing)
    # The two sides of a thin blade are one face apart: smoothing would blend
    # them into a chart that cannot lie flat.
    facing[thin] = normal[thin]
    label = np.zeros(len(faces), dtype=np.int64)
    for value in np.unique(part):
        chosen = part == value
        weight = area[chosen] + 1e-12
        offset = centre[chosen] - np.average(centre[chosen], axis=0, weights=weight)
        _, axes = np.linalg.eigh((offset * weight[:, None]).T @ offset)
        local = facing[chosen] @ axes
        axis = np.abs(local).argmax(axis=1)
        sign = (local[np.arange(len(local)), axis] > 0).astype(np.int64)
        label[chosen] = int(value) * 6 + axis * 2 + sign
    label = label * (int(paint.max()) + 1) + paint
    chart = components(len(faces), pairs, label[pairs[:, 0]] == label[pairs[:, 1]])
    surface = area.sum()
    for _ in range(200):
        ids, index = np.unique(chart, return_inverse=True)
        chart_area = np.bincount(index, weights=area)
        chart_faces = np.bincount(index)
        small = (chart_area < surface * min_share) | (chart_faces < min_faces)
        mostly_thin = np.bincount(index, weights=thin.astype(float)) > 0.5 * chart_faces
        small = np.where(mostly_thin, chart_faces < 6, small)
        if not small.any():
            break
        border = defaultdict(float)
        for a, b, size in zip(index[pairs[:, 0]].tolist(), index[pairs[:, 1]].tolist(), length.tolist()):
            if a != b:
                border[(a, b)] += size
                border[(b, a)] += size
        mean = np.zeros((len(ids), 3))
        np.add.at(mean, index, facing * area[:, None])
        mean = unit(mean)
        painted = np.zeros(len(ids), dtype=np.int64)
        painted[index] = paint
        best = {}
        for (a, b), size in border.items():
            # Never fold a piece onto one that faces the other way, or onto
            # one painted by another material's rules.
            if (small[a] and painted[a] == painted[b] and mean[a] @ mean[b] > 0.1
                    and (a not in best or size > best[a][1])):
                best[a] = (b, size)
        if not best:
            break
        remap = np.arange(len(ids))
        done = set()
        for a in sorted(best, key=lambda k: chart_area[k]):
            b = best[a][0]
            if a in done or b in done:
                continue
            remap[a] = b
            done.update((a, b))
        chart = remap[index]
    _, chart = np.unique(chart, return_inverse=True)
    mixed = np.unique(np.stack([chart, paint], axis=1), axis=0)
    if len(mixed) != int(chart.max()) + 1:
        raise SystemExit("a chart holds two materials; nothing was written")
    seam = chart[pairs[:, 0]] != chart[pairs[:, 1]]
    return chart, edges[seam]


# ---------------------------------------------------------------------------
# Measuring a layout (the same definitions as `studio blender inspect`)


def overlap_texels(uvs, size):
    """Texels whose centre lies inside more than one triangle of the layout."""
    cover = np.zeros((size, size), dtype=np.uint8)
    texel = uvs * size
    low = np.clip(np.floor(texel.min(axis=1)).astype(np.int64), 0, size - 1)
    high = np.clip(np.ceil(texel.max(axis=1)).astype(np.int64), 0, size)
    for (ax, ay), (bx, by), (cx, cy), (x0, y0), (x1, y1) in zip(
        texel[:, 0].tolist(), texel[:, 1].tolist(), texel[:, 2].tolist(), low.tolist(), high.tolist()
    ):
        area = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        if x1 <= x0 or y1 <= y0 or abs(area) < 1e-12:
            continue
        x = np.arange(x0, x1) + 0.5
        y = (np.arange(y0, y1) + 0.5)[:, None]
        w0 = ((bx - ax) * (y - ay) - (x - ax) * (by - ay)) / area
        w1 = ((cx - bx) * (y - by) - (x - bx) * (cy - by)) / area
        w2 = ((ax - cx) * (y - cy) - (x - cx) * (ay - cy)) / area
        inside = (w0 > 0) & (w1 > 0) & (w2 > 0)
        block = cover[y0:y1, x0:x1]
        block[inside] = np.minimum(block[inside] + 1, 3)
    return int((cover > 1).sum())


def thin_count(uvs, size):
    """Triangles narrower than half a texel across at their thinnest."""
    texel = uvs * size
    side = np.stack([
        np.linalg.norm(texel[:, (k + 1) % 3] - texel[:, k], axis=1) for k in range(3)
    ], axis=1)
    twice = np.abs(
        (texel[:, 1, 0] - texel[:, 0, 0]) * (texel[:, 2, 1] - texel[:, 0, 1])
        - (texel[:, 2, 0] - texel[:, 0, 0]) * (texel[:, 1, 1] - texel[:, 0, 1])
    )
    return int((twice / np.maximum(side.max(axis=1), 1e-12) < 0.5).sum())


def measure(points, faces, uvs, size):
    steps = np.round(uvs * 65536).astype(np.int64)
    corners = np.concatenate([faces.reshape(-1, 1), steps.reshape(-1, 2)], axis=1)
    _, identity = np.unique(corners, axis=0, return_inverse=True)
    identity = np.asarray(identity).reshape(-1, 3).astype(np.int64)
    a, b = identity.reshape(-1), identity[:, (1, 2, 0)].reshape(-1)
    key = np.minimum(a, b) * (int(identity.max()) + 1) + np.maximum(a, b)
    order = np.argsort(key, kind="stable")
    same = key[order][1:] == key[order][:-1]
    owner = np.repeat(np.arange(len(faces)), 3)[order]
    pairs = np.stack([owner[:-1][same], owner[1:][same]], axis=1)
    roots = components(len(faces), pairs, np.ones(len(pairs), dtype=bool))
    _, sizes = np.unique(roots, return_counts=True)
    corner = points[faces]
    surface = 0.5 * np.linalg.norm(np.cross(corner[:, 1] - corner[:, 0], corner[:, 2] - corner[:, 0]), axis=1)
    layout = 0.5 * np.abs(
        (uvs[:, 1, 0] - uvs[:, 0, 0]) * (uvs[:, 2, 1] - uvs[:, 0, 1])
        - (uvs[:, 2, 0] - uvs[:, 0, 0]) * (uvs[:, 1, 1] - uvs[:, 0, 1])
    )
    mapped = (surface > 0) & (layout > 1e-14)
    scale = np.sqrt(surface[mapped] / layout[mapped])
    order = np.argsort(scale)
    running = np.cumsum(surface[mapped][order])
    at = lambda f: float(scale[order][min(np.searchsorted(running, running[-1] * f), len(order) - 1)])
    return {
        "islands": int(len(sizes)),
        "small_islands": int((sizes <= 2).sum()),
        "map_used": float(layout.sum()),
        "unmapped_triangles": int(((surface > 0) & ~mapped).sum()),
        "thin_triangles": thin_count(uvs[surface > 0], size),
        "overlap_texels": overlap_texels(uvs, size),
        "surface_per_uv_median": at(0.5) if len(scale) else None,
        "surface_per_uv_coarse": at(0.9) if len(scale) else None,
    }


def corner_index(mesh):
    """Loop index of each triangle corner, in polygon order."""
    start = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", start)
    return (start[:, None] + np.arange(3)[None, :]).reshape(-1)


def layer_uvs(obj, layer):
    mesh = obj.data
    flat = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    layer.data.foreach_get("uv", flat)
    return flat.reshape(-1, 2)[corner_index(mesh)].reshape(-1, 3, 2)


# ---------------------------------------------------------------------------


def carry(objects, old_names, new_name, source, target, size):
    """Bake the image the old layout shows onto the new layout."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    image = bpy.data.images.load(str(source))
    result = bpy.data.images.new("relayout-carry", size, size, alpha=False)
    result.colorspace_settings.name = image.colorspace_settings.name
    kept = {obj.name: list(obj.data.materials) for obj in objects}
    temporary = []
    for obj in objects:
        material = bpy.data.materials.new(f"relayout-carry-{obj.name}")
        temporary.append(material)
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        nodes.clear()
        where = nodes.new("ShaderNodeUVMap")
        where.uv_map = old_names[obj.name]
        colour = nodes.new("ShaderNodeTexImage")
        colour.image = image
        emit = nodes.new("ShaderNodeEmission")
        out = nodes.new("ShaderNodeOutputMaterial")
        dest = nodes.new("ShaderNodeTexImage")
        dest.image = result
        links.new(where.outputs["UV"], colour.inputs["Vector"])
        links.new(colour.outputs["Color"], emit.inputs["Color"])
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        nodes.active = dest
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj.data.uv_layers.active = obj.data.uv_layers[new_name]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.bake(type="EMIT", margin=max(2, size // 256), use_clear=True)
    result.filepath_raw = str(target)
    result.file_format = "PNG"
    result.save()
    # The bake materials were scaffolding: the saved file keeps its own.
    for obj in objects:
        obj.data.materials.clear()
        for material in kept[obj.name]:
            obj.data.materials.append(material)
    for material in temporary:
        bpy.data.materials.remove(material)
    bpy.data.images.remove(result)


def main():
    args = options()
    if Path(args.save).resolve() == Path(bpy.data.filepath).resolve():
        raise SystemExit("--save must not be the source file")
    if bool(args.carry) != bool(args.carry_out):
        raise SystemExit("--carry and --carry-out go together")
    wanted = set(args.object)
    objects = [
        o for o in bpy.context.scene.objects
        if o.type == "MESH" and len(o.data.polygons) and (not wanted or o.name in wanted)
    ]
    if not objects or (wanted and len(objects) != len(wanted)):
        raise SystemExit("no mesh to lay out, or an --object name was not found")
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    all_points, all_faces, all_part, all_thin, all_paint, part_names, spans = [], [], [], [], [], [], []
    paints = {}
    before, old_names = [], {}
    offset = 0
    for obj in objects:
        triangulate(obj)
        points, faces, part, thin, paint, names = read(obj, len(part_names), set(args.thin), paints)
        old = next((l for l in obj.data.uv_layers if l.active_render), obj.data.uv_layers.active)
        old_names[obj.name] = old.name if old else None
        before.append((points, faces, layer_uvs(obj, old) if old else None))
        spans.append((offset, len(points), len(faces)))
        all_points.append(points)
        all_faces.append(faces + offset)
        all_part.append(part)
        all_thin.append(thin)
        all_paint.append(paint)
        part_names += names
        offset += len(points)
    points = np.concatenate(all_points)
    faces = np.concatenate(all_faces)
    part = np.concatenate(all_part)
    thin = np.concatenate(all_thin)
    paint = np.concatenate(all_paint)

    welded_points, remap = weld(points)
    welded = remap[faces]
    good = (welded[:, 0] != welded[:, 1]) & (welded[:, 1] != welded[:, 2]) & (welded[:, 0] != welded[:, 2])
    chart, seams = charts(
        welded_points, welded[good], part[good], thin[good], paint[good],
        args.smooth, args.min_share, args.min_faces,
    )

    # A welded working copy: unwrap and pack happen here, then go back by corner.
    mesh = bpy.data.meshes.new("relayout-work")
    mesh.from_pydata(welded_points.tolist(), [], welded[good].tolist())
    mesh.update()
    work = bpy.data.objects.new("relayout-work", mesh)
    bpy.context.scene.collection.objects.link(work)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = work
    work.select_set(True)
    edge = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edge)
    edge = np.sort(edge.reshape(-1, 2), axis=1)
    base = int(edge.max()) + 1
    cut = np.isin(edge[:, 0] * base + edge[:, 1], seams[:, 0] * base + seams[:, 1])
    mesh.edges.foreach_set("use_seam", cut)
    mesh.uv_layers.new(name="relayout")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # Angle based flattens some triangles on spikes to nothing; minimum
    # stretch (Blender 4.3 and later) does not.
    known = {item.identifier for item in bpy.ops.uv.unwrap.get_rna_type().properties["method"].enum_items}
    method = {"angle": "ANGLE_BASED", "stretch": "MINIMUM_STRETCH"}.get(
        args.unwrap, "MINIMUM_STRETCH" if "MINIMUM_STRETCH" in known else "ANGLE_BASED"
    )
    if method not in known:
        raise SystemExit("--unwrap stretch needs Blender 4.3 or later")
    bpy.ops.uv.unwrap(method=method, fill_holes=True, correct_aspect=True, margin=args.margin)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, margin=args.margin, margin_method="FRACTION", shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    order = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", order)
    if not np.array_equal(order.reshape(-1, 3), welded[good]):
        raise SystemExit("the working copy reordered its corners; nothing was written")
    flat = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers["relayout"].data.foreach_get("uv", flat)
    new = np.zeros((len(faces), 3, 2))
    new[good] = flat.reshape(-1, 3, 2)
    bpy.data.objects.remove(work, do_unlink=True)
    bpy.data.meshes.remove(mesh)

    report = {
        "objects": [], "charts": int(chart.max()) + 1, "collapsed_triangles": int((~good).sum()),
        "unwrap": method, "blender": bpy.app.version_string, "map_size": args.size, "materials": len(paints),
    }
    done = 0
    for obj, (first, _, count), (own_points, own_faces, old_uvs) in zip(objects, spans, before):
        layer = obj.data.uv_layers.get(args.layer) or obj.data.uv_layers.new(name=args.layer)
        values = np.zeros((len(obj.data.loops), 2))
        values[corner_index(obj.data)] = new[done:done + count].reshape(-1, 2)
        layer.data.foreach_set("uv", values.reshape(-1))
        layer.active_render = True
        obj.data.uv_layers.active = layer
        own_welded, own_remap = weld(own_points)
        report["objects"].append({
            "name": obj.name,
            "triangles": int(count),
            "before": measure(own_welded, own_remap[own_faces], old_uvs, args.size) if old_uvs is not None else None,
            "after": measure(own_welded, own_remap[own_faces], new[done:done + count], args.size),
        })
        done += count
    report["before"] = (
        measure(welded_points, welded, np.concatenate([b[2] for b in before]), args.size)
        if all(b[2] is not None for b in before) else None
    )
    report["after"] = measure(welded_points, welded, new, args.size)
    chart_part = {}
    for value, where in zip(chart.tolist(), part[good].tolist()):
        chart_part.setdefault(value, where)
    by_part = defaultdict(int)
    for where in chart_part.values():
        by_part[part_names[where]] += 1
    report["charts_by_part"] = dict(sorted(by_part.items(), key=lambda item: -item[1]))

    if args.carry:
        if any(name is None for name in old_names.values()):
            raise SystemExit("--carry needs an old layout on every chosen mesh")
        Path(args.carry_out).parent.mkdir(parents=True, exist_ok=True)
        carry(objects, old_names, args.layer, Path(args.carry).resolve(), Path(args.carry_out).resolve(), args.size)
        report["carried"] = {"size": args.size}

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save).resolve()))
    print("RELAYOUT", json.dumps({"before": report["before"], "after": report["after"]}))


main()
