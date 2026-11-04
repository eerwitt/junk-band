class_name JunkCardboardRig
extends RefCounted
## Rigid layered paper. No image reads, mesh rebuilds or texture uploads in pose().

var pieces: Array[Dictionary] = []
var _key: String = ""
var _last_floor := Vector2.ZERO
var _speed: float = 0.0


func clear(host: JunkPuppet) -> void:
	for piece: Dictionary in pieces:
		piece.face.free()
		piece.shadow.free()
	pieces.clear()
	_key = ""
	_speed = 0.0
	host._body.self_modulate.a = 1.0
	host._shadow.self_modulate.a = 1.0
	host._edge.visible = true


func configure(host: JunkPuppet, rig: Dictionary, layers: Dictionary) -> void:
	if rig.is_empty():
		if not pieces.is_empty(): clear(host)
		return
	var signature: String = JSON.stringify(rig)
	if signature == _key: return
	if host._art_size != Vector2(rig.width, rig.height): return
	var required: Array = [{"name": "body", "sprite": rig.body, "pivot": {"x": 0.5, "y": 0.5}, "maxAngle": 0.0}]
	required.append_array(rig.parts)
	# Keep the complete poster visible until every layer is ready.
	for part: Dictionary in required:
		if not layers.has(str(part.sprite)): return
		if layers[str(part.sprite)].canvas != Vector2(rig.width, rig.height): return
	clear(host)
	_key = signature
	_last_floor = host.position
	var rim: int = maxi(2, roundi(maxf(host._art_size.x, host._art_size.y) * 0.019))
	for part: Dictionary in required:
		var layer: Dictionary = layers[str(part.sprite)]
		var prepared: Dictionary = JunkCardboardCutout.prepare(layer.texture, rim)
		var face := Sprite2D.new()
		face.texture = prepared.texture
		face.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
		face.z_index = 1 if part.name == "body" else 0
		var front := ShaderMaterial.new()
		front.shader = preload("res://shaders/cardboard_face.gdshader")
		face.material = front
		host._body.add_child(face)
		var edge := MeshInstance2D.new()
		edge.mesh = prepared.mesh
		edge.show_behind_parent = true
		var stock := ShaderMaterial.new()
		stock.shader = preload("res://shaders/cardboard_edge.gdshader")
		edge.material = stock
		face.add_child(edge)
		var shadow := Sprite2D.new()
		shadow.texture = prepared.texture
		var shade := ShaderMaterial.new()
		shade.shader = preload("res://shaders/cardboard_shadow.gdshader")
		shadow.material = shade
		host._shadow.add_child(shadow)
		pieces.append({"name": str(part.name), "face": face, "shadow": shadow, "materials": [front, stock, shade], "center": layer.center, "pivot": Vector2(part.pivot.x, part.pivot.y) * host._art_size - host._art_size * 0.5, "limit": float(part.maxAngle), "angle": 0.0, "velocity": 0.0, "uploaded": {}})
	host._body.self_modulate.a = 0.0
	host._shadow.self_modulate.a = 0.0
	host._edge.visible = false
	pose(host, 0, true, 0, 0)


func pose(host: JunkPuppet, beat: float, reduced: bool, delta: float, pulse: float) -> void:
	if pieces.is_empty(): return
	var speed: float = host.position.distance_to(_last_floor) / maxf(delta, 0.001) if delta > 0.0 else 0.0
	_last_floor = host.position
	_speed = lerpf(_speed, minf(speed, 160.0), 1.0 - exp(-12.0 * delta))
	var walking: float = clampf(_speed / 65.0, 0.0, 1.0) if not host._held else 0.0
	var phase: float = beat * PI
	var impact: float = sin(clampf(host._landing_age / 0.18, 0, 1) * PI) * 0.10
	var seed: float = float(str(host.performer.get("id", "")).hash() % 65521) / 65521.0 * 100.0
	for piece: Dictionary in pieces:
		var side: float = -1.0 if str(piece.name).begins_with("left") else 1.0
		var leg: bool = str(piece.name).ends_with("leg")
		var target: float = sin(phase) * side * walking * (0.14 if leg else -0.22)
		target += side * (pulse * (0.035 if leg else 0.13) + impact * (0.25 if leg else 1.0))
		if reduced or piece.name == "body":
			piece.angle = 0.0
			piece.velocity = 0.0
		elif not host._held:
			var state: Array[Vector2] = JunkMotionMath.spring(Vector2(piece.angle, 0), Vector2(piece.velocity, 0), Vector2(clampf(target, -piece.limit, piece.limit), 0), delta)
			piece.angle = clampf(state[0].x, -piece.limit, piece.limit)
			piece.velocity = state[1].x
		var offset: Vector2 = host._body.offset + piece.center
		piece.face.offset = offset
		piece.shadow.offset = offset
		var pivot: Vector2 = host._body.offset + piece.pivot
		_sync(piece, "yaw", host._cardboard_yaw)
		_sync(piece, "thickness", host._thickness)
		_sync(piece, "joint_angle", piece.angle)
		_sync(piece, "joint_pivot", pivot)
		if piece.uploaded.get("seed") != seed:
			piece.materials[0].set_shader_parameter("character_seed", seed)
			piece.materials[1].set_shader_parameter("character_seed", seed)
			piece.uploaded.seed = seed
		if piece.uploaded.get("offset") != offset:
			piece.materials[1].set_shader_parameter("pivot_offset", offset)
			piece.uploaded.offset = offset
		var texture_size: Vector2 = piece.face.texture.get_size()
		var root_blur_x: Vector2 = host._uploaded_blur_x if host._uploaded_blur_x.is_finite() else Vector2.ZERO
		var root_blur_y: Vector2 = host._uploaded_blur_y if host._uploaded_blur_y.is_finite() else Vector2.ZERO
		var blur_x: Vector2 = (root_blur_x * host._body.texture.get_size()).rotated(-piece.angle) / texture_size
		var blur_y: Vector2 = (root_blur_y * host._body.texture.get_size()).rotated(-piece.angle) / texture_size
		if piece.uploaded.get("blur_x") != blur_x or piece.uploaded.get("blur_y") != blur_y:
			piece.materials[2].set_shader_parameter("blur_x", blur_x)
			piece.materials[2].set_shader_parameter("blur_y", blur_y)
			piece.uploaded.blur_x = blur_x
			piece.uploaded.blur_y = blur_y


func _sync(piece: Dictionary, parameter: String, value: Variant) -> void:
	if piece.uploaded.get(parameter) == value: return
	for material: ShaderMaterial in piece.materials:
		material.set_shader_parameter(parameter, value)
	piece.uploaded[parameter] = value
