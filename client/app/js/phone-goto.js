function parseThreadKey(threadKey) {
  const key = String(threadKey || "");
  if (key.startsWith("player:")) {
    return { kind: "player", id: key.slice("player:".length), worldId: "" };
  }
  if (key.startsWith("npc:")) {
    const rest = key.slice("npc:".length);
    const separator = rest.indexOf(":");
    if (separator <= 0 || separator === rest.length - 1) return null;
    return { kind: "npc", id: rest.slice(separator + 1), worldId: rest.slice(0, separator) };
  }
  return null;
}

export function phoneGotoTarget(state) {
  const app = state.ui?.phoneApp;
  if (app === "friends") {
    const entries = state.user?.friends?.friends || [];
    if (!entries.length) return null;
    const index = Math.max(0, Math.min(Number(state.ui?.phoneFriendIndex || 0), entries.length - 1));
    const entry = entries[index];
    if (!entry || !entry.account_id) return null;
    return { kind: "player", id: String(entry.account_id), worldId: "", label: String(entry.username || "") };
  }
  if (app === "messages") {
    const inbox = state.ui?.phoneMessages || {};
    if (inbox.picking || !inbox.threadKey) return null;
    const thread = (inbox.threads || []).find(entry => entry.threadKey === inbox.threadKey);
    const parsed = parseThreadKey(inbox.threadKey);
    const kind = thread?.kind || parsed?.kind || "system";
    if (kind === "system" || !parsed) return null;
    if (kind === "player") {
      return { kind: "player", id: String(parsed.id), worldId: "", label: String(thread?.peerName || "") };
    }
    if (kind === "npc") {
      return { kind: "npc", id: String(parsed.id), worldId: String(parsed.worldId || ""), label: String(thread?.peerName || "") };
    }
    return null;
  }
  return null;
}

export function buildGotoCommand(target) {
  if (!target || !target.id) return "";
  if (target.kind === "npc") return `.goto @npc:${target.worldId}:${target.id}`;
  return `.goto @peep:${target.id}`;
}
