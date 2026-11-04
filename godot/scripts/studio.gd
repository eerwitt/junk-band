extends Control

const PAPER := Color("f7f5ec")
const INK := Color("29271f")
const MUTED := Color("716b5d")
const LINE := Color("dcd6c7")
const ORANGE := Color("b86339")
const MINT := Color("dce5db")
const FONT := preload("res://assets/NotoSans-Regular.ttf")
const MAX_PERFORMERS: int = 24
const SAVE_ICON := preload("res://assets/save.svg")
const ADD_ICON := preload("res://assets/add.svg")
const PLAY_ICON := preload("res://assets/play.svg")
const PAUSE_ICON := preload("res://assets/pause.svg")

var bridge: JunkBrowserBridge
var stage: JunkStage
var project: Dictionary = {}
var selection: String = ""
var playing: bool = false
var _syncing: bool = false
var _mobile: bool = false
var _play: Button
var _tempo: JunkTempoDial
var _transport: HBoxContainer
var _menu: JunkPerformerMenu
var _layout_controls: Dictionary = {}
var _content: HBoxContainer
var _center: VBoxContainer
var _last_layout_size := Vector2.ZERO
var _metric_elapsed: float = 0.0
var _play_pop: float = 10.0


func _ready() -> void:
	var studio_theme := Theme.new()
	studio_theme.default_font = FONT
	studio_theme.default_font_size = 13
	studio_theme.set_color("font_color", "Label", INK)
	studio_theme.set_color("font_color", "Button", INK)
	studio_theme.set_color("font_hover_color", "Button", INK)
	studio_theme.set_color("font_pressed_color", "Button", INK)
	studio_theme.set_stylebox("normal", "Button", _box(PAPER, LINE))
	studio_theme.set_stylebox("hover", "Button", _box(Color("eae4d4"), Color("b9ad96")))
	studio_theme.set_stylebox("pressed", "Button", _box(MINT, Color("a4b7a7")))
	studio_theme.set_stylebox("focus", "Button", _box(Color.TRANSPARENT, ORANGE, 2))
	studio_theme.set_stylebox("normal", "LineEdit", _box(PAPER, LINE))
	studio_theme.set_stylebox("focus", "LineEdit", _box(PAPER, ORANGE))
	studio_theme.set_color("font_color", "LineEdit", INK)
	studio_theme.set_color("caret_color", "LineEdit", ORANGE)
	studio_theme.set_color("font_selected_color", "LineEdit", INK)
	studio_theme.set_color("selection_color", "LineEdit", Color("eed479"))
	var separator := StyleBoxLine.new()
	separator.color = LINE
	separator.thickness = 1
	studio_theme.set_stylebox("separator", "HSeparator", separator)
	theme = studio_theme
	bridge = JunkBrowserBridge.new()
	add_child(bridge)
	bridge.packet_received.connect(_on_packet)
	_build()
	if not bridge.connect_browser():
		var file := FileAccess.open("res://assets/demo.json", FileAccess.READ)
		if file != null:
			var parsed: Variant = JSON.parse_string(file.get_as_text())
			if parsed is Dictionary:
				_apply_state({"project": parsed, "selected": "p-0", "playing": false, "saved": false, "mode": "editor preview", "notice": "Stage preview. Run the web export for browser audio, media and model services."})
	resized.connect(_on_resize)
	_on_resize.call_deferred()


func _box(fill: Color, border: Color = Color.TRANSPARENT, width: int = 1) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.set_border_width_all(width)
	box.set_corner_radius_all(5)
	box.content_margin_left = 12
	box.content_margin_right = 12
	box.content_margin_top = 8
	box.content_margin_bottom = 8
	return box


func _label(text: String, font_size: int = 13, color: Color = INK) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label


func _button(text: String, callback: Callable, accent: bool = false) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size.y = 38
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	if accent:
		button.add_theme_stylebox_override("normal", _box(ORANGE, ORANGE))
		button.add_theme_stylebox_override("hover", _box(Color("a65330"), Color("a65330")))
		button.add_theme_color_override("font_color", Color("fffdf5"))
		button.add_theme_color_override("font_hover_color", Color("fffdf5"))
	button.pressed.connect(callback)
	return button


func _margin(parent: Node, inset: int = 20) -> MarginContainer:
	var margin := MarginContainer.new()
	for side: String in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, inset)
	parent.add_child(margin)
	return margin


func _vbox(parent: Node, gap: int = 12) -> VBoxContainer:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", gap)
	parent.add_child(box)
	return box


func _hbox(parent: Node, gap: int = 10) -> HBoxContainer:
	var box := HBoxContainer.new()
	box.add_theme_constant_override("separation", gap)
	parent.add_child(box)
	return box


func _space(parent: Node) -> void:
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(spacer)


