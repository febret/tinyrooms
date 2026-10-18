import { escapeHtml } from "../presentation.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

function friendEntryMarkup(entry, actions) {
  return `<li class="friend-entry">
    <div class="friend-identity"><span class="friend-name ${entry.online ? "online" : ""}">${escapeHtml(entry.username)}</span>
      <span class="friend-presence">${entry.online ? "Online" : "Offline"}</span></div>
    <div class="friend-actions">${actions.map(({ action, label, tone }) => `<button type="button" class="${tone}" data-friend-action="${action}" data-account-id="${escapeHtml(entry.account_id)}" aria-label="${escapeHtml(`${label}: ${entry.username}`)}">${escapeHtml(label)}</button>`).join("")}</div>
  </li>`;
}

function friendGroupMarkup(title, entries, actions, emptyText) {
  return `<section class="friend-group"><h3>${escapeHtml(title)} <span class="journal-count">${entries.length}</span></h3>
    ${entries.length ? `<ul>${entries.map(entry => friendEntryMarkup(entry, actions)).join("")}</ul>` : `<p class="empty-state">${escapeHtml(emptyText)}</p>`}
  </section>`;
}

export function friendsPagesMarkup(state) {
  const friends = state.user?.friends || {};
  return {
    leftLabel: "Friends",
    rightLabel: "Incoming and outgoing friend requests",
    left: `<p class="journal-eyebrow">Good company</p>
      ${friendGroupMarkup("Friends", friends.friends || [], [{ action: "remove", label: "Remove", tone: "negative" }], "No friends yet. Select another peep and choose Add Friend.")}
      <p class="journal-note">New friendships start with a hello. Select a peep to send a friend request.</p>`,
    right: `<p class="journal-eyebrow">Keeping in touch</p>
      ${friendGroupMarkup("Incoming requests", friends.incoming || [], [{ action: "accept", label: "Accept", tone: "positive" }, { action: "decline", label: "Decline", tone: "negative" }], "No incoming requests.")}
      ${friendGroupMarkup("Sent requests", friends.outgoing || [], [{ action: "cancel", label: "Cancel", tone: "cancel" }], "No pending sent requests.")}`,
  };
}

export function friendsView(state) {
  return modalShell({ extraClass: "journal-view friends-view", ariaLabel: "Friends", title: "Friends", body: journalSpreadMarkup(friendsPagesMarkup(state)) });
}
