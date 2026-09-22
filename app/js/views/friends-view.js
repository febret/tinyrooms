import { escapeHtml } from "../presentation.js";
import { modalShell } from "./view-helpers.js";

export function friendsView(state) {
  const friends = state.user?.friends || { friends: [], incoming: [], outgoing: [] };
  const renderEntry = (entry, action, label, tone) => `
    <li class="friend-entry">
      <span class="friend-name ${entry.online ? "online" : ""}">${escapeHtml(entry.username)}</span>
      <button type="button" class="${tone}" data-friend-action="${action}" data-account-id="${escapeHtml(entry.account_id)}">${escapeHtml(label)}</button>
    </li>
  `;
  return modalShell({
    extraClass: "friends-view",
    ariaLabel: "Friends",
    title: "Friends",
    body: `
      <div class="modal-scroll">
        <section class="friend-group"><h3>Friends</h3>
          ${friends.friends.length ? `<ul>${friends.friends.map(entry => renderEntry(entry, "remove", "Remove", "negative")).join("")}</ul>` : '<div class="empty-state">No friends yet. Select another peep and choose Add Friend.</div>'}
        </section>
        <section class="friend-group"><h3>Requests</h3>
          ${friends.incoming.length ? `<ul>${friends.incoming.map(entry => `${renderEntry(entry, "accept", "Accept", "positive")}`).join("")}</ul>` : '<div class="empty-state">No incoming requests.</div>'}
          ${friends.incoming.length ? `<ul>${friends.incoming.map(entry => renderEntry(entry, "decline", "Decline", "negative")).join("")}</ul>` : ""}
        </section>
        <section class="friend-group"><h3>Sent</h3>
          ${friends.outgoing.length ? `<ul>${friends.outgoing.map(entry => renderEntry(entry, "cancel", "Cancel", "cancel")).join("")}</ul>` : '<div class="empty-state">No pending sent requests.</div>'}
        </section>
      </div>
    `,
  });
}
