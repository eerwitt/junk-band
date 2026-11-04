shader_type canvas_item;
render_mode unshaded;

uniform float yaw = -0.28;
uniform float thickness = 16.0;
uniform float character_seed = 0.0;
uniform vec2 pivot_offset = vec2(0.0);
uniform float joint_angle = 0.0;
uniform vec2 joint_pivot = vec2(0.0);
varying float facing;
varying float opacity;
varying float edge_light;

void vertex() {
	// UV.y stores depth; UV.x stores continuous distance along the cut edge.
	vec2 normal = COLOR.rg * 2.0 - 1.0;
	float j = cos(joint_angle), k = sin(joint_angle);
	mat2 joint = mat2(vec2(j, k), vec2(-k, j));
	normal = joint * normal;
	facing = -sin(yaw) * normal.x;
	edge_light = 0.77 + dot(normal, normalize(vec2(-0.6, -0.8))) * 0.18;
	opacity = COLOR.a;
	VERTEX += pivot_offset;
	VERTEX = joint * (VERTEX - joint_pivot) + joint_pivot;
	VERTEX.x = VERTEX.x * cos(yaw) + sin(yaw) * (UV.y - 0.5) * thickness;
}

void fragment() {
	if (facing <= 0.0001) { discard; }
	float depth = UV.y;
	float phase = UV.x * 0.65 + character_seed;
	float wave = 0.5 + 0.31 * sin(phase);
	float footprint = clamp(fwidth(depth) * 0.5, 0.008, 0.10);
	float flute = 1.0 - smoothstep(0.045, 0.045 + footprint, abs(depth - wave));
	// Average unresolved flutes along the cut, rather than smearing the liners across depth.
	float resolved = 1.0 - smoothstep(0.6, 2.2, fwidth(phase));
	flute = mix(0.35, flute, resolved);
	float liners = smoothstep(0.10, 0.10 + footprint, depth) * (1.0 - smoothstep(0.90 - footprint, 0.90, depth));
	vec3 cavity = vec3(0.29, 0.20, 0.12);
	vec3 kraft = vec3(0.69, 0.51, 0.31);
	vec3 edge = mix(kraft, mix(cavity, kraft * 0.9, flute), liners);
	COLOR = vec4(edge * edge_light, opacity);
}
