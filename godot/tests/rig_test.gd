extends SceneTree
## Technical fixture: verifies layering, joints, shadows and frozen pickup grips.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var stage := JunkStage.new()
	root.add_child(stage)
	stage.set_process(false)
	var body := Image.create(200, 240, false, Image.FORMAT_RGBA8)
	body.fill_rect(Rect2i(60, 25, 80, 126), Color("cf6034"))
	var original: Image = body.duplicate()
	var boxes: Array[Rect2i] = [Rect2i(35, 65, 31, 36), Rect2i(135, 65, 31, 36), Rect2i(70, 145, 16, 74), Rect2i(115, 145, 16, 74)]
	var names: Array[String] = ["left_arm", "right_arm", "left_leg", "right_leg"]
	var rig: Dictionary = {"width": 200, "height": 240, "body": "blob:asset:rig-body", "parts": []}
	for index: int in range(4):
		var limb := Image.create(200, 240, false, Image.FORMAT_RGBA8)
		limb.fill_rect(boxes[index], Color("d6ae75"))
		original.blend_rect(limb, Rect2i(0, 0, 200, 240), Vector2i.ZERO)
		body.fill_rect(boxes[index], Color.TRANSPARENT)
		var ref: String = "blob:asset:rig-" + names[index]
		stage.set_texture(ref, Marshalls.raw_to_base64(limb.save_png_to_buffer()))
		var joint: Vector2 = Vector2(64 if index == 0 else 136, 80) if index < 2 else Vector2(78 if index == 2 else 123, 149)
		rig.parts.append({"name": names[index], "sprite": ref, "pivot": {"x": joint.x / 200.0, "y": joint.y / 240.0}, "maxAngle": 0.2})
	stage.set_texture(rig.body, Marshalls.raw_to_base64(body.save_png_to_buffer()))
	stage.set_texture("fixture", Marshalls.raw_to_base64(original.save_png_to_buffer()))
	var project: Dictionary = {"assets": [{"id": "fixture", "rig": rig}], "performers": [{"id": "rig-test", "assetId": "fixture", "position": {"x": 0, "y": 0}}]}
	var delayed_layer: Dictionary = stage._rig_layers["blob:asset:rig-right_leg"]
	stage._rig_layers.erase("blob:asset:rig-right_leg")
	stage.queue_arrival("rig-test")
	stage.apply_scene(project, "")
	assert(not stage._puppets["rig-test"].visible, "Arrival must wait for every rig layer")
	stage._rig_layers["blob:asset:rig-right_leg"] = delayed_layer
	stage.apply_scene(project, "")
	var puppet: JunkPuppet = stage._puppets["rig-test"]
	puppet.pose(0, false, 1.0 / 60.0)
	assert(puppet._rig.pieces.size() == 5, "All four limbs and the body must be installed atomically")
	assert(puppet._body.self_modulate.a == 0 and puppet._shadow.self_modulate.a == 0, "The original poster and silhouette must not double-draw the rig")
	for index: int in range(15): puppet.pose(1, false, 1.0 / 120.0, 1)
	var angles: Array[float] = []
	for piece: Dictionary in puppet._rig.pieces:
		angles.append(piece.angle)
		assert(absf(piece.angle) <= piece.limit)
		assert(piece.materials[0].get_shader_parameter("joint_angle") == piece.materials[2].get_shader_parameter("joint_angle"), "Face and silhouette must share the same joint rotation")
		assert(piece.materials[0].get_shader_parameter("joint_pivot") == piece.materials[1].get_shader_parameter("joint_pivot"), "Printed face and thick edge must rotate about the same attachment")
	assert(absf(angles[1]) > 0.01, "Actual note pulses must articulate the paper arms")
	puppet.begin_pickup(Vector2(0, -45))
	puppet.move_pickup(Vector2(100, 30))
	for index: int in range(60): puppet.pose(2 + index / 60.0, false, 1.0 / 120.0, 1)
	for index: int in range(angles.size()):
		assert(is_equal_approx(puppet._rig.pieces[index].angle, angles[index]), "Freeze joint angles during a pinch so the held material cannot swim under the grip")
	puppet.end_pickup()
	for index: int in range(60): puppet.pose(3, true, 1.0 / 120.0, 1)
	for piece: Dictionary in puppet._rig.pieces: assert(is_zero_approx(piece.angle), "Reduced motion must return all joints to rest")
	stage.apply_scene(project, "")
	assert(puppet._rig.pieces.size() == 5, "Repeated scene updates must reuse the installed rig")
	puppet._rig.configure(puppet, {}, {})
	assert(puppet._rig.pieces.is_empty() and puppet._body.self_modulate.a == 1 and puppet._edge.visible)
	stage.free()
	print("Rig regression passed: atomic layers, rigid joints, synchronized shadows, stable pickup grip and reduced motion")
	quit()
