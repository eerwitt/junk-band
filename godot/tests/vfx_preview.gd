extends SceneTree
## Renders the real studio with the base band against a simulated audio clock, and saves
## frames for looking at motion and effects without a browser. Needs a display (xvfb).
##   godot --path godot --script res://tests/vfx_preview.gd -- --band=band.json --out=frames --scenario=dance
## `--band` is the JSON written by scripts/preview_vfx.py: {project, events}.

var _studio: Control
var _stage: JunkStage
var _bridge: JunkBrowserBridge
var _project: Dictionary
var _events: Array = []
var _bpm: float = 112.0
var _clock: float = 0.0
var _playing: bool = true
var _frame: int = 0
var _out: String = ""
var _scenario: String = "dance"
var _shots: Dictionary = {}
var _end_frame: int = 0
var _band_root: String = ""
var _steps: Array = []
var _metrics: Dictionary = {}
var _measure: bool = false


func _initialize() -> void:
	_audio_off()

	var args: Dictionary = {}
	for argument: String in OS.get_cmdline_user_args():
		var parts: PackedStringArray = argument.trim_prefix("--").split("=", true, 1)
		args[parts[0]] = parts[1] if parts.size() > 1 else "1"
	_out = str(args.get("out", "user://frames"))
	_scenario = str(args.get("scenario", "dance"))
	_measure = args.has("metrics")
	_band_root = str(args.get("public", ProjectSettings.globalize_path("res://").path_join("../public")))
	DirAccess.make_dir_recursive_absolute(_out)
	var parsed: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(str(args.band)))
	_project = parsed.project
	_events = parsed.events
	_bpm = float(_project.bpm)
	_clock = float(args.get("start", "0")) * 60.0 / _bpm
	var studio_scene: PackedScene = load("res://scenes/studio.tscn")
	_studio = studio_scene.instantiate()
	root.add_child(_studio)
	_setup.call_deferred(args)


func _setup(args: Dictionary) -> void:
	_stage = _studio.stage
	_bridge = _studio.bridge
	for asset: Dictionary in _project.assets:
		var image := Image.load_from_file(_band_root.path_join(str(asset.sprite).trim_prefix("/")))
		if image != null: _stage.textures[str(asset.id)] = ImageTexture.create_from_image(image)
	_studio._apply_state({"project": _project, "selected": "", "playing": true})
	process_frame.connect(_tick)
	# Stand in for the browser store: apply the stage's own edits to the project.
	_stage.action.connect(func(kind: String, payload: Dictionary) -> void:
		if kind != "update_performer": return
		for performer: Dictionary in _project.performers:
			if str(performer.id) == str(payload.id): performer.merge(payload.patch, true)
		_studio._apply_state({"project": _project, "selected": str(payload.id), "playing": _playing})
	)
	match _scenario:
		"dance":
			_end_frame = int(args.get("frames", "180"))
			for index: int in range(0, _end_frame, int(args.get("every", "6"))): _shots[index] = true
		_:
			_steps = _scenario_steps(_scenario)
			for step: Dictionary in _steps: _end_frame = maxi(_end_frame, int(step.at) + 1)
			for index: int in range(0, _end_frame, int(args.get("every", "3"))): _shots[index] = true


func _audio_off() -> void:
	pass


## Scripted moments, frame-indexed at 60 fps.
func _scenario_steps(name: String) -> Array:
	match name:
		"pause": return [{"at": 30, "do": "pause"}, {"at": 120, "do": "play"}]
		"remove": return [{"at": 20, "do": "remove", "id": "p-7"}, {"at": 110, "do": "noop"}]
		"arrive": return [{"at": 10, "do": "add", "id": "p-new", "hero": true}, {"at": 150, "do": "noop"}]
		"clone": return [{"at": 10, "do": "add", "id": "p-clone", "source": "p-7"}, {"at": 110, "do": "noop"}]
		"menu": return [{"at": 10, "do": "inspect", "id": "p-7"}, {"at": 60, "do": "close"}, {"at": 90, "do": "noop"}]
		"card": return [{"at": 5, "do": "inspect", "id": "p-7"}, {"at": 30, "do": "card"}, {"at": 60, "do": "punch", "step": 2}, {"at": 75, "do": "punch", "step": 6}, {"at": 110, "do": "noop"}]
		"path": return [{"at": 5, "do": "path", "id": "p-7"}, {"at": 70, "do": "path_end", "id": "p-7"}, {"at": 160, "do": "erase", "id": "p-7"}, {"at": 200, "do": "noop"}]
		"wrap": return [{"at": 200, "do": "noop"}]
		"walk": return [{"at": 200, "do": "noop"}]
	return [{"at": 60, "do": "noop"}]


