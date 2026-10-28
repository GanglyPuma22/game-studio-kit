"""Read geometry in metres, Y up, retaining connected-part identities."""
import numpy as np
import trimesh
from pygltflib import GLTF2

from .gltf_pose import Model, acc, qmat
from .attachment import part_labels, part_owners


def validate(path):
    g = GLTF2().load(str(path))
    if any(b.uri for b in g.buffers):
        raise ValueError("Only self-contained GLB geometry buffers are supported")
    unsupported = set(g.extensionsRequired or []) - {'KHR_mesh_quantization'}
    if unsupported:
        raise ValueError(f"Required glTF extensions are unsupported: {sorted(unsupported)}")
    for mesh in g.meshes:
        for primitive in mesh.primitives:
            if primitive.mode not in (None, 4):
                raise ValueError("Only TRIANGLES primitives are supported")
    animated = {c.target.node for a in g.animations for c in a.channels if c.target.path != 'weights'}
    if any(g.nodes[i].matrix for i in animated):
        raise ValueError("Animated node matrices are unsupported; export TRS transforms")
    if g.skins or animated:
        joints = {j for s in g.skins for j in s.joints}
        if any(g.nodes[j].matrix for j in joints):
            raise ValueError("Skinned node matrices are unsupported; export TRS transforms")
        if any(s.inverseBindMatrices is None for s in g.skins):
            raise ValueError("Skinned QA requires explicit inverse bind matrices")
        names = [a.name for a in g.animations]
        if any(not name or name == "rest" for name in names) or len(set(names)) != len(names):
            raise ValueError("Clips need unique nonempty names other than 'rest'")
        for animation in g.animations:
            if any(s.interpolation not in (None, "LINEAR", "STEP", "CUBICSPLINE") for s in animation.samplers):
                raise ValueError("Only LINEAR, STEP and CUBICSPLINE animation is supported")
            if any(c.target.path not in ("translation", "rotation", "scale", "weights") for c in animation.channels):
                raise ValueError("Unsupported animation target")
        for node in g.nodes:
            if node.mesh is None or node.skin is None:
                continue
            for p in g.meshes[node.mesh].primitives:
                if p.indices is None or p.attributes.JOINTS_0 is None or p.attributes.WEIGHTS_0 is None:
                    raise ValueError("Skin primitives require indices, JOINTS_0 and WEIGHTS_0")
                if getattr(p.attributes, "JOINTS_1", None) is not None:
                    raise ValueError("More than four joint weights per vertex are unsupported")
    return g


def split(tm):
    if not len(tm.faces) or not np.isfinite(tm.vertices).all():
        raise ValueError("Model needs finite vertices and at least one triangle")
    tm.merge_vertices(merge_tex=True, merge_norm=True)
    labels = trimesh.graph.connected_component_labels(tm.face_adjacency, node_count=len(tm.faces))
    parts = [tm.submesh([np.flatnonzero(labels == i)], append=True) for i in range(int(labels.max()) + 1)]
    return parts, labels


def double_sided(g, primitive):
    """glTF materials are single-sided (back faces culled) unless they say otherwise."""
    if primitive.material is None or not g.materials:
        return False
    return bool(g.materials[primitive.material].doubleSided)


def posable(g):
    """Skinned or node-animated files are measured per pose through Model."""
    return bool(g.skins) or any(c.target.path != 'weights' for a in g.animations for c in a.channels)


def load(path, manifest=None):
    manifest = manifest or {}
    g = validate(path)
    notes = ['Morph targets were not checked'] if any(p.targets for m in g.meshes for p in m.primitives) else []
    if posable(g):
        model = Model(str(path), gltf=g, exclude_meshes=manifest.get('exclude_meshes', ()),
                      exclude_clips=manifest.get('exclude_clips'))
        if model.excluded_clips:
            notes.append('Clips excluded by the manifest: ' + ', '.join(model.excluded_clips))
        if manifest.get('exclude_meshes'):
            notes.append('Meshes excluded by the manifest: ' + ', '.join(manifest['exclude_meshes']))
        if (not np.isfinite(model.wt).all() or (model.wt < 0).any() or (model.wt > 1).any()
                or not np.allclose(model.wt.sum(axis=1), 1, atol=1e-3)):
            raise ValueError("Skin weights must be finite, in [0, 1], and sum to one")
        tm = trimesh.Trimesh(model.posed(), model.idx, process=False)
        tm.metadata['qa_notes'] = notes
        if not len(tm.faces) or not np.isfinite(tm.vertices).all():
            raise ValueError("Skin needs finite posed vertices and at least one triangle")
        # Skin names come from the unmerged index space, just as in M12.
        raw_labels = part_labels(model)
        tm.metadata['face_part'] = raw_labels
        tm.metadata['double_faces'] = model.face_double
        parts = [tm.submesh([np.flatnonzero(raw_labels == i)], append=True)
                 for i in range(int(raw_labels.max()) + 1)]
        for part in parts:
            part.merge_vertices(merge_tex=True, merge_norm=True)
        names = [f"{name} / part-{i}" for i, name in enumerate(part_owners(model, raw_labels))]
        return tm, parts, names, model
    meshes, face_names, face_double = [], [], []
    # Decode only POSITION and indices. No image decoding, materials, texture
    # copies, normals or UVs are needed for these geometric measurements.
    def visit(index, parent, ancestor, stack):
        if index in stack:
            raise ValueError('Cycle in scene nodes')
        node = g.nodes[index]
        if node.matrix:
            local = np.array(node.matrix, dtype=float).reshape(4, 4).T
        else:
            local = np.eye(4)
            local[:3, :3] = qmat(node.rotation or [0, 0, 0, 1]) * np.array(node.scale or [1, 1, 1])
            local[:3, 3] = node.translation or [0, 0, 0]
        world = parent @ local
        label = node.name or ancestor or f'node-{index}'
        if node.mesh is not None and not ({node.name, g.meshes[node.mesh].name} & set(manifest.get('exclude_meshes', ()))):
            for primitive in g.meshes[node.mesh].primitives:
                vertices = acc(g, primitive.attributes.POSITION).astype(np.float64)
                indices = acc(g, primitive.indices).reshape(-1) if primitive.indices is not None else np.arange(len(vertices))
                if len(indices) % 3 or (indices < 0).any() or (indices >= len(vertices)).any():
                    raise ValueError('Invalid triangle indices')
                mesh = trimesh.Trimesh(vertices, indices.reshape(-1, 3), process=False)
                mesh.apply_transform(world)
                meshes.append(mesh)
                face_names.extend([label] * len(mesh.faces))
                face_double.extend([double_sided(g, primitive)] * len(mesh.faces))
        for child in node.children or []:
            visit(child, world, label, stack | {index})
    if not g.scenes:
        raise ValueError('No active scene')
    for node in g.scenes[g.scene or 0].nodes:
        visit(node, np.eye(4), '', set())
    if not meshes:
        raise ValueError("No mesh instances in the active scene")
    tm = trimesh.util.concatenate(meshes)
    tm.metadata['qa_notes'] = notes
    parts, labels = split(tm)
    tm.metadata['face_part'] = labels
    tm.metadata['double_faces'] = np.array(face_double, bool)
    names = [" + ".join(sorted({face_names[j] for j in np.flatnonzero(labels == i)})) + f" / part-{i}"
             for i in range(len(parts))]
    return tm, parts, names, None


def part_inventory(parts, names):
    return [{"id": i, "name": names[i], "triangles": len(p.faces),
             "bounds_m": p.bounds.tolist(), "centroid_m": p.centroid.tolist()}
            for i, p in enumerate(parts)]
