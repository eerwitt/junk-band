extends SceneTree


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	assert(JunkLoopTiming.BARS == 16 and JunkLoopTiming.STEPS == 256)
	var stage := JunkStage.new()
	root.add_child(stage)
	stage.position = Vector2(45, 35)
	stage.size = Vector2(1000, 600)
	stage.set_process(false)
	var performer: Dictionary = {"id": "test", "assetId": "art", "position": {"x": -120, "y": 20}, "motion": "still", "path": []}
	var project: Dictionary = {"performers": [performer], "assets": [{"id": "art", "tile": 0}]}
	stage.apply_scene(project, "test")
	stage._process(1.0 / 60.0)
	var puppet: JunkPuppet = stage._puppets["test"]
	_test_weighted_lift(puppet._source_art)
	_test_landing_contact(puppet._source_art)
	_test_drop_response(puppet._source_art)
	_test_impact_reaction(puppet._source_art)
	_test_path_facing(puppet._source_art)
	var initial: Vector2 = puppet.position
	var foot_y: float = (puppet._foot_y_pixels - puppet._art_padding - 0.85 * puppet._art_size.y) * puppet._base_scale
	assert((puppet._shadow.transform * Vector2(0, foot_y / puppet._base_scale)).distance_to(Vector2(0, foot_y)) < 0.01)
	var commits: Array = []
	var landings: Array = []
	stage.action.connect(func(kind: String, payload: Dictionary) -> void:
		if kind == "update_performer": commits.append(payload)
	)
	puppet.landed.connect(func(point: Vector2, strength: float) -> void: landings.append({"point": point, "strength": strength}))
	var pointer: Vector2 = stage._world.to_global(initial + Vector2(20, -60))
	_mouse_button(pointer, true)
	await process_frame
	stage._process(1.0 / 60.0)
	assert(puppet._held)
	var destination: Vector2 = initial + Vector2(130, 40)
	var moved_pointer: Vector2 = stage._world.to_global(destination + Vector2(20, -60))
	_mouse_motion(moved_pointer)
	await process_frame
	stage._process(1.0 / 60.0)
	assert(puppet.position.distance_to(destination) > 20, "A weighted pickup must lag rather than lock to the mouse")
	assert(puppet.position.x > initial.x, "The spring should immediately begin following")
	_assert_shadow_under_body(puppet)
	for index: int in range(6): stage._process(1.0 / 60.0)
	assert(puppet.position.distance_to(destination + Vector2(0, 6)) < 28, "Snappy pickup should catch up within 120 ms")
	assert(puppet._body.scale.y / puppet._base_scale <= 1.019, "Cardboard must stay mostly rigid during a pull")
	assert(absf(puppet._body.skew) <= 0.0121, "A weighted lean must not turn into rubbery shear")
	var maximum_x: float = puppet.position.x
	for index: int in range(150):
		stage._process(1.0 / 120.0)
		maximum_x = maxf(maximum_x, puppet.position.x)
	assert(maximum_x > destination.x + 2 and maximum_x < destination.x + 18, "Elastic carry must recoil with bounded overshoot")
	assert(puppet.position.distance_to(destination) < 0.3, "The floor spring must not include vertical pickup height")
	assert(puppet._lift_height > 29.0 and puppet._lift_height < 31.0, "The rendered cutout should rise independently above its floor anchor")
	assert(absf(puppet._body.scale.y / puppet._base_scale - 1.0) < 0.003, "Settled cardboard should recover its rigid shape")
	_assert_shadow_under_body(puppet)
	var visible_foot: Vector2 = puppet._body.to_global(puppet._project_cardboard(Vector2(0, (puppet._foot_y_pixels - puppet._body.texture.get_height() * 0.5) + puppet._body.offset.y)))
	assert(puppet._drop_shadow.global_position.y > visible_foot.y + 3.0, "The held shadow must clear the opaque cutout's feet")
	assert((puppet._drop_shadow.texture as GradientTexture2D).gradient.sample(0.0).a >= 0.3, "The held shadow must have enough contrast to read on paper")
	var grip: Vector2 = puppet._body.to_global(puppet._project_cardboard(puppet._pinch_local))
	var shadow_before_reversal: Vector2 = puppet._drop_shadow.global_position
	_mouse_motion(moved_pointer + Vector2(-80, -30))
	await process_frame
	stage._process(1.0 / 60.0)
	_assert_shadow_under_body(puppet)
	assert(puppet._drop_shadow.global_position.distance_to(shadow_before_reversal) < 30, "The shadow must lag and recoil with the floor position instead of jumping with the cursor")
	assert(puppet._body.to_global(puppet._project_cardboard(puppet._pinch_local)).distance_to(grip) < 30, "The weighted body should recoil instead of teleporting on reversal")
	_mouse_motion(moved_pointer)
	await process_frame
	for index: int in range(60): stage._process(1.0 / 120.0)
	_mouse_button(moved_pointer, false)
	await process_frame
	assert(commits.size() == 1 and commits[0].patch.path.is_empty())
	for index: int in range(80):
		stage._process(1.0 / 120.0)
		assert(puppet.position.distance_to(destination) < 15, "Delayed model acknowledgement must never snap a drop to its old position")
	assert(landings.size() == 1, "One release must produce exactly one landing effect")
	performer.position = {"x": destination.x, "y": destination.y}
	stage.apply_scene(project, "test")
	for index: int in range(100): stage._process(1.0 / 120.0)
	assert(puppet.position.distance_to(destination) < 0.2 and not puppet._settling)
	assert(landings.size() == 1)
	puppet.pose(2, false, 0.016, 1)
	assert(puppet._elevation > 0 and puppet._elevation <= 6, "An audible note produces a subtle bounce")
	puppet.pose(2, true, 0.016, 1)
	assert(is_zero_approx(puppet._elevation), "Reduced motion suppresses musical bounce")
	var points := PackedVector2Array([destination, destination + Vector2(80, -40), destination + Vector2(150, 35)])
	performer.path = JunkMotionMath.recorded_path(points)
	stage.apply_scene(project, "test")
	var knots: Array = puppet.path_knots
	assert(JunkMotionMath.path_position(knots, 0).distance_to(destination) < 0.001)
	assert(JunkMotionMath.path_position(knots, 64).distance_to(destination) < 0.001)
	assert(JunkMotionMath.path_position(knots, 63.999).distance_to(destination) < 0.001, "The closed path returns home before the wrap")
	var seam_velocity: Vector2 = (JunkMotionMath.path_position(knots, 63.99) - JunkMotionMath.path_position(knots, 63.98)) / 0.01
	assert(seam_velocity.length() < 0.4, "Return should settle gently at the seam within Vector2 precision")
	var low: Array[Vector2] = [Vector2.ZERO, Vector2.ZERO]
	var high: Array[Vector2] = [Vector2.ZERO, Vector2.ZERO]
	for index: int in range(60): low = JunkMotionMath.spring(low[0], low[1], Vector2(100, 50), 1.0 / 60)
	for index: int in range(120): high = JunkMotionMath.spring(high[0], high[1], Vector2(100, 50), 1.0 / 120)
	assert(low[0].distance_to(high[0]) < 0.001, "Spring motion must be independent of frame rate")
	low = [Vector2.ZERO, Vector2.ZERO]
	high = [Vector2.ZERO, Vector2.ZERO]
	for index: int in range(30): low = JunkMotionMath.spring(low[0], low[1], Vector2(100, 50), 1.0 / 60, true)
	for index: int in range(60): high = JunkMotionMath.spring(high[0], high[1], Vector2(100, 50), 1.0 / 120, true)
	assert(low[0].distance_to(high[0]) < 0.001, "Elastic recoil must also be independent of frame rate")
	var route: PackedVector2Array = stage._sample_path("test")
	var inked: Array[float] = []
	for frame: int in range(12):
		var length: float = 0.0
		for dash: PackedVector2Array in stage.route_dashes(route, 10.0 + frame / 30.0):
			for index: int in range(1, dash.size()): length += dash[index].distance_to(dash[index - 1])
		inked.append(length)
	assert(inked.min() > inked.max() * 0.9, "The marching route must not blink as its dashes move (%s)" % [inked])
	stage.cancel_path()
	var camera_pointer: Vector2 = stage.size * Vector2(0.4, 0.35)
	var camera_anchor: Vector2 = stage._world_point(camera_pointer)
	stage.zoom_at(camera_pointer, 1.7)
	assert(stage._world_point(camera_pointer).distance_to(camera_anchor) < 0.001, "Zoom must preserve the world point under the pointer")
	var pan_start: Vector2 = stage.camera_pan
	var pan_pointer: Vector2 = stage.get_global_transform() * camera_pointer
	_mouse_button(pan_pointer, true, MOUSE_BUTTON_MIDDLE)
	await process_frame
	_mouse_motion(pan_pointer + Vector2(85, -35))
	await process_frame
	_mouse_button(pan_pointer + Vector2(85, -35), false, MOUSE_BUTTON_MIDDLE)
	await process_frame
	assert(stage.camera_pan.distance_to(pan_start + Vector2(85, -35)) < 0.01, "Camera pan must track screen-space pointer distance")
	stage._process(1.0 / 60.0)
	var zoomed_grip: Vector2 = stage._world.to_global(puppet.position + Vector2(12, -70))
	_mouse_button(zoomed_grip, true)
	await process_frame
	_mouse_motion(zoomed_grip + Vector2(35, 15))
	await process_frame
	stage._process(1.0 / 60.0)
	assert(puppet._held)
	_assert_shadow_under_body(puppet)
	# Pan the old out-of-bounds area into view and release there through real input.
	stage.camera_pan += Vector2(900, 350)
	stage._sync_camera()
	var outside := Vector2(-900, -420)
	var outside_pointer: Vector2 = stage._world.to_global(outside + stage._grab_offset)
	_mouse_motion(outside_pointer)
	await process_frame
	stage._process(1.0 / 60.0)
	_mouse_button(outside_pointer, false)
	await process_frame
	assert(commits.size() == 2)
	assert(Vector2(commits[-1].patch.position.x, commits[-1].patch.position.y).distance_to(outside) < 0.01, "A drop outside the old stage bounds must preserve its world position")
	performer.position = {"x": outside.x, "y": outside.y}
	performer.path = []
	stage.apply_scene(project, "test")
	for index: int in range(180): stage._process(1.0 / 120.0)
	assert(puppet.position.distance_to(outside) < 0.2 and not puppet._held)
	assert(puppet.z_index > puppet._shadow.z_index, "Off-stage characters must stay above the floor layer")
	var outside_path: Array = JunkMotionMath.recorded_path(PackedVector2Array([outside, Vector2(-1050, -500)]))
	assert(is_equal_approx(outside_path[-1].x, -1050.0) and is_equal_approx(outside_path[-1].y, -500.0), "Paths must retain off-stage coordinates too")
	stage.cancel_path()
	stage.reset_camera()
	assert(is_equal_approx(stage.camera_zoom, 1.0) and stage.camera_pan == Vector2.ZERO)
	stage.queue_free()
	print("Pickup regression passed: elastic carry, gravity, delayed drop acknowledgement, one landing, note bounce, smooth closed paths and frame-rate independence")
	quit()


