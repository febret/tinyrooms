import { escapeHtml } from "../presentation.js";

function vibeMarkup(vibes) {
  const toward = vibes?.toward?.label || "Neutral 😐";
  const from = vibes?.from?.label || "Neutral 😐";
  return `<div class="phone-vibes" aria-label="Reciprocal vibes">
    <span class="phone-vibe"><span class="phone-vibe-label">You</span>${escapeHtml(toward)}</span>
    <span class="phone-vibe"><span class="phone-vibe-label">Them</span>${escapeHtml(from)}</span>
  </div>`;
}

function friendEntryMarkup(entry, actions, { selected = false, index = null } = {}) {
  return `<li class="friend-entry${selected ? " selected" : ""}"${selected ? ' aria-current="true"' : ""}${index === null ? "" : ` data-phone-friend-index="${index}"`}>
    <div class="friend-identity"><span class="friend-name ${entry.online ? "online" : ""}">${escapeHtml(entry.username)}</span>
      <span class="friend-presence">${entry.online ? "Online" : "Offline"}</span></div>
    ${vibeMarkup(entry.vibes)}
    <div class="friend-actions">${actions.map(({ action, label, tone }) => `<button type="button" class="${tone}" data-friend-action="${action}" data-account-id="${escapeHtml(entry.account_id)}" aria-label="${escapeHtml(`${label}: ${entry.username}`)}">${escapeHtml(label)}</button>`).join("")}</div>
  </li>`;
}

function friendGroupMarkup(title, entries, actions, emptyText, { selectedIndex = null } = {}) {
  return `<section class="friend-group"><h3>${escapeHtml(title)} <span class="phone-count">${entries.length}</span></h3>
    ${entries.length ? `<ul>${entries.map((entry, position) => friendEntryMarkup(entry, actions, { selected: position === selectedIndex, index: position })).join("")}</ul>` : `<p class="empty-state">${escapeHtml(emptyText)}</p>`}
  </section>`;
}

export function friendsPagesMarkup(state) {
  const friends = state.user?.friends || {};
  const entries = friends.friends || [];
  const selectedIndex = entries.length ? Math.max(0, Math.min(Number(state.ui?.phoneFriendIndex || 0), entries.length - 1)) : null;
  return {
    leftLabel: "Friends",
    rightLabel: "Friend requests",
    left: friendGroupMarkup("Friends", entries, [{ action: "remove", label: "Remove", tone: "negative" }], "No friends yet. Select another peep and choose Add Friend.", { selectedIndex }),
    right: `${friendGroupMarkup("Incoming requests", friends.incoming || [], [{ action: "accept", label: "Accept", tone: "positive" }, { action: "decline", label: "Decline", tone: "negative" }], "No incoming requests.")}
      ${friendGroupMarkup("Sent requests", friends.outgoing || [], [{ action: "cancel", label: "Cancel", tone: "cancel" }], "No pending sent requests.")}`,
  };
}

export function friendsAppMarkup(state) {
  const pages = friendsPagesMarkup(state);
  return `<div class="phone-app-body">
    <p class="phone-eyebrow">Good company</p>
    ${pages.left}
    ${pages.right}
    <p class="phone-note">New friendships start with a hello. Select a peep to send a friend request, then use Go to to visit them.</p>
  </div>`;
}
