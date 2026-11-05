class_name JunkPunchCard
extends Control

## Rhythm as a strip of card, one row of sixteen holes for each bar it holds: a punched hole is a
## hit. Tap a hole to change it. A card longer than four bars shows four rows at a time, with
## tabs along the top to turn to the others; while the song plays they turn with it.

signal toggled_step(step: int)

const STEPS: int = 16
const HOLE_RADIUS: float = 7.0
const ROW_HEIGHT: float = 25.0
const ROWS_SHOWN: int = 4
const TAB_HEIGHT: float = 20.0
## Room at the left of each row for its bar number.
const LEFT: float = 18.0
## How long a tab you turned to stays put before the card follows the song again.
const TURN_HOLD_S: float = 4.0
const INK := Color("29271f")
const ORANGE := Color("b86339")
const FONT_SIZE: int = 10

## Card steps (0 up to bars × 16) that are punched.
var pattern: Dictionary = {}
var bars: int = 1:
	set(value):
		bars = maxi(1, value)
		page = clampi(page, 0, pages() - 1)
		_resize()
var page: int = 0
var beat: float = 0.0
var playing: bool = false
## In a phrase, the whole sound plays from the first hole to the end of the card: shown as a
## strip of colour under the holes, so you can see where it will be heard.
var phrase: bool = false
var _hover: int = -1
var _hover_tab: int = -1
var reduced_motion: bool = false
## Punched-out chads falling from the card, and holes popping as they change.
var _chads: Array[Dictionary] = []
var _pops: Dictionary = {}
var _clock: float = 0.0
var _shake: float = 10.0
var _turned_at: float = -100.0


func _init() -> void:
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	tooltip_text = "Tap a hole to punch it or fill it back in."
	mouse_exited.connect(func() -> void: _hover = -1; _hover_tab = -1; queue_redraw())
	_resize()


func pages() -> int:
	return ceili(float(bars) / ROWS_SHOWN)


func rows() -> int:
	return mini(bars, ROWS_SHOWN)


func _top() -> float:
	return TAB_HEIGHT if pages() > 1 else 0.0


func _resize() -> void:
	custom_minimum_size = Vector2(332, _top() + rows() * ROW_HEIGHT + 2.0)
	update_minimum_size()
	queue_redraw()


## Where a hole is drawn, for a step on the page showing; off the page it is far away.
func hole_center(step: int) -> Vector2:
	var row: int = step / STEPS - page * ROWS_SHOWN
	var column: int = step % STEPS
	# A little gap between each group of four, so the beats can be read at a glance.
	var groups: float = float(column / 4)
	var slot: float = (size.x - LEFT - 24.0) / STEPS
	return Vector2(LEFT + slot * (column + 0.5) + groups * 8.0, _top() + ROW_HEIGHT * (row + 0.5))


func _on_page(step: int) -> bool:
	return step / STEPS / ROWS_SHOWN == page


func _step_at(point: Vector2) -> int:
	var row: int = floori((point.y - _top()) / ROW_HEIGHT)
	if point.y < _top() or row < 0 or row >= rows(): return -1
	var bar: int = page * ROWS_SHOWN + row
	if bar >= bars: return -1
	var nearest: int = -1
	var distance: float = 13.0
	for column: int in range(STEPS):
		var away: float = absf(hole_center(bar * STEPS + column).x - point.x)
		if away < distance:
			distance = away
			nearest = bar * STEPS + column
	return nearest


func _tab_rect(index: int) -> Rect2:
	var width: float = minf(44.0, (size.x - LEFT) / pages())
	return Rect2(LEFT + index * width, 1.0, width - 3.0, TAB_HEIGHT - 4.0)


func _tab_at(point: Vector2) -> int:
	if pages() < 2 or point.y >= _top(): return -1
	for index: int in range(pages()):
		if _tab_rect(index).grow(1.5).has_point(point): return index
	return -1


func turn_to(index: int) -> void:
	page = clampi(index, 0, pages() - 1)
	_turned_at = _clock
	queue_redraw()


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		var over: int = _step_at(event.position)
		var tab: int = _tab_at(event.position)
		if over != _hover or tab != _hover_tab:
			_hover = over
			_hover_tab = tab
			queue_redraw()
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		var tab: int = _tab_at(event.position)
		if tab >= 0:
			turn_to(tab)
			accept_event()
			return
		var step: int = _step_at(event.position)
		if step >= 0:
			toggled_step.emit(step)
			accept_event()


