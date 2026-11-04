extends SceneTree
## Dancing and band moments: beat-locked groove, note pops, leaving, cloning and joining.


func _initialize() -> void:
	_run.call_deferred()


func _texture() -> Texture2D:
	var image := Image.create(80, 120, false, Image.FORMAT_RGBA8)
	image.fill_rect(Rect2i(8, 8, 64, 104), Color("bd7046"))
	return ImageTexture.create_from_image(image)


func _puppet(id: String, motion: String = "dance") -> JunkPuppet:
	var puppet := JunkPuppet.new()
	root.add_child(puppet)
	puppet.performer = {"id": id, "position": {"x": 0, "y": 0}, "motion": motion}
	puppet.set_art(_texture())
	return puppet


func _test_groove() -> void:
	var puppet := _puppet("groove")
	# Silent band: no groove at all, however the beat moves.
	for frame: int in range(120):
		puppet.pose(frame / 60.0, false, 1.0 / 60.0, 0.0)
		assert(is_zero_approx(puppet._elevation), "A stopped band must stand still")
	puppet.groove_energy = 1.0
	var lowest: float = INF
	var highest: float = -INF
	for frame: int in range(240):
		puppet.pose(frame / 60.0, false, 1.0 / 60.0, 0.0)
		lowest = minf(lowest, puppet._elevation)
		highest = maxf(highest, puppet._elevation)
	assert(highest - lowest > 1.0, "A playing band dances, even between its own notes")
	assert(highest < 20.0, "Dancing stays a groove, not a jump")
	# The groove reads the beat, so the same beat gives the same pose at any frame rate.
	var a: JunkPuppet = _puppet("rate")
	var b: JunkPuppet = _puppet("rate")
	a.groove_energy = 1.0
	b.groove_energy = 1.0
	for frame: int in range(60): a.pose(frame / 60.0, false, 1.0 / 60.0, 0.0)
	for frame: int in range(240): b.pose(frame / 240.0, false, 1.0 / 240.0, 0.0)
	a.pose(1.0, false, 1.0 / 60.0, 0.0)
	b.pose(1.0, false, 1.0 / 240.0, 0.0)
	assert(absf(a._elevation - b._elevation) < 0.5 and absf(a._body.rotation - b._body.rotation) < 0.01, "Groove must follow the beat, not the frame rate")
	# A note snaps the cutout tall.
	var before: float = puppet._body.scale.y
	puppet.note_hit(1.0, true)
	puppet.pose(4.25, false, 1.0 / 60.0, 0.0)
	puppet.pose(4.25 + 1.0 / 30.0, false, 1.0 / 60.0, 0.0)
	assert(puppet._body.scale.y > before, "A note stretches the character upward")
	# Held characters do not dance in the hand.
	puppet.begin_pickup(puppet.position + Vector2(0, -40))
	for frame: int in range(30): puppet.pose(5.0 + frame / 60.0, false, 1.0 / 60.0, 0.0)
	assert(is_zero_approx(puppet._dance_yaw), "Pickup freezes the dance turn")
	puppet.end_pickup()
	# Reduced motion keeps everyone still.
	for frame: int in range(30):
		puppet.pose(6.0 + frame / 60.0, true, 1.0 / 60.0, 0.0)
		assert(is_zero_approx(puppet._elevation) and is_zero_approx(puppet._dance_yaw))
	for node: JunkPuppet in [puppet, a, b]: node.free()


func _test_departure() -> void:
	var puppet := _puppet("leaving")
	var gone: Array = []
	puppet.departed.connect(func(who: JunkPuppet) -> void: gone.append(who))
	puppet.pose(0.0, false, 1.0 / 60.0, 0.0)
	var width: float = puppet._body.scale.x
	puppet.depart()
	assert(puppet.departing())
	for frame: int in range(10): puppet.pose(frame / 60.0, false, 1.0 / 60.0, 0.0)
	assert(puppet._body.scale.x < width, "Leaving crumples the cutout")
	for frame: int in range(30): puppet.pose(frame / 60.0, false, 1.0 / 60.0, 0.0)
	assert(gone.size() == 1 and not puppet.departing(), "A crumple ends once, then the stage takes over")
	puppet.free()


func _test_stage_moments() -> void:
	var stage := JunkStage.new()
	root.add_child(stage)
	stage.set_process(false)
	stage.size = Vector2(1400, 820)
	var project: Dictionary = {"assets": [{"id": "demo", "tile": 0}], "performers": [{"id": "one", "assetId": "demo", "position": {"x": -120, "y": 0}}]}
	stage.apply_scene(project, "")
	for frame: int in range(30): stage._process(1.0 / 120.0)
	# A clone hops out of its original and lands on its own spot, once.
	project.performers.append({"id": "two", "assetId": "demo", "position": {"x": 60, "y": 20}})
	stage.queue_arrival("two", "clone", "one")
	stage.apply_scene(project, "")
	var clone: JunkPuppet = stage._puppets.two
	stage._process(1.0 / 120.0)
	assert(clone.position.distance_to(Vector2(-120, 0)) < 20.0, "A clone starts from the character it copies")
	for frame: int in range(180): stage._process(1.0 / 120.0)
	assert(clone.position.distance_to(Vector2(60, 20)) < 0.5, "A clone ends on its own spot")
	assert(stage.landing_count() == 1)
	# A brand new character falls from high up and lands as the hero.
	project.performers.append({"id": "three", "assetId": "demo", "position": {"x": 200, "y": -30}})
	stage.queue_arrival("three", "new")
	stage.apply_scene(project, "")
	var hero: JunkPuppet = stage._puppets.three
	stage._process(1.0 / 120.0)
	assert(hero._lift_height > JunkPuppet.CARRY_HEIGHT * 2.0 and hero.hero_landing)
	for frame: int in range(150): stage._process(1.0 / 120.0)
	assert(stage.landing_count() == 2 and not hero.hero_landing, "A hero lands exactly once")
	# Removing crumples; unloading does not.
	stage.queue_departure("one")
	project.performers = project.performers.filter(func(p: Dictionary) -> bool: return p.id != "one")
	stage.apply_scene(project, "")
	assert(not stage._puppets.has("one"), "A leaving character no longer takes input")
	for frame: int in range(80): stage._process(1.0 / 120.0)
	var poofs: int = 0
	var crumpling: int = 0
	for child: Node in stage._world.get_children():
		if child is JunkLandingEffect and child.poof: poofs += 1
		if child is JunkPuppet and not child.is_queued_for_deletion() and str(child.performer.id) == "one": crumpling += 1
	assert(poofs == 1 and crumpling == 0, "A removed character crumples, then goes in one puff")
	project.performers = []
	stage.apply_scene(project, "")
	for child: Node in stage._world.get_children():
		if child is JunkPuppet: assert(child.is_queued_for_deletion(), "Unloading a project removes characters at once")
	stage.free()


func _run() -> void:
	_test_groove()
	_test_departure()
	_test_stage_moments()
	print("Groove regression passed: beat-locked dancing, note pops, pickup and reduced motion, crumple and poof, clone hop and hero arrival")
	quit()
