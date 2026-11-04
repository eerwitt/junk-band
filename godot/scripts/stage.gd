class_name JunkStage
extends Control

signal action(kind: String, payload: Dictionary)

var selected_id: String = ""
var inspected_id: String = ""
var reduced_motion: bool = false
var draw_path: bool = false
var bridge: JunkBrowserBridge
var performers: Array = []
var textures: Dictionary = {}
var _rig_layers: Dictionary = {}
var _world: Node2D
var _puppets: Dictionary = {}
var _drag_id: String = ""
var _drag_origin: Vector2
var _drag_point: Vector2
var _grab_offset: Vector2 = Vector2.ZERO
var _moved: bool = false
var _path_points: PackedVector2Array = []
var _atlas: Texture2D = preload("res://assets/sprites.png")
var _ground: GradientTexture2D
var scrubber: JunkOrbitScrubber
var _cursor: String = "default"
var _path_home: Vector2
var _landing_count: int = 0
var camera_zoom: float = 1.0
var camera_pan: Vector2 = Vector2.ZERO
var _panning: bool = false
var _pan_pointer: Vector2 = Vector2.ZERO
var _pending_arrivals: Dictionary = {}
var _arrival_seen: Dictionary = {}
var _impact_age: float = 10.0
var _impact_kick: Vector2 = Vector2.ZERO
const FOCUS_ZOOM: float = 1.1
const WING_CLEARANCE: float = 100.0
const NOTE_ROW_HEIGHT: float = 40.0
const NOTE_ROWS: int = 5
const WING_SLOTS: Array[Vector2] = [
	Vector2(470, -40), Vector2(545, 70), Vector2(440, -175), Vector2(555, -130),
	Vector2(455, 160), Vector2(385, 245), Vector2(330, -240), Vector2(555, 190),
]
const RING_RADII := Vector2(380, 230)
const SIT_OUT_RADIUS: float = 1.06
## The section being looped and zoomed into. Empty plays the whole song.
var focus_id: String = ""
var sections: Array = []
var _section_zoom: float = 1.0
var _scrub_origin: Vector2 = Vector2.ZERO
var _scrub_moved: bool = false
var _press_section: int = -1


func queue_arrival(id: String) -> void:
	if not _arrival_seen.has(id): _pending_arrivals[id] = true


func cancel_path() -> void:
	draw_path = false
	if scrubber != null:
		scrubber.dragging = false
	mouse_default_cursor_shape = Control.CURSOR_ARROW
	if _puppets.has(_drag_id):
		_puppets[_drag_id].end_pickup()
	_drag_id = ""
	_path_points.clear()
	_moved = false
	queue_redraw()
	_set_cursor("default")


func start_path(id: String) -> void:
	cancel_path()
	selected_id = id
	draw_path = true
	mouse_default_cursor_shape = Control.CURSOR_CROSS


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	focus_mode = Control.FOCUS_ALL
	var gradient := Gradient.new()
	gradient.offsets = PackedFloat32Array([0.0, 0.58, 1.0])
	gradient.colors = PackedColorArray([Color(0.86, 0.82, 0.70, 0.30), Color(0.86, 0.82, 0.70, 0.17), Color(0.86, 0.82, 0.70, 0.0)])
	_ground = GradientTexture2D.new()
	_ground.gradient = gradient
	_ground.width = 512
	_ground.height = 512
	_ground.fill = GradientTexture2D.FILL_RADIAL
	_ground.fill_from = Vector2(0.5, 0.5)
	_ground.fill_to = Vector2(0.5, 0.0)
	scrubber = JunkOrbitScrubber.new()
	add_child(scrubber)
	_world = Node2D.new()
	add_child(_world)
	resized.connect(queue_redraw)
	mouse_exited.connect(_pointer_left)


func _set_cursor(cursor: String) -> void:
	if cursor == _cursor:
		return
	_cursor = cursor
	if bridge != null:
		bridge.set_cursor(cursor)


