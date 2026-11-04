class_name JunkPerformerMenu
extends Control

signal changed(id: String, patch: Dictionary)
signal delete_requested(id: String)
signal duplicate_requested(id: String)
signal dismissed
signal path_requested(id: String)
signal clear_path_requested(id: String)
## The character to hear clearly over a quiet band, or "" to give the song back.
signal spotlight_changed(id: String)
signal tapped(id: String)
## The cards have finished dealing out, so every control is where it will stay.
signal settled

const CARD_PANEL_WIDTH: float = 356.0
const TAP_RESTART_MS: int = 2000
const DEAL_STAGGER: float = 0.016
const DEAL_TIME: float = 0.2
const CARD_DROP_TIME: float = 0.22
const SETTLE_TIME: float = DEAL_STAGGER * 8.0 + DEAL_TIME
const RHYTHM_CARDS: Dictionary = {
	"Steady": [0, 4, 8, 12],
	"Offbeat": [2, 6, 10, 14],
	"Gallop": [0, 3, 4, 7, 8, 11, 12, 15],
	"Sparse": [0, 10],
	"Busy": [0, 2, 4, 6, 8, 10, 12, 14],
}

var performer_id: String = ""
var controls: Dictionary = {}
var _cards: Array[Control] = []
var _blur: ColorRect
var _back_buffer: BackBufferCopy
var _syncing: bool = false
var _gain: HSlider
var _rate: HSlider
var _pan: HSlider
var _mode: OptionButton
var _exit: OptionButton
var _skull: Button
var _pencil: Button
var _eraser: Button
var _duplicate: Button
var _punch: Button
var _tuned: CheckBox
var _card_panel: PanelContainer
var _holes: JunkPunchCard
var _last_tap_ms: int = -100000
## Seconds since the menu or the rhythm card opened, for the cards fanning out.
var _open_age: float = 10.0
var _card_age: float = 10.0
var reduced_motion: bool = false
## The song's position, for the moving mark on the card and for tapping in time.
var beat: float = 0.0:
	set(value):
		beat = value
		if _holes != null: _holes.beat = value
var playing: bool = false:
	set(value):
		playing = value
		if _holes != null: _holes.playing = value


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	z_index = 2500
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_back_buffer = BackBufferCopy.new()
	_back_buffer.copy_mode = BackBufferCopy.COPY_MODE_RECT
	add_child(_back_buffer)
	_blur = ColorRect.new()
	_blur.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var blur_material := ShaderMaterial.new()
	blur_material.shader = preload("res://shaders/focus_blur.gdshader")
	_blur.material = blur_material
	add_child(_blur)
	_gain = _slider_card("Volume", -36, 0, 1, "gainDb")
	_rate = _slider_card("Pitch / speed", 0.25, 3, 0.05, "rate")
	_pan = _slider_card("Pan", -1, 1, 0.05, "pan")
	controls["gain"] = _gain
	controls["rate"] = _rate
	controls["pan"] = _pan
	var rhythm: VBoxContainer = _card(166)
	_mode = _choice(rhythm, ["Pattern hits", "One shot", "Sample loop"])
	_mode.item_selected.connect(func(index: int) -> void: _change({"mode": ["repeat_hits", "one_shot", "continuous_loop"][index]}))
	_tuned = CheckBox.new()
	_tuned.text = "Height sets its note"
	_tuned.add_theme_font_size_override("font_size", 11)
	_tuned.tooltip_text = "Move it up the stage to play higher, down to play lower. Every note fits."
	_tuned.toggled.connect(func(on: bool) -> void: _change({"tuned": on}))
	rhythm.add_child(_tuned)
	controls["tuned"] = _tuned
	_exit = _choice(rhythm, ["Offstage: play", "Offstage: fade", "Offstage: quiet"])
	_exit.item_selected.connect(func(index: int) -> void: _change({"exit": ["continue", "fade", "mute"][index]}))
	_skull = Button.new()
	_skull.icon = preload("res://assets/skull.svg")
	_skull.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_skull.tooltip_text = "Remove performer"
	_skull.custom_minimum_size = Vector2(48, 48)
	_skull.z_index = 900
	_skull.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	for state: String in ["normal", "hover", "pressed", "focus"]:
		var paper := JunkCardboardStyle.new()
		paper.paper = Color("e9cead") if state == "hover" else Color("eee4cf")
		paper.pressed = state == "pressed"
		_skull.add_theme_stylebox_override(state, paper)
	_skull.pressed.connect(func() -> void: delete_requested.emit(performer_id); close())
	add_child(_skull)
	controls["delete_performer"] = _skull
	_pencil = _icon_button(preload("res://assets/pencil.svg"), "Draw motion path")
	_pencil.pressed.connect(func() -> void: path_requested.emit(performer_id); close())
	controls["draw_path"] = _pencil
	_eraser = _icon_button(preload("res://assets/eraser.svg"), "Clear motion path")
	_eraser.pressed.connect(func() -> void: clear_path_requested.emit(performer_id); close())
	controls["clear_path"] = _eraser
	_duplicate = _icon_button(preload("res://assets/duplicate.svg"), "Duplicate")
	_duplicate.pressed.connect(func() -> void: duplicate_requested.emit(performer_id); close())
	controls["duplicate"] = _duplicate
	_punch = _icon_button(preload("res://assets/punch.svg"), "Rhythm card")
	_punch.pressed.connect(func() -> void: _set_card_open(not _card_panel.visible))
	controls["punch"] = _punch
	_build_card_panel()
	hide()