func _test_weighted_lift(texture: Texture2D) -> void:
	var puppet := JunkPuppet.new()
	root.add_child(puppet)
	puppet.performer = {"id": "weight-test", "position": {"x": 0, "y": 0}}
	puppet.set_art(texture)
	puppet.pose(0, false, 0)
	var original_shadow: Transform2D = puppet._shadow.transform
	puppet.begin_pickup(Vector2(18, -70))
	for frame: int in range(7): puppet.pose(0, false, 1.0 / 120.0)
	assert(puppet._lift_height < -0.1 and absf(puppet.position.y) < 0.01, "Initial loading must affect body height without moving its floor position")
	assert(puppet._body.scale.y < puppet._base_scale, "The initial load should give a small, rigid compression")
	assert(puppet._shadow.modulate.a > 0.1 and is_zero_approx(puppet._drop_shadow.modulate.a), "Pickup must begin with the original mask, not swap immediately to the circle")
	for frame: int in range(120):
		if puppet._lift_height >= JunkPuppet.CARRY_HEIGHT * 0.5: break
		puppet.pose(0, false, 1.0 / 120.0)
		_assert_shadow_under_body(puppet)
		assert(puppet._shadow.modulate.a + puppet._drop_shadow.modulate.a <= 0.1301, "Overlapping representations must not darken as the object lifts")
	assert(absf(puppet._shadow.transform.y.x) < absf(original_shadow.y.x) * 0.65, "The original mask should progressively lose shear")
	assert(puppet._shadow.transform.y.length() < original_shadow.y.length() * 0.7, "The mask should shrink while it is still visible")
	assert(puppet._shadow.modulate.a > 0.08 and is_zero_approx(puppet._drop_shadow.modulate.a), "The circle must wait until the silhouette has gathered")
	for frame: int in range(120):
		if puppet._lift_height >= JunkPuppet.CARRY_HEIGHT * 0.85: break
		puppet.pose(0, false, 1.0 / 120.0)
	assert(puppet._shadow.modulate.a > 0.0 and puppet._drop_shadow.modulate.a > 0.0, "The compact mask and circle must overlap during their merge")
	for frame: int in range(30): puppet.pose(0, false, 1.0 / 120.0)
	assert(is_zero_approx(puppet._shadow.modulate.a) and puppet._drop_shadow.modulate.a > 0.11 and puppet._drop_shadow.modulate.a < 0.12, "Carry density should be lighter than the grounded mask but readable at stage scale")
	assert(puppet._lift_height > 29.0 and absf(puppet.position.y) < 0.01, "The lifted body must leave the floor anchor in place")
	var floor_at_carry: Vector2 = puppet.to_global(puppet._ground_foot)
	puppet._held = false
	var h: float = puppet._lift_height
	puppet.pose(0, false, 1.0 / 120.0)
	assert(puppet._lift_height < h, "Release must begin a fall in actual height")
	assert(absf(puppet.to_global(puppet._ground_foot).y - floor_at_carry.y) < 0.01, "Falling must not raise or lower the floor anchor")
	puppet._held = true
	var regrab: Vector2 = puppet._body.to_global(puppet._project_cardboard(Vector2(0, -40)))
	puppet.begin_pickup(regrab)
	puppet.pose(0, false, 0)
	var regrab_after: Vector2 = puppet._body.to_global(puppet._project_cardboard(puppet._pinch_local))
	assert(regrab_after.distance_to(regrab) < 0.01, "Regrabbing an airborne cutout must not apply its height twice")
	puppet.end_pickup()
	for frame: int in range(30): puppet.pose(0, true, 1.0 / 120.0)
	puppet.begin_pickup(Vector2(18, -70))
	puppet.pose(0, true, 1.0 / 60.0)
	assert(is_zero_approx(puppet._elevation) and is_equal_approx(puppet._body.scale.y, puppet._base_scale), "Reduced motion must omit the loaded dip and deformation")
	assert(is_equal_approx(puppet._lift_height, JunkPuppet.REDUCED_CARRY_HEIGHT), "Reduced motion must retain a modest static height cue")
	for frame: int in range(12): puppet.pose(0, true, 1.0 / 120.0)
	assert(absf(puppet._shadow.transform.y.x) < absf(original_shadow.y.x) * 0.65, "Reduced-motion pickup must visibly remove shadow skew")
	assert(puppet._shadow.transform.y.length() < original_shadow.y.length() * 0.7, "Reduced-motion pickup must visibly shrink the mask")
	assert(puppet._shadow.modulate.a > 0.1 and is_zero_approx(puppet._drop_shadow.modulate.a), "The modest reduced-motion lift retains the gathered silhouette")
	puppet.free()


