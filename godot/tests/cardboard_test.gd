extends SceneTree


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	# A donut exercises both the outside contour and an interior cut edge.
	var image := Image.create(64, 96, false, Image.FORMAT_RGBA8)
	image.fill_rect(Rect2i(8, 8, 48, 80), Color("ce5731"))
	image.fill_rect(Rect2i(25, 30, 14, 30), Color.TRANSPARENT)
	var texture := ImageTexture.create_from_image(image)
	var baked: Dictionary = JunkCardboardCutout.prepare(texture)
	assert(baked.texture.get_image().has_mipmaps())
	assert(baked.mesh.get_surface_count() == 1)
	assert(JunkCardboardCutout.prepare(texture).texture == baked.texture, "Clones must share baked art")
	var face: Image = baked.texture.get_image()
	assert(face.get_pixel(0, 0).a == 0, "Stock must leave transparent padding")
	assert(face.get_pixel(32 + int(baked.padding), 45 + int(baked.padding)).a == 0, "Interior cutouts must remain open")
	var detailed := Image.create(800, 1200, false, Image.FORMAT_RGBA8)
	detailed.fill_rect(Rect2i(20, 20, 760, 1160), Color("ae3a21"))
	for y: int in range(40, 48):
		for x: int in range(40, 48): detailed.set_pixel(x, y, Color.WHITE if (x + y) % 2 == 0 else Color.BLACK)
	var native_print: Dictionary = JunkCardboardCutout.prepare(ImageTexture.create_from_image(detailed))
	assert(native_print.art_size == Vector2(800, 1200), "Contour simplification must not shrink the original print")
	var native_face: Image = native_print.texture.get_image()
	for y: int in range(40, 48):
		for x: int in range(40, 48):
			assert(native_face.get_pixel(x + int(native_print.padding), y + int(native_print.padding)).is_equal_approx(detailed.get_pixel(x, y)), "Opaque source pixels must remain unchanged by stock preparation")
	var puppet := JunkPuppet.new()
	root.add_child(puppet)
	puppet.performer = {"id": "cardboard-test", "position": {"x": 0, "y": 0}}
	puppet.set_art(texture)
	puppet.pose(0, false, 0.016)
	var start_yaw: float = puppet._cardboard_yaw
	puppet.set_facing(-1)
	puppet.pose(0, false, 0.016)
	assert(absf(angle_difference(start_yaw, puppet._cardboard_yaw)) < 0.6, "Facing must turn continuously")
	for i: int in range(120): puppet.pose(0, false, 1.0 / 60.0)
	assert(cos(puppet._cardboard_yaw) < -0.9)
	puppet._cardboard_yaw = PI * 0.5
	assert(absf(puppet._project_cardboard(Vector2(30, 0)).x - puppet._project_cardboard(Vector2(-30, 0)).x) < 0.001)
	assert(puppet._thickness * puppet._base_scale > 3.0, "The side must retain physical width edge-on")
	# A turn must never detach the source point captured by the pinch.
	puppet._cardboard_yaw = -0.4
	puppet.pose(0, false, 0.0)
	var point: Vector2 = puppet._body.to_global(puppet._project_cardboard(Vector2(4, -22)))
	puppet.begin_pickup(point)
	for i: int in range(30): puppet.pose(0, false, 1.0 / 60.0)
	var projected_grip: Vector2 = puppet._body.to_global(puppet._project_cardboard(puppet._pinch_local))
	assert(projected_grip.distance_to(puppet.to_global(puppet._pinch_anchor - Vector2(0, puppet._lift_height))) < 0.01)
	puppet.queue_free()
	print("Cardboard regression passed: cached silhouettes, open holes, continuous turns, edge thickness and material grip")
	quit()
