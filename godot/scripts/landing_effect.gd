class_name JunkLandingEffect
extends Node2D
## Impact and skid VFX. Everything visible is a closed-form function of `_age` and
## bounded spawn records, so it stays frame-rate independent and can be sampled at any
## time. Layers sort into the world: marks under the shadows, dust behind and in front
## of the actor, and lettering on top.

const WORDS: Array[String] = ["plop", "thud", "bump", "pof", "pow", "tup"]
const LETTERS: Dictionary = {
	"p": [[Vector2(1, 3), Vector2(1, -7), Vector2(4, -8), Vector2(6, -6), Vector2(5, -3), Vector2(1, -3)]],
	"l": [[Vector2(2, -10), Vector2(1, -1), Vector2(3, 0)]],
	"o": [[Vector2(2, -7), Vector2(5, -7), Vector2(6, -5), Vector2(5, -1), Vector2(2, 0), Vector2(0, -2), Vector2(1, -6), Vector2(2, -7)]],
	"t": [[Vector2(3, -10), Vector2(2, -1), Vector2(4, 0)], [Vector2(0, -6), Vector2(6, -7)]],
	"h": [[Vector2(1, -10), Vector2(0, 0)], [Vector2(1, -4), Vector2(3, -7), Vector2(5, -6), Vector2(6, 0)]],
	"u": [[Vector2(0, -7), Vector2(0, -2), Vector2(2, 0), Vector2(5, -1), Vector2(6, -7), Vector2(6, 0)]],
	"d": [[Vector2(6, -10), Vector2(5, 0)], [Vector2(5, -6), Vector2(2, -7), Vector2(0, -4), Vector2(1, -1), Vector2(5, -1)]],
	"b": [[Vector2(1, -10), Vector2(0, 0)], [Vector2(1, -5), Vector2(4, -7), Vector2(6, -5), Vector2(5, -1), Vector2(0, 0)]],
	"m": [[Vector2(0, 0), Vector2(1, -7), Vector2(3, -7), Vector2(4, -1), Vector2(5, -7), Vector2(7, -6), Vector2(8, 0)]],
	"f": [[Vector2(1, 2), Vector2(2, -8), Vector2(4, -10), Vector2(6, -9)], [Vector2(0, -5), Vector2(6, -6)]],
	"w": [[Vector2(0, -7), Vector2(2, 0), Vector2(4, -5), Vector2(6, 0), Vector2(8, -7)]],
	"y": [[Vector2(0, -7), Vector2(3, -1)], [Vector2(6, -7), Vector2(3, -1), Vector2(1, 3)]],
	"a": [[Vector2(5, -6), Vector2(2, -7), Vector2(0, -4), Vector2(1, -1), Vector2(4, 0), Vector2(6, -3)], [Vector2(6, -7), Vector2(5, 0)]],
	"e": [[Vector2(0, -3), Vector2(6, -4), Vector2(5, -7), Vector2(2, -7), Vector2(0, -4), Vector2(1, -1), Vector2(5, 0)]],
	"i": [[Vector2(1, -7), Vector2(1, 0)], [Vector2(1, -10), Vector2(1.4, -9.4)]],
	"n": [[Vector2(1, -7), Vector2(0, 0)], [Vector2(1, -4), Vector2(3, -7), Vector2(5, -6), Vector2(6, 0)]],
	"!": [[Vector2(2, -10), Vector2(1, -3)], [Vector2(1, -0.6), Vector2(1.3, 0)]],
}
## A new character joining: bright paper confetti over the usual dust.
const CONFETTI_TONES: Array[Color] = [Color("b86339"), Color("dce5db"), Color("e8c34f"), Color("29271f"), Color("d9563b"), Color("8fb3a0"), Color("f7f5ec")]
const DUST_SHADER: Shader = preload("res://shaders/vfx_dust.gdshader")
const SKID_SHADER: Shader = preload("res://shaders/vfx_skid.gdshader")
const RIPPLE_SHADER: Shader = preload("res://shaders/vfx_ripple.gdshader")
const INK_SHADER: Shader = preload("res://shaders/vfx_ink.gdshader")
const MAX_TRAIL_SAMPLES: int = 48
const MAX_PUFFS: int = 64
const MAX_CHIPS: int = 72
## Seconds between wake puffs, and the slowest skid that still kicks anything up.
const WAKE_INTERVAL: float = 0.05
const WAKE_MIN_SPEED: float = 30.0
const MAX_STREAKS: int = 14
const TRAIL_FADE_TIME: float = 0.7
const TRAIL_HOLD_TIME: float = 0.2
## Cleanup starts this long before the measured stop plus hold. The floor spring creeps
## for a long time after the slide visibly ends, so waiting for it feels late.
const TRAIL_EARLY_START: float = 0.7
const TRAIL_MIN_START: float = 0.15
const WORD_TIME: float = 0.72
const HERO_WORD_TIME: float = 1.2
const ORANGE_INK := Color(0.62, 0.27, 0.12)
const DENT_TIME: float = 1.25
## Vertical compression of circles lying on the stage floor.
const FLOOR_SQUASH: float = 0.38
const CHIP_GRAVITY: float = 880.0
const INK := Color(0.27, 0.16, 0.08)
const CHIP_TONES: Array[Color] = [Color(0.56, 0.40, 0.23), Color(0.74, 0.58, 0.37), Color(0.33, 0.22, 0.12), Color(0.89, 0.82, 0.67)]