func _build_card_panel() -> void:
	_card_panel = PanelContainer.new()
	_card_panel.z_index = 900
	_card_panel.custom_minimum_size.x = CARD_PANEL_WIDTH
	_card_panel.add_theme_stylebox_override("panel", JunkCardboardStyle.new())
	add_child(_card_panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	_card_panel.add_child(box)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 3)
	box.add_child(row)
	for label: String in RHYTHM_CARDS:
		_add_card_button(row, label, "card_" + label.to_lower(), func() -> void: _set_pattern(RHYTHM_CARDS[label]))
	_add_card_button(row, "Surprise", "card_surprise", _surprise)
	_holes = JunkPunchCard.new()
	_holes.toggled_step.connect(_toggle_step)
	box.add_child(_holes)
	controls["holes"] = _holes
	var tap := Button.new()
	tap.text = "Tap in time to teach it"
	tap.add_theme_font_size_override("font_size", 11)
	tap.custom_minimum_size.y = 28
	tap.tooltip_text = "The band drops back while this card is open. Tap along, and it learns what you tapped."
	# On the press, not the release, or every tap lands late.
	tap.action_mode = BaseButton.ACTION_MODE_BUTTON_PRESS
	tap.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	tap.pressed.connect(_tap)
	box.add_child(tap)
	controls["tap"] = tap
	_card_panel.hide()


func _set_card_open(open: bool) -> void:
	if _card_panel.visible == open: return
	_card_panel.visible = open
	if open: _card_age = 10.0 if reduced_motion else 0.0
	spotlight_changed.emit(performer_id if open else "")


func _add_card_button(row: HBoxContainer, label: String, key: String, action: Callable) -> void:
	var button := Button.new()
	button.text = label
	button.add_theme_font_size_override("font_size", 10)
	button.add_theme_constant_override("h_separation", 0)
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.custom_minimum_size.y = 26
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.pressed.connect(action)
	row.add_child(button)
	controls[key] = button


## One bar, repeated across the whole song.
func _set_pattern(pattern: Array) -> void:
	var steps: Array = []
	for bar: int in range(JunkLoopTiming.BARS):
		for step: int in pattern:
			steps.append(bar * 16 + step)
	steps.sort()
	_show_pattern(pattern, true)
	_change({"steps": steps})


func _show_pattern(pattern: Array, animate: bool = false) -> void:
	var holes: Dictionary = {}
	for step: int in pattern: holes[step] = true
	if animate: _holes.animate_change(holes)
	_holes.pattern = holes
	_holes.queue_redraw()