func _pointer_left() -> void:
	scrubber.hovered = false
	scrubber.hover_index = -1
	scrubber.over_band = false
	if not scrubber.dragging and _drag_id.is_empty():
		_set_cursor("default")


func apply_scene(project: Dictionary, selection: String) -> void:
	selected_id = selection
	performers = project.get("performers", [])
	_apply_sections(project.get("sections", []))
	var keep: Dictionary = {}
	for performer: Dictionary in performers:
		var id: String = str(performer.id)
		keep[id] = true
		if not _puppets.has(id):
			var puppet := JunkPuppet.new()
			puppet.position = Vector2(float(performer.position.x), float(performer.position.y))
			_puppets[id] = puppet
			_world.add_child(puppet)
			puppet.landed.connect(_landed.bind(puppet))
		var current: JunkPuppet = _puppets[id]
		current.performer = performer
		current.path_knots = JunkMotionMath.closed_path(performer)
		current.visible = false
		for asset: Dictionary in project.get("assets", []):
			if asset.id == performer.assetId:
				var imported: bool = _sent_as_texture(str(asset.get("sprite", "")))
				if imported and not textures.has(str(asset.id)): break
				if _pending_arrivals.has(id) and asset.has("rig"):
					var ready: bool = _rig_layers.has(str(asset.rig.body))
					for part: Dictionary in asset.rig.parts: ready = ready and _rig_layers.has(str(part.sprite))
					if not ready: break
				current.set_art(texture_for(asset))
				current._rig.configure(current, asset.get("rig", {}), _rig_layers)
				current.visible = true
				if _pending_arrivals.has(id):
					_pending_arrivals.erase(id)
					_arrival_seen[id] = true
					current.arrive(reduced_motion)
				break
	for id: String in _puppets.keys():
		if not keep.has(id):
			_pending_arrivals.erase(id)
			_arrival_seen.erase(id)
			_puppets[id].queue_free()
			_puppets.erase(id)
	_place_wings()
	queue_redraw()


func _apply_sections(next: Array) -> void:
	sections = next
	var spans: Array = []
	for section: Dictionary in sections:
		spans.append({"start": float(section.startBar) / JunkLoopTiming.BARS, "end": float(section.endBar) / JunkLoopTiming.BARS, "label": str(section.label)})
	scrubber.set_sections(spans)
	scrubber.hover_index = -1 if scrubber.hover_index >= spans.size() else scrubber.hover_index
	if focus_id.is_empty():
		scrubber.focus_index = -1
		return
	var found: int = _section_index(focus_id)
	if found < 0:
		exit_section()
		return
	var previous: int = scrubber.focus_index
	scrubber.focus_index = found
	if previous != found: _announce_focus()


func _section_index(id: String) -> int:
	for index: int in range(sections.size()):
		if str(sections[index].id) == id: return index
	return -1


func _announce_focus() -> void:
	var section: Dictionary = sections[scrubber.focus_index]
	action.emit("focus_section", {"start": float(section.startBar) * (JunkLoopTiming.BEATS / JunkLoopTiming.BARS), "end": float(section.endBar) * (JunkLoopTiming.BEATS / JunkLoopTiming.BARS)})


func enter_section(index: int) -> void:
	if index < 0 or index >= sections.size(): return
	action.emit("close_inspector", {})
	focus_id = str(sections[index].id)
	scrubber.focus_index = index
	_announce_focus()


func exit_section() -> void:
	if focus_id.is_empty(): return
	focus_id = ""
	scrubber.focus_index = -1
	scrubber.over_band = false
	action.emit("focus_section", {})