var seed_value: int = 0
var strength: float = 0.4
var pixel_zoom: float = 1.0
var reduced_motion: bool = false
var sliding: bool = false
var slide_velocity: Vector2 = Vector2.ZERO
var character_bounds := Rect2(-35, -150, 70, 150)
## A new member of the band: a bigger hit, confetti and a cheer instead of a thud.
var hero: bool = false
## Removed from the band: a puff of paper scraps where it stood, and no dent.
var poof: bool = false
var word_override: String = ""
var _age: float = 0.0
var _host: JunkPuppet
var _trail: Array[Dictionary] = []
var _emission_time: float = 0.0
var _tracking: bool = false
var _stop_age: float = -1.0
var _fade_delays: PackedFloat32Array = PackedFloat32Array()
var _fade_sweep: float = 0.0
var _fade_start: float = -1.0
var _puffs: Array[Dictionary] = []
var _chips: Array[Dictionary] = []
var _streaks: Array[Dictionary] = []
var _rays: Array[Dictionary] = []
var _puff_cursor: int = 0
var _chip_cursor: int = 0
var _streak_cursor: int = 0
var _end_age: float = 0.0
var _spawned: bool = false
var _braked: bool = false
var _rng := RandomNumberGenerator.new()
var _body_size := Vector2(70, 150)
var _track_half: float = 26.0
var _last_contact: Vector2 = Vector2.INF
var _wake_clock: float = 0.0
var _streak_distance: float = 0.0
var _depth_y: Vector2 = Vector2.INF
var _skid_layer: Node2D
var _ripple_layer: Node2D
var _floor_ink: Node2D
var _back_dust: Node2D
var _front_dust: Node2D
var _front_ink: Node2D
var _confetti_layer: Node2D


class Batch:
	## One triangle-array draw per layer instead of one draw call for each quad.
	var points := PackedVector2Array()
	var colors := PackedColorArray()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()

	func quad(a: Vector2, b: Vector2, c: Vector2, d: Vector2, color: Color) -> void:
		var first: int = points.size()
		points.append_array(PackedVector2Array([a, b, c, d]))
		colors.append_array(PackedColorArray([color, color, color, color]))
		uvs.append_array(PackedVector2Array([Vector2(-1, -1), Vector2(1, -1), Vector2(1, 1), Vector2(-1, 1)]))
		indices.append_array(PackedInt32Array([first, first + 1, first + 2, first, first + 2, first + 3]))

	## Hand-inked stroke: a thin tail swelling to a belly, then a pointed head.
	func stroke(tail: Vector2, head: Vector2, width: float, color: Color) -> void:
		var along: Vector2 = head - tail
		if along.length() < 0.001: return
		var normal: Vector2 = along.orthogonal().normalized() * width * 0.5
		var belly: Vector2 = tail + along * 0.62
		var first: int = points.size()
		points.append_array(PackedVector2Array([tail - normal * 0.1, tail + normal * 0.1, belly + normal, belly - normal, head + normal * 0.06, head - normal * 0.06]))
		colors.append_array(PackedColorArray([color, color, color, color, color, color]))
		uvs.append_array(PackedVector2Array([Vector2(0, -1), Vector2(0, 1), Vector2(0, 1), Vector2(0, -1), Vector2(0, 1), Vector2(0, -1)]))
		indices.append_array(PackedInt32Array([first, first + 1, first + 2, first, first + 2, first + 3, first + 3, first + 2, first + 4, first + 3, first + 4, first + 5]))

	func flush(layer: CanvasItem) -> void:
		if points.is_empty(): return
		RenderingServer.canvas_item_add_triangle_array(layer.get_canvas_item(), indices, points, colors, uvs)


func _init() -> void:
	_skid_layer = _layer(99, SKID_SHADER, _draw_skid)
	_ripple_layer = _layer(99, RIPPLE_SHADER, _draw_ripple)
	_floor_ink = _layer(99, INK_SHADER, _draw_floor_ink)
	_back_dust = _layer(100, DUST_SHADER, _draw_back_dust)
	_front_dust = _layer(101, DUST_SHADER, _draw_front_dust)
	_front_ink = _layer(101, INK_SHADER, _draw_front_ink)
	# Thrown up over everyone's heads, so it is drawn above the band.
	_confetti_layer = _layer(3090, INK_SHADER, _draw_confetti)


func _layer(depth: int, shader: Shader, painter: Callable) -> Node2D:
	var layer := Node2D.new()
	layer.z_as_relative = false
	layer.z_index = depth
	var shade := ShaderMaterial.new()
	shade.shader = shader
	layer.material = shade
	layer.draw.connect(painter)
	add_child(layer)
	return layer


func configure(puppet: JunkPuppet) -> void:
	_host = puppet
	sliding = puppet._slide_drop
	slide_velocity = puppet._slide_velocity
	character_bounds = puppet.floor_visual_bounds()
	character_bounds.position -= position
	_body_size = character_bounds.size
	_track_half = clampf(_body_size.x * 0.33, 18.0, 40.0)
	_depth_y = Vector2(puppet.position.y, puppet.position.y)
	if sliding:
		# Reserve space for the whole remaining slide, so the actor cannot catch
		# up into its own lettering after the effect has been placed.
		var destination_bounds: Rect2 = character_bounds
		destination_bounds.position += puppet._held_position - puppet.position
		character_bounds = character_bounds.merge(destination_bounds)
		_depth_y = Vector2(minf(puppet.position.y, puppet._held_position.y), maxf(puppet.position.y, puppet._held_position.y))
		_tracking = true
		_fade_start = maxf(_predict_stop(puppet) + TRAIL_HOLD_TIME - TRAIL_EARLY_START, TRAIL_MIN_START)
		for sample: Dictionary in puppet._slide_history:
			# The body is still settling onto the floor here, so the mark starts light.
			_append_sample(sample.point - position, slide_velocity.normalized(), float(sample.time) - puppet._release_time, false, 0.34)
		_emit_trail()


