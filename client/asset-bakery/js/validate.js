export const BAKE_TOOLS = ["image", "asset", "sound", "TEMPLATE"];
export const SIMPLIFY_STRATEGIES = ["auto", "decimate", "retopo"];

export function previewKind(output) {
  const suffix = String(output || "").toLowerCase().split(".").pop() || "";
  if (["glb", "gltf", "obj", "fbx"].includes(suffix)) return "model";
  if (["wav", "mp3", "ogg"].includes(suffix)) return "audio";
  return "image";
}

export function taskMatches(task, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;
  const haystack = `${task.label || ""} ${task.tool || ""} ${task.prompt || ""}`.toLowerCase();
  return haystack.includes(needle);
}

export function validateTaskDraft(task) {
  const errors = [];
  if (!task || typeof task !== "object") return ["Task must be an object."];
  if (!String(task.label || "").trim()) errors.push("Label is required.");
  if (!BAKE_TOOLS.includes(task.tool)) errors.push(`Tool must be one of ${BAKE_TOOLS.join(", ")}.`);
  if (task.tool !== "TEMPLATE" && !String(task.prompt || "").trim()) {
    errors.push("Prompt is required.");
  }
  if (task.tool !== "TEMPLATE" && !String(task.output || "").trim()) {
    errors.push("Output is required.");
  }
  const args = task.args || {};
  if (args.seed !== undefined && args.seed !== null && (!Number.isInteger(args.seed) || args.seed < 1)) {
    errors.push("Seed must be a positive integer.");
  }
  for (const key of ["width", "height"]) {
    const value = args[key];
    if (value !== undefined && value !== null && (!Number.isInteger(value) || value < 16 || value > 4096)) {
      errors.push(`${key} must be an integer between 16 and 4096.`);
    }
  }
  if (args.steps !== undefined && args.steps !== null && (!Number.isInteger(args.steps) || args.steps < 1 || args.steps > 150)) {
    errors.push("Steps must be an integer between 1 and 150.");
  }
  if (args.faces !== undefined && args.faces !== null && (!Number.isInteger(args.faces) || args.faces < 50 || args.faces > 20000)) {
    errors.push("Faces must be an integer between 50 and 20000.");
  }
  return errors;
}

export function normalizeTaskForSave(task) {
  const cleaned = { ...(task || {}) };
  delete cleaned._preview;
  cleaned.args = { ...(task?.args || {}) };
  for (const [key, value] of Object.entries(cleaned.args)) {
    if (value === "" || value === null) delete cleaned.args[key];
  }
  if (cleaned.simplify && typeof cleaned.simplify === "object" && Object.keys(cleaned.simplify).length === 0) {
    delete cleaned.simplify;
  }
  return cleaned;
}

export function tasksSnapshot(tasks, simplify) {
  return JSON.stringify({
    tasks: (tasks || []).map(normalizeTaskForSave),
    simplify: simplify || {},
  });
}