## Everyone waits somewhere different, scattered round the ring near their own side, unless
## they have been put somewhere by hand. Slots are for the right side and mirrored for the left.
func _place_wings() -> void:
	var taken: Array[Vector2] = []
	var unplaced: Array = []
	for index: int in range(performers.size()):
		var performer: Dictionary = performers[index]
		var id: String = str(performer.id)
		if not _puppets.has(id): continue
		_puppets[id].walk_style = index % 3
		if performer.get("wing") is Dictionary:
			var spot := Vector2(float(performer.wing.x), float(performer.wing.y))
			_puppets[id].wing_point = spot
			taken.append(spot)
		else:
			unplaced.append(performer)
	for performer: Dictionary in unplaced:
		var id: String = str(performer.id)
		var side: float = -1.0 if float(performer.position.x) < 0.0 else 1.0
		var spot: Vector2 = _free_wing(side, absi(id.hash()), taken)
		_puppets[id].wing_point = spot
		taken.append(spot)


func _free_wing(side: float, seed_value: int, taken: Array[Vector2]) -> Vector2:
	for attempt_side: float in [side, -side]:
		for offset: int in range(WING_SLOTS.size()):
			var slot: Vector2 = WING_SLOTS[(seed_value + offset * 3) % WING_SLOTS.size()]
			var spot := Vector2(slot.x * attempt_side, slot.y)
			var clear: bool = true
			for other: Vector2 in taken:
				if other.distance_to(spot) < WING_CLEARANCE: clear = false
			if clear: return spot
	# A very full stage: share a slot, a little to one side of whoever is there.
	var slot: Vector2 = WING_SLOTS[seed_value % WING_SLOTS.size()]
	return Vector2((slot.x - 28.0) * side, slot.y + 24.0)


func _rest_in_wings(id: String, spot: Vector2) -> void:
	var puppet: JunkPuppet = _puppets[id]
	puppet.wing_point = spot
	puppet.set_present(false)
	puppet.finish_path()
	action.emit("update_performer", {"id": id, "patch": {"wing": {"x": spot.x, "y": spot.y}}})


func _section_id_at(beat_value: float) -> String:
	var section: int = scrubber.section_at_fraction(fposmod(beat_value, JunkLoopTiming.BEATS) / JunkLoopTiming.BEATS)
	return str(sections[section].id) if section >= 0 and section < sections.size() else ""


func _sits_out(id: String, beat_value: float) -> bool:
	var section: int = scrubber.section_at_fraction(fposmod(beat_value, JunkLoopTiming.BEATS) / JunkLoopTiming.BEATS)
	if section < 0 or section >= sections.size(): return false
	return sections[section].get("mutedIds", []).has(id)


func _outside_ring(point: Vector2) -> bool:
	return Vector2(point.x / RING_RADII.x, point.y / RING_RADII.y).length() > SIT_OUT_RADIUS


func puppet_snapshot() -> Dictionary:
	var result: Dictionary = {}
	for id: String in _puppets:
		var puppet: JunkPuppet = _puppets[id]
		result[id] = {"x": puppet.position.x, "y": puppet.position.y, "presence": puppet.presence, "alpha": puppet._body.modulate.a, "style": puppet.walk_style, "wingX": puppet.wing_point.x, "wingY": puppet.wing_point.y}
	return result


## Everything but the old sprite sheet arrives from the browser, once it has loaded.
func _sent_as_texture(sprite: String) -> bool:
	return sprite.begins_with("blob:asset:") or sprite.begins_with("/band/")


func texture_for(asset: Dictionary) -> Texture2D:
	if textures.has(str(asset.id)):
		return textures[str(asset.id)]
	if _sent_as_texture(str(asset.get("sprite", ""))): return null
	var atlas := AtlasTexture.new()
	atlas.atlas = _atlas
	var tile: int = int(asset.get("tile", 0))
	var regions: Array[Rect2] = [Rect2(0.10, 0.01, 0.33, 0.47), Rect2(0.55, 0.01, 0.36, 0.47), Rect2(0.13, 0.48, 0.26, 0.49), Rect2(0.56, 0.48, 0.32, 0.49)]
	var region: Rect2 = regions[clampi(tile, 0, 3)]
	atlas.region = Rect2(region.position * _atlas.get_size(), region.size * _atlas.get_size())
	textures[str(asset.id)] = atlas
	return atlas