func _toggle_step(step: int) -> void:
	var pattern: Array = _holes.pattern.keys()
	if pattern.has(step): pattern.erase(step)
	else: pattern.append(step)
	# An empty card would leave someone on stage with nothing to play.
	if pattern.is_empty(): return
	_set_pattern(pattern)


func _surprise() -> void:
	var pattern: Array = [0]
	for step: int in range(1, 16):
		if randf() < (0.45 if step % 2 == 0 else 0.18): pattern.append(step)
	_set_pattern(pattern)


## The first tap after a pause starts a new pattern, and every tap adds the nearest step.
func _tap() -> void:
	tapped.emit(performer_id)
	var now: int = Time.get_ticks_msec()
	var pattern: Array = [] if now - _last_tap_ms > TAP_RESTART_MS else _holes.pattern.keys()
	_last_tap_ms = now
	var step: int = posmod(roundi(beat * 4.0), 16)
	_holes.flash(step)
	if not pattern.has(step): pattern.append(step)
	_set_pattern(pattern)


func _icon_button(icon: Texture2D, hint: String) -> Button:
	var button := Button.new()
	button.icon = icon
	button.tooltip_text = hint
	button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	button.z_index = 900
	button.custom_minimum_size = Vector2(42, 44)
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_stylebox_override("normal", JunkCardboardStyle.new())
	add_child(button)
	return button


