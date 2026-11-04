extends SceneTree
## Deterministic phase sheet using shipped artwork and actual arrival physics/VFX.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	root.size = Vector2i(1440, 620)
	var paper := ColorRect.new()
	paper.color = Color("f7f5ec")
	paper.size = Vector2(1440, 620)
	root.add_child(paper)
	var stage := JunkStage.new()
	var texture: Texture2D = stage.texture_for({"id": "preview", "tile": 0})
	var times: Array[float] = [0.0, 0.12, 0.25, 0.48, 0.0]
	var names: Array[String] = ["Release · 0 ms", "Fall · 120 ms", "Contact · 250 ms", "Settle · 480 ms", "Reduced motion"]
	for index: int in range(times.size()):
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		puppet.performer = {"id": "arrival-preview", "position": {"x": 145 + index * 285, "y": 370}}
		puppet.set_art(texture)
		puppet.pose(0, false, 0)
		puppet.scale = Vector2.ONE * 1.65
		var reduced: bool = index == 4
		puppet.arrive(reduced)
		puppet.pose(0, reduced, 0)
		var elapsed: float = 0.0
		while elapsed < times[index] - 0.00001:
			var step: float = minf(1.0 / 120.0, times[index] - elapsed)
			puppet.pose(0, reduced, step)
			elapsed += step
		var contact: Vector2 = puppet.to_global(puppet._ground_foot)
		if puppet._landing_age < 0.72:
			var effect := JunkLandingEffect.new()
			effect.z_index = 3100
			effect.position = contact
			effect.scale = puppet.scale
			effect._age = puppet._landing_age
			effect.pixel_zoom = puppet.scale.x
			effect.strength = 0.38
			effect.seed_value = 1
			effect.reduced_motion = reduced
			root.add_child(effect)
			effect.set_process(false)
		var label := Label.new()
		label.text = names[index] + "\nHeight: %.1f" % puppet._lift_height
		label.position = Vector2(40 + index * 285, 450)
		label.add_theme_font_size_override("font_size", 21)
		label.add_theme_color_override("font_color", Color("473a2a"))
		root.add_child(label)
		var floor_line := Line2D.new()
		floor_line.default_color = Color(0.35, 0.28, 0.18, 0.18)
		floor_line.width = 1.0
		floor_line.points = PackedVector2Array([Vector2(35 + index * 285, contact.y), Vector2(255 + index * 285, contact.y)])
		root.add_child(floor_line)
	stage.free()
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://../artifacts/arrival-phases.png")
	print("Character arrival phase sheet saved")
	quit()
