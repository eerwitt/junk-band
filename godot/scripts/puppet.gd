class_name JunkPuppet
extends Node2D

signal landed(point: Vector2, strength: float)

const CARRY_HEIGHT: float = 30.0
const REDUCED_CARRY_HEIGHT: float = 12.0
const SHADOW_LIGHT: Vector2 = Vector2(0.38, -0.16)
const DROP_GRAVITY: float = 1050.0
const SLIDE_FLOOR_OMEGA: float = 10.5
## How far a new character falls when it first joins the band, against an ordinary drop.
const HERO_DROP_HEIGHT: float = 120.0
const DEPART_TIME: float = 0.34
## How far back along x a route has to go before the character turns to face that way.
const PATH_TURN_DISTANCE: float = 10.0
## Dance styles. Each character keeps one, chosen from its id, so the band never moves as one.
const GROOVE_SWAY: int = 0
const GROOVE_BOB: int = 1
const GROOVE_TWIST: int = 2
const GROOVE_STOMP: int = 3

signal departed(puppet: JunkPuppet)
## A foot came down while walking on or off. `strength` is 0..1.
signal stepped(point: Vector2, strength: float)

var performer: Dictionary = {}
var inspected: bool = false
var path_knots: Array = []
var _body: Sprite2D
var _shadow: Sprite2D
var _drop_shadow: Sprite2D
var _base_scale: float = 1.0
var _elevation: float = 0.0
var _preview_at: float = -100.0
var _held: bool = false
var _held_position: Vector2
var _pickup_amount: float = 0.0
var _hold_time: float = 0.0
var _shadow_lift: float = 0.0
var _lift_height: float = 0.0
var _lift_velocity: float = 0.0
var _ground_foot: Vector2 = Vector2.ZERO
var _foot_y_pixels: float = 0.0
var _pinch_local: Vector2 = Vector2.ZERO
var _pinch_anchor: Vector2 = Vector2.ZERO
var _pinch_lean: float = 0.0
var _pinch_rotation: float = 0.0
var _pickup_sway: float = 0.0
var _carry_position: Vector2
var _carry_velocity: Vector2 = Vector2.ZERO
var _settling: bool = false
var _path_handoff: bool = false
var _landing_pending: bool = false
var _release_time: float = 0.0
var _landing_age: float = 10.0
var _drop_strength: float = 0.3
var _slide_drop: bool = false
var _slide_velocity: Vector2 = Vector2.ZERO
var _slide_history: Array[Dictionary] = []
var _slide_lean: float = 0.0
var _slide_lean_velocity: float = 0.0
var _slide_braked: bool = false
var _slide_peak_lean: float = 0.0
var _rock_side: float = 1.0
var _jolt_age: float = 10.0
var _jolt_amount: float = 0.0
var _source_art: Texture2D
var _art_size: Vector2 = Vector2.ONE
var _art_padding: float = 0.0
var _art_centroid: Vector2 = Vector2.ZERO
var _art_variance: Vector2 = Vector2.ONE
var _edge: MeshInstance2D
var _face_material: ShaderMaterial
var _edge_material: ShaderMaterial
var _shadow_material: ShaderMaterial
var _cardboard_yaw: float = -0.28
var _facing: float = 1.0
var _heading_extreme: float = 0.0
var _thickness: float = 1.0
var _material_id: String = ""
var _uploaded_yaw: float = INF
var _uploaded_offset: Vector2 = Vector2.INF
var _uploaded_blur_x: Vector2 = Vector2.INF
var _uploaded_blur_y: Vector2 = Vector2.INF
var _rig := JunkCardboardRig.new()
var _arrival_active: bool = false
## Where this actor waits, outside the ring, for a section it sits out.
var wing_point: Vector2 = Vector2.ZERO
var presence: float = 1.0
var _presence_target: float = 1.0
var _walk_clock: float = 0.0
var _walk_heading: float = 1.0
var _teeter_age: float = 10.0
## How they travel on and off: long bounds, the waddle with a turn, or a teetering run.
var walk_style: int = WALK_FLIP
## 0..1, how much the whole band is dancing: rises when the music starts, slumps when it stops.
var groove_energy: float = 0.0
var hovered: bool = false
var _hover_amount: float = 0.0
var _groove_style: int = -1
var _groove_offbeat: bool = false
var _groove_scale: float = 1.0
var _activity: float = 0.0
var _hit_age: float = 10.0
var _hit_strength: float = 0.0
var _hit_side: float = 1.0
var _slump_age: float = 10.0
var _rest_yaw: float = -0.28
var _dance_yaw: float = 0.0
var _departure_age: float = -1.0
var _depart_side: float = 1.0
var hero_landing: bool = false
## Where the character stood, as drawn, when it began to leave.
var depart_bounds := Rect2()
var _step_clock: float = 0.0
var _last_step_phase: float = 0.0
const WALK_BOUND: int = 0
const WALK_FLIP: int = 1
const WALK_TEETER: int = 2
const WALK_SECONDS: Array[float] = [0.95, 0.62, 0.72]
const BOUNDS_PER_TRIP: float = 3.0


