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
var reduced_motion: bool = false
## Punched-out chads falling from the card, and holes popping as they change.
var _chads: Array[Dictionary] = []
var _pops: Dictionary = {}
var _clock: float = 0.0
var _shake: float = 10.0


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


## Called before the pattern changes, so it can tell punched holes from filled ones.
func animate_change(next: Dictionary) -> void:
	if reduced_motion: return
	var order: int = 0
	for step: int in range(STEPS):
		var was: bool = pattern.has(step)
		var now: bool = next.has(step)
		if was == now: continue
		# A whole new card ripples along; a single hole is immediate.
		_pops[step] = _clock + order * 0.018
		order += 1
		if now: _chads.append({"at": hole_center(step), "birth": _clock + (order - 1) * 0.018, "spin": randf_range(-14.0, 14.0), "drift": randf_range(-30.0, 30.0)})
	if _chads.size() > 24: _chads = _chads.slice(_chads.size() - 24)
	if order > 0: _shake = 0.0


## A tap in time: the hole it landed on flashes.
func flash(step: int) -> void:
	if reduced_motion: return
	_pops[step] = _clock


func _process(delta: float) -> void:
	_clock += delta
	_shake += delta
	if is_visible_in_tree(): queue_redraw()


func _draw() -> void:
	var current: int = int(fposmod(beat * 4.0, STEPS)) if playing else -1
	# The punch knocks the card down a touch.
	var knock: Vector2 = Vector2(0, exp(-_shake * 20.0) * sin(_shake * 50.0) * 2.0) if _shake < 0.4 else Vector2.ZERO
	draw_set_transform(knock)
	for step: int in range(STEPS):
		var center: Vector2 = hole_center(step)
		var punched: bool = pattern.has(step)
		var pop_age: float = _clock - float(_pops.get(step, -10.0))
		if pop_age >= 0.0 and pop_age < 0.4:
			var ring: float = pop_age / 0.4
			draw_circle(center, HOLE_RADIUS + 2.0 + ring * 9.0, Color(ORANGE, 0.5 * (1.0 - ring)), false, 1.6, true)
		if step == current:
			draw_circle(center, HOLE_RADIUS + 3.0, Color(ORANGE, 0.35), true, -1, true)
		if punched:
			draw_circle(center, HOLE_RADIUS, ORANGE if step == current else INK, true, -1, true)
		else:
			draw_circle(center, HOLE_RADIUS, Color(INK, 0.38), false, 1.2, true)
		if step == _hover:
			draw_circle(center, HOLE_RADIUS + 1.5, Color(INK, 0.6), false, 1.2, true)
	draw_set_transform(Vector2.ZERO)
	for chad: Dictionary in _chads:
		var age: float = _clock - float(chad.birth)
		if age < 0.0 or age > 0.7: continue
		# A paper disc drops out of the back of the card, spinning edge-on as it falls.
		var at: Vector2 = chad.at + Vector2(float(chad.drift) * age, 30.0 * age + 420.0 * age * age)
		var turn: float = absf(cos(age * float(chad.spin)))
		var fade: float = 1.0 - smoothstep(0.4, 0.7, age)
		draw_set_transform(at, age * float(chad.spin) * 0.3, Vector2(maxf(turn, 0.15), 1.0))
		draw_circle(Vector2.ZERO, HOLE_RADIUS - 0.5, Color(0.93, 0.89, 0.81, fade), true, -1, true)
		draw_circle(Vector2.ZERO, HOLE_RADIUS - 0.5, Color(INK, 0.45 * fade), false, 1.0, true)
	draw_set_transform(Vector2.ZERO)
