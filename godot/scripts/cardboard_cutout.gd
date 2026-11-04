class_name JunkCardboardCutout
extends RefCounted
## Immutable, bounded shared art preparation. No image reads or mesh rebuilds in pose().

const MAX_SIZE: int = 512
const MAX_ART_SIZE: int = 2048
const CACHE_LIMIT: int = 24
static var _cache: Dictionary = {}


static func prepare(source: Texture2D, paper_rim: int = -1) -> Dictionary:
	var key: String = str(source.get_instance_id()) + ":" + str(paper_rim)
	if _cache.has(key): return _cache[key]
	var image: Image = source.get_image()
	if image == null or image.is_empty(): return {}
	if image.is_compressed(): image.decompress()
	image.convert(Image.FORMAT_RGBA8)
	# Keep print resolution independent of the inexpensive contour preparation.
	var art_ratio: float = minf(1.0, float(MAX_ART_SIZE) / maxf(image.get_width(), image.get_height()))
	if art_ratio < 1.0:
		image.resize(maxi(1, roundi(image.get_width() * art_ratio)), maxi(1, roundi(image.get_height() * art_ratio)), Image.INTERPOLATE_LANCZOS)
	var art_size := image.get_size()
	var rim: int = maxi(2, roundi(maxi(art_size.x, art_size.y) * 0.019))
	if paper_rim >= 0: rim = maxi(2, paper_rim)
	var padding: int = rim + 2
	var size: Vector2i = art_size + Vector2i.ONE * padding * 2
	var padded := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
	padded.blit_rect(image, Rect2i(Vector2i.ZERO, art_size), Vector2i.ONE * padding)
	var mask_image: Image = padded.duplicate()
	var ratio: float = minf(1.0, float(MAX_SIZE) / maxf(size.x, size.y))
	var mask_size := Vector2i(maxi(1, roundi(size.x * ratio)), maxi(1, roundi(size.y * ratio)))
	if ratio < 1.0: mask_image.resize(mask_size.x, mask_size.y, Image.INTERPOLATE_LANCZOS)
	var mask_rim: int = maxi(1, roundi(rim * ratio))
	var mask := BitMap.new()
	mask.create_from_image_alpha(mask_image, 0.18)
	mask.grow_mask(mask_rim, Rect2i(Vector2i.ZERO, mask_size))
	var inner_mask := BitMap.new()
	inner_mask.create_from_image_alpha(mask_image, 0.18)
	inner_mask.grow_mask(maxi(0, mask_rim - 1), Rect2i(Vector2i.ZERO, mask_size))
	var contours: Array[PackedVector2Array] = mask.opaque_to_polygons(Rect2i(Vector2i.ZERO, mask_size), 0.65)
	# Bake the stock under the print; preserve the original artwork's antialiasing.
	var stock := Color("ead8b6")
	var outer_gray: Image = _gray(mask)
	# Painted with native blits rather than a per-texel script loop; the result is identical.
	# Most of the time here goes to the two grow_mask calls above, not to painting.
	var face := Image.create(mask_size.x, mask_size.y, false, Image.FORMAT_RGBA8)
	# Colored transparent texels avoid a black fringe in filtered mip levels.
	face.fill(Color(stock, 0.0))
	var layer := Image.create(mask_size.x, mask_size.y, false, Image.FORMAT_RGBA8)
	layer.fill(Color("b18a58"))
	face.blit_rect_mask(layer, _alpha_mask(outer_gray), Rect2i(Vector2i.ZERO, mask_size), Vector2i.ZERO)
	layer.fill(stock)
	face.blit_rect_mask(layer, _alpha_mask(_gray(inner_mask)), Rect2i(Vector2i.ZERO, mask_size), Vector2i.ZERO)
	# The shadow only needs the silhouette's mean and spread, so a sparse grid is plenty.
	var bits: PackedByteArray = outer_gray.get_data()
	var stride: int = maxi(1, floori(mini(mask_size.x, mask_size.y) / 96.0))
	var mass: float = 0.0
	var first_moment := Vector2.ZERO
	var second_moment := Vector2.ZERO
	for y: int in range(stride >> 1, mask_size.y, stride):
		var row: int = y * mask_size.x
		for x: int in range(stride >> 1, mask_size.x, stride):
			if bits[row + x] != 0:
				var sample_point := Vector2(x + 0.5, y + 0.5) * Vector2(size) / Vector2(mask_size)
				mass += 1.0
				first_moment += sample_point
				second_moment += sample_point * sample_point
	var centroid: Vector2 = first_moment / maxf(mass, 1.0)
	var variance: Vector2 = second_moment / maxf(mass, 1.0) - centroid * centroid
	if mask_size != size: face.resize(size.x, size.y, Image.INTERPOLATE_LANCZOS)
	face.blend_rect(padded, Rect2i(Vector2i.ZERO, size), Vector2i.ZERO)
	face.generate_mipmaps()
	var result: Dictionary = {
		"source": source, "texture": ImageTexture.create_from_image(face),
		"mesh": _edge_mesh(contours, Vector2(size) * 0.5, Vector2(size) / Vector2(mask_size), 512.0 / maxf(art_size.x, art_size.y)),
		"art_size": Vector2(art_size), "padding": float(padding),
		"foot": float(image.get_used_rect().end.y + padding),
		"centroid": centroid - Vector2(size) * 0.5,
		"variance": variance,
	}
	if _cache.size() >= CACHE_LIMIT: _cache.erase(_cache.keys()[0])
	_cache[key] = result
	return result