## A true half-turn through the cut edge, rather than a negative scale / instant flip.
func set_facing(direction: float) -> void:
	if absf(direction) > 0.01: _facing = signf(direction)


## Walk on or off. Being carried or settling wins, and the walk picks up afterwards.
func set_present(present: bool) -> void:
	_presence_target = 1.0 if present else 0.0


## On the stage straight away, as when dropped there by hand.
func snap_present() -> void:
	_presence_target = 1.0
	presence = 1.0


func _project_cardboard(point: Vector2) -> Vector2:
	return Vector2(point.x * cos(_cardboard_yaw) + sin(_cardboard_yaw) * signf(cos(_cardboard_yaw)) * _thickness * 0.5, point.y)


func _pivot_offset(pivot: Dictionary) -> Vector2:
	return _body.texture.get_size() * 0.5 - Vector2(float(pivot.x), float(pivot.y)) * _art_size - Vector2.ONE * _art_padding


func begin_pickup(point: Vector2) -> void:
	_arrival_active = false
	_slide_drop = false
	var visual_grip: Vector2 = point - position
	_pinch_local = _body.to_local(to_global(visual_grip))
	_pinch_anchor = visual_grip + Vector2(0, _lift_height)
	var cosine: float = cos(_cardboard_yaw)
	if absf(cosine) > 0.08:
		_pinch_local.x = (_pinch_local.x - sin(_cardboard_yaw) * signf(cosine) * _thickness * 0.5) / cosine
	var width: float = float(_body.texture.get_width()) if _body.texture != null else 1.0
	_pinch_lean = clampf(-(_pinch_local.x - _body.offset.x) / width * 0.06, -0.02, 0.02)
	_pinch_rotation = _body.rotation
	_rest_yaw = _cardboard_yaw
	_dance_yaw = 0.0
	_pickup_sway = 0.0
	_carry_position = position
	if not _settling: _carry_velocity = Vector2.ZERO
	_settling = false
	_path_handoff = false
	_landing_pending = false
	_held = true
	_held_position = position
	_hold_time = 0.28 if _lift_height > 1.0 else 0.0
	_preview_at = -100.0


func move_pickup(point: Vector2) -> void:
	_pickup_sway = clampf(_pickup_sway - (point.x - _held_position.x) * 0.0015, -0.02, 0.02)
	_held_position = point


func end_pickup(target: Vector2 = Vector2.INF, dropped: bool = false) -> void:
	_held = false
	if target != Vector2.INF: _held_position = target
	_settling = dropped
	_landing_pending = dropped
	_release_time = 0.0
	_drop_strength = clampf(0.3 + _carry_velocity.length() / 600.0, 0.25, 0.85)
	# Measured on real drags: a gentle set-down still moves ~140 units/s with a few units
	# of lag. That is a drop with weight, not a skid that has nowhere to go.
	_slide_drop = dropped and (_carry_position.distance_to(_held_position) > 18.0 or _carry_velocity.length() > 260.0)
	_slide_velocity = _carry_velocity
	_slide_history.clear()
	_slide_braked = false
	_slide_peak_lean = 0.0
	_rock_side = -signf(_cardboard_yaw + 0.001) if absf(_carry_velocity.x) < 1.0 else signf(_carry_velocity.x)
	if _slide_drop:
		_slide_history.append({"point": transform * _ground_foot, "time": 0.0})
		if _slide_velocity.length() < 30.0: _slide_velocity = (_held_position - _carry_position) * 8.0
		# Put the weight down promptly while floor motion continues into a skid.
		_lift_velocity = minf(_lift_velocity, -maxf(_lift_height, 0.0) / 0.055)


## Let go off the ring: already waiting there, so the drop lands and skids in place
## instead of springing back on stage and walking out.
func drop_offstage(spot: Vector2) -> void:
	wing_point = spot
	_presence_target = 0.0
	presence = 0.0
	end_pickup(spot, true)


func finish_path() -> void:
	_held = false
	_path_handoff = true
	_settling = false
	_landing_pending = false


func preview() -> void:
	_preview_at = Time.get_ticks_msec() / 1000.0


## A nearby heavy landing travels through the floor and bumps this actor. `delay` is how
## long the wave takes to arrive.
func jolt(amount: float, delay: float) -> void:
	if _held: return
	_jolt_age = -delay
	_jolt_amount = clampf(amount, 0.0, 1.0)


func arrive(reduced_motion: bool, hero: bool = false) -> void:
	# This is height above the actor's actual floor position, including path motion.
	# Reuse gravity, silhouette gathering and the existing landing response.
	_arrival_active = true
	_slide_drop = false
	_lift_height = 0.0 if reduced_motion else (HERO_DROP_HEIGHT if hero else CARRY_HEIGHT * 0.85)
	_lift_velocity = 0.0
	_drop_strength = 1.0 if hero else 0.38
	hero_landing = hero and not reduced_motion


