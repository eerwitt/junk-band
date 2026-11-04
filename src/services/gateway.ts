import { z } from "zod";

const base = (window.JUNK_CONFIG?.apiBase ?? "/api").replace(/\/$/, "");
const healthSchema = z.object({
  mode: z.enum(["mock", "live"]),
  sam: z.boolean(),
  audio: z.boolean(),
  image: z.boolean().default(false),
});
export type Health = z.infer<typeof healthSchema>;
export const mediaSchema = z.object({
  id: z.string(),
  duration_s: z.number(),
  width: z.number(),
  height: z.number(),
  audio_present: z.boolean(),
  filename: z.string(),
});
export type Media = z.infer<typeof mediaSchema>;
const jobSchema = z.object({
  id: z.string(),
  queue_position: z.number().optional(),
  status: z.enum(["queued", "processing", "ready", "failed"]),
  stage: z.enum(["sending", "separating", "collecting"]).nullable().optional(),
  error: z.string().nullable(),
  target_url: z.string().nullable(),
  residual_url: z.string().nullable(),
  provenance: z.string(),
  metrics: z.record(z.string(), z.union([z.number(), z.string()])),
});
export type Job = z.infer<typeof jobSchema>;
const characterJobSchema = z.object({
  id: z.string(),
  queue_position: z.number().optional(),
  status: z.enum(["queued", "processing", "ready", "failed"]),
  stage: z.enum(["painting", "cutting", "rigging", "ready"]),
  source_cutout_url: z.string(),
  character_url: z.string().nullable(),
  error: z.string().nullable(),
  provenance: z.string(),
  rig: z
    .object({
      width: z.number().int().min(1).max(2048),
      height: z.number().int().min(1).max(2048),
      body_url: z.string(),
      parts: z
        .array(
          z.object({
            name: z.enum(["left_arm", "right_arm", "left_leg", "right_leg"]),
            url: z.string(),
            pivot: z.tuple([
              z.number().min(0).max(1),
              z.number().min(0).max(1),
            ]),
            max_angle: z.number().positive().max(0.5),
          })
        )
        .length(4),
    })
    .nullable()
    .optional(),
});
export type CharacterJob = z.infer<typeof characterJobSchema>;
const cutoutSchema = z.object({
  cutout_id: z.string(),
  cutout_url: z.string(),
  mask_url: z.string().optional(),
  card_url: z.string().optional(),
  provenance: z.string(),
});
export type Cutout = z.infer<typeof cutoutSchema>;
const pickedSchema = z.object({
  cutout_id: z.string(),
  cutout_url: z.string(),
  mask_url: z.string(),
  card_url: z.string(),
  frame_s: z.number(),
  name: z.string(),
  sound: z.string(),
  sound_start_s: z.number(),
  sound_end_s: z.number(),
  provenance: z.string(),
});
export type Picked = z.infer<typeof pickedSchema>;

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    credentials: "include",
    signal: init?.signal ?? AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    const body = await response.text();
    let value: unknown = null;
    try {
      value = JSON.parse(body);
    } catch {
      value = null;
    }
    const parsed = z.object({ detail: z.unknown() }).safeParse(value);
    const detail = parsed.success ? parsed.data.detail : null;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Service returned ${response.status}. Check the gateway and retry.`
    );
  }
  return response.json();
}
function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
export const gateway = {
  health: async (): Promise<Health> =>
    healthSchema.parse(await request("/health")),
  upload: async (file: File, signal?: AbortSignal): Promise<Media> => {
    const data = new FormData();
    data.append("file", file);
    return mediaSchema.parse(
      await request("/media", {
        method: "POST",
        body: data,
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(120000)])
          : AbortSignal.timeout(120000),
      })
    );
  },
  pick: async (
    mediaId: string,
    frameS: number,
    box: number[] | null,
    concept: string | null,
    startS: number,
    endS: number
  ): Promise<Picked> =>
    pickedSchema.parse(
      await request("/selections", {
        ...json({
          media_id: mediaId,
          frame_s: frameS,
          box,
          concept,
          start_s: startS,
          end_s: endS,
        }),
        signal: AbortSignal.timeout(180000),
      })
    ),
  maskCutout: async (
    mediaId: string,
    frameS: number,
    mask: Blob,
    baseCutoutId?: string
  ): Promise<Cutout> => {
    const form = new FormData();
    form.append("file", mask, "mask.png");
    form.append("frame_s", String(frameS));
    if (baseCutoutId) form.append("base_cutout_id", baseCutoutId);
    return cutoutSchema.parse(
      await request(`/media/${encodeURIComponent(mediaId)}/mask`, {
        method: "POST",
        body: form,
        signal: AbortSignal.timeout(60000),
      })
    );
  },
  character: async (
    cutoutId: string,
    description: string,
    details: string
  ): Promise<CharacterJob> =>
    characterJobSchema.parse(
      await request(
        "/characters",
        json({ cutout_id: cutoutId, description, details })
      )
    ),
  characterJob: async (
    id: string,
    signal: AbortSignal
  ): Promise<CharacterJob> =>
    characterJobSchema.parse(
      await request(`/characters/${encodeURIComponent(id)}`, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(30000)]),
      })
    ),
  separate: async (
    mediaId: string,
    startS: number,
    endS: number,
    description: string
  ): Promise<Job> =>
    jobSchema.parse(
      await request(
        "/separate",
        json({ media_id: mediaId, start_s: startS, end_s: endS, description })
      )
    ),
  job: async (id: string, signal: AbortSignal): Promise<Job> =>
    jobSchema.parse(
      await request(`/jobs/${encodeURIComponent(id)}`, {
        signal: AbortSignal.any([signal, AbortSignal.timeout(30000)]),
      })
    ),
  assetUrl: (path: string): string =>
    path.startsWith("/") ? `${base}${path}` : path,
  blob: async (path: string): Promise<Blob> => {
    const response = await fetch(gateway.assetUrl(path), {
      credentials: "include",
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok)
      throw new Error("Could not fetch the generated asset. Retry the job.");
    return response.blob();
  },
};
