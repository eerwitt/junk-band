import type { Project } from "../domain/project";
import { motionSchema, projectSchema } from "../domain/project";
import { transformSteps, compileEvents } from "../domain/music";
import type { Proposal } from "./gateway";
import { loopSteps } from "../domain/timing";

export function previewProposal(project: Project, proposal: Proposal): Project {
  const next = structuredClone(project);
  for (const action of proposal.actions) {
    const p = next.performers.find((p) => p.id === action.performerId);
    if (!p)
      throw new Error("Suggestion refers to a performer outside this scene.");
    if (action.kind === "set_motion")
      p.motion = motionSchema.parse(action.value);
    else if (action.kind === "set_gain_db") {
      if (
        typeof action.value !== "number" ||
        action.value < -30 ||
        action.value > -3
      )
        throw new Error("Suggested gain is outside the safe range.");
      p.gainDb = action.value;
    } else {
      if (
        !["offbeat_echo", "mirror", "halve", "fill"].includes(
          String(action.value)
        )
      )
        throw new Error("Unknown rhythm operation.");
      p.steps = transformSteps(
        p.steps,
        action.value as Parameters<typeof transformSteps>[1]
      );
    }
  }
  projectSchema.parse(next);
  const events = compileEvents(next);
  if (!events.length)
    throw new Error("This suggestion would silence the scene.");
  if (
    Array.from(
      { length: loopSteps },
      (_, step) => events.filter((e) => e.step === step).length
    ).some((n) => n > 12)
  )
    throw new Error("This suggestion is too dense.");
  return next;
}