## A clone hops out of the character it was copied from, and lands on its own spot.
func arrive_from(source: Vector2, reduced_motion: bool) -> void:
	if reduced_motion or source.distance_to(position) < 1.0:
		arrive(reduced_motion)
		return
	_arrival_active = true
	_slide_drop = false
	_lift_height = 6.0
	_lift_velocity = 330.0
	_drop_strength = 0.45
	_carry_position = source
	_carry_velocity = Vector2.ZERO
	_held_position = position
	_settling = true
	_landing_pending = false
	position = source


## The sound actually played. The body pops up and twists toward alternate sides.
func note_hit(velocity: float, downbeat: bool) -> void:
	_hit_age = 0.0
	_hit_strength = clampf(velocity, 0.0, 1.0) * (1.0 if downbeat else 0.72)
	_hit_side = -_hit_side
	_activity = minf(1.0, _activity + 0.22 + velocity * 0.18)


## The music stopped: let the breath out and settle.
func slump() -> void:
	_slump_age = 0.0


## Removed from the band: crumple up, then the stage puffs it away.
func depart() -> void:
	depart_bounds = floor_visual_bounds()
	_departure_age = 0.0
	_held = false
	_depart_side = 1.0 if hash(str(performer.get("id", ""))) % 2 == 0 else -1.0


func departing() -> bool:
	return _departure_age >= 0.0


func _init() -> void:
	_shadow = Sprite2D.new()
	_shadow.z_as_relative = false
	_shadow.z_index = 100
	_shadow_material = ShaderMaterial.new()
	_shadow_material.shader = preload("res://shaders/cardboard_shadow.gdshader")
	_shadow.material = _shadow_material
	_shadow.modulate = Color(0.24, 0.20, 0.14, 0.13)
	add_child(_shadow)
	_drop_shadow = Sprite2D.new()
	_drop_shadow.z_as_relative = false
	_drop_shadow.z_index = 100
	var gradient := Gradient.new()
	# Gaussian density avoids the bright-edged ring of a three-stop cone.
	var stops := PackedFloat32Array()
	var colors := PackedColorArray()
	for index: int in range(17):
		var distance: float = float(index) / 16.0
		stops.append(distance)
		colors.append(Color(1, 1, 1, (exp(-4.5 * distance * distance) - exp(-4.5)) / (1.0 - exp(-4.5))))
	gradient.offsets = stops
	gradient.colors = colors
	var soft_circle := GradientTexture2D.new()
	soft_circle.gradient = gradient
	soft_circle.width = 128
	soft_circle.height = 128
	soft_circle.fill = GradientTexture2D.FILL_RADIAL
	soft_circle.fill_from = Vector2(0.5, 0.5)
	soft_circle.fill_to = Vector2(0.5, 0.0)
	_drop_shadow.texture = soft_circle
	_drop_shadow.modulate = Color(0.24, 0.20, 0.14, 0)
	add_child(_drop_shadow)
	_body = Sprite2D.new()
	_body.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	_face_material = ShaderMaterial.new()
	_face_material.shader = preload("res://shaders/cardboard_face.gdshader")
	_body.material = _face_material
	add_child(_body)
	_edge = MeshInstance2D.new()
	_edge.show_behind_parent = true
	_edge_material = ShaderMaterial.new()
	_edge_material.shader = preload("res://shaders/cardboard_edge.gdshader")
	_edge.material = _edge_material
	_body.add_child(_edge)


func set_art(texture: Texture2D) -> void:
	if _source_art == texture:
		return
	var cutout: Dictionary = JunkCardboardCutout.prepare(texture)
	if cutout.is_empty(): return
	_source_art = texture
	_rig.clear(self)
	_material_id = ""
	_body.texture = cutout.texture
	_shadow.texture = cutout.texture
	_edge.mesh = cutout.mesh
	_art_size = cutout.art_size
	_art_padding = cutout.padding
	_art_centroid = cutout.centroid
	_art_variance = cutout.variance
	_base_scale = minf(150.0 / _art_size.y, 144.0 / _art_size.x)
	_foot_y_pixels = cutout.foot
	_thickness = _art_size.y * 0.074
	_face_material.set_shader_parameter("thickness", _thickness)
	_edge_material.set_shader_parameter("thickness", _thickness)
	_shadow_material.set_shader_parameter("thickness", _thickness)