func _build() -> void:
	var root := VBoxContainer.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)
	var content := _hbox(root, 0)
	_content = content
	content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var center := _vbox(content, 0)
	_center = center
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.custom_minimum_size.x = 380
	stage = JunkStage.new()
	stage.bridge = bridge
	stage.size_flags_vertical = Control.SIZE_EXPAND_FILL
	stage.custom_minimum_size = Vector2(350, 260)
	stage.action.connect(_stage_action)
	center.add_child(stage)
	_build_transport(stage)
	var stage_footer := _hbox(_margin(center, 12), 6)
	_space(stage_footer)
	var keys := _button("Keys", func() -> void: bridge.command("help"))
	stage_footer.add_child(keys)
	_layout_controls["help"] = keys
	var export_button := _button("", func() -> void: bridge.command("export"), true)
	export_button.icon = SAVE_ICON
	export_button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	export_button.tooltip_text = "Save WAV"
	export_button.custom_minimum_size.x = 42
	stage_footer.add_child(export_button)
	_layout_controls["export"] = export_button
	_menu = JunkPerformerMenu.new()
	add_child(_menu)
	_menu.changed.connect(func(id: String, patch: Dictionary) -> void: bridge.command("update_performer", {"id": id, "patch": patch}))
	_menu.duplicate_requested.connect(func(id: String) -> void: bridge.command("select", {"id": id}); bridge.command("clone"))
	_menu.delete_requested.connect(func(id: String) -> void: bridge.command("select", {"id": id}); bridge.command("remove"))
	_menu.dismissed.connect(func() -> void: stage.inspected_id = ""; _publish_layout.call_deferred())
	_menu.path_requested.connect(func(id: String) -> void: stage.start_path(id))
	_menu.clear_path_requested.connect(func(id: String) -> void: stage.erase_path(id); bridge.command("update_performer", {"id": id, "patch": {"path": []}}))
	_menu.spotlight_changed.connect(func(id: String) -> void: bridge.command("spotlight", {"id": id} if id else {}))
	_menu.settled.connect(func() -> void: _publish_layout.call_deferred())
	_menu.tapped.connect(func(id: String) -> void: bridge.command("tap_note", {"id": id}))


func _cardboard_button(icon: Texture2D, hint: String, callback: Callable) -> Button:
	var button := _button("", callback)
	button.icon = icon
	button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	button.tooltip_text = hint
	button.custom_minimum_size = Vector2(56, 48)
	for state: String in ["normal", "hover", "pressed", "focus"]:
		var style := JunkCardboardStyle.new()
		style.paper = ORANGE.lightened(0.08) if state == "hover" else ORANGE
		style.pressed = state == "pressed"
		if state == "focus":
			style.paper = Color.TRANSPARENT
			style.ink = INK
		button.add_theme_stylebox_override(state, style)
	return button


func _build_transport(parent: Node) -> void:
	_transport = HBoxContainer.new()
	_transport.z_index = 2000
	_transport.add_theme_constant_override("separation", 18)
	parent.add_child(_transport)
	_play = _cardboard_button(PLAY_ICON, "Play", func() -> void: bridge.command("toggle"))
	_transport.add_child(_play)
	_layout_controls["play"] = _play
	_tempo = JunkTempoDial.new()
	_tempo.value_changed.connect(func(value: int) -> void:
		if not _syncing: bridge.command("settings", {"bpm": value})
	)
	_transport.add_child(_tempo)
	_layout_controls["bpm"] = _tempo
	var bring := _cardboard_button(ADD_ICON, "Add a sound or video", func() -> void: bridge.command("source"))
	_transport.add_child(bring)
	_layout_controls["source"] = bring


func _stage_action(kind: String, payload: Dictionary) -> void:
	if kind == "inspect":
		selection = str(payload.id)
		var performer: Dictionary = _selected()
		if not performer.is_empty():
			stage.inspected_id = selection
			_menu.open_for(performer, stage.performer_anchor(selection))
			_publish_layout.call_deferred()
	elif kind == "close_inspector":
		_menu.close()
	else:
		bridge.command(kind, payload)


func _selected() -> Dictionary:
	for performer: Dictionary in project.get("performers", []):
		if str(performer.id) == selection: return performer
	return {}


func _on_packet(packet: Dictionary) -> void:
	match str(packet.get("type", "")):
		"arrival": stage.queue_arrival(str(packet.id), str(packet.get("kind", "")), str(packet.get("source", "")))
		"departure": stage.queue_departure(str(packet.id))
		"close_inspector": _menu.close()
		"state": _apply_state(packet)
		"texture":
			stage.set_texture(str(packet.assetId), str(packet.data))
			stage.apply_scene(project, selection)


func _apply_state(packet: Dictionary) -> void:
	project = packet.get("project", project)
	selection = str(packet.get("selected", selection))
	var was_playing: bool = playing
	playing = bool(packet.get("playing", false))
	if playing != was_playing: _play_pop = 0.0
	_syncing = true
	_play.icon = PAUSE_ICON if playing else PLAY_ICON
	_play.tooltip_text = "Pause" if playing else "Play"
	_tempo.set_value_quiet(float(project.get("bpm", 112)))
	_menu.set_stage_full(project.get("performers", []).size() >= MAX_PERFORMERS)
	stage.reduced_motion = bool(packet.get("reducedMotion", false))
	_menu.reduced_motion = stage.reduced_motion
	_menu._holes.reduced_motion = stage.reduced_motion
	stage.apply_scene(project, selection)
	if _menu.visible:
		if selection != _menu.performer_id: _menu.close()
		else: _menu.sync(_selected())
	_syncing = false
	_publish_layout.call_deferred()