func _card(width: float) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.z_index = 900
	panel.custom_minimum_size.x = width
	panel.add_theme_stylebox_override("panel", JunkCardboardStyle.new())
	add_child(panel)
	_cards.append(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	panel.add_child(box)
	return box


func _slider_card(label_text: String, minimum: float, maximum: float, step: float, key: String) -> HSlider:
	var box: VBoxContainer = _card(124)
	var label := Label.new()
	label.text = label_text
	label.add_theme_font_size_override("font_size", 11)
	box.add_child(label)
	var slider := HSlider.new()
	slider.min_value = minimum
	slider.max_value = maximum
	slider.step = step
	slider.custom_minimum_size = Vector2(98, 26)
	slider.value_changed.connect(func(value: float) -> void: _change({key: value}))
	box.add_child(slider)
	return slider


func _choice(parent: Node, labels: Array[String]) -> OptionButton:
	var option := OptionButton.new()
	option.add_theme_font_size_override("font_size", 11)
	option.custom_minimum_size.y = 28
	for label: String in labels: option.add_item(label)
	parent.add_child(option)
	return option


func _change(patch: Dictionary) -> void:
	if not _syncing: changed.emit(performer_id, patch)


func sync(performer: Dictionary) -> void:
	if performer.is_empty():
		close()
		return
	_syncing = true
	_gain.set_value_no_signal(float(performer.gainDb))
	_rate.set_value_no_signal(float(performer.rate))
	_pan.set_value_no_signal(float(performer.pan))
	_mode.select(["repeat_hits", "one_shot", "continuous_loop"].find(performer.mode))
	_exit.select(["continue", "fade", "mute"].find(performer.exit))
	_eraser.visible = not performer.path.is_empty()
	_tuned.set_pressed_no_signal(bool(performer.get("tuned", false)))
	var first_bar: Array = []
	for step: Variant in performer.steps:
		if int(step) < 16: first_bar.append(int(step))
	_show_pattern(first_bar)
	_syncing = false


func open_for(performer: Dictionary, anchor: Vector2) -> void:
	_set_card_open(false)
	var reopened: bool = visible and performer_id == str(performer.id)
	performer_id = str(performer.id)
	sync(performer)
	if not reopened: _open_age = 10.0 if reduced_motion else 0.0
	show()
	arrange(anchor)


func _process(delta: float) -> void:
	if not visible: return
	var was_settled: bool = is_settled()
	_open_age += delta
	_card_age += delta
	if is_settled() and not was_settled: settled.emit()


## Open, and nothing is still flying into place.
func is_settled() -> bool:
	return visible and _open_age >= SETTLE_TIME and (not _card_panel.visible or _card_age >= CARD_DROP_TIME)


## Back-out ease: overshoots a touch past 1 and settles, like card snapping into place.
static func _snap(t: float) -> float:
	var x: float = clampf(t, 0.0, 1.0) - 1.0
	return 1.0 + x * x * (2.7 * x + 1.7)


## Each piece flies out from the character in turn, turning flat as it lands.
func _deal(control: Control, center: Vector2, target: Vector2, order: int) -> void:
	var t: float = clampf((_open_age - order * DEAL_STAGGER) / DEAL_TIME, 0.0, 1.0)
	if t >= 1.0:
		control.position = target
		control.scale = Vector2.ONE
		control.rotation = 0.0
		control.modulate.a = 1.0 if control != _duplicate or not _duplicate.disabled else 0.45
		return
	var eased: float = _snap(t)
	control.pivot_offset = control.size * 0.5
	var home: Vector2 = center - control.size * 0.5
	control.position = home.lerp(target, eased)
	control.scale = Vector2.ONE * lerpf(0.35, 1.0, minf(eased, 1.08))
	control.rotation = (1.0 - eased) * (0.35 if order % 2 == 0 else -0.35)
	control.modulate.a = smoothstep(0.0, 0.35, t) * (1.0 if control != _duplicate or not _duplicate.disabled else 0.45)


func arrange(anchor: Vector2) -> void:
	var bottom_room: float = 340.0 if _card_panel.visible else 240.0
	var center := Vector2(clampf(anchor.x, 183, maxf(183, size.x - 183)), clampf(anchor.y, 170, maxf(170, size.y - bottom_room)))
	var radius: float = minf(225, (size.x - 12) / 2.0)
	_blur.position = center - Vector2.ONE * radius
	_blur.size = Vector2.ONE * radius * 2.0
	_back_buffer.rect = Rect2(_blur.position - Vector2.ONE * 6.0, _blur.size + Vector2.ONE * 12.0)
	var offsets: Array[Vector2] = [Vector2(-62, -155), Vector2(-180, -30), Vector2(56, -30), Vector2(-83, 82)]
	_blur.modulate.a = smoothstep(0.0, 0.16, _open_age)
	# Dealt clockwise from the top, so the circle visibly opens out around the character.
	_deal(_cards[0], center, center + offsets[0], 0)
	_deal(_duplicate, center, center + Vector2(70, -150), 1)
	_deal(_cards[2], center, center + offsets[2], 2)
	_deal(_skull, center, center + Vector2(104, 92), 3)
	_deal(_cards[3], center, center + offsets[3], 4)
	_deal(_eraser, center, center + Vector2(-128, 92), 5)
	_deal(_pencil, center, center + Vector2(-180, 92), 6)
	_deal(_cards[1], center, center + offsets[1], 7)
	_deal(_punch, center, center + Vector2(-118, -150), 8)
	# Up beside Volume, well away from the skull.
	var card_target: Vector2 = center + Vector2(-CARD_PANEL_WIDTH * 0.5, 232)
	var drop: float = 1.0 if reduced_motion or _card_age >= CARD_DROP_TIME else _snap(_card_age / CARD_DROP_TIME)
	_card_panel.position = card_target + Vector2(0, (1.0 - drop) * -40.0)
	_card_panel.pivot_offset = Vector2(CARD_PANEL_WIDTH * 0.5, 0)
	_card_panel.scale = Vector2(1.0, lerpf(0.6, 1.0, minf(drop, 1.04)))
	_card_panel.modulate.a = clampf(drop * 1.6, 0.0, 1.0)


func set_stage_full(full: bool) -> void:
	if _duplicate == null: return
	_duplicate.disabled = full
	_duplicate.tooltip_text = "The stage is full. Remove someone to make room." if full else "Duplicate"
	if _open_age > 1.0: _duplicate.modulate.a = 0.45 if full else 1.0


func close() -> void:
	_set_card_open(false)
	hide()
	performer_id = ""
	dismissed.emit()
