extends SceneTree
## Diagnostic adapter around the unchanged current colony controller.
## Candidate clips stay on their own skeleton: no retargeting or root removal.
const Controller = preload("res://features/living_colony/kite_approach.gd")

class Population extends Node3D:
	var disturbances := 0
	func get_debug_state() -> Dictionary:
		return {"actors": []}
	func disturb(_position: Vector3, _radius: float) -> void:
		disturbances += 1

var role := "baseline"
var output := ""
var plan: Dictionary
var world: Node3D
var bird: Node3D
var camera: Camera3D
var player: AnimationPlayer
var skeleton: Skeleton3D
var checks: Dictionary = {}
var observations: Dictionary = {}
var replay: FileAccess
var frame_times: Array[float] = []
var cpu_times: Array[float] = []
var warmup_cpu_times: Array[float] = []
var gpu_times: Array[float] = []
var coupled_population: Node3D
var mite_states: Dictionary = {}
var mite_max_playback := 0.0
var mite_max_flee_speed := 0.0
var mite_max_flee_playback := 0.0

func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--role="): role = arg.substr(7)
		if arg.begins_with("--output="): output = arg.substr(9)
	call_deferred("_run")

func _find(node: Node, type_name: String) -> Node:
	if node.is_class(type_name): return node
	for child in node.get_children():
		var found := _find(child, type_name)
		if found != null: return found
	return null

func _pose() -> Array[Transform3D]:
	var result: Array[Transform3D] = []
	for i in skeleton.get_bone_count(): result.append(skeleton.get_bone_global_pose(i))
	return result

func _rig(node: Node) -> Array:
	var sk := _find(node, "Skeleton3D") as Skeleton3D
	var result: Array = []
	for i in sk.get_bone_count():
		var rest := sk.get_bone_rest(i)
		result.append({"name": sk.get_bone_name(i), "parent": sk.get_bone_parent(i),
			"rest": [rest.origin.x,rest.origin.y,rest.origin.z,
				rest.basis.x.x,rest.basis.x.y,rest.basis.x.z,
				rest.basis.y.x,rest.basis.y.y,rest.basis.y.z,
				rest.basis.z.x,rest.basis.z.y,rest.basis.z.z]})
	return result

func _seam(clip: String) -> Dictionary:
	var animation := player.get_animation(clip)
	animation.loop_mode = Animation.LOOP_NONE
	player.play(clip)
	player.seek(0.0, true)
	var first := _pose()
	player.seek(animation.length, true)
	var last := _pose()
	var translation := 0.0
	var rotation := 0.0
	for i in first.size():
		translation = maxf(translation, first[i].origin.distance_to(last[i].origin))
		rotation = maxf(rotation, first[i].basis.get_rotation_quaternion().angle_to(last[i].basis.get_rotation_quaternion()))
	animation.loop_mode = Animation.LOOP_LINEAR
	player.play(clip)
	player.seek(0.0, true)
	return {"clip": clip, "length_seconds": animation.length,
		"max_bone_endpoint_translation_m": translation, "max_bone_endpoint_rotation_rad": rotation}

