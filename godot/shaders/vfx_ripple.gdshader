shader_type canvas_item;
render_mode unshaded, blend_mix;
// The floor reacting to weight: a pressure wave embossed through the paper and the
// dent left behind. Vertex colour packs: r wave radius, g wave width, b dent, a wave.

uniform float seed = 0.0;
uniform vec3 ink = vec3(0.25, 0.16, 0.08);
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
	vec2 q = UV;
	float d = length(q);
	vec2 unit = q / max(d, 0.0001);
	float angle = atan(q.y, q.x);
	vec2 around = unit * 2.4 + seed;
	float wobble = (noise(around) - 0.5) * 0.09;
	float width = max(packed.g, 0.002);
	float x = (d + wobble * packed.r - packed.r) / width;
	// Derivative of a soft bump: leading crest catches light, trailing slope falls away.
	float slope = -x * exp(-x * x * 0.9) * 1.65;
	float facing = dot(unit, vec2(-0.62, -0.78));
	float relief = slope * (0.55 + 0.45 * facing);
	float wave = packed.a * (1.0 - smoothstep(0.86, 1.0, d));
	float occlusion = exp(-x * x * 0.55) * 0.3 * wave;
	float shadow = max(-relief, 0.0) * wave + occlusion;
	float light = max(relief, 0.0) * wave;

	// The dent: dark pressed centre whose edge erodes as the paper recovers.
	float dent = packed.b;
	float grain = noise(q * 15.0 + seed) * 0.6 + noise(q * 37.0 - seed) * 0.4;
	float bloom = 1.0 - smoothstep(0.03, 0.27, d + (grain - 0.5) * 0.12);
	float erosion = smoothstep(1.0 - dent, 1.0 - dent + 0.35, grain + bloom * 0.45);
	float pressed = bloom * erosion * mix(0.22, 0.62, dent);
	// Hairline creases pushed outward from the point of contact.
	float rays = noise(vec2(angle * 8.5 + seed, d * 1.3));
	float crease = smoothstep(0.035, 0.0, abs(rays - 0.5)) * smoothstep(0.07, 0.14, d) * (1.0 - smoothstep(0.2, 0.42, d));
	float creases = crease * erosion * 0.55 * smoothstep(0.1, 0.55, dent);

	float dark = clamp(shadow * 0.62 + pressed + creases, 0.0, 0.92);
	float bright = clamp(light * 0.82, 0.0, 0.85) * (1.0 - dark);
	float alpha = dark + bright;
	vec3 tone = mix(vec3(1.0, 0.985, 0.94), ink, dark / max(alpha, 0.001));
	COLOR = vec4(tone, alpha);
}