func _ready() -> void:
	_spawn_contact()
	# Puppets sort by floor Y. Sitting one step either side puts dust around the actor.
	var floor_y: Vector2 = _depth_y if _depth_y != Vector2.INF else Vector2(position.y, position.y)
	_back_dust.z_index = clampi(int(floor_y.x) + 499, 100, 2998)
	_front_dust.z_index = clampi(int(floor_y.y) + 501, 102, 3000)
	_front_ink.z_index = _front_dust.z_index
	_redraw_all()


func _emit_trail(endpoint: bool = false) -> void:
	if not is_instance_valid(_host) or _host._held: return
	var contact: Vector2 = _host.transform * _host._ground_foot - position
	var velocity: Vector2 = _host._carry_velocity
	var direction: Vector2 = velocity.normalized() if velocity.length() > 8.0 else slide_velocity.normalized()
	_append_sample(contact, direction, _age, endpoint, _pressure_for(velocity.length()))


func _pressure_for(speed: float) -> float:
	return clampf(0.58 + speed / 700.0, 0.58, 1.0)


func _append_sample(point: Vector2, direction: Vector2, birth: float, endpoint: bool = false, pressure: float = 1.0) -> void:
	if not _trail.is_empty() and point.distance_to(_trail[-1].point) < 2.0 / maxf(pixel_zoom, 0.25):
		if endpoint and _trail.size() > 1:
			_trail[-1].point = point
			_trail[-1].birth = birth
		return
	if _trail.size() >= MAX_TRAIL_SAMPLES:
		# Preserve both ends while coarsening old samples on unusually long slides.
		for index: int in range(_trail.size() - 2, 0, -2): _trail.remove_at(index)
	_trail.append({"point": point, "direction": direction, "birth": birth, "pressure": pressure})


func trail_opacity(index: int) -> float:
	if _fade_start < 0.0 or _age < _fade_start or index >= _fade_delays.size(): return 1.0
	# The oldest marks go first: the fade follows the character from release to stop.
	var fade_age: float = _age - _fade_start - _fade_delays[index]
	return 1.0 - smoothstep(0.0, TRAIL_FADE_TIME, fade_age)


## Spaced by distance rather than by deposition time, or the sweep would cross the fast
## part of the slide in a blink and then crawl through the last slow few units.
func _predict_stop(puppet: JunkPuppet) -> float:
	# Same closed form and stop rule as the floor spring, from this moment of contact.
	var omega: float = JunkPuppet.SLIDE_FLOOR_OMEGA
	var offset: Vector2 = puppet._carry_position - puppet._held_position
	var impulse: Vector2 = puppet._carry_velocity + omega * offset
	var time: float = 0.0
	while time < 4.0:
		var decay: float = exp(-omega * time)
		var gap: Vector2 = (offset + impulse * time) * decay
		var velocity: Vector2 = (puppet._carry_velocity - omega * impulse * time) * decay
		if gap.length() < 0.2 and velocity.length() < 1.0: return time
		time += 1.0 / 120.0
	return time


func _prepare_fade() -> void:
	var arcs: Array[float] = [0.0]
	for index: int in range(1, _trail.size()):
		arcs.append(arcs[-1] + (_trail[index].point as Vector2).distance_to(_trail[index - 1].point))
	var total: float = maxf(arcs[-1], 0.001)
	_fade_sweep = lerpf(0.7, 1.4, clampf(total / 300.0, 0.0, 1.0))
	_fade_delays.resize(_trail.size())
	for index: int in range(_trail.size()):
		_fade_delays[index] = arcs[index] / total * _fade_sweep


func word() -> String:
	return word_override if not word_override.is_empty() else WORDS[seed_value % WORDS.size()]


static func _advance(letter: String) -> float:
	if letter in ["m", "w"]: return 10.0
	if letter in ["i", "!"]: return 5.0
	return 8.0


func _letter_scale() -> float:
	return float(15 + seed_value % 3) / (11.0 * maxf(0.25, pixel_zoom)) * (1.55 if hero else 1.0)


func word_origin() -> Vector2:
	var zoom: float = maxf(0.25, pixel_zoom)
	var letter_scale: float = _letter_scale()
	var width: float = 0.0
	for letter: String in word(): width += _advance(letter) * letter_scale
	var side: float = -signf(slide_velocity.x) if sliding and absf(slide_velocity.x) > 10.0 else (1.0 if seed_value % 2 == 0 else -1.0)
	var x: float = character_bounds.end.x + 14.0 / zoom if side > 0.0 else character_bounds.position.x - 14.0 / zoom - width
	if hero or poof:
		# Over the head: a cheer, or a last word where it stood.
		return Vector2(-width * 0.5, character_bounds.position.y - 28.0 / zoom)
	return Vector2(x, maxf(character_bounds.end.y, 0.0) + 24.0 / zoom)


