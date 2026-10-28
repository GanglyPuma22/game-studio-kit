"""Build tiny deterministic GLB fixtures; no checked-in binaries or Blender files."""
from pathlib import Path

import numpy as np
import trimesh


def box(extents, center):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    return mesh


def export(path, pieces):
    scene = trimesh.Scene()
    for name, mesh in pieces:
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(scene.export(file_type="glb"))


def build(root):
    root = Path(root)
    base = box((0.6, 0.6, 0.6), (0, 0.3, 0))
    floating = box((0.15, 0.15, 0.15), (0, 0.9, 0))
    # A tip seated in the base has half its vertices on the base face. Its
    # disappearance must still be named, rather than hidden by that root contact.
    tip = box((0.5, 0.15, 0.15), (0.55, 0.5, 0))
    inverted = base.copy()
    inverted.faces = inverted.faces[:, ::-1]
    # The middle of the top pushed down through the bottom: one connected
    # part crossing itself, which M13 (between parts) cannot see.
    folded = base.subdivide().subdivide().subdivide()
    v = folded.vertices.copy()
    r = np.hypot(v[:, 0], v[:, 2])
    top = v[:, 1] > 0.6 - 1e-6
    v[top, 1] -= 0.9 * np.clip(1 - r[top] / 0.2, 0, 1)
    folded = trimesh.Trimesh(v, folded.faces, process=False)
    # LOD1 adds a 5 cm spike at a corner: small in a far silhouette, several pixels at the switch distance.
    spiked = base.copy()
    spiked.vertices[0] = spiked.vertices[0] + (spiked.vertices[0] - spiked.bounds.mean(axis=0)) * 0.15
    cases = {
        "clean": [[("body", base)], [("body", base)]],
        "inverted": [[("body", inverted)], [("body", inverted)]],
        "folded": [[("body", folded)], [("body", folded)]],
        "spiked": [[("body", base)], [("body", spiked)]],
        "floating": [[("body", base), ("floating-cube", floating)]] * 2,
        "clipping": [[("cross-x", box((1.6, 0.22, 0.24), (0, 0.2, 0))),
                      ("cross-z", box((0.24, 0.18, 1.6), (0, 0.23, 0)))]] * 2,
        "dropped": [[("body", base), ("tip", tip)], [("body", base)]],
    }
    for name, lods in cases.items():
        for i, pieces in enumerate(lods):
            export(root / name / f"{name}-lod{i}.glb", pieces)
    (root / "ecology.md").write_text(
        "# Test organism\n\n## Habitat\nRocky, wind-exposed slopes.\n\n"
        "## Traits\n- Low profile because this reduces exposure to wind.\n", encoding="utf-8")
    return root


def skinned(path):
    """Two rigid pieces touch at rest; the second detaches during a linear clip."""
    import numpy as np
    from pygltflib import (GLTF2, Accessor, BufferView, Node, Skin, Animation,
                          AnimationSampler, AnimationChannel, AnimationChannelTarget)
    export(path, [("body", box((0.6, 0.6, 0.6), (0, 0.3, 0))),
                  ("tip", box((0.2, 0.2, 0.2), (0, 0.7, 0)))])
    g = GLTF2().load(str(path))
    blob = bytearray(g.binary_blob())
    def acc(array, type_, component):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        data = array.tobytes()
        blob.extend(data)
        view = len(g.bufferViews)
        g.bufferViews.append(BufferView(buffer=0, byteOffset=offset, byteLength=len(data)))
        index = len(g.accessors)
        g.accessors.append(Accessor(bufferView=view, componentType=component, count=len(array), type=type_))
        return index
    first_joint = len(g.nodes)
    g.nodes.extend([Node(name="body-joint"), Node(name="tip-joint")])
    g.scenes[g.scene or 0].nodes.extend([first_joint, first_joint + 1])
    inverse = np.stack([np.eye(4), np.eye(4)]).astype("<f4").reshape(2, 16)
    g.skins = [Skin(joints=[first_joint, first_joint + 1], inverseBindMatrices=acc(inverse, "MAT4", 5126))]
    for node in g.nodes:
        if node.mesh is not None:
            node.skin = 0
            for primitive in g.meshes[node.mesh].primitives:
                count = g.accessors[primitive.attributes.POSITION].count
                joints = np.zeros((count, 4), dtype="<u2")
                joints[:, 0] = int(node.name == "tip")
                weights = np.zeros((count, 4), dtype="<f4")
                weights[:, 0] = 1
                primitive.attributes.JOINTS_0 = acc(joints, "VEC4", 5123)
                primitive.attributes.WEIGHTS_0 = acc(weights, "VEC4", 5126)
    times = acc(np.array([[0], [1]], dtype="<f4"), "SCALAR", 5126)
    positions = acc(np.array([[0, 0, 0], [0, 0.4, 0]], dtype="<f4"), "VEC3", 5126)
    g.animations = [Animation(name="detach", samplers=[AnimationSampler(input=times, output=positions, interpolation="LINEAR")],
                              channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(node=first_joint + 1, path="translation"))])]
    g.buffers[0].byteLength = len(blob)
    g.set_binary_blob(bytes(blob))
    g.save(str(path))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    build(parser.parse_args().out)
