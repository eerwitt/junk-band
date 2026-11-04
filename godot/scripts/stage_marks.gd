class_name JunkStageMarks
extends Node2D
## Small, frequent marks shared by the whole band: inked sound lines and music notes on each
## note, dust under footsteps, and pencil crumbs where a path was rubbed out. One node and a
## few batched draws for everyone, with capped records, so a busy song stays cheap.

const INK := Color(0.27, 0.16, 0.08)
const ORANGE := Color("b86339")
const NOTE_TONES: Array[Color] = [Color("29271f"), Color("b86339"), Color("8a9f8c"), Color("c9a23e")]
const MAX_LINES: int = 96
const MAX_NOTES: int = 24
const MAX_PUFFS: int = 48
const MAX_CRUMBS: int = 160
## The busiest parts (sixteenth-note hats) would scribble over themselves without a gap.
const MIN_MARK_GAP: float = 0.16
const MIN_NOTE_GAP: float = 0.38

var pixel_zoom: float = 1.0
var _age: float = 0.0
var _lines: Array[Dictionary] = []
var _notes: Array[Dictionary] = []
var _puffs: Array[Dictionary] = []
var _crumbs: Array[Dictionary] = []
var _cursors: Dictionary = {}
var _last_mark: Dictionary = {}
var _last_note: Dictionary = {}
var _rng := RandomNumberGenerator.new()
var _ink_layer: Node2D
var _glyph_layer: Node2D
var _dust_layer: Node2D
var _end_age: float = 0.0


func _init() -> void:
	_rng.seed = 7
	_dust_layer = _layer(99, preload("res://shaders/vfx_dust.gdshader"), _draw_dust)
	_ink_layer = _layer(3050, preload("res://shaders/vfx_ink.gdshader"), _draw_ink)
	_glyph_layer = _layer(3050, null, _draw_glyphs)


func _layer(depth: int, shader: Shader, painter: Callable) -> Node2D:
	var layer := Node2D.new()
	layer.z_as_relative = false
	layer.z_index = depth
	if shader != null:
		var shade := ShaderMaterial.new()
		shade.shader = shader
		layer.material = shade
	layer.draw.connect(painter)
	add_child(layer)
	return layer


func _keep(list: Array[Dictionary], record: Dictionary, cap: int, key: String) -> void:
	if list.size() < cap:
		list.append(record)
	else:
		var cursor: int = int(_cursors.get(key, 0))
		list[cursor] = record
		_cursors[key] = (cursor + 1) % cap
	_end_age = maxf(_end_age, _age + float(record.life))


## A note sounded. `top` is the head of the character on the floor plane's screen space,
## `half_width` half its drawn width.
func note(id: String, top: Vector2, half_width: float, strength: float, downbeat: bool, tuned: bool) -> void:
	if _age - float(_last_mark.get(id, -10.0)) >= MIN_MARK_GAP or downbeat:
		_last_mark[id] = _age
		var count: int = 3 if downbeat else 2
		var reach: float = lerpf(15.0, 26.0, strength) * (1.25 if downbeat else 1.0)
		# Fanned over the head, the middle one tallest, like lines drawn around a struck bell.
		var spread: float = 0.55 if downbeat else 0.42
		var tilt: float = _rng.randf_range(-0.18, 0.18)
		for index: int in range(count):
			var share: float = (float(index) / maxf(count - 1, 1) - 0.5) * 2.0
			var angle: float = -PI * 0.5 + share * spread * 1.6 + tilt
			var unit := Vector2(cos(angle), sin(angle))
			var root: Vector2 = top + Vector2(share * half_width * 0.55, 0) + unit * (8.0 + absf(share) * 4.0)
			_keep(_lines, {"root": root, "unit": unit, "reach": reach * (1.0 - absf(share) * 0.25), "birth": _age, "life": 0.28 if downbeat else 0.22, "width": 7.0 if downbeat else 5.5, "alpha": 0.9 if downbeat else 0.7}, MAX_LINES, "lines")
	if tuned and _age - float(_last_note.get(id, -10.0)) >= MIN_NOTE_GAP:
		_last_note[id] = _age
		var side: float = 1.0 if _rng.randf() < 0.5 else -1.0
		_keep(_notes, {"at": top + Vector2(side * half_width * 0.7, 6.0), "drift": Vector2(side * _rng.randf_range(10.0, 22.0), -_rng.randf_range(34.0, 52.0)), "birth": _age, "life": 0.95, "size": lerpf(0.85, 1.15, strength), "tone": NOTE_TONES[_rng.randi() % NOTE_TONES.size()], "double": _rng.randf() < 0.3, "spin": _rng.randf_range(-0.3, 0.3)}, MAX_NOTES, "notes")