func set_texture(asset_id: String, encoded: String) -> void:
	var image := Image.new()
	var result: Error = image.load_png_from_buffer(Marshalls.base64_to_raw(encoded))
	if result != OK:
		push_error("Could not decode accepted cutout")
		return
	if asset_id.begins_with("blob:asset:"):
		var bounds: Rect2i = image.get_used_rect()
		if not bounds.has_area(): return
		_rig_layers[asset_id] = {"texture": ImageTexture.create_from_image(image.get_region(bounds)), "center": Vector2(bounds.position) + Vector2(bounds.size) * 0.5 - Vector2(image.get_size()) * 0.5, "canvas": Vector2(image.get_size())}
		return
	textures[asset_id] = ImageTexture.create_from_image(image)


func rig_snapshot() -> Array:
	var result: Array = []
	for id: String in _puppets:
		var puppet: JunkPuppet = _puppets[id]
		if puppet._rig.pieces.is_empty(): continue
		var joints: Dictionary = {}
		for piece: Dictionary in puppet._rig.pieces: joints[piece.name] = piece.angle
		result.append({"id": id, "pieces": puppet._rig.pieces.size(), "joints": joints, "held": puppet._held, "height": puppet._lift_height})
	return result


func world_zoom() -> float:
	return minf(0.8, minf(size.x / 1400.0, size.y / 820.0)) * camera_zoom * _section_zoom


func _sync_camera() -> void:
	var zoom: float = world_zoom()
	_world.position = size / 2.0 + Vector2(0, 34 * zoom) + camera_pan + _impact_offset()
	_world.scale = Vector2.ONE * zoom
	scrubber.position = _world.position
	scrubber.radii = Vector2(380, 230) * zoom


## The stage takes the hit and rings out. Fixed viewport controls do not move with it.
func _impact_offset() -> Vector2:
	if _impact_age >= 0.5: return Vector2.ZERO
	return _impact_kick * exp(-_impact_age * 11.0) * cos(_impact_age * 52.0)


func _kick_stage(point: Vector2, strength: float, puppet: JunkPuppet) -> void:
	if reduced_motion: return
	_impact_age = 0.0
	if puppet != null and puppet._slide_drop:
		# A skid shoves sideways along its travel, and leaves neighbours undisturbed.
		_impact_kick = puppet._slide_velocity.normalized() * lerpf(0.5, 1.4, strength)
		return
	_impact_kick = Vector2(0, lerpf(3.5, 9.0, strength))
	for id: String in _puppets:
		var other: JunkPuppet = _puppets[id]
		if other == puppet: continue
		# Measured on the floor plane, since screen Y is foreshortened.
		var gap := other.position - point
		var distance: float = Vector2(gap.x, gap.y / JunkLandingEffect.FLOOR_SQUASH).length()
		if distance < 210.0:
			other.jolt((1.0 - distance / 210.0) * strength * 1.25, distance / 1000.0)


func zoom_at(pointer: Vector2, factor: float) -> void:
	var anchor: Vector2 = _world_point(pointer)
	camera_zoom = clampf(camera_zoom * factor, 0.5, 4.0)
	var zoom: float = world_zoom()
	camera_pan = pointer - size / 2.0 - Vector2(0, 34 * zoom) - anchor * zoom
	_sync_camera()
	if not _drag_id.is_empty(): _drag_point = _world_point(pointer) - _grab_offset
	queue_redraw()


func reset_camera() -> void:
	camera_zoom = 1.0
	camera_pan = Vector2.ZERO
	_sync_camera()
	queue_redraw()


func performer_anchor(id: String) -> Vector2:
	if _puppets.has(id):
		return _puppets[id].global_position + Vector2(0, -45 * world_zoom())
	return global_position + size / 2.0


