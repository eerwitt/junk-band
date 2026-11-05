extends SceneTree

## The rhythm card: how long it is, what it shows, and what punching, ready-made cards, lengths
## and tapping send back.


func _initialize() -> void:
	_run.call_deferred()


func _repeat(card: Array, bars: int) -> Array:
	var steps: Array = []
	for repeat: int in range(JunkLoopTiming.STEPS / (bars * 16)):
		for step: int in card: steps.append(repeat * bars * 16 + step)
	steps.sort()
	return steps


func _run() -> void:
	var menu := JunkPerformerMenu.new()
	root.add_child(menu)
	menu.size = Vector2(1200, 900)
	menu.reduced_motion = true
	var patches: Array = []
	menu.changed.connect(func(_id: String, patch: Dictionary) -> void: patches.append(patch))
	# A clap on the second bar of every two: a two-bar card, shown as it is.
	var clap: Array = _repeat([28], 2)
	var performer: Dictionary = {"id": "clap", "gainDb": -12.0, "rate": 1.0, "pan": 0.0, "mode": "repeat_hits", "exit": "fade", "path": [], "steps": clap}
	assert(JunkPerformerMenu.card_bars_of(clap) == 2)
	assert(JunkPerformerMenu.card_bars_of(_repeat([0, 4], 1)) == 1)
	assert(JunkPerformerMenu.card_bars_of([JunkLoopTiming.STEPS - 2]) == JunkLoopTiming.BARS, "A hit once a song is a whole-song card")
	menu.open_for(performer, Vector2(600, 300))
	assert(menu._card_bars == 2 and menu._holes.bars == 2)
	assert(menu._holes.pattern.keys() == [28], "The card shows the hit where it is, on bar two")
	assert(patches.is_empty(), "Opening the card changes nothing")
	# Longer: the same song, now with room to change bars three and four.
	menu._set_card_bars(4)
	assert(patches.back().cardBars == 4 and patches.back().steps == clap, "A longer card repeats itself, so nothing changes")
	menu._toggle_step(3 * 16 + 4)
	var punched: Array = patches.back().steps
	assert(patches.back().cardBars == 4 and punched == _repeat([28, 60, 52], 4))
	# A ready-made card fills every bar of this one.
	menu._set_ready_made(JunkPerformerMenu.RHYTHM_CARDS["Steady"])
	assert(patches.back().steps == _repeat([0, 4, 8, 12], 1) and patches.back().cardBars == 4, "The card keeps its length")
	# Teaching it by tapping: the first tap starts again, wherever in the four bars it lands.
	menu._last_tap_ms = -1000000
	menu.beat = 9.0
	menu._tap()
	assert(patches.back().steps == _repeat([36], 4))
	assert(menu._holes.page == 0)
	menu.beat = 14.0
	menu._tap()
	assert(patches.back().steps == _repeat([36, 56], 4), "Taps soon after each other build one phrase")
	# Shorter keeps the first bars.
	menu._set_card_bars(1)
	assert(patches.back().steps == _repeat([0], 1), "Nothing in the first bar, so it keeps a downbeat")
	# A whole-song card shows four bars at a time and turns with the song.
	menu._set_card_bars(JunkLoopTiming.BARS)
	var card: JunkPunchCard = menu._holes
	assert(card.pages() == JunkLoopTiming.BARS / 4 and card.rows() == 4)
	card.playing = true
	card.beat = 4.0 * 13.0 + 1.0
	card._process(0.016)
	card._turned_at = -100.0
	card._process(0.016)
	assert(card.page == 3, "Bar fourteen is on the fourth page")
	card.turn_to(0)
	card.beat = 4.0 * 20.0
	card._process(0.016)
	assert(card.page == 0, "A page you turned to stays a moment")
	# Phrase mode explains itself.
	performer.mode = "phrase"
	performer.steps = _repeat([0], 2)
	performer.cardBars = 2
	menu.sync(performer)
	assert(menu._mode.selected == JunkPerformerMenu.MODES.find("phrase"))
	assert(menu._card_hint.text.contains("whole sound"))
	assert(menu._holes.phrase, "The card shows where the phrase is heard")
	performer.mode = "repeat_hits"
	menu.sync(performer)
	assert(not menu._holes.phrase)
	print("Card regression passed: card lengths, true patterns, longer and shorter cards, ready-made cards, tapped phrases, page turns and phrase mode")
	quit()
