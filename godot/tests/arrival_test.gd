extends SceneTree

func _initialize() -> void:
	_run.call_deferred()

func _press(stage: JunkStage, point: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = pressed
	event.position = point
	stage._gui_input(event)


func _test_orbit_priority() -> void:
	var stage := JunkStage.new()
	root.add_child(stage)
	stage.set_process(false)
	stage.size = Vector2(1400, 820)
	# Stands across the orbit's left edge, with the line running through its body.
	var performer: Dictionary = {"id": "edge", "assetId": "demo", "position": {"x": -380, "y": 60}}
	stage.apply_scene({"assets": [{"id": "demo", "tile": 0}], "performers": [performer]}, "")
	for frame: int in range(10): stage._process(1.0 / 120.0)
	var on_character: Vector2 = stage._world.position + Vector2(-380, 0) * stage.world_zoom()
	assert(stage.scrubber.hit(on_character), "The test point must lie on the orbit line")
	_press(stage, on_character, true)
	assert(stage._drag_id == "edge" and not stage.scrubber.dragging, "A character on the orbit line must be picked up instead of seeking")
	_press(stage, on_character, false)
	# Empty stretches of the same line must still seek.
	var open_line: Vector2 = stage._world.position + Vector2(0, -230) * stage.world_zoom()
	assert(stage.scrubber.hit(open_line))
	_press(stage, open_line, true)
	assert(stage.scrubber.dragging and stage._drag_id.is_empty(), "The orbit must still seek where no character stands")
	_press(stage, open_line, false)
	stage.free()


func _run() -> void:
	var stage := JunkStage.new()
	root.add_child(stage)
	stage.set_process(false)
	var starter: Dictionary = {"id": "starter", "assetId": "demo", "position": {"x": -180, "y": 0}}
	var project: Dictionary = {"assets": [{"id": "demo", "tile": 0}], "performers": [starter]}
	stage.apply_scene(project, "")
	for frame: int in range(60): stage._process(1.0 / 120.0)
	assert(stage.landing_count() == 0, "Initial load must not replay arrival effects")
	var imported: Dictionary = {"id": "imported", "assetId": "photo", "position": {"x": 160, "y": 30}}
	project.assets.append({"id": "photo", "sprite": "blob:asset:photo"})
	project.performers.append(imported)
	stage.queue_arrival("imported")
	stage.apply_scene(project, "")
	var puppet: JunkPuppet = stage._puppets.imported
	assert(not puppet.visible and puppet._body.texture == null, "Never display a fake starter while accepted artwork loads")
	assert(not puppet.contains_world(Vector2.ZERO), "An invisible pending character must not intercept pointer input")
	assert(stage.texture_for(project.assets[-1]) == null, "Missing imported art must not create/cache an atlas substitute")
	stage._process(1.0 / 60.0)
	var image := Image.create(80, 120, false, Image.FORMAT_RGBA8)
	image.fill_rect(Rect2i(8, 8, 64, 104), Color("bd7046"))
	stage.set_texture("photo", Marshalls.raw_to_base64(image.save_png_to_buffer()))
	stage.apply_scene(project, "")
	stage._process(1.0 / 120.0)
	assert(puppet.visible and puppet._arrival_active and puppet._lift_height > 20.0)
	assert(puppet.position.distance_to(Vector2(160, 30)) < 0.001, "Arrival height must not alter the committed floor position")
	for frame: int in range(90):
		stage._process(1.0 / 120.0)
		assert(puppet.position.distance_to(Vector2(160, 30)) < 0.001)
	assert(stage.landing_count() == 1 and not puppet._arrival_active)
	stage.queue_arrival("imported")
	stage.apply_scene(project, "")
	for frame: int in range(90): stage._process(1.0 / 120.0)
	assert(stage.landing_count() == 1 and is_zero_approx(puppet._lift_height), "Repeated packets must not replay arrival")
	# Picking up during an entrance interrupts its pending collision cleanly.
	puppet.arrive(false)
	stage._process(1.0 / 120.0)
	puppet.begin_pickup(puppet.position + Vector2(0, -45))
	for frame: int in range(60): stage._process(1.0 / 120.0)
	assert(stage.landing_count() == 1 and not puppet._arrival_active)
	puppet.end_pickup(puppet.position, true)
	for frame: int in range(90): stage._process(1.0 / 120.0)
	assert(stage.landing_count() == 2, "Interrupting arrival must leave one ordinary drop")
	stage.reduced_motion = true
	var quiet: Dictionary = {"id": "quiet", "assetId": "demo", "position": {"x": 0, "y": -70}}
	project.performers.append(quiet)
	stage.queue_arrival("quiet")
	stage.apply_scene(project, "")
	var reduced: JunkPuppet = stage._puppets.quiet
	assert(is_zero_approx(reduced._lift_height))
	stage._process(1.0 / 60.0)
	assert(stage.landing_count() == 3 and not reduced._arrival_active, "Reduced motion must retain one acknowledgement without a fall")
	quiet.path = [{"beat": 4.0, "x": 120.0, "y": -30.0}]
	reduced.path_knots = JunkMotionMath.closed_path(quiet)
	reduced.arrive(false)
	for frame: int in range(90): reduced.pose(2, false, 1.0 / 120.0)
	assert(reduced.position.distance_to(JunkMotionMath.path_position(reduced.path_knots, 2)) < 0.001, "An entrance must not pin a recorded path to its home position")
	assert(not reduced._settling and stage.landing_count() == 4)
	stage.free()
	_test_orbit_priority()
	print("Arrival regression passed: real-art gate, quiet hydration, fixed floor anchor, one landing, interrupted pickup, reduced motion and character priority over the orbit")
	quit()
