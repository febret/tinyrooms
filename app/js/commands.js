export const COMMANDS = [
  { name: ".help", summary: "Show common commands." },
  { name: ".look", summary: "Describe the current selection." },
  { name: ".go @way:<id>", summary: "Move through a room exit." },
  { name: ".say <text>", summary: "Speak in the room." },
  { name: ".inspect @card:<id>", summary: "Inspect a prop or card." },
  { name: ".pickup @card:<stack> <qty>", summary: "Pick up a room stack quantity." },
  { name: ".drop @card:<stack> <qty> [x y z]", summary: "Drop an owned stack quantity, optionally at a board position." },
  { name: ".equip @card:<stack>", summary: "Equip an item or action stack." },
  { name: ".unequip @card:<stack>", summary: "Unequip an item or action stack." },
  { name: ".use @card:<stack> [target]", summary: "Use an equipped card, optionally on a target peep." },
  { name: ".emote @card:<id>", summary: "Play an owned emote." },
  { name: ".split @card:<stack> <qty>", summary: "Split a stack into a new unequipped stack." },
  { name: ".merge @card:<src> @card:<dst> [qty]", summary: "Merge two stacks of the same card." },
  { name: ".merge_all", summary: "Merge all identical inventory stacks." },
  { name: ".skill @card:<stack> <slot>", summary: "Slot a skill card into an unlocked slot." },
  { name: ".unskill <slot>", summary: "Remove a skill from a slot." },
  { name: ".level_up", summary: "Spend Kudos to reach the next level." },
  { name: ".claim_bops", summary: "Claim today's Daily Bops." },
  { name: ".buy_pack <pack> <operation_id>", summary: "Buy and open a card pack." },
  { name: ".sell @card:<stack> <qty>", summary: "Sell owned cards for Bops." },
  { name: ".friend <add|accept|decline|cancel|remove> <peep>", summary: "Manage friends." },
  { name: ".pin_peep @peep:<id> [on|off]", summary: "Pin or unpin a peep in your sidebar." },
  { name: ".swap_sticker <sticker>", summary: "Swap your peep sticker for Bops." },
  { name: ".shop", summary: "Open the card-pack shop." },
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

/** Build a pickup/drop command from a quantity-dialog intent. */
export function buildQuantityCommand(intent, stackId, quantity) {
  const verb = intent === "pickup" ? "pickup" : "drop";
  return `.${verb} @card:${stackId} ${Math.max(1, Number(quantity || 1))}`;
}

/** Slot or clear a skill card, and manage equipment and social commands. */
export function buildSkillCommand(stackId, slotIndex) {
  return `.skill @card:${stackId} ${Number(slotIndex)}`;
}

export function buildUnskillCommand(slotIndex) {
  return `.unskill ${Number(slotIndex)}`;
}

export function buildFriendCommand(action, accountId) {
  return `.friend ${action} @peep:${accountId}`;
}

export function buildPinCommand(peepId, mode) {
  return `.pin_peep @peep:${peepId}${mode ? ` ${mode}` : ""}`;
}

export function buildUseCommand(stackId) {
  return `.use @card:${stackId}`;
}

export function buildEmoteCommand(stackId) {
  return `.emote @card:${stackId}`;
}

export function buildEquipCommand(stackId) {
  return `.equip @card:${stackId}`;
}

export function buildUnequipCommand(stackId) {
  return `.unequip @card:${stackId}`;
}

export function buildSwapStickerCommand(sticker) {
  return `.swap_sticker ${sticker}`;
}

export function buildSplitCommand(stackId, quantity) {
  return `.split @card:${stackId} ${Number(quantity)}`;
}

export function buildMergeCommand(sourceId, destinationId) {
  return `.merge @card:${sourceId} @card:${destinationId}`;
}

export function buildSellCommand(stackId, quantity = 1) {
  return `.sell @card:${stackId} ${Math.max(1, Number(quantity || 1))}`;
}

export function buildMergeAllCommand() {
  return ".merge_all";
}