## One byte per texel, 255 where the bit is set.
static func _gray(bits: BitMap) -> Image:
	var gray: Image = bits.convert_to_image()
	if gray.get_format() != Image.FORMAT_L8: gray.convert(Image.FORMAT_L8)
	return gray


## The same coverage as alpha, for blit_rect_mask. Doubling the width by nearest neighbour
## repeats every byte, and those pairs read back as luminance-alpha texels.
static func _alpha_mask(gray: Image) -> Image:
	var size: Vector2i = gray.get_size()
	var doubled: Image = gray.duplicate()
	doubled.resize(size.x * 2, size.y, Image.INTERPOLATE_NEAREST)
	return Image.create_from_data(size.x, size.y, false, Image.FORMAT_LA8, doubled.get_data())


static func _edge_mesh(contours: Array[PackedVector2Array], center: Vector2, contour_scale: Vector2, flute_scale: float) -> ArrayMesh:
	var vertices := PackedVector2Array()
	var colors := PackedColorArray()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for contour: PackedVector2Array in contours:
		if contour.size() < 3: continue
		var distance: float = 0.0
		var clockwise: bool = Geometry2D.is_polygon_clockwise(contour)
		for i: int in range(contour.size()):
			var a: Vector2 = contour[i] * contour_scale
			var b: Vector2 = contour[(i + 1) % contour.size()] * contour_scale
			var tangent: Vector2 = (b - a).normalized()
			var normal := Vector2(tangent.y, -tangent.x)
			if clockwise: normal = -normal
			var normal_color := Color(normal.x * 0.5 + 0.5, normal.y * 0.5 + 0.5, 0, 1)
			var start: int = vertices.size()
			vertices.append_array(PackedVector2Array([a - center, a - center, b - center, b - center]))
			colors.append_array(PackedColorArray([normal_color, normal_color, normal_color, normal_color]))
			var end: float = distance + a.distance_to(b) * flute_scale
			uvs.append_array(PackedVector2Array([Vector2(distance, 0), Vector2(distance, 1), Vector2(end, 0), Vector2(end, 1)]))
			indices.append_array(PackedInt32Array([start, start + 1, start + 2, start + 2, start + 1, start + 3]))
			distance = end
	var mesh := ArrayMesh.new()
	if not vertices.is_empty():
		var arrays: Array = []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = vertices
		arrays[Mesh.ARRAY_COLOR] = colors
		arrays[Mesh.ARRAY_TEX_UV] = uvs
		arrays[Mesh.ARRAY_INDEX] = indices
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
