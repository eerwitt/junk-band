class_name JunkOrbitScrubber
extends Node2D

const SEGMENTS: int = 160
const BAND_WIDTH: float = 34.0
const RING_REACH: float = 16.0
const FOCUSED_RING_REACH: float = 9.0
const BAND_GAP: float = 8.0
const FONT := preload("res://assets/NotoSans-Regular.ttf")
const SHADE := Color(0.62, 0.49, 0.32)
const LABEL_INK := Color(0.30, 0.24, 0.15)

var radii := Vector2(300, 180)
var hovered: bool = false
var dragging: bool = false
var beat: float = 0.0
var pulse: float = 0.0
## Each is {"start", "end", "label"}, with start and end as fractions of the whole song.
var sections: Array = []
var hover_index: int = -1
var focus_index: int = -1
var over_band: bool = false
var _emphasis: float = 0.0
var _reveal: Array[float] = []
var _focus_amount: float = 0.0
var _band_glow: float = 0.0
var _stamp_index: int = -1
var _stamp_age: float = 10.0
var _lap_age: float = 10.0


func set_sections(next: Array) -> void:
	sections = next
	_reveal.resize(next.size())


func advance(current_beat: float, delta: float) -> void:
	beat = current_beat
	_emphasis = lerpf(_emphasis, 1.0 if hovered or dragging else 0.0, 1.0 - exp(-14.0 * delta))
	for index: int in range(_reveal.size()):
		_reveal[index] = move_toward(_reveal[index], 1.0 if index == hover_index else 0.0, delta / (0.22 if index == hover_index else 0.16))
	_focus_amount = move_toward(_focus_amount, 1.0 if focus_index >= 0 else 0.0, delta / 0.55)
	_band_glow = lerpf(_band_glow, 1.0 if over_band else 0.0, 1.0 - exp(-14.0 * delta))
	_stamp_age += delta
	_lap_age += delta
	queue_redraw()


## The song moved into a new section: its arc flashes and its name is stamped beside it.
func stamp_section(index: int) -> void:
	if index < 0 or index >= sections.size(): return
	_stamp_index = index
	_stamp_age = 0.0


## The loop came back round: a highlight races the whole ring.
func lap() -> void:
	_lap_age = 0.0


func reveal_amount() -> float:
	var most: float = 0.0
	for amount: float in _reveal: most = maxf(most, amount)
	return most


func point_at(fraction: float) -> Vector2:
	var angle: float = fraction * TAU
	return Vector2(-sin(angle) * radii.x, -cos(angle) * radii.y) * (1.0 + pulse * 0.005 if not dragging else 1.0)


func _rim(fraction: float, offset: float) -> Vector2:
	var angle: float = fraction * TAU
	return Vector2(-sin(angle) * (radii.x + offset), -cos(angle) * (radii.y + offset))


func _text_scale() -> float:
	return clampf(radii.x / 304.0, 0.55, 1.25)


func _band_width() -> float:
	return BAND_WIDTH * _text_scale()


func _fraction_at(point: Vector2) -> float:
	var local: Vector2 = point - position
	return fposmod(atan2(-local.x / radii.x, -local.y / radii.y), TAU) / TAU


## How far the point sits outside the ring, measured along its ray from the centre.
func _outward(point: Vector2) -> float:
	var local: Vector2 = point - position
	return local.length() - _rim(_fraction_at(point), 0.0).length()


## "ring" scrubs and picks a section, "band" is the outer strip that returns to the whole song.
func zone(point: Vector2) -> String:
	var distance: float = _outward(point)
	if focus_index >= 0:
		if absf(distance) <= FOCUSED_RING_REACH: return "ring"
		if distance > 0.0 and distance <= BAND_GAP + _band_width() + 4.0: return "band"
		return ""
	if absf(distance) <= RING_REACH: return "ring"
	# Once a section has opened out, its shaded area is part of the same target.
	if hover_index >= 0 and hover_index < _reveal.size() and distance > 0.0 and distance <= _band_width() * _reveal[hover_index] + 6.0:
		return "ring"
	return ""


func hit(point: Vector2) -> bool:
	return zone(point) != ""


func section_at_point(point: Vector2) -> int:
	return section_at_fraction(_fraction_at(point))


func section_at_fraction(fraction: float) -> int:
	for index: int in range(sections.size()):
		if fraction >= float(sections[index].start) and fraction < float(sections[index].end):
			return index
	return sections.size() - 1


func beat_at(point: Vector2) -> float:
	return _fraction_at(point) * JunkLoopTiming.BEATS


func _arc(from_fraction: float, to_fraction: float, offset: float, width: float, color: Color) -> void:
	if to_fraction - from_fraction <= 0.0005 or width <= 0.05: return
	var steps: int = maxi(2, ceili((to_fraction - from_fraction) * SEGMENTS))
	var points := PackedVector2Array()
	for index: int in range(steps + 1):
		points.append(_rim(lerpf(from_fraction, to_fraction, float(index) / steps), offset))
	draw_polyline(points, color, width, true)


