## Dumps a character model's skeleton and some of its clips as world-space bone
## frames (JSON), for moving poses between it and MotionBricks' SOMA skeleton (rig_map.py).
##   godot --headless --path . --script res://<path>/dump_skeleton.gd -- <glb res path> <out.json> [clip ...]
extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var scene: Node = load(args[0]).instantiate()
	root.add_child(scene)
	await process_frame
	var skel: Skeleton3D = scene.find_child("*", true, false) as Skeleton3D
	for n in scene.find_children("*", "Skeleton3D", true, false):
		skel = n
	var player: AnimationPlayer = scene.find_child("AnimationPlayer", true, false)
	var out := {"bones": [], "parents": [], "rest": [], "clips": {}, "all_clips": Array(player.get_animation_list())}
	for i in skel.get_bone_count():
		out.bones.append(skel.get_bone_name(i))
		out.parents.append(skel.get_bone_parent(i))
		out.rest.append(_xf(skel.get_bone_global_rest(i)))
	for c in args.slice(2):
		if not player.has_animation(c):
			continue
		var anim := player.get_animation(c)
		player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
		player.play(c)
		var frames: Array = []
		var n := int(round(anim.length * 30.0))
		for f in n + 1:
			player.seek(float(f) / 30.0, true)
			player.advance(0.0)
			skel.force_update_all_bone_transforms()
			var row: Array = []
			for i in skel.get_bone_count():
				row.append(_xf(skel.get_bone_global_pose(i)))
			frames.append(row)
		out.clips[c] = frames
	var fa := FileAccess.open(args[1], FileAccess.WRITE)
	fa.store_string(JSON.stringify(out))
	fa.close()
	print("dumped ", skel.get_bone_count(), " bones, clips ", out.clips.keys())
	quit()


func _xf(t: Transform3D) -> Array:
	var q := t.basis.get_rotation_quaternion()
	return [t.origin.x, t.origin.y, t.origin.z, q.x, q.y, q.z, q.w]