func _test_landing_contact(texture: Texture2D) -> void:
	for reduced: bool in [false, true]:
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		puppet.performer = {"id": "contact-test", "position": {"x": 0, "y": 0}}
		puppet.set_art(texture)
		puppet.pose(0, reduced, 0)
		puppet.begin_pickup(Vector2(42, -70))
		for frame: int in range(60): puppet.pose(0, reduced, 1.0 / 120.0)
		# Release while the body still trails a sharp reversal. The cursor is not contact.
		var destination := Vector2(450, -150)
		puppet.move_pickup(destination)
		puppet.pose(0, reduced, 1.0 / 120.0)
		var contacts: Array[Vector2] = []
		puppet.landed.connect(func(point: Vector2, _strength: float) -> void:
			assert(point.distance_to(puppet.transform * puppet._ground_foot) < 0.001, "Impact must use this frame's rendered floor contact")
			assert(point.distance_to(destination) > 20, "Impact must not use the cursor's release target")
			assert(puppet._lift_height <= 0.01, "Impact must wait for floor collision")
			contacts.append(point)
		)
		puppet.end_pickup(destination, true)
		for frame: int in range(120): puppet.pose(0, reduced, 1.0 / 120.0)
		assert(contacts.size() == 1, "Each drop emits one current contact, including reduced motion")
		puppet.free()