## Text along the ellipse, always reading left to right whichever side of the ring it is on.
func _curved_text(text: String, center: float, offset: float, font_size: int, color: Color) -> void:
	if color.a <= 0.01: return
	var direction: float = -1.0 if _rim(center, offset).y < 0.0 else 1.0
	var total: float = FONT.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	# Measured along the ellipse itself, which moves slower along its sides than its top.
	var fraction: float = _walk(center, -direction, total * 0.5, offset)
	for index: int in range(text.length()):
		var character: String = text[index]
		var advance_width: float = FONT.get_char_size(character.unicode_at(0), font_size).x
		var middle: float = _walk(fraction, direction, advance_width * 0.5, offset)
		var ahead: Vector2 = _rim(middle + direction * 0.002, offset) - _rim(middle - direction * 0.002, offset)
		draw_set_transform(_rim(middle, offset), ahead.angle())
		draw_char(FONT, Vector2(-advance_width * 0.5, font_size * 0.36), character, font_size, color)
		fraction = _walk(middle, direction, advance_width * 0.5, offset)
	draw_set_transform(Vector2.ZERO)


## The fraction reached by travelling that many pixels along the ellipse.
func _walk(fraction: float, direction: float, pixels: float, offset: float) -> float:
	var reached: float = fraction
	var left: float = pixels
	while left > 0.0:
		var stride: float = minf(left, 6.0)
		var angle: float = reached * TAU
		var speed: float = TAU * Vector2(cos(angle) * (radii.x + offset), sin(angle) * (radii.y + offset)).length()
		reached += direction * stride / maxf(speed, 1.0)
		left -= stride
	return reached


func _circumference(offset: float) -> float:
	var a: float = radii.x + offset
	var b: float = radii.y + offset
	var h: float = pow(a - b, 2) / pow(a + b, 2)
	return PI * (a + b) * (1.0 + 3.0 * h / (10.0 + sqrt(4.0 - 3.0 * h)))


func _draw_focus_band() -> void:
	if _focus_amount <= 0.003 or focus_index < 0 and sections.is_empty(): return
	var index: int = clampi(focus_index if focus_index >= 0 else 0, 0, sections.size() - 1)
	var section: Dictionary = sections[index]
	var eased: float = ease(_focus_amount, -2.2)
	var middle: float = (float(section.start) + float(section.end)) * 0.5
	var reach: float = 0.5 * eased
	var width: float = _band_width()
	var offset: float = BAND_GAP + width * 0.5
	_arc(middle - reach, middle + reach, offset, width, Color(SHADE, 0.13 + _band_glow * 0.12))
	_arc(middle - reach, middle + reach, BAND_GAP + width, 1.0, Color(SHADE, 0.28 + _band_glow * 0.25))
	var font_size: int = clampi(roundi(13.0 * _text_scale()), 10, 15)
	var label: String = str(section.label)
	var unit: float = FONT.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x + 46.0 * _text_scale()
	var perimeter: float = _circumference(offset)
	var count: int = maxi(1, floori(perimeter / unit))
	for repeat: int in range(count):
		var center: float = middle + float(repeat) / count
		var from_middle: float = absf(fposmod(center - middle + 0.5, 1.0) - 0.5)
		if from_middle > reach: continue
		if hover_index >= 0 and hover_index != focus_index and hover_index < _reveal.size() and _reveal[hover_index] > 0.1:
			var hovered_section: Dictionary = sections[hover_index]
			var inside: float = fposmod(center, 1.0)
			if inside > float(hovered_section.start) - 0.02 and inside < float(hovered_section.end) + 0.02: continue
		var fade: float = clampf((reach - from_middle) * 12.0, 0.0, 1.0)
		_curved_text(label, center, offset, font_size, Color(LABEL_INK, (0.5 + _band_glow * 0.3) * fade * _focus_amount))


func _draw_hover() -> void:
	var font_size: int = clampi(roundi(13.0 * _text_scale()), 10, 15)
	for index: int in range(mini(_reveal.size(), sections.size())):
		var amount: float = _reveal[index]
		if amount <= 0.003: continue
		if index == focus_index and _focus_amount > 0.5: continue
		var section: Dictionary = sections[index]
		var eased: float = ease(amount, -2.4)
		var middle: float = (float(section.start) + float(section.end)) * 0.5
		var half: float = (float(section.end) - float(section.start)) * 0.5 * eased
		var width: float = _band_width() * eased
		var gap: float = BAND_GAP if focus_index >= 0 else 3.0
		_arc(middle - half, middle + half, gap + width * 0.5, width, Color(SHADE, 0.24 * eased))
		_arc(middle - half, middle + half, gap + width, 1.0, Color(SHADE, 0.3 * eased))
		_curved_text(str(section.label), middle, gap + width * 0.5, font_size, Color(LABEL_INK, 0.72 * smoothstep(0.55, 1.0, amount)))