func _landed(point: Vector2, strength: float, puppet: JunkPuppet = null) -> void:
	if _landing_count > 0 and _world.get_child_count() > _puppets.size() + 5: return
	var effect := JunkLandingEffect.new()
	effect.position = point
	effect.z_index = 3100
	effect.seed_value = _landing_count
	effect.strength = strength
	effect.pixel_zoom = world_zoom()
	effect.reduced_motion = reduced_motion
	if puppet != null: effect.configure(puppet)
	_world.add_child(effect)
	_landing_count += 1
	_kick_stage(point, strength, puppet)
	action.emit("impact", {"strength": strength})


func landing_count() -> int:
	return _landing_count


func _process(delta: float) -> void:
	if _world == null:
		return
	_impact_age += delta
	var zoom_target: float = FOCUS_ZOOM if not focus_id.is_empty() else 1.0
	if not is_equal_approx(_section_zoom, zoom_target):
		_section_zoom = lerpf(_section_zoom, zoom_target, 1.0 - exp(-5.5 * delta))
		if absf(_section_zoom - zoom_target) < 0.0005: _section_zoom = zoom_target
		queue_redraw()
	_sync_camera()
	scrubber.pulse =bridge.master_pulse if bridge != null and not reduced_motion else 0.0
	var current_beat: float = bridge.beat() if bridge != null else 0.0
	scrubber.advance(current_beat, delta)
	for id: String in _puppets:
		var puppet: JunkPuppet = _puppets[id]
		puppet.inspected = id == inspected_id
		puppet.set_present(not _sits_out(id, current_beat))
		if id == _drag_id:
			puppet.move_pickup(_drag_point)
		puppet.pose(current_beat, reduced_motion, delta, bridge.pulse_for(id) if bridge != null else 0.0)


## A character standing on the orbit line takes the pointer over the line beneath it.
## Uses the drawn art bounds, so the line stays reachable right beside a narrow character.
func _orbit_available(point: Vector2) -> bool:
	if not scrubber.hit(point): return false
	var world: Vector2 = _world_point(point)
	for id: String in _puppets:
		var puppet: JunkPuppet = _puppets[id]
		if puppet.visible and puppet._body.texture != null and puppet.floor_visual_bounds().has_point(world):
			return false
	return true


func _world_point(point: Vector2) -> Vector2:
	return (point - _world.position) / _world.scale


