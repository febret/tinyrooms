import { escapeHtml } from "../presentation.js";
import { qrSvg } from "../qr-code.js";

function expiryLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function guestInviteAppMarkup(state) {
  const panel = state.ui?.phoneInvite || {};
  if (panel.loading) {
    return `<div class="phone-app-body phone-guest-invite">
      <p class="phone-empty">MAKING A CODE...</p>
    </div>`;
  }
  if (panel.error) {
    return `<div class="phone-app-body phone-guest-invite">
      <p class="phone-empty phone-error">${escapeHtml(panel.error)}</p>
      <button type="button" class="phone-invite-button" data-phone-invite-action="refresh">TRY AGAIN</button>
    </div>`;
  }
  const invite = panel.invite;
  if (!invite?.url) {
    return `<div class="phone-app-body phone-guest-invite">
      <p class="phone-empty">No invite code yet.</p>
      <button type="button" class="phone-invite-button" data-phone-invite-action="refresh">MAKE A CODE</button>
    </div>`;
  }
  const expires = expiryLabel(invite.expires_at);
  return `<div class="phone-app-body phone-guest-invite">
    <p class="phone-eyebrow">Bring a friend</p>
    <div class="phone-qr" role="img" aria-label="Guest invite QR code">${qrSvg(invite.url)}</div>
    <p class="phone-qr-url">${escapeHtml(invite.url)}</p>
    <dl class="phone-invite-details">
      <div><dt>ROOM</dt><dd>${escapeHtml(invite.room_label || invite.room_id || "")}</dd></div>
      <div><dt>WORLD</dt><dd>${escapeHtml(invite.world_id || "")}</dd></div>
      ${expires ? `<div><dt>GOOD UNTIL</dt><dd>${escapeHtml(expires)}</dd></div>` : ""}
    </dl>
    <div class="phone-invite-actions">
      <button type="button" class="phone-invite-button" data-phone-invite-action="copy" data-invite-url="${escapeHtml(invite.url)}">COPY LINK</button>
      <button type="button" class="phone-invite-button quiet" data-phone-invite-action="refresh">NEW CODE</button>
    </div>
    <p class="phone-note">Scanning joins this world and room as a guest on that device. Guests can revisit with the same link.</p>
  </div>`;
}