func _draw_stamp(width: float) -> void:
	if _stamp_index < 0 or _stamp_index >= sections.size() or _stamp_age > 1.4: return
	var section: Dictionary = sections[_stamp_index]
	var start: float = float(section.start)
	var end: float = float(section.end)
	# Inks along the section from where the cursor entered, then fades as one.
	var sweep: float = 1.0 - exp(-_stamp_age * 9.0)
	var fade: float = 1.0 - smoothstep(0.5, 1.2, _stamp_age)
	_arc(start, lerpf(start, end, sweep), 0.0, width + 3.0 * fade, Color(0.72, 0.42, 0.22, 0.55 * fade))
	# The name, stamped in the hover band's place: a pop, a hold, then gone.
	if hover_index == _stamp_index or (focus_index >= 0 and _focus_amount > 0.5): return
	var font_size: int = clampi(roundi(13.0 * _text_scale()), 10, 15)
	var pop: float = 1.0 + 0.35 * exp(-_stamp_age * 14.0) * cos(_stamp_age * 24.0)
	var shown: float = smoothstep(0.0, 0.06, _stamp_age) * (1.0 - smoothstep(0.85, 1.4, _stamp_age))
	_curved_text(str(section.label), (start + end) * 0.5, 3.0 + _band_width() * 0.5 * pop, roundi(font_size * pop), Color(LABEL_INK, 0.7 * shown))


func _draw_lap(width: float) -> void:
	if _lap_age > 0.9: return
	# A short bright comet leaves the top and runs once round, the way the cursor travels.
	var head: float = ease(clampf(_lap_age / 0.75, 0.0, 1.0), 0.6)
	var tail: float = maxf(0.0, head - 0.16)
	var fade: float = 1.0 - smoothstep(0.6, 0.9, _lap_age)
	var steps: int = 12
	for index: int in range(steps):
		var a: float = lerpf(tail, head, float(index) / steps)
		var b: float = lerpf(tail, head, float(index + 1) / steps)
		var share: float = float(index + 1) / steps
		var points := PackedVector2Array([point_at(a), point_at((a + b) * 0.5), point_at(b)])
		draw_polyline(points, Color(0.80, 0.52, 0.28, 0.7 * share * fade), width + 3.0 * share, true)


func _draw() -> void:
	_draw_focus_band()
	_draw_hover()
	var points := PackedVector2Array()
	var colors := PackedColorArray()
	for index: int in range(SEGMENTS + 1):
		var fraction: float = float(index) / SEGMENTS
		points.append(point_at(fraction))
		var warmth: float = (1.0 + sin(fraction * TAU - PI / 2.0)) * 0.5
		colors.append(Color(0.71, 0.64, 0.50, 0.15).lerp(Color(0.75, 0.60, 0.42, 0.32), warmth))
	var width: float = lerpf(2.5, 5.0, _emphasis) + pulse * 0.24
	if _emphasis > 0.005:
		draw_set_transform(Vector2(0, 2))
		draw_polyline(points, Color(0.30, 0.24, 0.15, _emphasis * 0.035), width + 6.0, true)
		draw_polyline(points, Color(0.30, 0.24, 0.15, _emphasis * 0.055), width + 2.0, true)
		draw_set_transform(Vector2.ZERO)
	draw_polyline_colors(points, colors, width + 2.0, true)
	draw_polyline(points, Color(1, 0.99, 0.95, 0.32), width, true)
	if focus_index >= 0 and focus_index < sections.size():
		_arc(float(sections[focus_index].start), float(sections[focus_index].end), 0.0, width + 2.5, Color(0.72, 0.45, 0.25, 0.5 * _focus_amount))
	for section: Dictionary in sections:
		var notch: float = 3.0 + _emphasis * 3.0
		draw_line(_rim(float(section.start), -notch), _rim(float(section.start), notch), Color(0.30, 0.24, 0.15, 0.16 + _emphasis * 0.26), 1.0, true)
	var progress := PackedVector2Array()
	var fraction: float = clampf(beat / JunkLoopTiming.BEATS, 0.0, 1.0)
	for index: int in range(int(fraction * SEGMENTS) + 1):
		progress.append(point_at(float(index) / SEGMENTS))
	progress.append(point_at(fraction))
	if fraction > 0.0001:
		draw_polyline(progress, Color(0.66, 0.45, 0.28, 0.30 + _emphasis * 0.18), width, true)
	_draw_stamp(width)
	_draw_lap(width)
	var handle: Vector2 = point_at(fraction)
	draw_circle(handle + Vector2(0, 1), 4.0 + _emphasis * 1.5, Color(0.30, 0.24, 0.15, 0.10), true, -1, true)
	draw_circle(handle, 3.0 + _emphasis * 1.5, Color("ba8057"), true, -1, true)
