extends SceneTree
## Real pickup/release poses and VFX, sampled at deterministic frame times. The top row
## is a stationary drop, the bottom row a fast slide released during an actual drag.

const DROP_TIMES: Array[float] = [0.016, 0.05, 0.11, 0.2, 0.36, 0.62]
const SLIDE_TIMES: Array[float] = [0.04, 0.1, 0.18, 0.3, 0.46, 0.8]
const COLUMN: float = 345.0
const STEP: float = 1.0 / 120.0

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	root.size = Vector2i(2070, 1040)
	var paper := ColorRect.new()
	paper.color = Color("f7f5ec")
	paper.size = Vector2(2070, 1040)
	root.add_child(paper)
	var source := JunkStage.new()
	var texture: Texture2D = source.texture_for({"id": "preview", "tile": 0})
	for cell: int in range(12):
		var sliding: bool = cell >= 6
		var column: int = cell % 6
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		var home := Vector2((70.0 if sliding else 172.0) + column * COLUMN, 880.0 if sliding else 370.0)
		puppet.performer = {"id": "drop-preview", "position": {"x": home.x, "y": home.y}}
		puppet.set_art(texture)
		puppet.pose(0, false, 0)
		puppet.begin_pickup(home + Vector2(18, -65))
		for frame: int in range(80): puppet.pose(0, false, STEP)
		var target: Vector2 = home
		if sliding:
			# A brisk real drag, about 800 world units per second, released while moving.
			for frame: int in range(32):
				target += Vector2(6.7, 0)
				puppet.move_pickup(target)
				puppet.pose(0, false, STEP)
		var effects: Array[JunkLandingEffect] = []
		puppet.landed.connect(func(point: Vector2, strength: float) -> void:
			var effect := JunkLandingEffect.new()
			effect.position = point
			effect.seed_value = 1 if sliding else column
			effect.strength = strength
			effect.pixel_zoom = 1.0
			effect.configure(puppet)
			effect.z_index = 3100
			root.add_child(effect)
			effect.set_process(false)
			effects.append(effect)
		)
		puppet.end_pickup(target, true)
		puppet.performer.position = {"x": target.x, "y": target.y}
		var contact_clock: float = -1.0
		var limit: float = (SLIDE_TIMES if sliding else DROP_TIMES)[column]
		for frame: int in range(600):
			puppet.pose(0, false, STEP)
			for effect: JunkLandingEffect in effects: effect._process(STEP)
			if not effects.is_empty():
				contact_clock = maxf(contact_clock, 0.0) + STEP
				if contact_clock >= limit: break
		var label := Label.new()
		label.text = ("Slide" if sliding else "Drop") + " +%d ms" % int(limit * 1000)
		label.position = Vector2(30 + column * COLUMN, 470 if sliding else 490 + 450)
		label.position.y = 960.0 if sliding else 450.0
		label.add_theme_font_size_override("font_size", 19)
		label.add_theme_color_override("font_color", Color("473a2a"))
		root.add_child(label)
	source.free()
	await process_frame
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://../artifacts/drop-response.png")
	print("Drop response phase sheet saved")
	quit()
