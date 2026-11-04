import { z } from "zod";
import { projectSchema, type Project } from "../domain/project";
import { loadBlob, saveBlob } from "./database";

const bundleSchema = z.object({
  format: z.literal("junk-bundle-v1"),
  project: projectSchema,
  media: z
    .array(z.object({ id: z.string(), type: z.string(), data: z.string() }))
    .max(1024),
});

export async function exportBundle(project: Project): Promise<Blob> {
  const ids = new Set(
    project.assets
      .flatMap((a) => [
        a.audioId.startsWith("demo-") || a.audioId.startsWith("band-")
          ? ""
          : a.audioId,
        a.sprite.startsWith("blob:asset:") ? a.sprite.slice(11) : "",
        a.sourceSprite?.startsWith("blob:asset:")
          ? a.sourceSprite.slice(11)
          : "",
        ...(a.rig
          ? [a.rig.body, ...a.rig.parts.map((part) => part.sprite)].map((ref) =>
              ref.slice(11)
            )
          : []),
      ])
      .filter(Boolean)
  );
  const media: { id: string; type: string; data: string }[] = [];
  for (const id of ids) {
    const blob = await loadBlob(id);
    if (!blob)
      throw new Error(
        "Some project media is missing. Reimport it before saving a portable project."
      );
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
    media.push({ id, type: blob.type, data });
  }
  return new Blob(
    [JSON.stringify({ format: "junk-bundle-v1", project, media })],
    { type: "application/json" }
  );
}
export async function importBundle(file: File): Promise<Project> {
  if (file.size > 100 * 1024 * 1024)
    throw new Error("Project bundle must be under 100 MB.");
  const bundle = bundleSchema.parse(JSON.parse(await file.text()));
  for (const item of bundle.media) {
    if (!["audio/wav", "audio/x-wav", "image/png"].includes(item.type))
      throw new Error("Unsupported media in project bundle.");
    const bytes = Uint8Array.from(atob(item.data), (c) => c.charCodeAt(0));
    await saveBlob(item.id, new Blob([bytes], { type: item.type }));
  }
  return bundle.project;
}
