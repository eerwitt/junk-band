extends SceneTree
## Deterministic contact sheet of floor position, lift height and shadow projection.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	root.size = Vector2i(1440, 1100)
	var paper := ColorRect.new()
	paper.color = Color("f7f5ec")
	paper.size = Vector2(1440, 1100)
	root.add_child(paper)
	var stage := JunkStage.new()
	var texture: Texture2D = stage.texture_for({"id": "preview", "tile": 0})
	var times: Array[float] = [-1.0, 0.06, 0.16, 0.25, 0.42]
	var names: Array[String] = ["Grounded", "Load · 60 ms", "Lift · 160 ms", "Separate · 250 ms", "Carry · 420 ms"]
	for cell: int in range(times.size() * 2):
		var index: int = cell % times.size()
		var reduced: bool = cell >= times.size()
		var row_y: float = 500.0 if reduced else 0.0
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		puppet.performer = {"id": "weight-preview", "position": {"x": 145 + index * 285, "y": 370 + row_y}}
		puppet.set_art(texture)
		puppet.pose(0, reduced, 0)
		puppet.scale = Vector2.ONE * 1.65
		if times[index] >= 0.0:
			puppet.begin_pickup(puppet.position + Vector2(15, -70))
			var elapsed: float = 0.0
			while elapsed < times[index] - 0.00001:
				var step: float = minf(1.0 / 120.0, times[index] - elapsed)
				puppet.pose(0, reduced, step)
				elapsed += step
		var label := Label.new()
		label.text = ("Reduced motion\n" if reduced else "Full motion\n") + names[index] + "\nHeight: %.1f" % maxf(puppet._lift_height, 0.0)
		label.position = Vector2(50 + index * 285, 450 + row_y)
		label.add_theme_font_size_override("font_size", 21)
		label.add_theme_color_override("font_color", Color("473a2a"))
		root.add_child(label)
		var floor_line := Line2D.new()
		floor_line.default_color = Color(0.35, 0.28, 0.18, 0.18)
		floor_line.width = 1.0
		var contact_y: float = puppet.position.y + puppet._ground_foot.y * puppet.scale.y
		floor_line.points = PackedVector2Array([Vector2(35 + index * 285, contact_y), Vector2(255 + index * 285, contact_y)])
		root.add_child(floor_line)
	stage.free()
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://../artifacts/pickup-depth.png")
	print("Weighted pickup contact sheet saved")
	quit()