func _process(delta: float) -> void:
	_spawn_contact()
	_age += delta
	if sliding and _tracking:
		_emission_time += delta
		var active: bool = is_instance_valid(_host) and not _host._held and _host._slide_drop
		var stopped: bool = not active
		if active:
			stopped = _host.position.distance_to(_host._held_position) < 0.2 and _host._carry_velocity.length() < 1.0
			_emit_wake(delta)
		if _emission_time >= 0.025 or stopped:
			_emission_time = fmod(_emission_time, 0.025)
			if active: _emit_trail(stopped)
			# Marks laid while cleanup is already running still join its sweep.
			if _fade_start >= 0.0 and _age >= _fade_start: _prepare_fade()
		if stopped:
			_tracking = false
			_stop_age = _age
			_fade_start = minf(_fade_start, _age + TRAIL_HOLD_TIME) if _fade_start >= 0.0 else _age + TRAIL_HOLD_TIME
			_prepare_fade()
	var finished: bool = _age > maxf(HERO_WORD_TIME if hero else WORD_TIME, _end_age)
	if sliding:
		finished = finished and not _tracking and not _trail.is_empty() and is_zero_approx(trail_opacity(_trail.size() - 1))
	if finished: queue_free()
	else: _redraw_all()


func _redraw_all() -> void:
	queue_redraw()
	if not is_inside_tree(): return
	for layer: Node2D in [_skid_layer, _ripple_layer, _floor_ink, _back_dust, _front_dust, _front_ink, _confetti_layer]:
		layer.queue_redraw()


# --- Spawning -----------------------------------------------------------------


func _spawn_contact() -> void:
	if _spawned: return
	_spawned = true
	_rng.seed = hash(seed_value * 7919 + 13)
	_end_age = DENT_TIME if not sliding and not poof else 0.0
	if reduced_motion: return
	# Contact records are born at age zero, so an effect can be sampled mid-life.
	var sampled_age: float = _age
	_age = 0.0
	if poof: _spawn_poof()
	elif sliding: _spawn_touchdown()
	else: _spawn_impact()
	if hero: _spawn_confetti()
	_age = sampled_age


## How much of a landing's energy goes down into the floor rather than along it.
func _impact_share() -> float:
	if poof: return 0.0
	if not sliding: return 1.0
	return 1.0 - smoothstep(260.0, 900.0, slide_velocity.length())


func _spawn_impact(share: float = 1.0) -> void:
	var power: float = clampf(strength, 0.25, 1.0)
	# A wide skirt of dust blown out flat along the floor by the falling weight.
	var skirt: int = int((15.0 + power * 9.0) * share)
	for index: int in range(skirt):
		var angle: float = (float(index) + _rng.randf_range(-0.3, 0.3)) / skirt * TAU
		var flat := Vector2(cos(angle), sin(angle) * FLOOR_SQUASH)
		var speed: float = _rng.randf_range(215.0, 380.0) * (0.72 + power * 0.55)
		_add_puff(flat * _rng.randf_range(6.0, 14.0), flat * speed, _rng.randf_range(5.5, 8.0), _rng.randf_range(12.0, 34.0), _rng.randf_range(7.0, 11.0), _rng.randf_range(15.0, 28.0) * (0.85 + power * 0.4), _rng.randf_range(0.55, 1.1), _rng.randf_range(0.55, 0.85), sin(angle) > -0.05)
	# Air squeezed out from under the body pushes a column up behind it.
	for index: int in range(int(5.0 * share)):
		var offset := Vector2(_rng.randf_range(-12.0, 12.0), _rng.randf_range(-4.0, 1.0))
		_add_puff(offset, Vector2(offset.x * 2.6, -8.0), 4.0, _rng.randf_range(58.0, 104.0), _rng.randf_range(8.0, 12.0), _rng.randf_range(20.0, 32.0), _rng.randf_range(0.7, 1.15), _rng.randf_range(0.42, 0.62), false)
	# Dense low cushion that sells the first frames of contact.
	_add_puff(Vector2(0, -1), Vector2.ZERO, 6.0, 8.0, 14.0, 36.0 + power * 10.0, 0.34, 0.7, false)
	var chips: int = int((10.0 + power * 9.0) * share)
	for index: int in range(chips):
		var angle: float = _rng.randf() * TAU
		_add_chip(Vector2(cos(angle) * 10.0, sin(angle) * 4.0), Vector2(cos(angle), sin(angle) * FLOOR_SQUASH) * _rng.randf_range(35.0, 120.0), _rng.randf_range(140.0, 330.0) * (0.75 + power * 0.5), _rng.randf_range(0.8, 1.15))
	# Comic impact lines, shooting out along the floor plane.
	var count: int = 0 if sliding else 11
	for index: int in range(count):
		var angle: float = (float(index) + _rng.randf_range(-0.28, 0.28)) / count * TAU
		_rays.append({"unit": Vector2(cos(angle), sin(angle) * FLOOR_SQUASH * 1.25), "start": _rng.randf_range(24.0, 32.0), "reach": (75.0 if index % 2 == 0 else 48.0) * (0.72 + power * 0.5), "width": _rng.randf_range(2.6, 4.4)})


## Balled-up paper bursting into scraps: a round cloud and pieces flung up and out.
func _spawn_poof() -> void:
	# Where the balled-up paper ends: low, just off the floor.
	var middle := Vector2(0, -18)
	for index: int in range(16):
		var angle: float = (float(index) + _rng.randf_range(-0.3, 0.3)) / 16.0 * TAU
		var unit := Vector2(cos(angle), sin(angle) * 0.7)
		_add_puff(middle + unit * 8.0, unit * _rng.randf_range(150.0, 280.0), 6.5, _rng.randf_range(24.0, 52.0), _rng.randf_range(10.0, 14.0), _rng.randf_range(24.0, 36.0), _rng.randf_range(0.55, 0.9), _rng.randf_range(0.6, 0.85), unit.y > 0.0)
	_add_puff(middle, Vector2.ZERO, 6.0, 24.0, 18.0, 52.0, 0.45, 0.85, true)
	for index: int in range(22):
		var angle: float = _rng.randf() * TAU
		var record_at: Vector2 = Vector2(cos(angle) * 8.0, sin(angle) * 4.0)
		_add_chip(record_at, Vector2(cos(angle), sin(angle) * FLOOR_SQUASH) * _rng.randf_range(60.0, 180.0), _rng.randf_range(160.0, 360.0), _rng.randf_range(0.8, 1.2), 1.5)