func pose(beat_value: float, reduced_motion: bool, delta: float = 0.0, note_pulse: float = 0.0) -> void:
	if performer.is_empty() or _body.texture == null:
		return
	_hold_time += delta if _held else 0.0
	var load_pulse: float = sin(clampf(_hold_time / 0.09, 0.0, 1.0) * PI) if _held and not reduced_motion else 0.0
	var lift: float = smoothstep(0.065, 0.28, _hold_time) if _held and not reduced_motion else 0.0
	var step: float = minf(delta, 0.1)
	var landed_this_frame: bool = false
	if reduced_motion:
		# A quiet, fixed held pose still needs depth feedback. No dip or recoil.
		_lift_height = REDUCED_CARRY_HEIGHT if _held else 0.0
		_lift_velocity = 0.0
	elif _held:
		var height_state: Array[Vector2] = JunkMotionMath.spring(Vector2(0, _lift_height), Vector2(0, _lift_velocity), Vector2(0, CARRY_HEIGHT * lift - load_pulse * 2.0), step, true)
		_lift_height = height_state[0].y
		_lift_velocity = height_state[1].y
	else:
		# Actual height drives landing, rather than an unrelated release timer.
		_lift_height += _lift_velocity * step - 0.5 * DROP_GRAVITY * step * step
		_lift_velocity -= DROP_GRAVITY * step
		if _lift_height <= 0.0:
			_lift_height = 0.0
			_lift_velocity = 0.0
	var b: float = fposmod(beat_value, JunkLoopTiming.BEATS)
	var base: Vector2 = Vector2(float(performer.position.x), float(performer.position.y))
	if not path_knots.is_empty(): base = JunkMotionMath.path_position(path_knots, b)
	var walking: bool = false
	if not _held and not _settling:
		var before: float = presence
		presence = move_toward(presence, _presence_target, delta / WALK_SECONDS[walk_style])
		walking = presence != before
		if walking:
			_walk_heading = signf(base.x - wing_point.x) * signf(presence - before)
			if is_zero_approx(_walk_heading): _walk_heading = 1.0
		elif before == presence and _walk_clock > 0.0 and not reduced_motion:
			# Arrived, at either end: each style has its own way of stopping.
			if walk_style == WALK_TEETER:
				_teeter_age = 0.0
			else:
				_jolt_age = 0.0
				_jolt_amount = 0.55
			_walk_clock = 0.0
		_walk_clock += delta if walking else 0.0
	if presence < 1.0:
		base = wing_point.lerp(base, smoothstep(0.0, 1.0, presence))
	var resting: Vector2 = base
	if _held or _settling or _path_handoff:
		var target: Vector2 = base if _path_handoff else _held_position
		# This spring moves only across the floor. Height has its own state above.
		# A slower floor spring gives a skid weight and time to be seen on the ground.
		var floor_omega: float = SLIDE_FLOOR_OMEGA if _slide_drop and _settling and not _held else 14.0
		var spring_state: Array[Vector2] = JunkMotionMath.spring(_carry_position, _carry_velocity, target, delta, not reduced_motion and (_held or (_settling and not _slide_drop)), floor_omega)
		_carry_position = spring_state[0]
		_carry_velocity = spring_state[1]
		base = _carry_position
		if not _held:
			_release_time += delta
			if _landing_pending and _lift_height <= 0.01:
				_landing_pending = false
				_landing_age = 0.0
				landed_this_frame = true
			if base.distance_to(target) < 0.2 and _carry_velocity.length() < 1.0 and _lift_height <= 0.01:
				if _path_handoff: _path_handoff = false
				elif resting.distance_to(target) < 0.01 and (presence <= 0.0 or performer.get("path", []).is_empty()): _settling = false
	position = base
	if _arrival_active and _lift_height <= 0.01:
		_arrival_active = false
		_landing_age = 0.0
		landed_this_frame = true
	var motion: String = performer.get("motion", "still")
	var phase: float = b * TAU
	_elevation = 0.0
	var turn: float = 0.0
	var squash: float = 0.0
	_pickup_amount = move_toward(_pickup_amount, 1.0 if _held else 0.0, delta / 0.09)
	var shadow_target: float = clampf(_lift_height / CARRY_HEIGHT, 0.0, 1.0)
	_shadow_lift = move_toward(_shadow_lift, shadow_target, delta * 4.0) if reduced_motion else shadow_target
	_pickup_sway *= exp(-8.0 * delta)
	_landing_age += delta
	if not reduced_motion:
		_elevation = note_pulse * (6.0 if motion == "hop" else 4.0)
		if motion == "roll":
			turn = b * PI / 2.0
		elif motion == "dance":
			turn = sin(phase / 2.0) * 0.018 + note_pulse * 0.02
		else:
			turn = note_pulse * 0.015
		squash = note_pulse * 0.4
		if _landing_age < 0.9 and not _slide_drop:
			# Weight arriving: slam into a held compression, kick back up into one
			# small hop, take a second lighter hit, then rock out the energy.
			var weight: float = clampf(_drop_strength, 0.25, 1.0)
			var slam: float = _landing_slam(_landing_age)
			squash += slam * (2.1 + weight * 1.5)
			_elevation -= slam * 2.4
			if _landing_age >= 0.1 and _landing_age < 0.31:
				_elevation += sin((_landing_age - 0.1) / 0.21 * PI) * (5.0 + weight * 9.0)
			turn += sin(_landing_age * 19.0) * exp(-_landing_age * 6.5) * (0.035 + weight * 0.06) * _rock_side
		_jolt_age += delta
		if _jolt_age >= 0.0 and _jolt_age < 0.2 and not _held:
			_elevation += sin(_jolt_age / 0.2 * PI) * _jolt_amount * 11.0
			turn += sin(_jolt_age / 0.2 * TAU) * _jolt_amount * 0.03
		if _slide_drop and _landing_age < 0.12:
			# Even at speed the weight has to arrive, before the feet take off again.
			squash += _landing_slam(_landing_age) * 2.0
		_update_slide_lean(delta)
		turn += _slide_lean
		if _slide_drop and _settling and _lift_height <= 0.01:
			# Crouched into the skid, then released as the speed bleeds off.
			squash += clampf(_carry_velocity.length() / 520.0, 0.0, 1.0) * 1.5
		if walking:
			match walk_style:
				WALK_BOUND:
					# Long arcs with a crouch at each landing.
					var trip: float = smoothstep(0.0, 1.0, presence)
					var arc: float = absf(sin(trip * PI * BOUNDS_PER_TRIP))
					_elevation += arc * 42.0
					squash += pow(1.0 - arc, 4.0) * 2.4
					turn += cos(trip * PI * BOUNDS_PER_TRIP * 2.0) * -0.05 * _walk_heading
				WALK_TEETER:
					# Quick little steps, tipped forward and only just keeping up with itself.
					_elevation += absf(sin(_walk_clock * 27.0)) * 5.0
					turn += _walk_heading * 0.17 + sin(_walk_clock * 27.0) * 0.1
				_:
					# A cardboard waddle: hop from foot to foot, rocking side to side.
					_elevation += absf(sin(_walk_clock * 13.0)) * 11.0
					turn += sin(_walk_clock * 13.0) * 0.07
					squash += absf(cos(_walk_clock * 13.0)) * 0.8
		_teeter_age += delta
		if _teeter_age < 0.8:
			turn += sin(_teeter_age * 17.0) * exp(-_teeter_age * 5.5) * 0.16 * _walk_heading
		if walking: _track_steps(delta)
		var groove: Vector4 = _groove(beat_value, delta, motion, walking)
		_elevation += groove.x
		turn += groove.y
		squash += groove.z
		_dance_yaw = groove.w
		_hover_amount = move_toward(_hover_amount, 1.0 if hovered and not _held else 0.0, delta / 0.12)
		var perk: float = smoothstep(0.0, 1.0, _hover_amount)
		_elevation += perk * 2.0
		squash -= perk * 0.45
	else:
		_slide_lean = 0.0
		_slide_lean_velocity = 0.0
		_dance_yaw = 0.0
	# Falling weight pulls the cutout long for the frames before it hits.
	var fall_stretch: float = 0.0
	if not reduced_motion and not _held and _lift_height > 0.01 and not _slide_drop:
		fall_stretch = clampf(-_lift_velocity / 290.0, 0.0, 1.0) * 0.032
	var pivot: Dictionary = performer.get("pivot", {"x": 0.5, "y": 0.85})
	var elapsed: float = Time.get_ticks_msec() / 1000.0 - _preview_at
	if not reduced_motion and not _held and elapsed >= 0 and elapsed < 0.28:
		_elevation += sin(elapsed / 0.28 * PI) * 5.0
	if _slide_drop and _settling and _lift_height <= 0.01:
		# Notes can still articulate the cutout, but cannot lift a grounded skid.
		_elevation = 0.0
	var pickup: float = _pickup_amount if not reduced_motion else 0.0
	var tension: Vector2 = _held_position - position if _held else Vector2.ZERO
	var stretch: float = pickup * minf(tension.length() / 90.0, 1.0) * 0.018
	squash *= 1.0 - _pickup_amount
	if _held or _pickup_amount > 0.0:
		var held_turn: float = _pinch_rotation + _pinch_lean + _pickup_sway + clampf(-tension.x * 0.0014, -0.085, 0.085) if not reduced_motion else 0.0
		var target_turn: float = held_turn if _held else lerp_angle(turn, held_turn, _pickup_amount)
		turn = lerp_angle(_body.rotation, target_turn, 1.0 - exp(-18.0 * delta))
	if _body.texture != null:
		_body.offset = _pivot_offset(pivot)
	# Only while actually travelling the route: held, settling, or waiting in the wings it is not
	# where the route is, and must not keep turning round on the spot.
	var on_path: bool = not path_knots.is_empty() and not _held and not _settling and not _path_handoff and presence >= 1.0
	if walking:
		set_facing(_walk_heading)
	elif on_path:
		# A drawn route wobbles with the hand that drew it. Turn only once really heading back,
		# or every wobble flips the cutout through its edge.
		if (position.x - _heading_extreme) * _facing > 0.0: _heading_extreme = position.x
		elif absf(position.x - _heading_extreme) > PATH_TURN_DISTANCE: set_facing(position.x - _heading_extreme)
	if not on_path: _heading_extreme = position.x
	var target_yaw: float = -0.28 if _facing > 0.0 else PI + 0.28
	# Freeze yaw while pinched: the inverse material grip remains exact.
	if not _held:
		# Only the flip style makes a move of turning round. The others just set off facing the way.
		var turn_rate: float = 10.0 if not walking or walk_style == WALK_FLIP else 50.0
		_rest_yaw = target_yaw if reduced_motion else lerp_angle(_rest_yaw, target_yaw, 1.0 - exp(-turn_rate * delta))
		# Dancing turns the cutout a little on its own spot, flashing the cut edge to the beat.
		_cardboard_yaw = _rest_yaw + _dance_yaw * (1.0 - _pickup_amount)
	if _material_id != str(performer.get("id", "")):
		_material_id = str(performer.get("id", ""))
		var material_seed: float = float(_material_id.hash() % 65521) / 65521.0 * 100.0
		_face_material.set_shader_parameter("character_seed", material_seed)
		_edge_material.set_shader_parameter("character_seed", material_seed)
		_thickness = _art_size.y * (0.068 + fposmod(material_seed, 1.0) * 0.012)
		_face_material.set_shader_parameter("thickness", _thickness)
		_edge_material.set_shader_parameter("thickness", _thickness)
		_shadow_material.set_shader_parameter("thickness", _thickness)
	if not is_equal_approx(_uploaded_yaw, _cardboard_yaw):
		_face_material.set_shader_parameter("yaw", _cardboard_yaw)
		_edge_material.set_shader_parameter("yaw", _cardboard_yaw)
		_shadow_material.set_shader_parameter("yaw", _cardboard_yaw)
		_uploaded_yaw = _cardboard_yaw
	if _uploaded_offset != _body.offset:
		_edge_material.set_shader_parameter("pivot_offset", _body.offset)
		_uploaded_offset = _body.offset
	_body.position = Vector2(0, -_elevation)
	_body.rotation = turn
	_body.scale = Vector2(_base_scale * (1.0 + squash * 0.025 - stretch * 0.5), _base_scale * (1.0 - squash * 0.035 + stretch))
	_body.scale *= Vector2(1.0 + load_pulse * 0.008, 1.0 - load_pulse * 0.012)
	_body.scale *= Vector2(1.0 - fall_stretch * 0.6, 1.0 + fall_stretch)
	_body.skew = clampf(-tension.x * 0.0002, -0.012, 0.012) * pickup
	var crumple: float = 0.0
	if _departure_age >= 0.0:
		_departure_age += delta
		var t: float = clampf(_departure_age / DEPART_TIME, 0.0, 1.0)
		# Balled up from the edges in, with a wince, a tip and a little leap before it goes.
		crumple = t * t * (3.0 - 2.0 * t)
		var wince: float = sin(minf(_departure_age / 0.08, 1.0) * PI) * (1.0 - t)
		_body.scale *= Vector2(1.0 + wince * 0.12 - crumple * 0.82, 1.0 - wince * 0.1 - crumple * 0.62)
		_body.rotation += _depart_side * (crumple * 1.4 + sin(_departure_age * 38.0) * 0.06 * (1.0 - t))
		_body.position.y -= sin(t * PI) * 18.0
		if t >= 1.0:
			_departure_age = -2.0
			departed.emit(self)
	if _held or _pickup_amount > 0.0:
		# Keep the material under the fingers fixed while the rest hangs and flexes.
		var material_transform := Transform2D(_body.rotation, _body.scale, _body.skew, Vector2.ZERO)
		var pinned_position: Vector2 = _pinch_anchor - material_transform * _project_cardboard(_pinch_local)
		_body.position = pinned_position if _held else _body.position.lerp(pinned_position, _pickup_amount)
	# Screen-space rise is independent of the floor spring and shadow anchor.
	_body.position.y -= _lift_height
	_body.modulate.a = 0.38 if performer.get("mute", false) else 1.0
	var shadow_scale: float = 1.0 - maxf(_elevation, 0.0) / 90.0
	var foot_y: float = (_foot_y_pixels - _art_padding - float(pivot.y) * _art_size.y) * _base_scale if _body.texture != null else 0.0
	var gather: float = smoothstep(0.05, 0.80, _shadow_lift)
	var circle_merge: float = smoothstep(0.55, 0.98, _shadow_lift)
	_shadow.offset = _body.offset
	# Project the silhouette from the foot contact, keeping both ends joined.
	var grounded_mask := Transform2D(
		Vector2(_base_scale * shadow_scale, 0),
		Vector2(-_base_scale * 0.38 * shadow_scale, _base_scale * 0.16 * shadow_scale),
		Vector2(foot_y * 0.38 * shadow_scale, foot_y * (1.0 - 0.16 * shadow_scale))
	)
	# Lean changes the footprint's X, but lifting must never raise its floor Y.
	var material_foot := Vector2(_body.offset.x, _foot_y_pixels - _body.texture.get_height() * 0.5 + _body.offset.y)
	var rendered_foot: Vector2 = _body.transform * _project_cardboard(material_foot)
	_ground_foot = Vector2(rendered_foot.x, foot_y)
	var light_offset: Vector2 = SHADOW_LIGHT * maxf(_lift_height, 0.0)
	grounded_mask.origin = _ground_foot + light_offset - grounded_mask.basis_xform(_project_cardboard(material_foot))
	var radius: float = lerpf(24.0, 34.0, _shadow_lift)
	var carry_center: Vector2 = _ground_foot + light_offset
	# Physically gather the same silhouette toward the carry footprint, removing its
	# shear and shortening its long axis. Only merge once that mask is small.
	var compact_mask := Transform2D(
		Vector2(radius * 2.0 / (_body.texture.get_width() * maxf(absf(cos(_cardboard_yaw)), 0.15)), 0),
		Vector2(0, radius * 0.8 / _body.texture.get_height()),
		Vector2.ZERO
	)
	var material_centroid: Vector2 = _project_cardboard(_art_centroid + _body.offset)
	compact_mask.origin = carry_center - compact_mask.basis_xform(material_centroid)
	_shadow.transform = Transform2D(grounded_mask.x.lerp(compact_mask.x, gather), grounded_mask.y.lerp(compact_mask.y, gather), grounded_mask.origin.lerp(compact_mask.origin, gather))
	# Both representations share the actual silhouette's center of mass. An
	# asymmetric character must not slide sideways when its mask becomes diffuse.
	_drop_shadow.position = _shadow.transform * material_centroid
	var projected_x: Vector2 = _shadow.transform.x * cos(_cardboard_yaw)
	var projected_y: Vector2 = _shadow.transform.y
	var floor_variance: Vector2 = projected_x * projected_x * _art_variance.x + projected_y * projected_y * _art_variance.y
	_drop_shadow.scale = Vector2(sqrt(maxf(floor_variance.x, 1.0)), sqrt(maxf(floor_variance.y, 1.0))) * 6.0 / 128.0
	var density: float = lerpf(0.13 * shadow_scale, 0.115, gather)
	_shadow.modulate.a = density * (1.0 - circle_merge)
	# Convert a floor-space penumbra through the full compressed/skewed basis.
	# Texture-space blur alone would be squashed into a hard little stamped card.
	var blur_x: Vector2 = Vector2.ZERO
	var blur_y: Vector2 = Vector2.ZERO
	if _shadow_lift > 0.001:
		var cosine: float = cos(_cardboard_yaw)
		var safe_cosine: float = signf(cosine) * maxf(absf(cosine), 0.15)
		var inverse_shadow := Transform2D(_shadow.transform.x * safe_cosine, _shadow.transform.y, Vector2.ZERO).affine_inverse()
		var penumbra: float = 4.0 * smoothstep(0.02, 0.85, _shadow_lift)
		blur_x = inverse_shadow.basis_xform(Vector2(penumbra, 0)) / _body.texture.get_size()
		blur_y = inverse_shadow.basis_xform(Vector2(0, penumbra)) / _body.texture.get_size()
	if blur_x != _uploaded_blur_x or blur_y != _uploaded_blur_y:
		_shadow_material.set_shader_parameter("blur_x", blur_x)
		_shadow_material.set_shader_parameter("blur_y", blur_y)
		_uploaded_blur_x = blur_x
		_uploaded_blur_y = blur_y
	_drop_shadow.modulate.a = circle_merge * density
	if crumple > 0.0:
		_shadow.modulate.a *= 1.0 - crumple
		_drop_shadow.modulate.a *= 1.0 - crumple
	_rig.pose(self, beat_value, reduced_motion, delta, note_pulse)
	z_index = 3600 if _held else (3000 if inspected else int(clampf(base.y + 500.0, 101.0, 2999.0)))
	if _slide_drop and (_landing_pending or landed_this_frame):
		# Retain the short release-to-contact section for the eventual skid effect.
		if _slide_history.size() < 32 and _release_time - float(_slide_history[-1].time) >= 1.0 / 120.0:
			_slide_history.append({"point": transform * _ground_foot, "time": _release_time})
	if landed_this_frame:
		# Emit only after this frame's body, grip and floor contact are current.
		# The stage consumes parent-space coordinates, independent of its camera.
		landed.emit(transform * _ground_foot, _drop_strength)


