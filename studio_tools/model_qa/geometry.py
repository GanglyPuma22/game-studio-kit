"""Read geometry in metres, Y up, retaining connected-part identities."""
import numpy as np
import trimesh
from pygltflib import GLTF2

from .gltf_pose import Model
from .attachment import part_labels


def validate(path):
    g = GLTF2().load(str(path))
    if any(b.uri for b in g.buffers) or any(i.uri for i in g.images):
        raise ValueError("Only self-contained GLBs with embedded buffers/images are supported")
    if g.extensionsRequired:
        raise ValueError(f"Required glTF extensions are unsupported: {g.extensionsRequired}")
    for mesh in g.meshes:
        for primitive in mesh.primitives:
            if primitive.mode not in (None, 4):
                raise ValueError("Only TRIANGLES primitives are supported")
            if primitive.targets:
                raise ValueError("Morph targets are unsupported; they cannot receive a QA pass")
    if any(a.sparse for a in g.accessors):
        raise ValueError("Sparse accessors are unsupported")
    if g.skins:
        # Do not silently omit geometry the reference's skin-0 sampler cannot see.
        if len(g.skins) != 1 or any(n.mesh is not None and n.skin != 0 for n in g.nodes):
            raise ValueError("Skinned QA requires exactly one skin and every mesh bound to it")
        if any(n.matrix for n in g.nodes):
            raise ValueError("Skinned node matrices are unsupported; export TRS transforms")
        if g.skins[0].inverseBindMatrices is None:
            raise ValueError("Skinned QA requires explicit inverse bind matrices")
        names = [a.name for a in g.animations]
        if any(not name or name == "rest" for name in names) or len(set(names)) != len(names):
            raise ValueError("Clips need unique nonempty names other than 'rest'")
        for animation in g.animations:
            if any(s.interpolation not in (None, "LINEAR") for s in animation.samplers):
                raise ValueError("Only LINEAR/slerp skin animation is supported")
            if any(c.target.path not in ("translation", "rotation", "scale") for c in animation.channels):
                raise ValueError("Unsupported animation target")
        for mesh in g.meshes:
            for p in mesh.primitives:
                if p.indices is None or p.attributes.JOINTS_0 is None or p.attributes.WEIGHTS_0 is None:
                    raise ValueError("Skin primitives require indices, JOINTS_0 and WEIGHTS_0")
                if getattr(p.attributes, "JOINTS_1", None) is not None:
                    raise ValueError("More than four joint weights per vertex are unsupported")
    elif g.animations:
        raise ValueError("Unskinned node animation is unsupported; no rest-only pass is issued")
    return g


def split(tm):
    if not len(tm.faces) or not np.isfinite(tm.vertices).all():
        raise ValueError("Model needs finite vertices and at least one triangle")
    tm.merge_vertices(merge_tex=True, merge_norm=True)
    labels = trimesh.graph.connected_component_labels(tm.face_adjacency, node_count=len(tm.faces))
    parts = [tm.submesh([np.flatnonzero(labels == i)], append=True) for i in range(int(labels.max()) + 1)]
    return parts, labels


def load(path):
    g = validate(path)
    if g.skins:
        model = Model(str(path))
        if (not np.isfinite(model.wt).all() or (model.wt < 0).any() or (model.wt > 1).any()
                or not np.allclose(model.wt.sum(axis=1), 1, atol=1e-3)):
            raise ValueError("Skin weights must be finite, in [0, 1], and sum to one")
        tm = trimesh.Trimesh(model.posed(), model.idx, process=False)
        if not len(tm.faces) or not np.isfinite(tm.vertices).all():
            raise ValueError("Skin needs finite posed vertices and at least one triangle")
        # Skin names come from the unmerged index space, just as in M12.
        raw_labels = part_labels(model)
        parts = [tm.submesh([np.flatnonzero(raw_labels == i)], append=True)
                 for i in range(int(raw_labels.max()) + 1)]
        for part in parts:
            part.merge_vertices(merge_tex=True, merge_norm=True)
        names = []
        for i in range(len(parts)):
            verts = np.unique(model.idx[raw_labels == i])
            joint = model.joints[int(np.bincount(model.jn[verts, 0]).argmax())]
            names.append(f"{g.nodes[joint].name or 'joint'} / part-{i}")
        return tm, parts, names, model
    scene = trimesh.load(str(path), force="scene")
    meshes, face_names = [], []
    authored_names = {n.name for n in g.nodes if n.name}
    for instance, node in enumerate(scene.graph.nodes_geometry):
        transform, geom = scene.graph.get(node)
        mesh = scene.geometry[geom].copy().apply_transform(transform)
        meshes.append(mesh)
        # Multi-material imports get random primitive-node suffixes from trimesh.
        # Use their authored ancestor, retaining a stable part index below.
        label, ancestor, visited = f"instance-{instance}", node, set()
        while ancestor is not None and ancestor not in visited:
            visited.add(ancestor)
            if ancestor in authored_names:
                label = str(ancestor)
                break
            ancestor = scene.graph.transforms.parents.get(ancestor)
        face_names.extend([label] * len(mesh.faces))
    if not meshes:
        raise ValueError("No mesh instances in the active scene")
    tm = trimesh.util.concatenate(meshes)
    parts, labels = split(tm)
    names = [" + ".join(sorted({face_names[j] for j in np.flatnonzero(labels == i)})) + f" / part-{i}"
             for i in range(len(parts))]
    return tm, parts, names, None


def part_inventory(parts, names):
    return [{"id": i, "name": names[i], "triangles": len(p.faces),
             "bounds_m": p.bounds.tolist(), "centroid_m": p.centroid.tolist()}
            for i, p in enumerate(parts)]