## Paper confetti thrown high, fluttering down and turning as it falls.
func _spawn_confetti() -> void:
	for index: int in range(44):
		var angle: float = -PI * 0.5 + _rng.randf_range(-1.25, 1.25)
		var record: Dictionary = {"at": Vector2(_rng.randf_range(-14.0, 14.0), _rng.randf_range(-4.0, 2.0)), "velocity": Vector2(cos(angle) * _rng.randf_range(260.0, 700.0), _rng.randf_range(-30.0, 30.0)), "loft": _rng.randf_range(480.0, 900.0), "life": _rng.randf_range(1.2, 1.7), "birth": _age + _rng.randf_range(0.0, 0.05), "spin": _rng.randf_range(-10.0, 10.0), "angle": _rng.randf() * TAU, "size": Vector2(_rng.randf_range(5.0, 9.0), _rng.randf_range(2.8, 4.6)), "tone": CONFETTI_TONES[_rng.randi() % CONFETTI_TONES.size()], "flutter": _rng.randf_range(4.0, 9.0)}
		if _chips.size() < MAX_CHIPS: _chips.append(record)
		else:
			_chips[_chip_cursor] = record
			_chip_cursor = (_chip_cursor + 1) % MAX_CHIPS
		_end_age = maxf(_end_age, _age + float(record.life))


func _spawn_touchdown() -> void:
	var direction: Vector2 = slide_velocity.normalized() if slide_velocity.length() > 1.0 else Vector2.RIGHT
	var speed: float = slide_velocity.length()
	var energy: float = clampf(speed / 480.0, 0.45, 1.0)
	var back: Vector2 = -direction
	var side: Vector2 = _floor_normal(direction)
	var contact: Vector2 = Vector2.ZERO
	if is_instance_valid(_host): contact = _host.transform * _host._ground_foot - position
	var share: float = _impact_share()
	if share > 0.05: _spawn_impact(share * 0.12)
	for index: int in range(3 + int(energy * 3.0)):
		var spread: float = _rng.randf_range(-1.0, 1.0)
		var throw: Vector2 = back * _rng.randf_range(120.0, 620.0) * energy + side * spread * _rng.randf_range(140.0, 360.0)
		_add_puff(contact + side * spread * _track_half * 0.4, throw, 4.5, _rng.randf_range(80.0, 190.0), _rng.randf_range(6.0, 9.0), _rng.randf_range(13.0, 21.0) * (0.8 + energy * 0.3), _rng.randf_range(0.55, 0.9), _rng.randf_range(0.8, 0.95), side.y * spread > 0.0)
	for index: int in range(1 + int(energy * 2.0)):
		var spread: float = _rng.randf_range(-1.0, 1.0)
		_add_chip(contact + side * spread * _track_half * 0.4, back * _rng.randf_range(30.0, 240.0) * energy + direction * speed * 0.25 + side * spread * 90.0, _rng.randf_range(110.0, 260.0) * energy, _rng.randf_range(0.65, 1.0))
	_last_contact = contact


## Rooster tail: dust kicked back and sideways, spaced by distance so frame rate and
## slide length cannot change how dense it looks.
func _emit_wake(delta: float) -> void:
	if _host._lift_height > 0.01: return
	var contact: Vector2 = _host.transform * _host._ground_foot - position
	if _last_contact == Vector2.INF: _last_contact = contact
	var travel: float = contact.distance_to(_last_contact)
	var velocity: Vector2 = _host._carry_velocity
	var speed: float = velocity.length()
	var direction: Vector2 = velocity / speed if speed > 1.0 else slide_velocity.normalized()
	if not reduced_motion:
		_streak_distance += travel
		# Timed, not spaced by distance: real slides are short, and must still throw plenty.
		if speed > WAKE_MIN_SPEED:
			_wake_clock += delta
			while _wake_clock >= WAKE_INTERVAL:
				_wake_clock -= WAKE_INTERVAL
				_spawn_wake_puff(_last_contact.lerp(contact, 1.0 - _wake_clock / maxf(delta, 0.001)), direction, speed)
		if _streak_distance >= 60.0 and speed > 650.0:
			_streak_distance = 0.0
			_spawn_streak(contact, direction, speed)
		if not _braked and speed < 85.0:
			_braked = true
			_spawn_braking(contact, direction)
	_last_contact = contact