func _test_impact_reaction(texture: Texture2D) -> void:
	for reduced: bool in [false, true]:
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		puppet.performer = {"id": "reaction-test", "position": {"x": 0, "y": 0}}
		puppet.set_art(texture)
		puppet.pose(0, reduced, 0)
		var rest_height: float = puppet._body.scale.y
		puppet.begin_pickup(Vector2(20, -65))
		for frame: int in range(90): puppet.pose(0, reduced, 1.0 / 120.0)
		var effects: Array[JunkLandingEffect] = []
		puppet.landed.connect(func(point: Vector2, strength: float) -> void:
			var effect := JunkLandingEffect.new()
			effect.position = point
			effect.strength = strength
			effect.reduced_motion = reduced
			effect.configure(puppet)
			effects.append(effect)
		)
		puppet.end_pickup(Vector2.ZERO, true)
		var flattest: float = rest_height
		var highest_rebound: float = 0.0
		var widest_rock: float = 0.0
		for frame: int in range(240):
			puppet.pose(0, reduced, 1.0 / 120.0)
			for effect: JunkLandingEffect in effects: effect._process(1.0 / 120.0)
			if not effects.is_empty():
				flattest = minf(flattest, puppet._body.scale.y)
				highest_rebound = maxf(highest_rebound, puppet._elevation)
				widest_rock = maxf(widest_rock, absf(puppet._body.rotation))
		assert(effects.size() == 1 and not effects[0].sliding)
		var effect: JunkLandingEffect = effects[0]
		if reduced:
			assert(is_equal_approx(flattest, rest_height) and is_zero_approx(highest_rebound) and is_zero_approx(widest_rock), "Reduced motion must not deform, hop or rock")
			assert(effect._puffs.is_empty() and effect._chips.is_empty() and effect._rays.is_empty(), "Reduced motion keeps only the stationary floor acknowledgement")
		else:
			assert(flattest < rest_height * 0.93, "A stationary drop must visibly compress the body")
			assert(highest_rebound > 4.0 and widest_rock > 0.02, "A stationary drop must rebound and rock out its energy")
			assert(effect._puffs.size() <= JunkLandingEffect.MAX_PUFFS and effect._chips.size() <= JunkLandingEffect.MAX_CHIPS, "Impact particles must remain bounded")
			assert(effect._puffs.size() > 15, "A stationary drop must throw a dust skirt")
		# A neighbour feels the wave only after it has crossed the floor.
		puppet.jolt(1.0, 0.1)
		puppet.pose(0, reduced, 1.0 / 120.0)
		assert(is_zero_approx(puppet._elevation), "A jolt must wait for the floor wave to arrive")
		var bumped: float = 0.0
		for frame: int in range(60):
			puppet.pose(0, reduced, 1.0 / 120.0)
			bumped = maxf(bumped, puppet._elevation)
		assert(is_zero_approx(bumped) if reduced else bumped > 4.0, "Neighbour jolts apply outside reduced motion")
		effect.free()
		puppet.free()


