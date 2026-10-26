import { escapeHtml } from "../presentation.js";

function threadKindLetter(kind) {
  if (kind === "player") return "F";
  if (kind === "npc") return "R";
  if (kind === "system") return "N";
  return "T";
}

function clockOf(iso) {
  const time = new Date(String(iso || ""));
  if (!Number.isFinite(time.getTime())) return "";
  return time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function threadMeta(thread) {
  const bits = [threadKindLetter(thread.kind)];
  const clock = clockOf(thread.lastAt);
  if (clock) bits.push(clock);
  const unread = Number(thread.unread || 0);
  if (unread) bits.push(String(unread));
  return bits.join(" · ");
}

function threadEntryMarkup(thread) {
  const unread = Number(thread.unread || 0);
  const label = `Open texts with ${thread.peerName || "Unknown"}${unread ? `, ${unread} unread` : ""}`;
  return `<li class="phone-thread${unread ? " unread" : ""}">
    <button type="button" class="phone-thread-open" data-phone-messages-action="open" data-thread-key="${escapeHtml(thread.threadKey)}" aria-label="${escapeHtml(label)}">
      <span class="phone-thread-line">
        <strong>${unread ? `<span class="phone-thread-dot" aria-hidden="true"></span>` : ""}${escapeHtml(thread.peerName || "Unknown")}</strong>
        <span class="phone-thread-meta">${escapeHtml(threadMeta(thread))}</span>
      </span>
      <span class="phone-thread-preview">${escapeHtml(thread.preview || "No texts yet.")}</span>
    </button>
  </li>`;
}

function threadListMarkup(inbox) {
  const threads = inbox.threads || [];
  return `<div class="phone-app-body phone-messages">
    <div class="phone-sms-head"><span>Inbox</span><button type="button" class="phone-sms-link" data-phone-messages-action="new">+ New</button></div>
    ${threads.length
      ? `<ul class="phone-thread-list">${threads.map(threadEntryMarkup).join("")}</ul>`
      : `<p class="phone-empty">No texts yet. Write to a friend, or wait for a roommate to say hi.</p>`}
  </div>`;
}

function peersMarkup(inbox) {
  const peers = inbox.peers || [];
  return `<div class="phone-app-body phone-messages">
    <div class="phone-sms-head"><span>New text</span><button type="button" class="phone-sms-link" data-phone-messages-action="back">Back</button></div>
    ${peers.length
      ? `<ul class="phone-thread-list">${peers.map(peer => `<li class="phone-thread">
        <button type="button" class="phone-thread-open" data-phone-messages-action="pick" data-thread-key="${escapeHtml(peer.threadKey)}" aria-label="${escapeHtml(`Text ${peer.name}`)}">
          <span class="phone-thread-line"><strong>${escapeHtml(peer.name)}</strong></span>
          <span class="phone-thread-preview">Start a new thread</span>
        </button>
      </li>`).join("")}</ul>`
      : `<p class="phone-empty">No one to text. Add a friend first.</p>`}
  </div>`;
}

function messageBubbleMarkup(message) {
  const outbound = message.direction === "out";
  return `<li class="phone-bubble ${outbound ? "out" : "in"}">
    <span class="phone-bubble-text">${escapeHtml(message.body)}</span>${clockOf(message.createdAt) ? `<span class="phone-bubble-time">${escapeHtml(clockOf(message.createdAt))}</span>` : ""}
  </li>`;
}

function threadViewMarkup(inbox, threadKey) {
  const thread = (inbox.threads || []).find(entry => entry.threadKey === threadKey);
  const messages = inbox.messages || [];
  const peerName = thread?.peerName || "Texts";
  const canSend = thread ? thread.kind !== "system" : true;
  return `<div class="phone-app-body phone-messages">
    <div class="phone-sms-head"><span>${escapeHtml(peerName)}</span><button type="button" class="phone-sms-link" data-phone-messages-action="back">Back</button></div>
    ${messages.length
      ? `<ul class="phone-bubbles" aria-label="${escapeHtml(`Texts with ${peerName}`)}">${messages.map(messageBubbleMarkup).join("")}</ul>`
      : `<p class="phone-empty">No texts yet. Say hi!</p>`}
    ${canSend
      ? `<form class="phone-compose" data-phone-messages-compose="${escapeHtml(threadKey)}">
        <input type="text" name="body" value="" maxlength="160" placeholder="Write message" autocomplete="off" aria-label="${escapeHtml(`Text ${peerName}`)}" data-phone-message-input="${escapeHtml(threadKey)}">
        <button type="submit">Send</button>
      </form>`
      : `<p class="phone-note">Notices are read-only.</p>`}
  </div>`;
}

export function messagesAppMarkup(state) {
  const inbox = state.ui?.phoneMessages || { threads: [], messages: [], peers: [], picking: false, threadKey: null };
  if (inbox.picking) return peersMarkup(inbox);
  if (inbox.threadKey) return threadViewMarkup(inbox, inbox.threadKey);
  return threadListMarkup(inbox);
}
