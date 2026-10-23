import { escapeHtml } from "./presentation.js";
import { PANEL_SIZE_CHOICES, bubbleTimeoutLabel } from "./preferences.js";
import { uiIconMarkup } from "./ui-icons.js";

export function quickSetting({ action, label, icon, pressed = null, disabled = false, title = "", wide = false }) {
  const pressedAttr = pressed === null ? "" : ` aria-pressed="${pressed}"`;
  const disabledAttr = disabled ? " disabled" : "";
  const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
  return `<button type="button" class="quick-setting${wide ? " wide" : ""}" data-top-action="${escapeHtml(action)}"${pressedAttr}${disabledAttr}${titleAttr}>
    ${uiIconMarkup(icon, { className: "quick-icon" })}
    <span class="quick-label">${escapeHtml(label)}</span>
  </button>`;
}

export function sizeSetting({ kind, label, value }) {
  const options = PANEL_SIZE_CHOICES.map(choice =>
    `<option value="${choice}"${choice === value ? " selected" : ""}>${choice[0].toUpperCase()}${choice.slice(1)}</option>`).join("");
  return `<label class="quick-setting size-setting wide" for="${escapeHtml(kind)}-size">
    <span class="quick-label">${escapeHtml(label)}</span>
    <select class="quick-select" id="${escapeHtml(kind)}-size" data-size-setting="${escapeHtml(kind)}" data-focus-key="${escapeHtml(kind)}-size">${options}</select>
  </label>`;
}

export function topBarMarkup(state, canFullscreen) {
  const fullscreenTitle = canFullscreen
    ? state.ui.fullscreen ? "Exit fullscreen" : "Enter fullscreen"
    : "Fullscreen is not supported on this device";
  return [
    quickSetting({ action: "peeps", label: "Peeps", icon: "peeps", pressed: state.ui.peepsVisible !== false }),
    quickSetting({ action: "log", label: "Log", icon: "log", pressed: state.ui.actionLogVisible }),
    quickSetting({ action: "sound", label: "Sound", icon: "sound", pressed: state.ui.soundEnabled }),
    quickSetting({ action: "fullscreen", label: "Fullscreen", icon: "fullscreen", pressed: state.ui.fullscreen, disabled: !canFullscreen, title: fullscreenTitle }),
    quickSetting({ action: "outlines", label: "Outlines", icon: "outlines", pressed: state.ui.outlineActiveProps }),
    quickSetting({ action: "bubble", label: `Bubbles: ${bubbleTimeoutLabel(state.ui.bubbleTimeout)}`, icon: "bubble" }),
    sizeSetting({ kind: "sidebar", label: "Peep sidebar size", value: state.ui.sidebarSize || "normal" }),
    sizeSetting({ kind: "toolbar", label: "Top toolbar size", value: state.ui.toolbarSize || "normal" }),
    state.loggedIn ? quickSetting({ action: "audio", label: "Audio", icon: "audio", pressed: state.ui.audioEnabled }) : "",
    state.ui.audioEnabled ? quickSetting({ action: "mute", label: state.ui.audioMuted ? "Unmute" : "Mute", icon: "mute", pressed: state.ui.audioMuted }) : "",
    quickSetting({ action: "commands", label: "Commands", icon: "commands" }),
    state.loggedIn ? quickSetting({ action: "logout", label: "Log out", icon: "logout", wide: true }) : "",
    state.loggedIn && !state.transport.connected && state.user?.initialStickerComplete
      ? quickSetting({ action: "reconnect", label: "Reconnect", icon: "reconnect", wide: true })
      : "",
  ].join("");
}