## A hand-drawn route wobbles. The cutout should turn only where the route really heads back,
## and never while it is held, settling or waiting off stage away from its route.
func _test_path_facing(texture: Texture2D) -> void:
	var points := PackedVector2Array()
	var rng := RandomNumberGenerator.new()
	rng.seed = 3
	for index: int in range(60):
		points.append(Vector2(sin(index / 9.0) * 40.0 + rng.randf_range(-3, 3), index * 4.0 if index < 30 else (60 - index) * 4.0))
	var performer: Dictionary = {"id": "facing-test", "position": {"x": points[0].x, "y": points[0].y}, "path": JunkMotionMath.recorded_path(points)}
	var puppet := JunkPuppet.new()
	root.add_child(puppet)
	puppet.performer = performer
	puppet.path_knots = JunkMotionMath.closed_path(performer)
	puppet.set_art(texture)
	var turns: int = 0
	var facing: float = puppet._facing
	var beat_value: float = 0.0
	while beat_value < JunkLoopTiming.BEATS:
		puppet.pose(beat_value, false, 1.0 / 60.0)
		if puppet._facing != facing: turns += 1
		facing = puppet._facing
		beat_value += 2.0 / 60.0
	assert(turns >= 1 and turns <= 3, "A wobbly route must turn the cutout only where it heads back, not on every wobble (%d turns)" % turns)
	# Waiting in the wings for a section it sits out: standing still, so it must not turn round.
	puppet.snap_present()
	puppet.drop_offstage(Vector2(-440, -175))
	for frame: int in range(240):
		puppet.pose(beat_value, false, 1.0 / 60.0)
		beat_value += 2.0 / 60.0
		if frame > 60: assert(puppet._facing == facing, "A character away from its route must not keep turning to follow it")
	puppet.queue_free()