func _spawn_wake_puff(at: Vector2, direction: Vector2, speed: float) -> void:
	var energy: float = clampf(speed / 480.0, 0.0, 1.0)
	var side: Vector2 = _floor_normal(direction)
	var spread: float = _rng.randf_range(-1.0, 1.0)
	# Thrown up and away, so each puff separates from the feet and reads on its own.
	var throw: Vector2 = -direction * _rng.randf_range(160.0, 520.0) * (0.55 + energy * 0.6) + side * spread * _rng.randf_range(120.0, 340.0)
	var life: float = lerpf(0.55, 0.95, energy) * _rng.randf_range(0.85, 1.15)
	var size: float = lerpf(10.0, 17.0, energy) * _rng.randf_range(0.8, 1.25)
	_add_puff(at - direction * _rng.randf_range(4.0, 14.0) + side * spread * _track_half * 0.3, throw, 4.0, _rng.randf_range(90.0, 210.0) * (0.6 + energy * 0.5), size * 0.5, size, life, lerpf(0.8, 0.95, energy), side.y * spread > 0.0)
	# Loose dirt flicked backward, arcing up and bouncing where it lands.
	for index: int in range(1 + int(_rng.randf() < 0.4 + energy * 0.5)):
		var scatter: float = _rng.randf_range(-1.0, 1.0)
		_add_chip(at + side * scatter * _track_half * 0.35, -direction * _rng.randf_range(50.0, 240.0) * (0.5 + energy * 0.6) + side * scatter * 90.0, _rng.randf_range(90.0, 280.0) * (0.5 + energy * 0.6), _rng.randf_range(0.5, 0.85))

func _spawn_streak(contact: Vector2, direction: Vector2, speed: float) -> void:
	var height: float = _body_size.y * _rng.randf_range(0.12, 0.86)
	var lateral: float = _body_size.x * 0.55 * maxf(absf(direction.x), 0.3)
	var length: float = clampf(speed * 0.2, 46.0, 150.0) * _rng.randf_range(0.65, 1.15)
	var head: Vector2 = contact - direction * lateral + Vector2(0, -height)
	var record: Dictionary = {"head": head, "tail": head - direction * length, "birth": _age, "life": _rng.randf_range(0.16, 0.26), "width": _rng.randf_range(3.2, 5.6)}
	if _streaks.size() < MAX_STREAKS: _streaks.append(record)
	else:
		_streaks[_streak_cursor] = record
		_streak_cursor = (_streak_cursor + 1) % MAX_STREAKS


## The feet are coming to rest, and a little dust settles around them.
func _spawn_braking(contact: Vector2, direction: Vector2) -> void:
	var travelled: float = 0.0
	if not _trail.is_empty(): travelled = contact.distance_to(_trail[0].point)
	var energy: float = clampf(travelled / 110.0, 0.35, 1.0)
	var side: Vector2 = _floor_normal(direction)
	# Only a breath of dust as the feet come to rest.
	for index: int in range(1 + int(energy * 2.0)):
		var spread: float = _rng.randf_range(-1.0, 1.0)
		_add_puff(contact + side * spread * _track_half * 0.3, direction * _rng.randf_range(20.0, 70.0) + side * spread * 40.0, 4.2, _rng.randf_range(6.0, 16.0), _rng.randf_range(7.0, 10.0), _rng.randf_range(18.0, 28.0), _rng.randf_range(0.5, 0.8), _rng.randf_range(0.4, 0.6), false)


func _add_puff(at: Vector2, velocity: Vector2, drag: float, rise: float, r0: float, r1: float, life: float, density: float, front: bool) -> void:
	var record: Dictionary = {"at": at, "velocity": velocity, "drag": drag, "rise": rise, "r0": r0, "r1": r1, "life": life, "density": density, "front": front, "birth": _age, "seed": _rng.randf(), "tone": _rng.randf(), "spin": _rng.randf() * TAU}
	if _puffs.size() < MAX_PUFFS: _puffs.append(record)
	else:
		_puffs[_puff_cursor] = record
		_puff_cursor = (_puff_cursor + 1) % MAX_PUFFS
	_end_age = maxf(_end_age, _age + life)


func _add_chip(at: Vector2, velocity: Vector2, loft: float, life: float, scale: float = 1.0) -> void:
	var record: Dictionary = {"at": at, "velocity": velocity, "loft": loft, "life": life, "birth": _age, "spin": _rng.randf_range(-16.0, 16.0), "angle": _rng.randf() * TAU, "size": Vector2(_rng.randf_range(2.2, 5.6), _rng.randf_range(1.2, 2.8)) * scale, "tone": CHIP_TONES[_rng.randi() % CHIP_TONES.size()]}
	if _chips.size() < MAX_CHIPS: _chips.append(record)
	else:
		_chips[_chip_cursor] = record
		_chip_cursor = (_chip_cursor + 1) % MAX_CHIPS
	_end_age = maxf(_end_age, _age + life)


## Perpendicular to a screen direction measured on the foreshortened floor plane.
func _floor_normal(direction: Vector2) -> Vector2:
	var on_floor := Vector2(direction.x, direction.y / FLOOR_SQUASH).normalized()
	return Vector2(-on_floor.y, on_floor.x * FLOOR_SQUASH)


# --- Layers -------------------------------------------------------------------