## Beat-locked dancing, plus the pop of each real note. Returns elevation, turn, squash
## and a yaw offset. Everything comes from the audio clock, so it stays on the beat.
func _groove(beat_value: float, delta: float, motion: String, walking: bool) -> Vector4:
	if _groove_style < 0:
		var seed: int = absi(hash(str(performer.get("id", ""))))
		_groove_style = seed % 4
		_groove_offbeat = (seed / 4) % 5 == 0
		_groove_scale = 0.85 + float((seed / 20) % 7) * 0.05
	_activity *= exp(-0.9 * delta)
	_hit_age += delta
	_slump_age += delta
	var result := Vector4.ZERO
	if _held or _settling or _departure_age >= 0.0 or _arrival_active:
		return result
	# Listening characters still nod along; the ones playing dance hardest.
	var energy: float = groove_energy * (0.45 + 0.55 * _activity) * _groove_scale * (0.5 if walking else 1.0) * presence
	var shifted: float = beat_value + (0.5 if _groove_offbeat else 0.0)
	var f: float = fposmod(shifted, 1.0)
	var accent: float = 1.3 if posmod(int(floor(shifted)), 4) == 0 else 1.0
	# Up between beats, down on the beat. The landing is quick and the hang is long.
	var air: float = pow(sin(f * PI), 1.6)
	var contact: float = exp(-f * 11.0) + smoothstep(0.86, 1.0, f) * 0.5
	# Leans that arrive on the beat and hang there, swapping side every beat.
	var swing: float = cos(shifted * PI)
	var lean: float = signf(swing) * pow(absf(swing), 0.55)
	var style: int = _groove_style
	if motion == "hop": style = GROOVE_BOB
	match style:
		GROOVE_SWAY:
			result.x = air * 4.0
			result.y = lean * 0.1
			result.z = contact * 0.9
			result.w = lean * 0.05
		GROOVE_BOB:
			result.x = air * (6.5 if motion == "hop" else 5.5)
			result.y = sin(shifted * TAU) * 0.012
			result.z = contact * 1.7
		GROOVE_TWIST:
			result.x = air * 2.5
			result.y = lean * 0.03
			result.z = contact * 0.8
			result.w = lean * 0.2
		_:
			# Stomp: rock onto one foot, then the other.
			var foot: float = signf(sin(shifted * PI))
			result.x = air * 5.0
			result.y = foot * air * 0.12
			result.z = contact * 1.4
	result *= energy * accent
	if _slump_age < 0.7:
		var sigh: float = sin(minf(_slump_age / 0.14, 1.0) * PI * 0.5) * exp(-_slump_age * 4.5)
		result.x -= sigh * 2.5
		result.z += sigh * 2.2
		result.y += sigh * 0.04 * _hit_side
	if _hit_age < 0.4:
		# Snap tall on the note, settle back with one small overshoot.
		var rise: float = sin(minf(_hit_age / 0.045, 1.0) * PI * 0.5)
		var pop: float = rise * exp(-_hit_age * 13.0) - 0.22 * sin(clampf((_hit_age - 0.09) / 0.2, 0.0, 1.0) * PI)
		result.z -= pop * 2.0 * _hit_strength
		result.y += pop * 0.05 * _hit_side * _hit_strength
		result.w += pop * 0.14 * _hit_side * _hit_strength
		if motion == "hop": result.x += sin(clampf(_hit_age / 0.24, 0.0, 1.0) * PI) * 9.0 * _hit_strength
	return result


