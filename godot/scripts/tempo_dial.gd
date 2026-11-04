class_name JunkTempoDial
extends Control

## A little cardboard metronome. The arm really swings on the beat and its weight slides as the
## tempo changes. Drag sideways to change it, tap it in time, scroll, or use the arrow keys.

signal value_changed(value: int)

const MIN_BPM: int = 80
const MAX_BPM: int = 160
const PIXELS_PER_BPM: float = 2.5
const DRAG_THRESHOLD: float = 4.0
const TAP_WINDOW_MS: int = 1600
const TAPS_NEEDED: int = 3
const FONT := preload("res://assets/NotoSans-Regular.ttf")
const INK := Color("29271f")
const MUTED := Color("716b5d")
const KRAFT := Color(0.69, 0.51, 0.31)
const KRAFT_DARK := Color(0.50, 0.36, 0.21)
const ORANGE := Color("b86339")

var value: int = 112
var beat: float = 0.0
var playing: bool = false
var dragging: bool = false
var _hovered: bool = false
var _drag_origin: float = 0.0
var _drag_start_value: int = 112
var _moved: bool = false
var _taps: Array[int] = []
var _swing: float = 0.0
var _emphasis: float = 0.0
var _flick: float = 0.0
var _card := JunkCardboardStyle.new()
var _keyboard_focus: bool = false


func _init() -> void:
	custom_minimum_size = Vector2(150, 60)
	focus_mode = Control.FOCUS_ALL
	mouse_default_cursor_shape = Control.CURSOR_HSIZE
	tooltip_text = "Tempo. Drag sideways to change it, or tap it in time."
	mouse_entered.connect(func() -> void: _hovered = true)
	mouse_exited.connect(func() -> void: _hovered = false)


func set_value_quiet(next: float) -> void:
	if not dragging: value = clampi(roundi(next), MIN_BPM, MAX_BPM)


func _change_to(next: int) -> void:
	var clamped: int = clampi(next, MIN_BPM, MAX_BPM)
	if clamped == value: return
	value = clamped
	value_changed.emit(value)


func _tap() -> void:
	_flick = 1.0
	var now: int = Time.get_ticks_msec()
	if not _taps.is_empty() and now - _taps[-1] > TAP_WINDOW_MS: _taps.clear()
	_taps.append(now)
	if _taps.size() > 6: _taps.remove_at(0)
	if _taps.size() >= TAPS_NEEDED:
		var gap: float = float(_taps[-1] - _taps[0]) / float(_taps.size() - 1)
		if gap > 0.0: _change_to(roundi(60000.0 / gap))


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			if event.pressed: _change_to(value + (1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -1))
			accept_event()
		elif event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed:
				grab_focus()
				_keyboard_focus = false
				dragging = true
				_moved = false
				_drag_origin = event.position.x
				_drag_start_value = value
			else:
				if dragging and not _moved: _tap()
				dragging = false
			accept_event()
	elif event is InputEventMouseMotion and dragging:
		var distance: float = event.position.x - _drag_origin
		_moved = _moved or absf(distance) >= DRAG_THRESHOLD
		if _moved: _change_to(_drag_start_value + roundi(distance / PIXELS_PER_BPM))
		accept_event()
	elif event is InputEventKey and event.pressed:
		_keyboard_focus = true
		var step: int = 0
		if event.keycode in [KEY_UP, KEY_RIGHT]: step = 1
		elif event.keycode in [KEY_DOWN, KEY_LEFT]: step = -1
		if step != 0:
			_change_to(value + step)
			accept_event()


func _notification(what: int) -> void:
	# Arriving by Tab shows where the keyboard is. A click does not need a box drawn round it.
	if what == NOTIFICATION_FOCUS_ENTER and not Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		_keyboard_focus = true


func _process(delta: float) -> void:
	var target: float = sin(beat * PI) * 0.46 if playing else 0.0
	_swing = target if playing else lerpf(_swing, 0.0, 1.0 - exp(-6.0 * delta))
	_emphasis = lerpf(_emphasis, 1.0 if dragging or _hovered else 0.0, 1.0 - exp(-14.0 * delta))
	_flick = move_toward(_flick, 0.0, delta * 4.0)
	queue_redraw()


