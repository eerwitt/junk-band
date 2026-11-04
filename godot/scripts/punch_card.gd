class_name JunkPunchCard
extends Control

## One bar of rhythm as a strip of card: a punched hole is a hit. Tap a hole to change it.

signal toggled_step(step: int)

const STEPS: int = 16
const HOLE_RADIUS: float = 7.0
const INK := Color("29271f")
const ORANGE := Color("b86339")

var pattern: Dictionary = {}
var beat: float = 0.0
var playing: bool = false
var _hover: int = -1


func _init() -> void:
	custom_minimum_size = Vector2(332, 26)
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	tooltip_text = "Tap a hole to punch it or fill it back in."
	mouse_exited.connect(func() -> void: _hover = -1; queue_redraw())


func hole_center(step: int) -> Vector2:
	# A little gap between each group of four, so the beats can be read at a glance.
	var groups: float = float(step / 4)
	var slot: float = (size.x - 24.0) / STEPS
	return Vector2(slot * (step + 0.5) + groups * 8.0, size.y * 0.5)


func _step_at(point: Vector2) -> int:
	var nearest: int = -1
	var distance: float = 13.0
	for step: int in range(STEPS):
		var away: float = absf(hole_center(step).x - point.x)
		if away < distance:
			distance = away
			nearest = step
	return nearest


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		var over: int = _step_at(event.position)
		if over != _hover:
			_hover = over
			queue_redraw()
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		var step: int = _step_at(event.position)
		if step >= 0:
			toggled_step.emit(step)
			accept_event()


func _process(_delta: float) -> void:
	if is_visible_in_tree(): queue_redraw()


func _draw() -> void:
	var current: int = int(fposmod(beat * 4.0, STEPS)) if playing else -1
	for step: int in range(STEPS):
		var center: Vector2 = hole_center(step)
		var punched: bool = pattern.has(step)
		if step == current:
			draw_circle(center, HOLE_RADIUS + 3.0, Color(ORANGE, 0.35), true, -1, true)
		if punched:
			draw_circle(center, HOLE_RADIUS, ORANGE if step == current else INK, true, -1, true)
		else:
			draw_circle(center, HOLE_RADIUS, Color(INK, 0.38), false, 1.2, true)
		if step == _hover:
			draw_circle(center, HOLE_RADIUS + 1.5, Color(INK, 0.6), false, 1.2, true)
