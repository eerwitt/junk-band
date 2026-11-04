shader_type canvas_item;
render_mode unshaded, blend_mix;
// Antialiased ink strokes and paper chips drawn as plain quads, which would otherwise
// alias because the stage has no MSAA. UV runs -1..1 across each axis of the shape.

varying vec4 tint;

void vertex() {
	tint = COLOR;
}

void fragment() {
	vec2 feather = fwidth(UV) * 1.3 + vec2(0.001);
	vec2 cover = 1.0 - smoothstep(vec2(1.0) - feather, vec2(1.0), abs(UV));
	COLOR = vec4(tint.rgb, tint.a * cover.x * cover.y);
}