## A foot came down. Two little puffs either side of it, kept low.
func step(point: Vector2, strength: float) -> void:
	for side: float in [-1.0, 1.0]:
		var throw := Vector2(side * _rng.randf_range(40.0, 80.0), _rng.randf_range(-4.0, 4.0)) * (0.6 + strength * 0.6)
		_keep(_puffs, {"at": point + Vector2(side * 6.0, 0), "velocity": throw, "rise": _rng.randf_range(6.0, 16.0), "r0": 3.5, "r1": lerpf(7.0, 12.0, strength), "birth": _age, "life": _rng.randf_range(0.35, 0.5), "density": lerpf(0.35, 0.6, strength), "seed": _rng.randf(), "tone": _rng.randf()}, MAX_PUFFS, "puffs")


## A path rubbed out: graphite crumbs along it, swept away from its start to its end.
func erase(points: PackedVector2Array) -> void:
	if points.size() < 2: return
	var total: float = 0.0
	for index: int in range(1, points.size()): total += points[index].distance_to(points[index - 1])
	var spacing: float = maxf(total / float(MAX_CRUMBS / 2), 7.0)
	var travelled: float = 0.0
	var next_crumb: float = 0.0
	for index: int in range(1, points.size()):
		var a: Vector2 = points[index - 1]
		var b: Vector2 = points[index]
		var length: float = a.distance_to(b)
		while next_crumb <= travelled + length:
			var at: Vector2 = a.lerp(b, (next_crumb - travelled) / maxf(length, 0.001))
			var delay: float = next_crumb / maxf(total, 1.0) * 0.35
			var flick := Vector2(_rng.randf_range(-1.0, 1.0), _rng.randf_range(-0.6, 0.4)).normalized() * _rng.randf_range(12.0, 34.0)
			_keep(_crumbs, {"at": at, "velocity": flick, "birth": _age + delay, "life": _rng.randf_range(0.35, 0.55), "size": Vector2(_rng.randf_range(1.4, 2.8), _rng.randf_range(0.9, 1.6)), "angle": _rng.randf() * TAU, "spin": _rng.randf_range(-12.0, 12.0), "grey": _rng.randf_range(0.32, 0.5)}, MAX_CRUMBS, "crumbs")
			next_crumb += spacing
		travelled += length


func busy() -> bool:
	return _age < _end_age


func _process(delta: float) -> void:
	_age += delta
	if _age < _end_age + 0.05:
		_ink_layer.queue_redraw()
		_glyph_layer.queue_redraw()
		_dust_layer.queue_redraw()


func _ink_width(world_width: float) -> float:
	var zoom: float = maxf(pixel_zoom, 0.25)
	return clampf(world_width, 2.0 / zoom, 6.0 / zoom)


func _draw_ink() -> void:
	var batch := JunkLandingEffect.Batch.new()
	for line: Dictionary in _lines:
		var age: float = _age - float(line.birth)
		var life: float = age / float(line.life)
		if age < 0.0 or life >= 1.0: continue
		# Shoots out fast, then the tail catches the head and the line snaps shut.
		var head: float = 1.0 - exp(-age * 34.0)
		var tail: float = smoothstep(0.35, 1.0, life)
		var root: Vector2 = line.root
		var unit: Vector2 = line.unit
		var reach: float = line.reach
		batch.stroke(root + unit * reach * tail, root + unit * reach * maxf(head, tail + 0.05), _ink_width(float(line.width)), Color(INK, float(line.alpha) * (1.0 - life * life)))
	for crumb: Dictionary in _crumbs:
		var age: float = _age - float(crumb.birth)
		var life: float = age / float(crumb.life)
		if age < 0.0 or life >= 1.0: continue
		var center: Vector2 = crumb.at + (crumb.velocity as Vector2) * (1.0 - exp(-5.0 * age)) / 5.0 + Vector2(0, 40.0 * age * age)
		var angle: float = float(crumb.angle) + float(crumb.spin) * age
		var size: Vector2 = crumb.size
		var along := Vector2(cos(angle), sin(angle)) * size.x
		var across := Vector2(-sin(angle), cos(angle)) * size.y
		var grey: float = crumb.grey
		batch.quad(center - along - across, center + along - across, center + along + across, center - along + across, Color(grey, grey * 0.97, grey * 0.92, 0.85 * (1.0 - smoothstep(0.55, 1.0, life))))
	batch.flush(_ink_layer)


