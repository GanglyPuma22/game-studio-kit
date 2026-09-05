extends Node3D
## Original pipeline fixture. Ordinary play and deterministic technical smoke share actions.

var player: CharacterBody3D
var camera: Camera3D
var creature: Node3D
var animation_player: AnimationPlayer
var cue: AudioStreamPlayer3D
var ambience: AudioStreamPlayer
var idle_clip: StringName
var response_clip: StringName
var label: Label
var response_count := 0
var audio_started := false
var moved_distance := 0.0
var smoking := false
var smoke_seconds := 0.0
var smoke_phase := 0
var peak_frame_ms := 0.0
var motion_changed := false
var rig: Skeleton3D
var initial_pose := Transform3D.IDENTITY
var smoke_output := ""
var failed := false

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--studio-smoke="):
			smoking = true
			smoke_output = arg.trim_prefix("--studio-smoke=")
	_bind("walk_forward", [KEY_W, KEY_UP])
	_bind("walk_back", [KEY_S, KEY_DOWN])
	_bind("walk_left", [KEY_A, KEY_LEFT])
	_bind("walk_right", [KEY_D, KEY_RIGHT])
	_bind("respond", [KEY_E])
	_build_environment()
	_build_player()
	var scene := load("res://assets/harbor-bell.glb") as PackedScene
	if scene == null:
		_fail("GLB did not import")
		return
	creature = scene.instantiate()
	add_child(creature)
	creature.position = Vector3(0, 0.05, -1)
	animation_player = _find_type(creature, "AnimationPlayer") as AnimationPlayer
	rig = _find_type(creature, "Skeleton3D") as Skeleton3D
	if animation_player == null or rig == null:
		_fail("Imported animation player or skeleton missing")
		return
	for clip in animation_player.get_animation_list():
		if String(clip).get_slice("/", String(clip).get_slice_count("/") - 1) == "idle":
			idle_clip = clip
		if String(clip).get_slice("/", String(clip).get_slice_count("/") - 1) == "response":
			response_clip = clip
	if idle_clip == &"" or response_clip == &"":
		_fail("Named idle/response clips missing")
		return
	animation_player.get_animation(idle_clip).loop_mode = Animation.LOOP_LINEAR
	animation_player.get_animation(response_clip).loop_mode = Animation.LOOP_NONE
	animation_player.animation_finished.connect(_animation_finished)
	animation_player.play(idle_clip)
	initial_pose = rig.get_bone_pose(rig.find_bone("Frond"))
	_build_audio()
	label = Label.new()
	label.position = Vector2(24, 24)
	label.add_theme_font_size_override("font_size", 22)
	var canvas := CanvasLayer.new()
	add_child(canvas)
	canvas.add_child(label)
	_update_label()

func _bind(action: StringName, keys: Array) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	for key in keys:
		var event := InputEventKey.new()
		event.physical_keycode = key
		InputMap.action_add_event(action, event)

func _find_type(node: Node, type: String) -> Node:
	if node.is_class(type):
		return node
	for child in node.get_children():
		var found := _find_type(child, type)
		if found != null:
			return found
	return null

func _material(color: Color) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = 0.85
	return mat

func _box(pos: Vector3, size: Vector3, color: Color, collision: bool) -> void:
	var mesh := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = size
	mesh.mesh = box
	mesh.material_override = _material(color)
	mesh.position = pos
	add_child(mesh)
	if collision:
		var body := StaticBody3D.new()
		body.position = pos
		var shape := CollisionShape3D.new()
		var resource := BoxShape3D.new()
		resource.size = size
		shape.shape = resource
		body.add_child(shape)
		add_child(body)

func _build_environment() -> void:
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.background_mode = Environment.BG_COLOR
	world.environment.background_color = Color(0.10, 0.17, 0.22)
	world.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	world.environment.ambient_light_color = Color(0.7, 0.8, 0.9)
	world.environment.ambient_light_energy = 0.6
	add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45, -35, 0)
	sun.light_energy = 1.2
	add_child(sun)
	_box(Vector3(0, -0.2, 0), Vector3(16, 0.4, 16), Color(0.24, 0.30, 0.28), true)
	_box(Vector3(-3, 0.9, -1), Vector3(0.35, 1.8, 0.35), Color(0.87, 0.75, 0.44), true)
	_box(Vector3(0, -0.05, 0), Vector3(2.5, 0.12, 8), Color(0.47, 0.44, 0.35), false)
	# Heightfield OBJ is a visible flanking mound, with generated matching trimesh collision.
	var terrain := load("res://assets/terrain.obj") as Mesh
	if terrain != null:
		var mound := MeshInstance3D.new()
		mound.mesh = terrain
		mound.material_override = _material(Color(0.32, 0.41, 0.28))
		mound.position = Vector3(4, 0, -1)
		add_child(mound)
		mound.create_trimesh_collision()

