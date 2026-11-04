shader_type canvas_item;
render_mode unshaded;

uniform float yaw = -0.28;
uniform float thickness = 16.0;
uniform vec2 blur_x = vec2(0.0);
uniform vec2 blur_y = vec2(0.0);
uniform float joint_angle = 0.0;
uniform vec2 joint_pivot = vec2(0.0);
varying vec4 shadow_tint;

void vertex() {
	shadow_tint = COLOR;
	float j = cos(joint_angle), k = sin(joint_angle);
	VERTEX = mat2(vec2(j, k), vec2(-k, j)) * (VERTEX - joint_pivot) + joint_pivot;
	float c = cos(yaw);
	VERTEX.x = VERTEX.x * c + sin(yaw) * sign(c) * thickness * 0.5;
}

void fragment() {
	float coverage = texture(TEXTURE, UV).a;
	if (length(blur_x) + length(blur_y) > 0.000001) {
		coverage *= 0.25;
		coverage += texture(TEXTURE, UV + blur_x).a * 0.125;
		coverage += texture(TEXTURE, UV - blur_x).a * 0.125;
		coverage += texture(TEXTURE, UV + blur_y).a * 0.125;
		coverage += texture(TEXTURE, UV - blur_y).a * 0.125;
		coverage += texture(TEXTURE, UV + blur_x + blur_y).a * 0.0625;
		coverage += texture(TEXTURE, UV + blur_x - blur_y).a * 0.0625;
		coverage += texture(TEXTURE, UV - blur_x + blur_y).a * 0.0625;
		coverage += texture(TEXTURE, UV - blur_x - blur_y).a * 0.0625;
	}
	COLOR = vec4(shadow_tint.rgb, shadow_tint.a * coverage);
}
