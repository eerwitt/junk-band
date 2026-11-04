class_name JunkCardboardStyle
extends StyleBox

var paper: Color = Color("eee4cf")
var ink: Color = Color(0.27, 0.22, 0.16, 0.70)
var pressed: bool = false


func _init() -> void:
	content_margin_left = 13
	content_margin_right = 13
	content_margin_top = 10
	content_margin_bottom = 10


func _draw(canvas: RID, rect: Rect2) -> void:
	var points := PackedVector2Array()
	var corners: Array[Vector2] = [Vector2(0.025, 0.07), Vector2(0.47, 0.015), Vector2(0.975, 0.04), Vector2(1, 0.80), Vector2(0.96, 0.96), Vector2(0.44, 1), Vector2(0.01, 0.93), Vector2(0, 0.22)]
	for corner: Vector2 in corners:
		points.append(rect.position + corner * rect.size + Vector2(0, 2 if pressed else 0))
	if paper.a > 0.0:
		for layer: int in range(3):
			var shadow := PackedVector2Array()
			var depth: float = float(3 - layer) * (0.7 if pressed else 1.7)
			for point: Vector2 in points:
				shadow.append(point + Vector2(1.2, depth))
			RenderingServer.canvas_item_add_polygon(canvas, shadow, PackedColorArray([Color(0.29, 0.23, 0.15, 0.025 + layer * 0.018)]))
		RenderingServer.canvas_item_add_polygon(canvas, points, PackedColorArray([paper]))
	points.append(points[0])
	RenderingServer.canvas_item_add_polyline(canvas, points, PackedColorArray([ink]), 1.2, true)