func _gui_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_HOME:
		reset_camera()
		accept_event()
		return
	if event is InputEventKey and event.pressed and event.keycode in [KEY_ENTER, KEY_KP_ENTER]:
		if focus_id.is_empty(): enter_section(scrubber.section_at_fraction(scrubber.beat / JunkLoopTiming.BEATS))
		else: exit_section()
		accept_event()
		return
	if event is InputEventMagnifyGesture:
		grab_focus()
		zoom_at(event.position, event.factor)
		accept_event()
		return
	if event is InputEventPanGesture:
		grab_focus()
		camera_pan -= event.delta * 12.0
		_sync_camera()
		queue_redraw()
		accept_event()
		return
	if event is InputEventMouseButton and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
		if event.pressed:
			grab_focus()
			zoom_at(event.position, pow(1.14, (1.0 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -1.0) * event.factor))
		accept_event()
		return
	if event is InputEventMouseButton and event.button_index in [MOUSE_BUTTON_MIDDLE, MOUSE_BUTTON_RIGHT]:
		if _drag_id.is_empty() and not scrubber.dragging:
			_panning = event.pressed
			_pan_pointer = event.position
			grab_focus()
			_set_cursor("grabbing" if _panning else "default")
		accept_event()
		return
	if event is InputEventMouseMotion and _panning:
		camera_pan += event.position - _pan_pointer
		_pan_pointer = event.position
		_sync_camera()
		queue_redraw()
		accept_event()
		return
	if _panning: return
	if event is InputEventKey and event.pressed and event.keycode in [KEY_LEFT, KEY_RIGHT, KEY_END]:
		var target: float = scrubber.beat
		if event.keycode == KEY_END: target = JunkLoopTiming.BEATS - 0.25
		else: target = clampf(target + (-0.25 if event.keycode == KEY_LEFT else 0.25), 0.0, JunkLoopTiming.BEATS - 0.25)
		action.emit("seek", {"beat": target})
		accept_event()
		return
	if event is InputEventMouseMotion:
		var over_ring: bool = _orbit_available(event.position)
		var ring_zone: String = scrubber.zone(event.position) if over_ring else ""
		scrubber.hovered = scrubber.dragging or ring_zone == "ring"
		scrubber.over_band = ring_zone == "band"
		scrubber.hover_index = scrubber.section_at_point(event.position) if scrubber.hovered else -1
		if scrubber.dragging:
			_set_cursor("grabbing")
			_scrub_moved = _scrub_moved or event.position.distance_to(_scrub_origin) > 5.0
			if _scrub_moved: action.emit("seek", {"beat": scrubber.beat_at(event.position)})
			return
		if not draw_path:
			var over_puppet: bool = false
			for id: String in _puppets:
				if _puppets[id].contains_world(_world_point(event.position)):
					over_puppet = true
					break
			mouse_default_cursor_shape = Control.CURSOR_DRAG if scrubber.hovered or over_puppet or scrubber.over_band else Control.CURSOR_ARROW
			_set_cursor("grabbing" if not _drag_id.is_empty() else ("grab" if scrubber.hovered or over_puppet or scrubber.over_band else "default"))
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if not event.pressed and scrubber.dragging:
			scrubber.dragging = false
			_set_cursor("grab" if scrubber.hit(event.position) else "default")
			if not _scrub_moved:
				enter_section(_press_section)
			elif not focus_id.is_empty():
				# Scrubbing into another section takes the focus along with it.
				enter_section(scrubber.section_at_point(event.position))
			return
		if event.pressed and not draw_path and _orbit_available(event.position):
			grab_focus()
			if scrubber.zone(event.position) == "band":
				exit_section()
				return
			action.emit("close_inspector", {})
			scrubber.dragging = true
			_scrub_origin = event.position
			_scrub_moved = false
			_press_section = scrubber.section_at_point(event.position)
			_set_cursor("grabbing")
			return
		if event.pressed:
			_drag_id = ""
			_drag_origin = event.position
			_drag_point = _world_point(event.position)
			_grab_offset = Vector2.ZERO
			_moved = false
			_path_points.clear()
			if draw_path and not selected_id.is_empty():
				_drag_id = selected_id
				_path_home = _puppets[_drag_id].position
				_grab_offset = _drag_point - _path_home
				_puppets[_drag_id].begin_pickup(_drag_point)
				_drag_point = _path_home
				_path_points.append(_drag_point)
				return
			var nearest: float = INF
			for id: String in _puppets:
				var puppet: JunkPuppet = _puppets[id]
				if puppet.contains_world(_drag_point):
					var distance: float = puppet.position.distance_to(_drag_point)
					if distance < nearest:
						nearest = distance
						_drag_id = id
			if not _drag_id.is_empty():
				var pinch_point: Vector2 = _drag_point
				_grab_offset = _drag_point - _puppets[_drag_id].position
				_drag_point = _puppets[_drag_id].position
				_puppets[_drag_id].begin_pickup(pinch_point)
				_set_cursor("grabbing")
				action.emit("select", {"id": _drag_id})
			else:
				action.emit("close_inspector", {})
		else:
			if not _drag_id.is_empty():
				if draw_path and _path_points.size() >= 2:
					action.emit("update_performer", {"id": _drag_id, "patch": {"position": {"x": _path_home.x, "y": _path_home.y}, "path": JunkMotionMath.recorded_path(_path_points), "motion": "glide"}})
					_puppets[_drag_id].finish_path()
					draw_path = false
					mouse_default_cursor_shape = Control.CURSOR_ARROW
				elif _moved and _sits_out(_drag_id, scrubber.beat) and _outside_ring(_drag_point):
					# Already waiting outside: wherever they are put is their spot from now on.
					_rest_in_wings(_drag_id, _drag_point)
				elif _moved and not focus_id.is_empty() and _outside_ring(_drag_point):
					# Off the stage in a section means sitting it out, waiting where they were dropped.
					_rest_in_wings(_drag_id, _drag_point)
					action.emit("set_part", {"sectionId": focus_id, "id": _drag_id, "present": false})
				elif _moved:
					var target: Vector2 = _drag_point
					if _sits_out(_drag_id, scrubber.beat):
						action.emit("set_part", {"sectionId": _section_id_at(scrubber.beat), "id": _drag_id, "present": true})
						_puppets[_drag_id].snap_present()
					action.emit("update_performer", {"id": _drag_id, "patch": {"position": {"x": target.x, "y": target.y}, "path": []}})
					_puppets[_drag_id].end_pickup(target, true)
				else:
					action.emit("inspect", {"id": _drag_id})
					_puppets[_drag_id].end_pickup()
				_set_cursor("grab")
			_drag_id = ""
			queue_redraw()
	elif event is InputEventMouseMotion and not _drag_id.is_empty():
		_drag_point = _world_point(event.position) - _grab_offset
		if not _moved and event.position.distance_to(_drag_origin) > 5:
			action.emit("close_inspector", {})
		_moved = _moved or event.position.distance_to(_drag_origin) > 5
		if _moved and not draw_path:
			action.emit("move_preview", {"id": _drag_id, "x": _drag_point.x, "y": _drag_point.y})
			queue_redraw()
		if draw_path and _path_points.size() < 128 and (_path_points.is_empty() or _path_points[-1].distance_to(_drag_point) > 6):
			_path_points.append(_drag_point)
			queue_redraw()


