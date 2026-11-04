shader_type canvas_item;
render_mode unshaded, blend_mix;
// Dry-brush smear deposited on the paper. UV.x is arc length in world units along
// the route, UV.y is -1..1 across it. Vertex colour packs: r pressure, g life, b seed.

uniform vec3 graphite = vec3(0.27, 0.18, 0.10);
uniform vec3 powder = vec3(0.62, 0.46, 0.28);
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

void vertex() {
	packed = COLOR;
}

void fragment() {
	float pressure = packed.r;
	float life = packed.g;
	float seed = packed.b * 37.0;
	float across = UV.y;
	float along = UV.x;
	// Long fibres dragged through the powder, plus coarser skips where contact chatters.
	float fibres = noise(vec2(along * 0.03 + seed, across * 9.5 + seed)) * 0.55;
	fibres += noise(vec2(along * 0.085 - seed, across * 21.0)) * 0.45;
	float chatter = noise(vec2(along * 0.14 + seed, across * 1.6 + seed * 0.5));
	float grit = noise(vec2(along * 1.1, across * 26.0) + seed);
	float edge = abs(across) + (noise(vec2(along * 0.11, sign(across) * 3.0 + seed)) - 0.5) * 0.3;
	float body = 1.0 - smoothstep(0.42, 1.02, edge);
	// Twin heel-dug tracks read as weight even on characters with no visible feet.
	float tracks = exp(-pow((abs(across) - 0.42) / 0.2, 2.0));
	float threshold = mix(0.68, 0.36, pressure);
	threshold += (1.0 - life) * 0.8;
	float cover = smoothstep(threshold, threshold + 0.26, fibres * 0.72 + chatter * 0.2 + grit * 0.12 + tracks * 0.14);
	float core = smoothstep(threshold + 0.16, threshold + 0.5, fibres + tracks * 0.18);
	vec3 tone = mix(powder, graphite, core * 0.4);
	float haze = (1.0 - smoothstep(0.2, 1.0, edge)) * 0.07 * pressure;
	float alpha = max(cover * body * mix(0.2, 0.36, core), haze) * smoothstep(0.0, 0.3, life);
	COLOR = vec4(tone, alpha);
}