## Footfalls while walking on or off, each style at its own pace.
func _track_steps(delta: float) -> void:
	var phase: float = 0.0
	match walk_style:
		WALK_BOUND: phase = smoothstep(0.0, 1.0, presence) * BOUNDS_PER_TRIP
		WALK_TEETER: phase = _walk_clock * 27.0 / PI
		_: phase = _walk_clock * 13.0 / PI
	_step_clock += delta
	if floor(phase) != floor(_last_step_phase) and _step_clock > 0.09:
		_step_clock = 0.0
		var strength: float = 1.0 if walk_style == WALK_BOUND else (0.35 if walk_style == WALK_TEETER else 0.6)
		stepped.emit(transform * _ground_foot, strength)
	_last_step_phase = phase


## 0..1 compression envelope: 40 ms slam, a short hold, release by 100 ms, second hit at 310 ms.
func _landing_slam(age: float) -> float:
	var first: float = smoothstep(0.0, 0.04, age) * (1.0 - smoothstep(0.065, 0.1, age))
	var second: float = smoothstep(0.31, 0.335, age) * (1.0 - smoothstep(0.345, 0.42, age)) * 0.34
	return first + second


## Feet are stopped by friction while the top keeps going. An underdamped exact spring
## leans the body back against the skid, then pitches it past upright when it brakes.
func _update_slide_lean(delta: float) -> void:
	var skidding: bool = _slide_drop and _settling and _lift_height <= 0.01
	var target: float = clampf(-_carry_velocity.x * 0.0008, -0.27, 0.27) if skidding else 0.0
	_slide_peak_lean = maxf(_slide_peak_lean, absf(target))
	if skidding and not _slide_braked and _carry_velocity.length() < 85.0:
		_slide_braked = true
		_slide_lean_velocity += signf(_slide_velocity.x) * _slide_peak_lean * 7.5
	var damping: float = 8.5
	var frequency: float = 15.0
	var time: float = minf(delta, 0.1)
	var offset: float = _slide_lean - target
	var oscillation: float = (_slide_lean_velocity + damping * offset) / frequency
	var decay: float = exp(-damping * time)
	_slide_lean = target + (offset * cos(frequency * time) + oscillation * sin(frequency * time)) * decay
	_slide_lean_velocity = (_slide_lean_velocity * cos(frequency * time) - (damping * oscillation + frequency * offset) * sin(frequency * time)) * decay


func floor_visual_bounds() -> Rect2:
	var art_rect: Rect2 = _body.get_rect()
	var corners: Array[Vector2] = [art_rect.position, Vector2(art_rect.end.x, art_rect.position.y), art_rect.end, Vector2(art_rect.position.x, art_rect.end.y)]
	var bounds := Rect2(transform * (_body.transform * _project_cardboard(corners[0])), Vector2.ZERO)
	for corner: Vector2 in corners:
		bounds = bounds.expand(transform * (_body.transform * _project_cardboard(corner)))
	return bounds


func contains_world(point: Vector2) -> bool:
	return visible and _body.texture != null and Rect2(position + Vector2(-85, -190), Vector2(170, 210)).has_point(point)