func _test_drop_response(texture: Texture2D) -> void:
	for reduced: bool in [false, true]:
		var puppet := JunkPuppet.new()
		root.add_child(puppet)
		puppet.performer = {"id": "slide-test", "position": {"x": 0, "y": 0}}
		puppet.set_art(texture)
		puppet.pose(0, reduced, 0)
		puppet.begin_pickup(Vector2(20, -65))
		for frame: int in range(90): puppet.pose(0, reduced, 1.0 / 120.0)
		puppet.end_pickup(Vector2.ZERO, true)
		assert(not puppet._slide_drop, "A stationary release must retain its normal impact")
		for frame: int in range(90): puppet.pose(0, reduced, 1.0 / 120.0)
		puppet.begin_pickup(Vector2(20, -65))
		for frame: int in range(60): puppet.pose(0, reduced, 1.0 / 120.0)
		puppet.move_pickup(Vector2(260, 30))
		puppet.pose(0, reduced, 1.0 / 120.0)
		puppet.end_pickup(Vector2(260, 30), true)
		var release_contact: Vector2 = puppet.transform * puppet._ground_foot
		assert(puppet._slide_drop, "Releasing a lagging character must choose a slide")
		var effects: Array[JunkLandingEffect] = []
		puppet.landed.connect(func(point: Vector2, _strength: float) -> void:
			var effect := JunkLandingEffect.new()
			effect.position = point
			effect.reduced_motion = reduced
			effect.configure(puppet)
			effects.append(effect)
		)
		var maximum_landed_speed: float = 0.0
		for frame: int in range(170):
			puppet.pose(0, reduced, 1.0 / 120.0, 1.0 if frame < 60 else 0.0)
			if puppet._lift_height <= 0.01:
				maximum_landed_speed = maxf(maximum_landed_speed, puppet._carry_velocity.length())
				if puppet._settling: assert(is_zero_approx(puppet._elevation), "Skidding cardboard must stay on the floor even on musical notes")
			for effect: JunkLandingEffect in effects: effect._process(1.0 / 120.0)
		assert(effects.size() == 1 and effects[0].sliding, "A skid must produce one directional effect")
		assert(maximum_landed_speed > 100.0, "The character must touch down while it is still sliding")
		var effect: JunkLandingEffect = effects[0]
		assert(effect._trail.size() > 1, "Both motion settings must retain the complete ground-contact trail")
		assert(effect._trail.size() <= JunkLandingEffect.MAX_TRAIL_SAMPLES, "Skid emission must remain bounded")
		assert(effect._puffs.size() <= JunkLandingEffect.MAX_PUFFS and effect._chips.size() <= JunkLandingEffect.MAX_CHIPS and effect._streaks.size() <= JunkLandingEffect.MAX_STREAKS, "Particle records must remain bounded")
		assert(effect._puffs.is_empty() == reduced, "Reduced motion keeps the ground trail without expanding particles")
		if not reduced:
			assert(effect._puffs.size() >= 8 and effect._chips.size() >= 6, "A slide must throw distinct dust puffs and dirt")
		if effect.sliding:
			assert((effect.position + effect._trail[0].point).distance_to(release_contact) < 0.001, "The trail must begin at release, including the section before floor collision")
			assert(not effect._tracking and effect._stop_age > 0.3, "Trail emission must continue until rest beyond the former 300 ms cutoff")
			var rest_contact: Vector2 = puppet.transform * puppet._ground_foot
			assert((effect.position + effect._trail[-1].point).distance_to(rest_contact) < 0.3, "The trail must reach the actual stopping point")
			var last: int = effect._trail.size() - 1
			var expected_start: float = effect._stop_age + JunkLandingEffect.TRAIL_HOLD_TIME - JunkLandingEffect.TRAIL_EARLY_START
			assert(absf(effect._fade_start - maxf(expected_start, JunkLandingEffect.TRAIL_MIN_START)) < 0.04, "Cleanup must start 700 ms ahead of the stop plus hold")
			effect._age = effect._fade_start
			assert(effect.trail_opacity(0) > 0.99 and effect.trail_opacity(last) > 0.99, "The whole trail must stay until cleanup starts")
			effect._age += JunkLandingEffect.TRAIL_FADE_TIME
			assert(effect.trail_opacity(0) < 0.001 and effect.trail_opacity(last) > 0.99, "The fade must clear the release end before the stopping end")
			effect._age = effect._fade_start + effect._fade_sweep + JunkLandingEffect.TRAIL_FADE_TIME * 0.5
			assert(effect.trail_opacity(last) > 0.4 and effect.trail_opacity(last) < 0.6, "The fade must reach the stopping end after the sweep")
			for index: int in range(1, effect._trail.size()):
				assert(effect.trail_opacity(index) >= effect.trail_opacity(index - 1) - 0.001, "Opacity must rise along the route toward the stop")
			effect._age = effect._fade_start + effect._fade_sweep + JunkLandingEffect.TRAIL_FADE_TIME
			assert(is_zero_approx(effect.trail_opacity(last)), "The completed fade must clear the whole trail")
		for zoom: float in [0.5, 1.0, 3.0]:
			effect.pixel_zoom = zoom
			for seed: int in range(JunkLandingEffect.WORDS.size()):
				effect.seed_value = seed
				var origin: Vector2 = effect.word_origin()
				assert(origin.y - 17.0 / zoom > effect.character_bounds.end.y, "The full word must be lower than the character")
				assert(origin.x < effect.character_bounds.position.x or origin.x > effect.character_bounds.end.x, "Impact words must sit beside the character's swept bounds")
		puppet.performer.position = {"x": 260, "y": 30}
		for frame: int in range(60): puppet.pose(0, reduced, 1.0 / 120.0)
		assert(not puppet._settling)
		puppet.pose(0, reduced, 1.0 / 120.0, 1.0)
		assert(is_zero_approx(puppet._elevation) if reduced else puppet._elevation > 0.0, "Ordinary note bounce must resume after the slide settles")
		effect.free()
		puppet.free()