func _apply_step(step: Dictionary) -> void:
	match str(step.do):
		"pause":
			_playing = false
			_studio._apply_state({"project": _project, "selected": "", "playing": false})
		"play":
			_playing = true
			_studio._apply_state({"project": _project, "selected": "", "playing": true})
		"remove":
			_studio._on_packet({"type": "departure", "id": str(step.id)})
			_project.performers = _project.performers.filter(func(p: Dictionary) -> bool: return str(p.id) != str(step.id))
			_studio._apply_state({"project": _project, "selected": "", "playing": _playing})
		"add":
			var source: Dictionary = _project.performers[7].duplicate(true)
			if step.has("source"):
				for performer: Dictionary in _project.performers:
					if str(performer.id) == str(step.source): source = performer.duplicate(true)
			source.id = str(step.id)
			source.position = {"x": float(source.position.x) + 70.0, "y": float(source.position.y) + 40.0}
			_project.performers.append(source)
			_studio._on_packet({"type": "arrival", "id": source.id, "kind": "new" if bool(step.get("hero", false)) else "clone", "source": str(step.get("source", ""))})
			_studio._apply_state({"project": _project, "selected": "", "playing": _playing})
		"inspect": _studio._stage_action("inspect", {"id": str(step.id)})
		"close": _studio._menu.close()
		"card": _studio._menu._set_card_open(true)
		"punch": _studio._menu._toggle_step(int(step.step))
		"path":
			_stage.start_path(str(step.id))
			var puppet: JunkPuppet = _stage._puppets[str(step.id)]
			var at: Vector2 = _screen(puppet.position + Vector2(0, -40))
			_path_start = at
			_mouse(at, true)
		"path_end":
			print("path points ", _stage._path_points.size())
			_mouse(Vector2.ZERO, false)
		"erase":
			for performer: Dictionary in _project.performers:
				if str(performer.id) == str(step.id): performer.path = []
			_studio._menu.clear_path_requested.emit(str(step.id))
			_studio._apply_state({"project": _project, "selected": "", "playing": _playing})


func _screen(world: Vector2) -> Vector2:
	return _stage._world.position + world * _stage.world_zoom()


func _mouse(at: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = pressed
	event.position = at if pressed else _last_mouse
	_last_mouse = event.position
	_stage._gui_input(event)

var _last_mouse: Vector2
var _path_start: Vector2


func _tick() -> void:
	var delta: float = 1.0 / 60.0
	for step: Dictionary in _steps:
		if int(step.at) == _frame: _apply_step(step)
	if _scenario == "path" and _frame > 5 and _frame < 70:
		var t: float = float(_frame - 5) / 64.0
		var motion := InputEventMouseMotion.new()
		motion.position = _path_start + Vector2(sin(t * TAU) * 150.0, (1.0 - cos(t * TAU)) * -45.0 + sin(t * TAU * 2.0) * 20.0)
		_last_mouse = motion.position
		_stage._gui_input(motion)
	if _playing: _clock += delta
	var beat: float = _clock * _bpm / 60.0
	_bridge._current_beat = fposmod(beat, 64.0)
	_bridge.audio_playing = _playing
	_bridge.master_pulse = _pulse(fposmod(beat, 1.0), 0.55) * (1.0 if int(beat) % 4 == 0 else 0.7) if _playing else 0.0
	var pulses: Dictionary = {}
	var hits: Dictionary = {}
	var duration: float = 0.45 * 60.0 / _bpm
	var song: float = 64.0 * 60.0 / _bpm
	var now: float = fposmod(_clock, song)
	for event: Dictionary in _events:
		var at: float = float(event.step) / 4.0 * 60.0 / _bpm
		var age: float = now - at
		if age < 0.0: age += song
		if age < 0.0 or age > 1.0 or not _playing: continue
		var id: String = str(event.performerId)
		pulses[id] = maxf(float(pulses.get(id, 0.0)), _pulse(age, duration) * float(event.velocity))
		if not hits.has(id) or age < float(hits[id][0]): hits[id] = [age, float(event.velocity)]
	_bridge._pulses = pulses
	if "_hits" in _bridge: _bridge.set("_hits", hits)
	if _measure: _record.call_deferred()
	_capture.call_deferred(_frame)
	_frame += 1


func _record() -> void:
	for id: String in _stage._puppets:
		var puppet: JunkPuppet = _stage._puppets[id]
		var sample: Array = [puppet._body.rotation, -puppet._body.position.y, puppet._cardboard_yaw, puppet._body.scale.y / maxf(puppet._base_scale, 0.0001)]
		if not _metrics.has(id): _metrics[id] = [sample.duplicate(), sample.duplicate()]
		for index: int in range(4):
			_metrics[id][0][index] = minf(_metrics[id][0][index], sample[index])
			_metrics[id][1][index] = maxf(_metrics[id][1][index], sample[index])


func _report() -> void:
	for id: String in _metrics:
		var low: Array = _metrics[id][0]
		var high: Array = _metrics[id][1]
		print("%s %-11s %-6s style=%d  turn %5.1f deg  lift %5.1f  yaw %5.1f deg  scaleY %.3f..%.3f" % [id, str(_stage._puppets[id].performer.name).substr(0, 11), str(_stage._puppets[id].performer.motion), _stage._puppets[id]._groove_style, rad_to_deg(high[0] - low[0]), high[1] - low[1], rad_to_deg(high[2] - low[2]), low[3], high[3]])


func _pulse(age: float, duration: float) -> float:
	if age <= 0.0 or age >= duration: return 0.0
	var t: float = age / duration
	return sin(PI * t) * (1.0 - t) * 1.7


func _capture(index: int) -> void:
	if not _shots.has(index):
		if index >= _end_frame:
			if _measure: _report()
			quit()
		return
	await RenderingServer.frame_post_draw
	var image: Image = root.get_texture().get_image()
	image.save_png(_out.path_join("%s_%04d.png" % [_scenario, index]))
	if index >= _end_frame - 1:
		if _measure: _report()
		quit()