func _process(delta: float) -> void:
	if _transport == null: return
	_transport.size = _transport.get_combined_minimum_size()
	# Transport belongs to the viewport, independent of the world camera.
	var zoom: float = minf(0.8, minf(stage.size.x / 1400.0, stage.size.y / 820.0))
	# Sits clear of the ring at its most zoomed in, with the name band around it, so it never moves.
	var clear_of_ring: float = 264.0 * zoom * JunkStage.FOCUS_ZOOM + (JunkOrbitScrubber.BAND_GAP + JunkOrbitScrubber.BAND_WIDTH) * clampf(380.0 * zoom / 304.0, 0.55, 1.25) + 12.0
	_transport.position = Vector2((stage.size.x - _transport.size.x) / 2.0, minf(stage.size.y - _transport.size.y - 12.0, stage.size.y / 2.0 + clear_of_ring))
	var pulse: float = bridge.master_pulse if not stage.reduced_motion else 0.0
	_tempo.beat = bridge.beat()
	_tempo.playing = bridge.audio_playing
	_menu.beat = bridge.beat()
	_menu.playing = bridge.audio_playing
	if _transport.get_global_rect().has_point(get_global_mouse_position()) or _tempo.dragging: pulse *= 0.15
	_transport.position.y -= pulse * 1.8
	_transport.pivot_offset = _transport.size / 2.0
	_transport.scale = Vector2.ONE * (1.0 + pulse * 0.004)
	# The button thumps down as it is struck and springs back with a little wobble.
	_play_pop += delta
	_play.pivot_offset = _play.size / 2.0
	var thump: float = 0.0 if stage.reduced_motion else exp(-_play_pop * 9.0) * cos(_play_pop * 30.0)
	_play.scale = Vector2(1.0 + thump * 0.07, 1.0 - thump * 0.09)
	_play.rotation = thump * 0.05
	if _menu.visible:
		_menu.arrange(stage.performer_anchor(_menu.performer_id))
	_metric_elapsed += delta
	if size != _last_layout_size:
		_last_layout_size = size
		_on_resize()
	if _metric_elapsed >= 1.0:
		_metric_elapsed = 0.0
		_publish_layout()


func _on_resize() -> void:
	_mobile = size.x < 850
	_center.custom_minimum_size.x = 350 if _mobile else 380
	stage.custom_minimum_size.y = 180 if _mobile else 260
	_publish_layout.call_deferred()


func _publish_layout() -> void:
	if bridge == null or stage == null: return
	var controls: Dictionary = {}
	for key: String in _layout_controls:
		var control: Control = _layout_controls[key]
		var rect: Rect2 = control.get_global_rect()
		controls[key] = {"x": rect.position.x, "y": rect.position.y, "w": rect.size.x, "h": rect.size.y, "visible": control.is_visible_in_tree()}
	for key: String in _menu.controls:
		var control: Control = _menu.controls[key]
		var rect: Rect2 = control.get_global_rect()
		# Still dealing out: not where it will be, so not yet reported as there.
		controls[key] = {"x": rect.position.x, "y": rect.position.y, "w": rect.size.x, "h": rect.size.y, "visible": control.is_visible_in_tree() and _menu.is_settled()}
	var orbit_handle: Vector2 = stage.global_position + stage.scrubber.position + stage.scrubber.point_at(0.25)
	controls["scrub"] = {"x": orbit_handle.x - 12, "y": orbit_handle.y - 12, "w": 24, "h": 24, "visible": stage.is_visible_in_tree()}
	bridge.publish_layout({"rigs": stage.rig_snapshot(), "viewport": {"x": size.x, "y": size.y}, "controls": controls, "inspector": _menu.is_settled(), "loopBeats": JunkLoopTiming.BEATS, "pathDrawing": stage.draw_path, "focusSection": stage.focus_id, "hoverSection": stage.scrubber.hover_index, "sectionReveal": stage.scrubber.reveal_amount(), "sectionZoom": stage._section_zoom, "puppets": stage.puppet_snapshot(), "landingCount": stage.landing_count(), "fps": Engine.get_frames_per_second(), "stage": {"x": stage.global_position.x, "y": stage.global_position.y, "w": stage.size.x, "h": stage.size.y, "zoom": stage.world_zoom(), "originX": stage._world.position.x, "originY": stage._world.position.y, "cameraZoom": stage.camera_zoom}})


func _unhandled_key_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo: return
	var focus: Control = get_viewport().gui_get_focus_owner()
	if focus is LineEdit or focus is TextEdit: return
	if event.keycode == KEY_SPACE:
		bridge.command("toggle")
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_Z and (event.ctrl_pressed or event.meta_pressed): bridge.command("undo")
	elif event.keycode == KEY_DELETE: bridge.command("remove")
	elif event.keycode == KEY_R: bridge.command("export")
	elif event.keycode == KEY_HOME:
		stage.reset_camera()
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_ESCAPE:
		stage.cancel_path()
		stage.exit_section()
		_menu.close()