func _run() -> void:
	plan = JSON.parse_string(FileAccess.get_file_as_string("res://qualification.json"))["plan"]
	DirAccess.make_dir_recursive_absolute("res://" + output)
	replay = FileAccess.open("res://" + output + "/replay.jsonl", FileAccess.WRITE)
	world = Node3D.new()
	root.add_child(world)
	var population := Population.new()
	world.add_child(population)
	if plan.get("coupled_colony", false):
		var bank := (load("res://context/bank.glb") as PackedScene).instantiate()
		world.add_child(bank)
		var colony := (load("res://context/colony.glb") as PackedScene).instantiate()
		world.add_child(colony)
		var fitter: RefCounted = load("res://features/living_colony/route_surface_fit.gd").new()
		fitter.configure(bank) # Native bank projection, explicit flat terrain query.
		var routes: Array = JSON.parse_string(FileAccess.get_file_as_string("res://features/living_colony/data/c-routes.json")).routes
		routes = fitter.fit(routes)
		coupled_population = load("res://features/living_colony/colony_population.gd").new()
		world.add_child(coupled_population)
		coupled_population.externally_driven = true
		checks["coupled_population_configured"] = coupled_population.configure(load("res://context/mite.glb"), routes, 41)
		for actor in coupled_population.get_children():
			var animation_player := _find(actor, "AnimationPlayer") as AnimationPlayer
			animation_player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	var scene := load("res://assets/" + role + ".glb") as PackedScene
	var baseline := (load("res://assets/baseline.glb") as PackedScene).instantiate()
	world.add_child(baseline)
	baseline.hide()
	bird = Controller.new()
	world.add_child(bird)
	bird.set_physics_process(false)
	bird.configure(scene, [coupled_population if coupled_population != null else population])
	player = bird.animation
	skeleton = _find(bird.visual, "Skeleton3D") as Skeleton3D
	player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	var modifier: SkeletonModifier3D = bird.reach_modifier
	modifier.active = false
	var rig := _rig(bird.visual)
	var baseline_rig := _rig(baseline)
	checks["exact_current_rig_identity"] = rig == baseline_rig
	observations["candidate_rig"] = rig
	observations["baseline_bones"] = baseline_rig.size()
	observations["imported_scale"] = [bird.visual.scale.x,bird.visual.scale.y,bird.visual.scale.z]
	checks["import_scale"] = bird.visual.scale.is_equal_approx(Vector3.ONE)
	var clip := String(player.get_animation_list()[0])
	for name in player.get_animation_list():
		if String(name).contains("glide"): clip = name; break
	observations["loop"] = _seam(clip)
	checks["loop_endpoint_translation"] = observations.loop.max_bone_endpoint_translation_m <= plan.thresholds.loop_translation_m
	checks["loop_endpoint_rotation"] = observations.loop.max_bone_endpoint_rotation_rad <= plan.thresholds.loop_rotation_rad
	modifier.active = true
	player.play(clip)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.10,0.16,0.20)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color.WHITE
	env.environment.ambient_light_energy = 0.65
	world.add_child(env)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-45,-30,0)
	world.add_child(light)
	camera = Camera3D.new()
	world.add_child(camera)
	camera.current = true
	camera.fov = float(plan.camera.fov)
	var native := DisplayServer.get_name() != "headless"
	if native:
		Engine.max_fps = 60
		# A decorated Windows window can be clamped to the work area.
		# Set only this owned fixture's window; never change host display settings.
		root.borderless = true
		root.position = Vector2i.ZERO
		root.size = Vector2i(1920,1080)
		await process_frame
	observations["settings"] = {"renderer": RenderingServer.get_current_rendering_method(),
		"viewport": [root.size.x,root.size.y], "physics_hz": Engine.physics_ticks_per_second,
		"native_frame_cap": 60 if native else 0}
	if native:
		checks["native_render_settings"] = RenderingServer.get_current_rendering_method() == "forward_plus" and root.size == Vector2i(1920,1080) and Engine.physics_ticks_per_second == 60
	if native: RenderingServer.viewport_set_measure_render_time(root.get_viewport_rid(), true)
	var phases: Dictionary = {}
	var finite := true
	var max_speed := 0.0
	var previous: Vector3 = bird.position
	var last_tick := Time.get_ticks_usec()
	for frame in int(plan.replay.frames):
		var started := Time.get_ticks_usec()
		var actor_replay: Array = []
		if coupled_population != null:
			if frame == 600:
				var state: Dictionary = coupled_population.get_debug_state()
				if not state.actors.is_empty(): coupled_population.set_observer(state.actors[0].world_position, true)
			if frame == 630: coupled_population.clear_observer()
			coupled_population.advance(1.0/60.0)
			for actor in coupled_population.get_children():
				var state: Dictionary = actor.get_debug_state()
				mite_states[state.state] = true
				if state.state == "flee": mite_max_flee_speed = maxf(mite_max_flee_speed, state.speed)
				var animation_player := _find(actor, "AnimationPlayer") as AnimationPlayer
				animation_player.advance(1.0/60.0)
				var effective_playback := animation_player.get_playing_speed()
				mite_max_playback = maxf(mite_max_playback, effective_playback)
				if state.state == "flee": mite_max_flee_playback = maxf(mite_max_flee_playback, effective_playback)
				actor_replay.append({"home_id": state.home_id,"state": state.state,"distance": state.distance,"speed": state.speed,
					"visible": state.visible,"playback": effective_playback,"clip": animation_player.current_animation,
					"clip_time": animation_player.current_animation_position,
					"position": [actor.position.x,actor.position.y,actor.position.z],
					"rotation": [actor.quaternion.x,actor.quaternion.y,actor.quaternion.z,actor.quaternion.w]})
		bird.advance(1.0/60.0)
		player.advance(1.0/60.0)
		phases[bird.phase] = true
		finite = finite and bird.position.is_finite() and bird.basis.is_finite()
		max_speed = maxf(max_speed, bird.position.distance_to(previous)*60.0)
		previous = bird.position
		camera.position = bird.position + Vector3(plan.camera.offset[0],plan.camera.offset[1],plan.camera.offset[2])
		camera.look_at(bird.position, Vector3.UP)
		var cpu_elapsed := float(Time.get_ticks_usec()-started)/1000.0
		if frame < int(plan.replay.warmup_frames): warmup_cpu_times.append(cpu_elapsed)
		else: cpu_times.append(cpu_elapsed)
		var bone_replay: Array = []
		for bone in skeleton.get_bone_count():
			var p := skeleton.get_bone_pose_position(bone)
			var r := skeleton.get_bone_pose_rotation(bone)
			bone_replay.append([p.x,p.y,p.z,r.x,r.y,r.z,r.w])
		replay.store_line(JSON.stringify({"frame": frame,"time": frame/60.0,"phase": bird.phase,
			"position": [bird.position.x,bird.position.y,bird.position.z], "clip": player.current_animation,
			"clip_time": player.current_animation_position,"flap_weight": modifier.flap_weight,"reach": modifier.reach,
			"bones_local": bone_replay,"mite_actors": actor_replay}))
		await process_frame
		var now := Time.get_ticks_usec()
		if frame >= int(plan.replay.warmup_frames):
			frame_times.append(float(now-last_tick)/1000.0)
			if native: gpu_times.append(RenderingServer.viewport_get_measured_render_time_gpu(root.get_viewport_rid()))
		last_tick = now
		var capture_requested := false
		for requested_frame in plan.replay.capture_frames:
			if frame == int(requested_frame): capture_requested = true
		if native and capture_requested:
			await RenderingServer.frame_post_draw
			root.get_texture().get_image().save_png("res://" + output + "/frame-%04d.png" % frame)
	replay.close()
	checks["controller_finite"] = finite
	checks["approach_depart_orbit"] = phases.has("approach") and phases.has("depart") and phases.has("orbit")
	checks["disturbance"] = bird.passes == 1
	if coupled_population != null:
		checks["mite_flee_observed"] = mite_states.has("flee")
		checks["mite_playback_clamp"] = mite_max_playback <= 2.75 + 0.000001
		checks["mite_flee_playback"] = absf(mite_max_flee_playback - 2.75) <= 0.000001
		checks["mite_flee_speed"] = absf(mite_max_flee_speed - 0.85) <= 0.000001
		observations["mite_states"] = mite_states.keys()
		observations["mite_max_playback"] = mite_max_playback
		observations["mite_max_flee_speed_mps"] = mite_max_flee_speed
		observations["mite_max_flee_playback"] = mite_max_flee_playback
	checks["bounded_controller_speed"] = max_speed <= float(plan.thresholds.max_speed_mps)
	observations["phases"] = phases.keys()
	observations["disturbances"] = population.disturbances
	observations["max_speed_mps"] = max_speed
	observations["clip_transition_coverage"] = "absent: current controller does not transition authored clips; generated clips need an explicit reviewed adapter"
	observations["context"] = "actual colony C population, source routes, bank projection and models; flat terrain query, no planetary frame bridge or perch wiring" if coupled_population != null else "unchanged controller; diagnostic population stub (no Mite gameplay), no planetary terrain or perch wiring"
	observations["generated_flap_overlay"] = "unchanged current additive reach/flap modifier remains active over raw candidate; visual double-flap risk requires review"
	var passed := true
	for value in checks.values(): passed = passed and bool(value)
	var result := {"automated_checks": "passed" if passed else "failed", "checks": checks,
		"observations": observations, "engine": Engine.get_version_info(),
		"native_rendered": native, "human_visual_review": "pending", "performance_qualification": "unverified",
		"timing": {"frame_ms": frame_times,"controller_cpu_ms": cpu_times,"viewport_gpu_ms": gpu_times,
			"warmup_controller_cpu_ms": warmup_cpu_times},
		"limits": ["loop endpoint pose comparison does not establish derivative continuity", "coupled context is bounded by the declared plan", "missing authored transition/bank coverage", "no production acceptance"]}
	var file := FileAccess.open("res://" + output + "/result.json", FileAccess.WRITE)
	file.store_string(JSON.stringify(result,"\t"))
	file.close()
	quit(0)