func _draw_skid() -> void:
	if not sliding or _trail.size() < 1: return
	var points: Array[Vector2] = []
	var pressures: Array[float] = []
	var lives: Array[float] = []
	for index: int in range(_trail.size()):
		points.append(_trail[index].point)
		pressures.append(float(_trail[index].get("pressure", 1.0)))
		lives.append(trail_opacity(index))
	if _tracking and is_instance_valid(_host) and not _host._held:
		# Keep the ribbon's head under the feet between the coarser recorded samples.
		var head: Vector2 = _host.transform * _host._ground_foot - position
		if head.distance_to(points[-1]) > 0.5:
			points.append(head)
			pressures.append(_pressure_for(_host._carry_velocity.length()))
			lives.append(1.0)
	var count: int = points.size()
	if count < 2: return
	var arcs: Array[float] = [0.0]
	for index: int in range(1, count): arcs.append(arcs[-1] + points[index].distance_to(points[index - 1]))
	var total: float = arcs[-1]
	var seed_channel: float = float(seed_value % 17) / 17.0
	var vertices := PackedVector2Array()
	var colors := PackedColorArray()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for index: int in range(count):
		# Tangent across a wider window, so short noisy samples cannot twist the strip.
		var tangent: Vector2 = points[mini(index + 2, count - 1)] - points[maxi(index - 2, 0)]
		var direction: Vector2 = tangent.normalized() if tangent.length() > 0.01 else Vector2.RIGHT
		# Tapers scale with the route, or a short real-world skid would be all taper.
		var taper: float = minf(26.0, total * 0.28)
		var cap: float = smoothstep(0.0, taper, arcs[index])
		# Round the live head under the feet, and leave a blunter stop once it has dug in.
		cap *= lerpf(0.12 if _tracking else 0.5, 1.0, smoothstep(0.0, taper * 0.8, total - arcs[index]))
		# Weight transfers gradually, so pressure may not step between neighbouring samples.
		var pressure: float = 0.0
		var weights: float = 0.0
		for near: int in range(maxi(index - 3, 0), mini(index + 4, count)):
			var weight: float = 4.0 - absi(near - index)
			pressure += pressures[near] * weight
			weights += weight
		pressure /= weights
		var half: float = _track_half * 0.66 * lerpf(0.5, 1.0, pressure) * maxf(cap, 0.04)
		var spread: Vector2 = _floor_normal(direction) * half
		var color := Color(pressure, lives[index], seed_channel, 1.0)
		vertices.append(points[index] - spread)
		vertices.append(points[index] + spread)
		colors.append(color)
		colors.append(color)
		uvs.append(Vector2(arcs[index], -1.0))
		uvs.append(Vector2(arcs[index], 1.0))
		if index > 0:
			var base: int = (index - 1) * 2
			indices.append_array(PackedInt32Array([base, base + 1, base + 3, base, base + 3, base + 2]))
	RenderingServer.canvas_item_add_triangle_array(_skid_layer.get_canvas_item(), indices, vertices, colors, uvs)


func _draw_ripple() -> void:
	var share: float = _impact_share()
	if share < 0.05: return
	var power: float = clampf(strength, 0.25, 1.0)
	var material_seed: float = float(seed_value % 31) * 1.37
	(_ripple_layer.material as ShaderMaterial).set_shader_parameter("seed", material_seed)
	var reach: float = (82.0 if reduced_motion else 105.0 + power * 55.0) / maxf(minf(pixel_zoom, 1.0), 0.5)
	var dent: float = (1.0 - smoothstep(0.1, DENT_TIME, _age)) * share
	var wave_radius: float = 0.42 if reduced_motion else 1.0 - exp(-5.2 * _age)
	var wave_width: float = 0.03 if reduced_motion else lerpf(0.055, 0.016, smoothstep(0.0, 0.5, _age))
	var wave: float = (1.0 - smoothstep(0.0, 0.42, _age)) * 0.5 if reduced_motion else pow(maxf(1.0 - _age / 0.68, 0.0), 1.6) * (0.68 + power * 0.32)
	# Contact has to read on the very first frame, before the wave has travelled.
	var flash: float = 0.0 if reduced_motion else 1.0 - smoothstep(0.0, 0.1, _age)
	wave *= share
	if sliding:
		wave *= 0.4
		dent *= 0.45
	var batch := Batch.new()
	var half := Vector2(reach, reach * FLOOR_SQUASH)
	batch.quad(-half, Vector2(half.x, -half.y), half, Vector2(-half.x, half.y), Color(wave_radius, wave_width, clampf(dent + flash * 0.3, 0.0, 1.0) * (0.42 if reduced_motion else 1.0), wave))
	batch.flush(_ripple_layer)


func _draw_floor_ink() -> void:
	if _rays.is_empty(): return
	var duration: float = 0.2
	if _age >= duration: return
	var batch := Batch.new()
	var fade: float = 1.0 - smoothstep(0.6, 1.0, _age / duration)
	for ray: Dictionary in _rays:
		var head: float = 1.0 - exp(-_age * 20.0)
		var tail: float = 1.0 - exp(-_age * 8.5)
		var start: Vector2 = ray.unit * (float(ray.start) + float(ray.reach) * tail)
		var finish: Vector2 = ray.unit * (float(ray.start) + float(ray.reach) * head)
		batch.stroke(start, finish, _ink_width(float(ray.width)), Color(INK, fade * 0.86))
	batch.flush(_floor_ink)


func _draw_back_dust() -> void:
	_draw_puffs(_back_dust, false)


func _draw_front_dust() -> void:
	_draw_puffs(_front_dust, true)


func _draw_puffs(layer: Node2D, front: bool) -> void:
	var batch := Batch.new()
	for puff: Dictionary in _puffs:
		if bool(puff.front) != front: continue
		var age: float = _age - float(puff.birth)
		var life: float = age / float(puff.life)
		if age < 0.0 or life >= 1.0: continue
		var drag: float = puff.drag
		var center: Vector2 = puff.at + puff.velocity * (1.0 - exp(-drag * age)) / drag
		# Dust stalls along the floor before buoyancy lifts it, curling slightly downwind.
		center.y -= float(puff.rise) * (1.0 - exp(-1.5 * age)) / 1.5
		var radius: float = lerpf(float(puff.r0), float(puff.r1), 1.0 - exp(-4.2 * age))
		var flat: float = lerpf(0.5, 0.92, smoothstep(0.0, 0.7, life))
		var grow: float = smoothstep(0.0, 0.05, age)
		var axis := Vector2(radius, 0)
		var up := Vector2(0, radius * flat)
		center.y -= up.y * 0.6
		batch.quad(center - axis - up, center + axis - up, center + axis + up, center - axis + up, Color(puff.seed, life, puff.tone, float(puff.density) * grow))
	batch.flush(layer)


