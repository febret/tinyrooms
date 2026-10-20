import { escapeHtml } from "../presentation.js";
import { journalSpreadMarkup, modalShell } from "./view-helpers.js";

function sendBeaconButton(entry) {
  return `<button type="button" class="positive" data-beacon-action="send" data-account-id="${escapeHtml(entry.account_id)}" aria-label="${escapeHtml(`Send beacon: ${entry.username}`)}">Send Beacon</button>`;
}

function friendEntryMarkup(entry, actions, extraActions = "") {
  return `<li class="friend-entry">
    <div class="friend-identity"><span class="friend-name ${entry.online ? "online" : ""}">${escapeHtml(entry.username)}</span>
      <span class="friend-presence">${entry.online ? "Online" : "Offline"}</span></div>
    <div class="friend-actions">${actions.map(({ action, label, tone }) => `<button type="button" class="${tone}" data-friend-action="${action}" data-account-id="${escapeHtml(entry.account_id)}" aria-label="${escapeHtml(`${label}: ${entry.username}`)}">${escapeHtml(label)}</button>`).join("")}${extraActions}</div>
  </li>`;
}

function friendGroupMarkup(title, entries, actions, emptyText, { beacon = false } = {}) {
  return `<section class="friend-group"><h3>${escapeHtml(title)} <span class="journal-count">${entries.length}</span></h3>
    ${entries.length ? `<ul>${entries.map(entry => friendEntryMarkup(entry, actions, beacon ? sendBeaconButton(entry) : "")).join("")}</ul>` : `<p class="empty-state">${escapeHtml(emptyText)}</p>`}
  </section>`;
}

function beaconEntryMarkup(beacon) {
  const place = beacon.crossWorld
    ? `${beacon.worldLabel || beacon.worldId} · ${beacon.roomLabel || beacon.roomId}`
    : beacon.roomLabel || beacon.roomId;
  return `<li class="friend-entry beacon-entry">
    <div class="friend-identity"><span class="friend-name">${escapeHtml(beacon.fromUsername)}</span>
      <span class="friend-presence">${escapeHtml(place)}</span></div>
    <div class="friend-actions">
      <button type="button" class="positive" data-beacon-action="use" data-account-id="${escapeHtml(beacon.fromAccountId)}" aria-label="${escapeHtml(`Travel to ${beacon.fromUsername}'s beacon`)}">Travel</button>
      <button type="button" class="negative" data-beacon-action="dismiss" data-account-id="${escapeHtml(beacon.fromAccountId)}" aria-label="${escapeHtml(`Dismiss ${beacon.fromUsername}'s beacon`)}">Dismiss</button>
    </div>
  </li>`;
}

function beaconGroupMarkup(beacons) {
  return `<section class="friend-group"><h3>Incoming beacons <span class="journal-count">${beacons.length}</span>
      <button type="button" class="cancel" data-beacon-refresh aria-label="Refresh beacons">Refresh</button></h3>
    ${beacons.length ? `<ul>${beacons.map(beaconEntryMarkup).join("")}</ul>` : `<p class="empty-state">No beacons waiting. Friends can send you one from their Friends page.</p>`}
  </section>`;
}

export function friendsPagesMarkup(state) {
  const friends = state.user?.friends || {};
  const beacons = state.user?.beacons || [];
  return {
    leftLabel: "Friends",
    rightLabel: "Beacons and friend requests",
    left: `<p class="journal-eyebrow">Good company</p>
      ${friendGroupMarkup("Friends", friends.friends || [], [{ action: "remove", label: "Remove", tone: "negative" }], "No friends yet. Select another peep and choose Add Friend.", { beacon: true })}
      <p class="journal-note">New friendships start with a hello. Select a peep to send a friend request, then send them a beacon to invite them to your room.</p>`,
    right: `<p class="journal-eyebrow">Keeping in touch</p>
      ${beaconGroupMarkup(beacons)}
      ${friendGroupMarkup("Incoming requests", friends.incoming || [], [{ action: "accept", label: "Accept", tone: "positive" }, { action: "decline", label: "Decline", tone: "negative" }], "No incoming requests.")}
      ${friendGroupMarkup("Sent requests", friends.outgoing || [], [{ action: "cancel", label: "Cancel", tone: "cancel" }], "No pending sent requests.")}`,
  };
}

export function friendsView(state) {
  return modalShell({ extraClass: "journal-view friends-view", ariaLabel: "Friends", title: "Friends", body: journalSpreadMarkup(friendsPagesMarkup(state)) });
}
