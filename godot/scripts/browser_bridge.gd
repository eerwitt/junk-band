class_name JunkBrowserBridge
extends Node

signal packet_received(packet: Dictionary)

var _api: JavaScriptObject
var _callback: JavaScriptObject
var _subscription: int = -1
var _current_beat: float = 0.0
var _pulses: Dictionary = {}
var _hits: Dictionary = {}
var master_pulse: float = 0.0
var audio_playing: bool = false


func _ready() -> void:
	process_priority = -100


func _process(_delta: float) -> void:
	if _api != null:
		var frame: Dictionary = JSON.parse_string(str(_api.frame()))
		_current_beat = float(frame.beat)
		_pulses = frame.pulses
		_hits = frame.get("onsets", {})
		master_pulse = float(frame.masterPulse)
		audio_playing = bool(frame.playing)


func connect_browser() -> bool:
	if not OS.has_feature("web"):
		return false
	_api = JavaScriptBridge.get_interface("JUNK")
	if _api == null:
		push_error("JUNK browser bridge was not loaded before Godot.")
		return false
	_callback = JavaScriptBridge.create_callback(_receive)
	_subscription = int(_api.subscribe(_callback))
	return true


func command(kind: String, payload: Dictionary = {}) -> void:
	if _api != null:
		_api.command(JSON.stringify({"kind": kind, "payload": payload}))


func beat() -> float:
	return _current_beat


func pulse_for(id: String) -> float:
	return float(_pulses.get(id, 0.0))


## The newest hit this character has sounded: x is its age in seconds, y its velocity.
## x is negative when nothing has played for a while.
func onset_for(id: String) -> Vector2:
	var hit: Variant = _hits.get(id)
	if hit is Array and hit.size() >= 2: return Vector2(float(hit[0]), float(hit[1]))
	return Vector2(-1.0, 0.0)


func set_cursor(cursor: String) -> void:
	if _api != null:
		_api.setCursor(cursor)


func publish_layout(layout: Dictionary) -> void:
	if _api != null:
		_api.publishLayout(JSON.stringify(layout))


func _receive(arguments: Array) -> void:
	if arguments.is_empty():
		return
	var parsed: Variant = JSON.parse_string(str(arguments[0]))
	if parsed is Dictionary:
		packet_received.emit(parsed)


func _exit_tree() -> void:
	if _api != null and _subscription >= 0:
		_api.unsubscribe(_subscription)
	_callback = null
