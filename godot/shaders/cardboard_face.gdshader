shader_type canvas_item;
render_mode unshaded;

// Object-space coordinates keep the fibres attached during carry, scale and turns.
uniform float yaw = -0.28;
uniform float thickness = 16.0;
uniform float character_seed = 0.0;
uniform float grain_strength : hint_range(0.0, 0.1) = 0.04;
uniform float back_print : hint_range(0.0, 1.0) = 1.0;
uniform float joint_angle = 0.0;
uniform vec2 joint_pivot = vec2(0.0);
varying vec4 tint;

float fibre_hash(vec2 p) {
	vec3 q = fract(vec3(p.xyx) * 0.1031);
	q += dot(q, q.yzx + 33.33 + character_seed);
	return fract((q.x + q.y) * q.z);
}

void vertex() {
	tint = COLOR;
	float j = cos(joint_angle), k = sin(joint_angle);
	VERTEX = mat2(vec2(j, k), vec2(-k, j)) * (VERTEX - joint_pivot) + joint_pivot;
	float c = cos(yaw);
	VERTEX.x = VERTEX.x * c + sin(yaw) * sign(c) * thickness * 0.5;
}

void fragment() {
	vec4 art = texture(TEXTURE, UV);
	// Keep one antialiased cut edge instead of a broad filtered-alpha halo.
	float edge_aa = clamp(fwidth(art.a) * 0.55, 0.035, 0.25);
	art.a = smoothstep(0.5 - edge_aa, 0.5 + edge_aa, art.a);
	vec2 texel = UV / TEXTURE_PIXEL_SIZE;
	float grain = fibre_hash(floor(texel * vec2(0.7, 1.8))) - 0.5;
	// Fade microscopic detail under minification instead of letting it sparkle.
	float detail = 1.0 - smoothstep(1.0, 3.5, max(length(dFdx(texel)), length(dFdy(texel))));
	float mottling = sin(texel.x * 0.043 + character_seed) * sin(texel.y * 0.037 - character_seed);
	float light = 0.96 + 0.04 * abs(cos(yaw)) + 0.025 * sin(yaw);
	vec3 paper = vec3(0.76, 0.63, 0.44);
	float print_amount = cos(yaw) < 0.0 ? back_print : 1.0;
	vec3 face = mix(paper, art.rgb, print_amount);
	face *= light + grain * grain_strength * detail + mottling * 0.008;
	COLOR = vec4(face, art.a) * tint;
}
