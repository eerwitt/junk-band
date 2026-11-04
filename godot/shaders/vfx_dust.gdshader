shader_type canvas_item;
render_mode unshaded, blend_mix;
// One billowing puff per quad. Vertex colour packs: r seed, g life, b tone, a density.
// Puffs dissolve by eroding a noise height field, so they never just alpha-fade.

uniform vec3 lit_tone = vec3(0.90, 0.81, 0.66);
uniform vec3 body_tone = vec3(0.71, 0.56, 0.38);
uniform vec3 shade_tone = vec3(0.43, 0.31, 0.19);
varying vec4 packed;

float hash(vec2 p) {
	p = fract(p * vec2(123.34, 456.21));
	p += dot(p, p + 45.32);
	return fract(p.x * p.y);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

float fbm(vec2 p) {
	float total = noise(p) * 0.55;
	p = mat2(vec2(0.8, 0.6), vec2(-0.6, 0.8)) * p * 2.03 + 11.0;
	total += noise(p) * 0.30;
	p = mat2(vec2(0.8, 0.6), vec2(-0.6, 0.8)) * p * 2.01 + 5.0;
	return total + noise(p) * 0.15;
}

void vertex() {
	packed = COLOR;
}

void fragment() {
	float seed = packed.r * 61.0;
	float life = packed.g;
	vec2 q = UV;
	float d = length(q);
	vec2 warp = vec2(fbm(q * 1.7 + seed), fbm(q * 1.7 - seed + 9.0)) - 0.5;
	float cloud = fbm(q * 2.6 + warp * 1.4 + seed + life * 0.6);
	float height = (1.0 - d * d) * 0.85 + (cloud - 0.5) * mix(0.5, 1.1, life);
	float erode = mix(0.02, 0.92, pow(life, 1.25));
	float soft = mix(0.16, 0.62, life);
	float alpha = smoothstep(erode, erode + soft, height) * smoothstep(1.0, 0.82, d);
	// Sun sits upper-left, matching the projected direction of the stage shadows.
	vec2 facing = q + warp * 0.9;
	float lit = 0.5 + 0.62 * dot(facing, vec2(-0.62, -0.78)) + (cloud - 0.5) * 0.7;
	lit = clamp(lit, 0.0, 1.0);
	vec3 tone = lit < 0.5 ? mix(shade_tone, body_tone, lit * 2.0) : mix(body_tone, lit_tone, lit * 2.0 - 1.0);
	tone = mix(tone, shade_tone, packed.b * 0.45);
	COLOR = vec4(tone, alpha * packed.a);
}