## While a tuned character is carried, the notes it can land on show across the stage.
func _draw_note_rows() -> void:
	if _drag_id.is_empty() or not _dragged_is_tuned(): return
	for row: int in range(-NOTE_ROWS, NOTE_ROWS + 1):
		var y: float = -row * NOTE_ROW_HEIGHT
		var share: float = y / RING_RADII.y
		var reach: float = RING_RADII.x * sqrt(maxf(1.0 - share * share, 0.0))
		var root: bool = row % 5 == 0
		draw_line(Vector2(-reach, y), Vector2(reach, y), Color(0.45, 0.32, 0.18, 0.4 if root else 0.16), 2.0 if root else 1.0, true)


func _dragged_is_tuned() -> bool:
	for performer: Dictionary in performers:
		if str(performer.id) == _drag_id: return bool(performer.get("tuned", false))
	return false


func _draw() -> void:
	var zoom: float = world_zoom()
	var center: Vector2 = size / 2.0 + Vector2(0, 34 * zoom) + camera_pan
	if _ground != null:
		var extent := Vector2(410, 250) * zoom
		draw_texture_rect(_ground, Rect2(center - extent, extent * 2.0), false)
	draw_set_transform(center, 0, Vector2.ONE * zoom)
	for performer: Dictionary in performers:
		if str(performer.id) != selected_id:
			continue
		var path: Array = performer.get("path", [])
		if path.size() > 1:
			var points: PackedVector2Array = []
			var knots: Array = JunkMotionMath.closed_path(performer)
			for index: int in range(257):
				points.append(JunkMotionMath.path_position(knots, float(index) / 256 * JunkLoopTiming.BEATS))
			draw_polyline(points, Color(0.72, 0.40, 0.22, 0.5), 2, true)
	if _path_points.size() > 1 and draw_path:
		draw_polyline(_path_points, Color("b76b43"), 2, true)
	_draw_note_rows()
	draw_set_transform(Vector2.ZERO)
