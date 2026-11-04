extends SceneTree
## Render a material contact sheet with the actual Compatibility renderer.
## godot --path godot --script res://tests/cardboard_preview.gd


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	root.size = Vector2i(1440, 900)
	var backdrop := ColorRect.new()
	backdrop.color = Color("f1eadb")
	backdrop.size = Vector2(1440, 900)
	root.add_child(backdrop)
	var stage := JunkStage.new()
	var texture: Texture2D = stage.texture_for({"id": "preview", "tile": 0})
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--reference="):
			var reference := Image.load_from_file(arg.trim_prefix("--reference="))
			if reference != null: texture = ImageTexture.create_from_image(reference)
	var angles: Array[float] = [-0.18, -0.65, -1.2, -PI / 2, -2.3, -PI - 0.18]
	var labels: Array[String] = ["Rest", "Turn", "Cut edge", "Side", "Reverse turn", "Reverse"]
	for row: int in range(2):
		for i: int in range(angles.size()):
			var puppet := JunkPuppet.new()
			root.add_child(puppet)
			puppet.performer = {"id": "preview-%d" % i, "position": {"x": 130 + i * 235, "y": 360 + row * 420}}
			puppet.set_art(texture if row == 0 else stage.texture_for({"id": "other", "tile": 1}))
			puppet.pose(0, false, 0.016)
			puppet.scale = Vector2.ONE * 2.5
			puppet._face_material.set_shader_parameter("yaw", angles[i])
			puppet._edge_material.set_shader_parameter("yaw", angles[i])
			puppet._shadow_material.set_shader_parameter("yaw", angles[i])
			puppet._body.rotation = -0.10 if row == 1 else 0.0
			var label := Label.new()
			label.text = labels[i]
			label.position = Vector2(55 + i * 235, 405 + row * 420)
			label.add_theme_color_override("font_color", Color("473a2a"))
			label.add_theme_font_size_override("font_size", 20)
			root.add_child(label)
	stage.free()
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://../artifacts/cardboard-material.png")
	print("Cardboard material contact sheet saved")
	quit()
