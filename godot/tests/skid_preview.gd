extends SceneTree
## Full release-to-rest skid and its matched reverse fade, using actual poses.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	root.size = Vector2i(1440, 560)
	var paper := ColorRect.new()
	paper.color = Color("f7f5ec")
	paper.size = Vector2(1440, 560)
	root.add_child(paper)
	var source := JunkStage.new()
	var texture: Texture2D = source.texture_for({"id": "preview", "tile": 0})
	var times: Array[float] = [0.12, 0.72, 2.0, 3.6]
	var titles: Array[String] = ["Drawing from release", "Full trail at rest", "Fade from start to stop", "Cleared"]
	for cell: int in range(4):
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		var home := Vector2(65 + cell * 355, 330)
		puppet.performer = {"id": "skid-preview", "position": {"x": home.x, "y": home.y}}
		puppet.set_art(texture)
		puppet.pose(0, false, 0)
		puppet.begin_pickup(home + Vector2(18, -65))
		for frame: int in range(80): puppet.pose(0, false, 1.0 / 120.0)
		var target: Vector2 = home + Vector2(180, 0)
		puppet.move_pickup(target)
		puppet.pose(0, false, 1.0 / 120.0)
		var effects: Array[JunkLandingEffect] = []
		puppet.landed.connect(func(point: Vector2, strength: float) -> void:
			var effect := JunkLandingEffect.new()
			effect.position = point
			effect.seed_value = 1
			effect.strength = strength
			effect.configure(puppet)
			effect.z_index = 3100
			root.add_child(effect)
			effect.set_process(false)
			effects.append(effect)
		)
		puppet.end_pickup(target, true)
		puppet.performer.position = {"x": target.x, "y": target.y}
		var elapsed: float = 0.0
		while elapsed < times[cell]:
			puppet.pose(0, false, 1.0 / 120.0)
			for effect: JunkLandingEffect in effects: effect._process(1.0 / 120.0)
			elapsed += 1.0 / 120.0
		var label := Label.new()
		label.text = titles[cell] + "\n%d ms" % int(times[cell] * 1000)
		label.position = Vector2(30 + cell * 355, 420)
		label.add_theme_font_size_override("font_size", 20)
		label.add_theme_color_override("font_color", Color("473a2a"))
		root.add_child(label)
	source.free()
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://../artifacts/skid-reverse.png")
	print("Reverse skid phase sheet saved")
	quit()
