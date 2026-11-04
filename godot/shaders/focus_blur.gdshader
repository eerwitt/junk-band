shader_type canvas_item;
render_mode unshaded;

uniform sampler2D screen_texture : hint_screen_texture, repeat_disable, filter_linear;

void fragment() {
	float distance_from_center = length((UV - vec2(0.5)) * 2.0);
	float feather = 1.0 - smoothstep(0.65, 1.0, distance_from_center);
	if (feather < 0.001) {
		discard;
	}
	// Bilinear pairs evaluate a continuous 5x5 Gaussian in nine texture reads.
	vec2 step_uv = SCREEN_PIXEL_SIZE * 1.2;
	vec3 blurred = texture(screen_texture, SCREEN_UV).rgb * 0.140625;
	blurred += texture(screen_texture, SCREEN_UV + vec2(step_uv.x, 0.0)).rgb * 0.1171875;
	blurred += texture(screen_texture, SCREEN_UV - vec2(step_uv.x, 0.0)).rgb * 0.1171875;
	blurred += texture(screen_texture, SCREEN_UV + vec2(0.0, step_uv.y)).rgb * 0.1171875;
	blurred += texture(screen_texture, SCREEN_UV - vec2(0.0, step_uv.y)).rgb * 0.1171875;
	blurred += texture(screen_texture, SCREEN_UV + step_uv).rgb * 0.09765625;
	blurred += texture(screen_texture, SCREEN_UV - step_uv).rgb * 0.09765625;
	blurred += texture(screen_texture, SCREEN_UV + vec2(step_uv.x, -step_uv.y)).rgb * 0.09765625;
	blurred += texture(screen_texture, SCREEN_UV + vec2(-step_uv.x, step_uv.y)).rgb * 0.09765625;
	COLOR = vec4(mix(blurred, vec3(0.968, 0.960, 0.925), 0.12), feather * 0.94);
}
