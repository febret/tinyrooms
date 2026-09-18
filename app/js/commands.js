export const COMMANDS = [
  { name: ".help", summary: "Show common commands." },
  { name: ".look", summary: "Describe the current selection." },
  { name: ".go @way:<id>", summary: "Move through a room exit." },
  { name: ".say <text>", summary: "Speak in the room." },
  { name: ".inspect @card:<id>", summary: "Inspect a prop or card." },
  { name: ".pickup @card:<stack> <qty>", summary: "Pick up a room stack quantity." },
  { name: ".drop @card:<stack> <qty>", summary: "Drop an owned stack quantity." },
  { name: ".favorite @card:<id>", summary: "Toggle a favorite core card." },
  { name: ".play <activity>", summary: "Open a room or account activity." },
  { name: ".cancel", summary: "Cancel targeting or a pending interaction." },
];

/** Quote user-provided text so it survives the command tokenizer. */
function quote(text) {
  return `"${String(text ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Convert chat input into the command-string pipeline expected by the server. */
export function chatToCommand(input) {
  const text = String(input || "").trim();
  if (!text) return "";
  return text.startsWith(".") || text.startsWith("\\") ? text : `.say ${quote(text)}`;
}

/** Build a `.favorite` command for a core or stack card identifier. */
export function buildFavoriteCommand(cardId) {
  return `.favorite @card:${cardId}`;
}

/** Build a pickup/drop command from a quantity-dialog intent. */
export function buildQuantityCommand(intent, stackId, quantity) {
  const verb = intent === "pickup" ? "pickup" : "drop";
  return `.${verb} @card:${stackId} ${Math.max(1, Number(quantity || 1))}`;
}
