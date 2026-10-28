## Rigid blocks for a skinned humanoid (references/block-motion-rules.md),
## for checking a skinned character's clips against rule 8b or keeping a
## procedural pose out of its own body. Bone names follow the common
## Unreal-mannequin naming (Quaternius, Mixamo-converted and many CC0 bases
## use it); edit BLOCKS and TRIM_TO for another skeleton. Each box comes from the skin's
## own vertices that follow that bone most (fingers count for the hand, the
## toes for the foot; cloth is left out), between the 4th and 96th
## percentile so a stray vertex does not swell it, and limbs run joint to
## joint. Read from the model at load.
extends RefCounted

const MotionCheck := preload("motion_check.gd")

## The blocks, parents before children.
const BLOCKS := ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "Head",
	"clavicle_l", "upperarm_l", "lowerarm_l", "hand_l",
	"clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
	"thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r"]
## A limb block ends at the next joint.
const TRIM_TO := {"upperarm_l": "lowerarm_l", "lowerarm_l": "hand_l", "upperarm_r": "lowerarm_r", "lowerarm_r": "hand_r",
	"thigh_l": "calf_l", "calf_l": "foot_l", "thigh_r": "calf_r", "calf_r": "foot_r"}
## Bones whose skin is cloth (it flows, it is not a block).
const CLOTH := ["scarf", "tabard", "sash", "skirt", "coat_", "cape_", "Blade"]

var skel: Skeleton3D
var names: Array = []          # block names (BLOCKS that the skeleton has)
var bone: PackedInt32Array      # block -> skeleton bone index
var parent: PackedInt32Array    # block -> parent block (-1 for the root)
var rest: Array = []            # block -> rest pose (skeleton space)
var box_c: Array = []           # block -> box centre (its bone frame), or null
var box_h: Array = []           # block -> box half size
var check: RefCounted           # a MotionCheck on these blocks (its allowances)
var idx := {}                   # block name -> block


func _init(p_skel: Skeleton3D) -> void:
	skel = p_skel
	var bone_of := {}
	for n in BLOCKS:
		var b := skel.find_bone(n)
		if b >= 0:
			idx[n] = names.size()
			names.append(n)
			bone.append(b)
			bone_of[b] = idx[n]
			rest.append(skel.get_bone_global_rest(b))
	for i in names.size():
		var p := skel.get_bone_parent(bone[i])
		while p >= 0 and not bone_of.has(p):
			p = skel.get_bone_parent(p)
		parent.append(bone_of[p] if p >= 0 else -1)
	_fit(bone_of)
	check = make_check()


## The block a skeleton bone's skin belongs to (-1 for cloth or none).
func _block_of(b: int, bone_of: Dictionary) -> int:
	var x := b
	while x >= 0:
		var nm := skel.get_bone_name(x)
		for c in CLOTH:
			if nm.begins_with(c):
				return -1
		if bone_of.has(x):
			return bone_of[x]
		x = skel.get_bone_parent(x)
	return -1


func _fit(bone_of: Dictionary) -> void:
	var pts: Array = []
	for i in names.size():
		pts.append([PackedFloat32Array(), PackedFloat32Array(), PackedFloat32Array()])
	for m in skel.find_children("*", "MeshInstance3D", true, false):
		var mi := m as MeshInstance3D
		if mi.mesh == null or mi.skin == null:
			continue
		var sk: Skin = mi.skin
		var bind_bone := PackedInt32Array()
		for j in sk.get_bind_count():
			var bb := sk.get_bind_bone(j)
			if bb < 0:
				bb = skel.find_bone(sk.get_bind_name(j))
			bind_bone.append(bb)
		for si in mi.mesh.get_surface_count():
			var arr: Array = mi.mesh.surface_get_arrays(si)
			var verts: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			var bones = arr[Mesh.ARRAY_BONES]
			var weights = arr[Mesh.ARRAY_WEIGHTS]
			if bones == null or weights == null or verts.is_empty():
				continue
			var per: int = bones.size() / verts.size()
			for v in range(0, verts.size(), 2):
				var best := -1
				var bw := 0.0
				for k in per:
					var w: float = weights[v * per + k]
					if w > bw:
						bw = w
						best = bones[v * per + k]
				if best < 0 or best >= bind_bone.size():
					continue
				var sb := bind_bone[best]
				if sb < 0:
					continue
				var blk := _block_of(sb, bone_of)
				if blk < 0:
					continue
				var in_skel: Vector3 = skel.get_bone_global_rest(sb) * (sk.get_bind_pose(best) * verts[v])
				var q: Vector3 = (rest[blk] as Transform3D).affine_inverse() * in_skel
				pts[blk][0].append(q.x)
				pts[blk][1].append(q.y)
				pts[blk][2].append(q.z)
	for i in names.size():
		var xs: PackedFloat32Array = pts[i][0]
		if xs.size() < 8:
			box_c.append(null)
			box_h.append(Vector3.ZERO)
			continue
		var lo := Vector3.ZERO
		var hi := Vector3.ZERO
		for ax in 3:
			var a: PackedFloat32Array = pts[i][ax]
			a.sort()
			lo[ax] = a[int(a.size() * 0.04)]
			hi[ax] = a[int(a.size() * 0.96) - 1]
		var nm: String = names[i]
		if TRIM_TO.has(nm) and idx.has(TRIM_TO[nm]):
			var end: Vector3 = (rest[i] as Transform3D).affine_inverse() * (rest[idx[TRIM_TO[nm]]] as Transform3D).origin
			lo.y = maxf(lo.y, minf(0.0, end.y))
			hi.y = minf(hi.y, maxf(0.0, end.y))
		box_c.append((lo + hi) * 0.5)
		box_h.append(((hi - lo) * 0.5).max(Vector3.ONE * 0.01))


## A rule checker on these blocks: every pair but parent and child, the
## feet as contacts.
func make_check() -> RefCounted:
	var mc := MotionCheck.new()
	var desc := {"no_overlap": "all", "contacts": ["foot_l", "foot_r"], "default_limit": 180.0}
	# A person-sized body: a graze under 3 cm (a hand brushing a thigh) is
	# contact, not a block through another.
	mc.floor_m = 0.03
	mc.setup_rig(names, parent, rest, box_c, box_h, desc)
	return mc


## The blocks' poses now (skeleton space), read from the skeleton.
func poses() -> Array:
	var out: Array = []
	for i in names.size():
		out.append(skel.get_bone_global_pose(bone[i]))
	return out


## How far blocks a and b (by name) overlap at these poses past their
## allowance (skeleton units).
func over(a: String, ta: Transform3D, b: String, tb: Transform3D) -> float:
	var ia: int = idx.get(a, -1)
	var ib: int = idx.get(b, -1)
	if ia < 0 or ib < 0 or ia == ib or parent[ia] == ib or parent[ib] == ia:
		return 0.0
	return check.pair_over(ia, ta, ib, tb)