## Slower tempos carry the weight higher up the arm, as on a real metronome.
func _weight_share() -> float:
	return remap(float(value), MIN_BPM, MAX_BPM, 0.9, 0.34)


func _draw() -> void:
	_card.pressed = dragging
	draw_style_box(_card, Rect2(Vector2.ZERO, size))
	_draw_metronome(Vector2(8, 5), Vector2(36, size.y - 10))
	var left: float = 52.0
	var right: float = size.x - 10.0
	var number_size: int = 25 if dragging else 23
	var number: String = str(value)
	draw_string(FONT, Vector2(left, 31), number, HORIZONTAL_ALIGNMENT_LEFT, -1, number_size, ORANGE.darkened(0.15) if dragging else INK)
	var number_width: float = FONT.get_string_size(number, HORIZONTAL_ALIGNMENT_LEFT, -1, number_size).x
	draw_string(FONT, Vector2(left + number_width + 5, 31), "BPM", HORIZONTAL_ALIGNMENT_LEFT, -1, 10, MUTED)
	_draw_ruler(left, right, size.y - 16.0)
	if has_focus() and _keyboard_focus:
		draw_rect(Rect2(Vector2(2, 2), size - Vector2(4, 4)), ORANGE, false, 1.5)


func _draw_ruler(left: float, right: float, y: float) -> void:
	for bpm: int in range(MIN_BPM, MAX_BPM + 1, 10):
		var x: float = remap(float(bpm), MIN_BPM, MAX_BPM, left, right)
		var tall: bool = bpm % 40 == 0
		draw_line(Vector2(x, y), Vector2(x, y + (6.0 if tall else 3.5)), Color(INK, 0.28 + _emphasis * 0.22), 1.0, true)
	var marker: float = remap(float(value), MIN_BPM, MAX_BPM, left, right)
	var height: float = 5.0 + _emphasis * 2.0
	draw_colored_polygon(PackedVector2Array([Vector2(marker - height * 0.8, y - height + 1.0), Vector2(marker + height * 0.8, y - height + 1.0), Vector2(marker, y + 2.0)]), ORANGE)


func _draw_metronome(origin: Vector2, box: Vector2) -> void:
	var base_left := origin + Vector2(0, box.y)
	var base_right := origin + box
	var top_left := origin + Vector2(box.x * 0.3, 0)
	var top_right := origin + Vector2(box.x * 0.7, 0)
	var body := PackedVector2Array([top_left, top_right, base_right, base_left])
	draw_colored_polygon(body, KRAFT)
	var outline := body.duplicate()
	outline.append(body[0])
	draw_polyline(outline, Color(INK, 0.7), 1.2, true)
	var pivot := origin + Vector2(box.x * 0.5, box.y - 5.0)
	var length: float = box.y - 9.0
	var scale_top: float = origin.y + 5.0
	for index: int in range(4):
		var y: float = lerpf(scale_top, pivot.y - 8.0, float(index) / 3.0)
		draw_line(Vector2(pivot.x - 3.5, y), Vector2(pivot.x + 3.5, y), Color(KRAFT_DARK, 0.75), 1.0, true)
	var angle: float = _swing + sin(_flick * TAU) * _flick * 0.35
	var tip := pivot + Vector2(sin(angle), -cos(angle)) * length
	draw_line(pivot, tip, INK, 1.6, true)
	var weight: Vector2 = pivot.lerp(tip, _weight_share())
	var across := Vector2(cos(angle), sin(angle))
	var along := Vector2(sin(angle), -cos(angle))
	draw_colored_polygon(PackedVector2Array([weight - across * 4.0 - along * 2.5, weight + across * 4.0 - along * 2.5, weight + across * 3.0 + along * 2.5, weight - across * 3.0 + along * 2.5]), ORANGE)
	draw_circle(pivot, 2.2, INK, true, -1, true)
