const TOKEN_PATTERN = /"([^"\\]|\\.)*"|'([^'\\]|\\.)*'|[^\s]+/g;

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
export function quote(text) {
  return `"${String(text ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Tokenize the milestone command grammar with single or double quotes. */
export function tokenize(commandText) {
  const input = String(commandText || "").trim();
  if (!input) return [];
  return [...input.matchAll(TOKEN_PATTERN)].map(match => {
    const token = match[0];
    if ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'"))) {
      return token.slice(1, -1).replace(/\\(["'\\])/g, "$1");
    }
    return token;
  });
}

/** Parse typed milestone target tokens like @card:stack-1 or @sunbeam. */
export function parseTargetToken(token) {
  const value = String(token || "");
  if (!value.startsWith("@")) return null;
  if (!value.includes(":")) return { type: "username", id: value.slice(1) };
  const [type, ...rest] = value.slice(1).split(":");
  return { type, id: rest.join(":") };
}

/** Convert chat input into the command-string pipeline expected by the server. */
export function chatToCommand(input) {
  const text = String(input || "").trim();
  if (!text) return "";
  return text.startsWith(".") || text.startsWith("\\") ? text : `.say ${quote(text)}`;
}

/** Build a `.go` command for a room exit. */
export function buildGoCommand(wayId) {
  return `.go @way:${wayId}`;
}

/** Build a `.favorite` command for a core or stack card identifier. */
export function buildFavoriteCommand(cardId) {
  return `.favorite @card:${cardId}`;
}

/** Build a `.pickup` command for a room stack and quantity. */
export function buildPickupCommand(stackId, quantity) {
  return `.pickup @card:${stackId} ${Math.max(1, Number(quantity || 1))}`;
}

/** Build a `.drop` command for an owned stack and quantity. */
export function buildDropCommand(stackId, quantity) {
  return `.drop @card:${stackId} ${Math.max(1, Number(quantity || 1))}`;
}

/** Build a `.play` command for an activity or equipped card. */
export function buildPlayCommand(targetId) {
  return `.play ${targetId}`;
}