## Called before the pattern changes, so it can tell punched holes from filled ones.
func animate_change(next: Dictionary) -> void:
	if reduced_motion: return
	var order: int = 0
	for step: int in range(bars * STEPS):
		var was: bool = pattern.has(step)
		var now: bool = next.has(step)
		if was == now or not _on_page(step): continue
		# A whole new card ripples along; a single hole is immediate.
		_pops[step] = _clock + order * 0.012
		order += 1
		if now: _chads.append({"at": hole_center(step), "birth": _clock + (order - 1) * 0.012, "spin": randf_range(-14.0, 14.0), "drift": randf_range(-30.0, 30.0)})
	if _chads.size() > 24: _chads = _chads.slice(_chads.size() - 24)
	if order > 0: _shake = 0.0


## A tap in time: the hole it landed on flashes, and the card turns to show it.
func flash(step: int) -> void:
	if not _on_page(step): page = step / STEPS / ROWS_SHOWN
	_turned_at = _clock
	if reduced_motion: return
	_pops[step] = _clock


func current_step() -> int:
	return posmod(int(beat * 4.0), bars * STEPS) if playing else -1


func _process(delta: float) -> void:
	_clock += delta
	_shake += delta
	# While the song plays the card turns to the bars being heard, unless you just turned it.
	var current: int = current_step()
	if current >= 0 and pages() > 1 and _clock - _turned_at > TURN_HOLD_S:
		page = current / STEPS / ROWS_SHOWN
	if is_visible_in_tree(): queue_redraw()


func _draw() -> void:
	var current: int = current_step()
	var font: Font = get_theme_default_font()
	# The punch knocks the card down a touch.
	var knock: Vector2 = Vector2(0, exp(-_shake * 20.0) * sin(_shake * 50.0) * 2.0) if _shake < 0.4 else Vector2.ZERO
	if pages() > 1:
		for index: int in range(pages()):
			var tab: Rect2 = _tab_rect(index)
			var open: bool = index == page
			var heard: bool = current >= 0 and current / STEPS / ROWS_SHOWN == index
			draw_rect(tab, Color(ORANGE, 0.22) if open else Color(INK, 0.06), true)
			draw_rect(tab, Color(INK, 0.55 if open or index == _hover_tab else 0.22), false, 1.0)
			if heard: draw_rect(Rect2(tab.position + Vector2(0, tab.size.y - 2.5), Vector2(tab.size.x, 2.5)), ORANGE, true)
			var first: int = index * ROWS_SHOWN + 1
			var label: String = "%d–%d" % [first, mini(bars, first + ROWS_SHOWN - 1)]
			draw_string(font, Vector2(tab.position.x, tab.position.y + 12.0), label, HORIZONTAL_ALIGNMENT_CENTER, tab.size.x, FONT_SIZE, Color(INK, 0.85 if open else 0.55))
	draw_set_transform(knock)
	if phrase and not pattern.is_empty():
		var first: int = pattern.keys().min()
		for row: int in range(rows()):
			var bar: int = page * ROWS_SHOWN + row
			if bar >= bars or (bar + 1) * STEPS <= first: continue
			var from: Vector2 = hole_center(maxi(first, bar * STEPS))
			var to: Vector2 = hole_center(bar * STEPS + STEPS - 1)
			var band := Rect2(from.x - HOLE_RADIUS - 2.0, from.y - HOLE_RADIUS - 2.0, to.x - from.x + HOLE_RADIUS * 2.0 + 4.0, HOLE_RADIUS * 2.0 + 4.0)
			draw_rect(band, Color(ORANGE, 0.16), true)
			if bar * STEPS <= first: draw_rect(Rect2(band.position, Vector2(3.0, band.size.y)), Color(ORANGE, 0.7), true)
	for row: int in range(rows()):
		var bar: int = page * ROWS_SHOWN + row
		if bar >= bars: break
		var y: float = _top() + ROW_HEIGHT * (row + 0.5)
		if bars > 1:
			var playing_bar: bool = current >= 0 and current / STEPS == bar
			draw_string(font, Vector2(0, y + 4.0), str(bar + 1), HORIZONTAL_ALIGNMENT_RIGHT, LEFT - 5.0, FONT_SIZE, ORANGE if playing_bar else Color(INK, 0.5))
		for column: int in range(STEPS):
			var step: int = bar * STEPS + column
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