func _assert_shadow_under_body(puppet: JunkPuppet) -> void:
	var foot_in_material := Vector2(puppet._body.offset.x, puppet._foot_y_pixels - puppet._body.texture.get_height() * 0.5 + puppet._body.offset.y)
	var visible_foot: Vector2 = puppet._body.to_global(puppet._project_cardboard(foot_in_material))
	var actual_shadow: Vector2 = puppet._drop_shadow.global_position
	var light_offset: Vector2 = puppet.global_transform.basis_xform(JunkPuppet.SHADOW_LIGHT * maxf(puppet._lift_height, 0.0))
	var floor_contact: Vector2 = puppet.to_global(puppet._ground_foot)
	var centroid: Vector2 = puppet._project_cardboard(puppet._art_centroid + puppet._body.offset)
	assert(actual_shadow.distance_to(puppet._shadow.to_global(centroid)) < 0.01, "The diffuse footprint must share the original mask's center throughout pickup")
	if puppet._shadow_lift >= 0.99:
		assert((actual_shadow - light_offset).distance_to(floor_contact) < 0.01, "The carried shadow must project from the floor anchor using the fixed light direction")
		assert(absf(actual_shadow.x - light_offset.x - visible_foot.x) < 0.01, "The shadow's floor X must follow the rendered body and its spring lag")
	if puppet._lift_height > 15.0:
		assert(actual_shadow.y > visible_foot.y, "Lifting the body must open a gap above its floor shadow")


func _mouse_button(point: Vector2, pressed: bool, button: MouseButton = MOUSE_BUTTON_LEFT) -> void:
	var event := InputEventMouseButton.new()
	event.position = point
	event.global_position = point
	event.button_index = button
	event.pressed = pressed
	root.push_input(event)


func _mouse_motion(point: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.position = point
	event.global_position = point
	event.button_mask = MOUSE_BUTTON_MASK_LEFT
	root.push_input(event)
