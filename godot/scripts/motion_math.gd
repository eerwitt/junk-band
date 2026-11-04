class_name JunkMotionMath
extends RefCounted


static func closed_path(performer: Dictionary) -> Array:
	var path: Array = performer.get("path", [])
	if path.is_empty(): return []
	var home: Dictionary = performer.position
	var knots: Array = [{"beat": 0.0, "x": home.x, "y": home.y}]
	var last: float = float(path[-1].beat)
	var factor: float = minf(1.0, (JunkLoopTiming.BEATS - 4.0) / maxf(last, 0.001))
	for point: Dictionary in path:
		if float(point.beat) > 0.0:
			knots.append({"beat": float(point.beat) * factor, "x": point.x, "y": point.y})
	knots.append({"beat": JunkLoopTiming.BEATS, "x": home.x, "y": home.y})
	return knots


static func path_position(knots: Array, beat: float) -> Vector2:
	var b: float = fposmod(beat, JunkLoopTiming.BEATS)
	for index: int in range(knots.size() - 1):
		var a: Dictionary = knots[index]
		var z: Dictionary = knots[index + 1]
		if b < float(z.beat):
			var duration: float = float(z.beat) - float(a.beat)
			var t: float = (b - float(a.beat)) / duration
			return (2 * t * t * t - 3 * t * t + 1) * Vector2(a.x, a.y) + (t * t * t - 2 * t * t + t) * duration * _tangent(knots, index) + (-2 * t * t * t + 3 * t * t) * Vector2(z.x, z.y) + (t * t * t - t * t) * duration * _tangent(knots, index + 1)
	return Vector2(knots[0].x, knots[0].y)


static func _tangent(knots: Array, index: int) -> Vector2:
	if index == 0 or index == knots.size() - 1: return Vector2.ZERO
	var a: Dictionary = knots[index - 1]
	var z: Dictionary = knots[index + 1]
	return Vector2(float(z.x) - float(a.x), float(z.y) - float(a.y)) / (float(z.beat) - float(a.beat))


static func recorded_path(points: PackedVector2Array) -> Array:
	var distances: Array[float] = [0.0]
	for index: int in range(1, points.size()):
		distances.append(distances[-1] + points[index].distance_to(points[index - 1]))
	var total: float = maxf(distances[-1], 0.001)
	var result: Array = []
	for index: int in range(points.size()):
		if index > 0 and distances[index] - distances[index - 1] < 0.001: continue
		result.append({"beat": distances[index] / total * (JunkLoopTiming.BEATS - 8.0), "x": points[index].x, "y": points[index].y})
	return result


static func spring(position: Vector2, velocity: Vector2, target: Vector2, delta: float, elastic: bool = false, omega: float = 14.0) -> Array[Vector2]:
	if elastic:
		# Short weighted catch and a single small recoil, rather than a rubbery float.
		var damping: float = 18.0
		var frequency: float = 20.0
		var time: float = minf(delta, 0.1)
		var offset: Vector2 = position - target
		var oscillation: Vector2 = (velocity + damping * offset) / frequency
		var decay: float = exp(-damping * time)
		return [target + (offset * cos(frequency * time) + oscillation * sin(frequency * time)) * decay, (velocity * cos(frequency * time) - (damping * oscillation + frequency * offset) * sin(frequency * time)) * decay]
	# Exact critically damped spring: stable across frame rates and tab pauses.
	var offset: Vector2 = position - target
	var impulse: Vector2 = velocity + omega * offset
	var decay: float = exp(-omega * minf(delta, 0.1))
	var time: float = minf(delta, 0.1)
	return [target + (offset + impulse * time) * decay, (velocity - omega * impulse * time) * decay]