func _build_player() -> void:
	player = CharacterBody3D.new()
	player.position = Vector3(0, 0.1, 3.6)
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.3
	capsule.height = 1.8
	shape.shape = capsule
	shape.position.y = 0.9
	player.add_child(shape)
	camera = Camera3D.new()
	camera.position.y = 1.6
	camera.fov = 70
	player.add_child(camera)
	add_child(player)
	camera.current = true

func _build_audio() -> void:
	for name in ["SFX", "Ambience"]:
		if AudioServer.get_bus_index(name) < 0:
			AudioServer.add_bus()
			AudioServer.set_bus_name(AudioServer.bus_count - 1, name)
	cue = AudioStreamPlayer3D.new()
	cue.stream = load("res://assets/response.wav")
	cue.bus = &"SFX"
	cue.max_distance = 12
	cue.volume_db = -4
	cue.position = creature.position
	add_child(cue)
	ambience = AudioStreamPlayer.new()
	var stream := load("res://assets/ambience.wav") as AudioStreamWAV
	stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
	stream.loop_begin = 0
	stream.loop_end = stream.data.size() / (2 * (2 if stream.stereo else 1))
	ambience.stream = stream
	ambience.bus = &"Ambience"
	ambience.volume_db = -12
	add_child(ambience)
	ambience.play()

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		player.rotate_y(-event.relative.x * 0.002)
		camera.rotation.x = clamp(camera.rotation.x - event.relative.y * 0.002, -1.3, 1.3)
	if event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _physics_process(delta: float) -> void:
	if failed or player == null or animation_player == null:
		return
	peak_frame_ms = max(peak_frame_ms, delta * 1000)
	if smoking:
		_smoke_inputs(delta)
	var input := Input.get_vector("walk_left", "walk_right", "walk_forward", "walk_back")
	var direction := player.transform.basis * Vector3(input.x, 0, input.y)
	player.velocity.x = direction.x * 2.5
	player.velocity.z = direction.z * 2.5
	if not player.is_on_floor():
		player.velocity.y -= 9.8 * delta
	else:
		player.velocity.y = 0
	var before := player.position
	player.move_and_slide()
	moved_distance += Vector2(player.position.x - before.x, player.position.z - before.z).length()
	if Input.is_action_just_pressed("respond"):
		respond()
	if rig != null:
		var pose := rig.get_bone_pose(rig.find_bone("Frond"))
		if not pose.is_equal_approx(initial_pose):
			motion_changed = true
	_update_label()

func respond() -> void:
	if player.position.distance_to(creature.position) > 3.0 or animation_player.current_animation == response_clip:
		return
	response_count += 1
	animation_player.play(response_clip, 0.15)
	cue.play()
	audio_started = cue.playing

func _animation_finished(clip: StringName) -> void:
	if clip == response_clip:
		animation_player.play(idle_clip, 0.2)

func _update_label() -> void:
	if label == null:
		return
	label.text = "HARBOR POCKET · functional pipeline fixture\nWASD / arrows: walk · click + mouse: look · E nearby: respond · Esc: release mouse\n1.8 m ochre marker · responses: %d\n" % response_count
	if player.position.distance_to(creature.position) <= 3.0:
		label.text += "Press E to wake the harbor bell."

func _smoke_inputs(delta: float) -> void:
	smoke_seconds += delta
	if smoke_phase == 0:
		Input.action_press("walk_forward")
		smoke_phase = 1
	if smoke_seconds > 1.0 and smoke_phase == 1:
		Input.action_release("walk_forward")
		Input.action_press("respond")
		smoke_phase = 2
	elif smoke_phase == 2:
		Input.action_release("respond")
		smoke_phase = 3
	if smoke_seconds > 5:
		var report := {
			"kind": "technical_runtime_smoke", "engine_version": Engine.get_version_info().string,
			"imported_clips": animation_player.get_animation_list(), "bone_count": rig.get_bone_count(),
			"moved_distance_m": moved_distance, "response_count": response_count,
			"audio_player_started": audio_started, "motion_pose_changed": motion_changed,
			"returned_to_idle": animation_player.current_animation == idle_clip,
			"physics_step_peak_ms": peak_frame_ms, "audio_driver": AudioServer.get_driver_name(),
			"ordinary_input_review": "not_run", "visual_review": "not_run", "listening": "not_run"
		}
		report["ok"] = moved_distance > 1.5 and response_count == 1 and audio_started and motion_changed and animation_player.current_animation == idle_clip
		var file := FileAccess.open(smoke_output, FileAccess.WRITE)
		if file == null:
			_fail("Cannot write smoke evidence")
			return
		file.store_string(JSON.stringify(report, "\t"))
		file.close()
		smoking = false
		set_physics_process(false)
		_finish_smoke(report.ok)

func _finish_smoke(ok: bool) -> void:
	# Release the mixer-owned streams before shutting down the isolated process.
	cue.stop()
	ambience.stop()
	cue.stream = null
	ambience.stream = null
	await get_tree().create_timer(0.15).timeout
	get_tree().quit(0 if ok else 1)

func _fail(message: String) -> void:
	failed = true
	push_error(message)
	get_tree().quit(1)