func _draw_front_ink() -> void:
	var batch := Batch.new()
	for streak: Dictionary in _streaks:
		var life: float = (_age - float(streak.birth)) / float(streak.life)
		if life < 0.0 or life >= 1.0: continue
		# The head stays put while the tail races in, so each line snaps shut.
		var tail: Vector2 = (streak.tail as Vector2).lerp(streak.head, smoothstep(0.1, 1.0, life))
		batch.stroke(tail, streak.head, _ink_width(float(streak.width)), Color(INK, (0.3 if sliding else 0.74) * (1.0 - life * life)))
	_draw_chips(batch, false)
	batch.flush(_front_ink)


func _draw_confetti() -> void:
	if not hero: return
	var batch := Batch.new()
	_draw_chips(batch, true)
	batch.flush(_confetti_layer)


func _draw_chips(batch: Batch, confetti: bool) -> void:
	for chip: Dictionary in _chips:
		if chip.has("flutter") != confetti: continue
		var age: float = _age - float(chip.birth)
		var life: float = age / float(chip.life)
		if age < 0.0 or life >= 1.0: continue
		var floor_point: Vector2 = chip.at + chip.velocity * (1.0 - exp(-1.8 * age)) / 1.8
		var height: float = _chip_height(float(chip.loft), age)
		if chip.has("flutter"):
			# Light paper: burst up and out, caught by the air, then drifting down side to side.
			floor_point = chip.at + (chip.velocity as Vector2) * (1.0 - exp(-3.0 * age)) / 3.0
			height = maxf(float(chip.loft) / 3.0 * (1.0 - exp(-3.0 * age)) - 60.0 * age, 0.0)
			floor_point.x += sin(age * float(chip.flutter)) * 10.0 * smoothstep(0.15, 0.6, age)
		var center: Vector2 = floor_point + Vector2(0, -height)
		# Cardboard flakes flip end over end, so their visible width changes as they tumble.
		var angle: float = float(chip.angle) + float(chip.spin) * age
		var size: Vector2 = chip.size
		var along := Vector2(cos(angle), sin(angle)) * maxf(size.x * absf(cos(angle * 0.7)), 1.1)
		var across := Vector2(-sin(angle), cos(angle)) * size.y
		var tone: Color = chip.tone
		tone.a = 1.0 - smoothstep(0.72, 1.0, life)
		batch.quad(center - along - across, center + along - across, center + along + across, center - along + across, tone)


## Ballistic arc with two decaying floor bounces. Rests on the floor afterward.
func _chip_height(loft: float, age: float) -> float:
	var time: float = age
	var speed: float = loft
	for bounce: int in range(3):
		var airtime: float = 2.0 * speed / CHIP_GRAVITY
		if time < airtime: return speed * time - 0.5 * CHIP_GRAVITY * time * time
		time -= airtime
		speed *= 0.42
	return 0.0


## Hold a readable screen width when zoomed out, without bloating when zoomed in.
func _ink_width(world_width: float) -> float:
	var zoom: float = maxf(pixel_zoom, 0.25)
	return clampf(world_width, 1.5 / zoom, 6.5 / zoom)


func _draw() -> void:
	var t: float = clampf(_age / (HERO_WORD_TIME if hero else WORD_TIME), 0, 1)
	if t >= 1.0: return
	var zoom: float = maxf(0.25, pixel_zoom)
	var fade: float = 1.0 - smoothstep(0.42, 0.95, t)
	var word: String = word()
	var word_ink := Color(0.27, 0.15, 0.07, fade) if not hero else Color(ORANGE_INK, fade)
	var paper := Color(0.97, 0.955, 0.91, fade * 0.92)
	var letter_scale: float = _letter_scale()
	var anchor: Vector2 = word_origin()
	var width: float = 0.0
	for letter: String in word: width += _advance(letter) * letter_scale
	# Stamped on: overshoots large for a beat and snaps down around its own centre.
	var pop: float = 1.0
	if not reduced_motion: pop = 1.0 + 0.62 * exp(-_age * 19.0) * cos(_age * 26.0)
	var pivot: Vector2 = anchor + Vector2(width * 0.5, -5.0 * letter_scale)
	for pass_index: int in range(2):
		var cursor: float = anchor.x
		for index: int in range(word.length()):
			var drift: float = 0.0 if reduced_motion else t * 2.0
			var origin := Vector2(cursor, anchor.y + (drift + sin(index * 4 + seed_value) * 0.45) / zoom)
			origin = pivot + (origin - pivot) * pop
			draw_set_transform(origin, sin(index * 3 + seed_value) * 0.06, Vector2.ONE * letter_scale * pop)
			for stroke: Array in LETTERS[word[index]]:
				# A paper knockout keeps the lettering legible where dust blows past it.
				var stroke_width: float = (4.6 if pass_index == 0 else 2.0) / (zoom * letter_scale * pop)
				draw_polyline(PackedVector2Array(stroke), paper if pass_index == 0 else word_ink, stroke_width, true)
			cursor += _advance(word[index]) * letter_scale
	draw_set_transform(Vector2.ZERO)