## Hand-drawn music notes that float up off tuned characters and wobble as they go.
func _draw_glyphs() -> void:
	for note: Dictionary in _notes:
		var age: float = _age - float(note.birth)
		var life: float = age / float(note.life)
		if age < 0.0 or life >= 1.0: continue
		var drift: Vector2 = note.drift
		var center: Vector2 = note.at + drift * (1.0 - exp(-2.5 * age)) + Vector2(sin(age * 9.0) * 3.0, 0)
		var pop: float = 1.0 + 0.5 * exp(-age * 16.0) * cos(age * 22.0)
		var size: float = float(note.size) * pop / maxf(minf(pixel_zoom, 1.2), 0.5)
		var tone: Color = note.tone
		tone.a = (1.0 - smoothstep(0.55, 1.0, life)) * smoothstep(0.0, 0.06, age)
		_glyph_layer.draw_set_transform(center, float(note.spin) + sin(age * 7.0) * 0.12, Vector2.ONE * size)
		_note_glyph(tone, bool(note.double))
	_glyph_layer.draw_set_transform(Vector2.ZERO)


func _note_glyph(tone: Color, double: bool) -> void:
	var heads: Array[Vector2] = [Vector2(0, 0)]
	if double: heads.append(Vector2(9, -3))
	# Tilted oval heads.
	var points := PackedVector2Array()
	for index: int in range(13):
		var angle: float = float(index) / 12.0 * TAU
		points.append(Vector2(cos(angle) * 3.6, sin(angle) * 2.5).rotated(-0.45))
	for head: Vector2 in heads:
		var shape := PackedVector2Array()
		for point: Vector2 in points: shape.append(point + head)
		_glyph_layer.draw_colored_polygon(shape, tone)
	var stem: Vector2 = heads[-1] + Vector2(3.2, -1.0)
	if double:
		_glyph_layer.draw_line(Vector2(3.2, -1.0), Vector2(3.2, -15.0), tone, 1.3, true)
		_glyph_layer.draw_line(stem, stem + Vector2(0, -14.0), tone, 1.3, true)
		_glyph_layer.draw_line(Vector2(3.2, -15.0), stem + Vector2(0, -14.0), tone, 2.4, true)
	else:
		_glyph_layer.draw_line(stem, stem + Vector2(0, -14.0), tone, 1.3, true)
		_glyph_layer.draw_polyline(PackedVector2Array([stem + Vector2(0, -14.0), stem + Vector2(4.5, -10.0), stem + Vector2(5.0, -5.5)]), tone, 1.3, true)


func _draw_dust() -> void:
	var batch := JunkLandingEffect.Batch.new()
	for puff: Dictionary in _puffs:
		var age: float = _age - float(puff.birth)
		var life: float = age / float(puff.life)
		if age < 0.0 or life >= 1.0: continue
		var center: Vector2 = puff.at + (puff.velocity as Vector2) * (1.0 - exp(-7.0 * age)) / 7.0
		center.y -= float(puff.rise) * (1.0 - exp(-2.0 * age)) / 2.0
		var radius: float = lerpf(float(puff.r0), float(puff.r1), 1.0 - exp(-6.0 * age))
		var axis := Vector2(radius, 0)
		var up := Vector2(0, radius * lerpf(0.5, 0.85, life))
		center.y -= up.y * 0.6
		batch.quad(center - axis - up, center + axis - up, center + axis + up, center - axis + up, Color(puff.seed, life, puff.tone, float(puff.density) * smoothstep(0.0, 0.04, age)))
	batch.flush(_dust_layer)
