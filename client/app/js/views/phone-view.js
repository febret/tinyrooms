import { withBase } from "../base-path.js";
import { escapeHtml } from "../presentation.js";
import { parentPath, songForItem, starredSongs, trackLabel } from "../phone-music.js";
import { friendsAppMarkup } from "./friends-view.js";

const APP_LABELS = { apps: "Menu", friends: "Friends", chiptune: "Chiptune" };
const APP_ICONS = {
  friends: "/app/assets/phone/phone-icon-friends.png",
  chiptune: "/app/assets/phone/phone-icon-chiptune.png",
};
const MUSIC_TABS = [
  { id: "suggestions", label: "Top" },
  { id: "starred", label: "Stars" },
  { id: "browse", label: "Files" },
];

function clockLabel() {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, "0");
  const minutes = String(now.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function statusBarMarkup() {
  return `<header class="phone-statusbar">
    <span class="phone-carrier">TINYROOMS</span>
    <span class="phone-status-time">${clockLabel()}</span>
    <span class="phone-status-icons" aria-hidden="true">
      <span class="phone-signal"><i></i><i></i><i></i><i></i></span>
      <span class="phone-battery"></span>
    </span>
  </header>`;
}

function homeMarkup(state) {
  const friends = state.user?.friends?.friends?.length || 0;
  const starred = state.user?.starredTracks?.length || 0;
  const now = new Date();
  const date = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).toUpperCase();
  return `<div class="phone-home">
    <div class="phone-home-clock">
      <strong>${clockLabel()}</strong>
      <span>${escapeHtml(date)}</span>
    </div>
    <div class="phone-apps" role="list" aria-label="Phone apps">
      <button type="button" class="phone-app" role="listitem" data-phone-app="friends" aria-label="Open Friends app">
        <img class="phone-app-icon" src="${withBase(APP_ICONS.friends)}" alt="" width="40" height="40">
        <span class="phone-app-name">FRIENDS</span>
        <span class="phone-app-meta">${friends} ${friends === 1 ? "peep" : "peeps"}</span>
      </button>
      <button type="button" class="phone-app" role="listitem" data-phone-app="chiptune" aria-label="Open Chiptune app">
        <img class="phone-app-icon" src="${withBase(APP_ICONS.chiptune)}" alt="" width="40" height="40">
        <span class="phone-app-name">CHIPTUNE</span>
        <span class="phone-app-meta">${starred} starred</span>
      </button>
    </div>
  </div>`;
}

function trackRowMarkup(item, state, { starred = starredSongs(state.user), canStar = true } = {}) {
  const song = songForItem(item);
  if (!song) return "";
  const isDirectory = item.kind === "directory";
  const title = escapeHtml(item.title || song);
  const subtitle = escapeHtml(item.subtitle || "");
  const isStarred = starred.has(song);
  const action = isDirectory
    ? `<button type="button" class="phone-track-open" data-phone-music-action="browse" data-phone-music-path="${escapeHtml(item.path || "")}">OPEN</button>`
    : `<button type="button" class="phone-track-play" data-phone-music-action="play" data-song="${escapeHtml(song)}" data-label="${escapeHtml(item.title || "")}" aria-label="${escapeHtml(`Play ${item.title || song}`)}">PLAY</button>`;
  const star = canStar && !isDirectory
    ? `<button type="button" class="phone-star ${isStarred ? "starred" : ""}" data-phone-music-action="star" data-song="${escapeHtml(song)}" data-label="${escapeHtml(item.title || "")}" aria-label="${escapeHtml(`${isStarred ? "Unstar" : "Star"} ${item.title || song}`)}" aria-pressed="${isStarred}">${isStarred ? "★" : "☆"}</button>`
    : "";
  return `<li class="phone-track${isDirectory ? " directory" : ""}">
    <span class="phone-track-text"><strong>${title}</strong>${subtitle ? `<small>${subtitle}</small>` : ""}</span>
    <span class="phone-track-actions">${star}${action}</span>
  </li>`;
}

function trackListMarkup(items, state, emptyText, options = {}) {
  if (!items.length) return `<p class="phone-empty">${escapeHtml(emptyText)}</p>`;
  return `<ul class="phone-track-list">${items.map(item => trackRowMarkup(item, state, options)).join("")}</ul>`;
}

function nowPlayingMarkup(music) {
  const playing = Boolean(music.enabled && music.track);
  return `<section class="phone-now-playing ${playing ? "playing" : ""}" aria-label="Chiptune player">
    <div class="phone-equalizer" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
    <div class="phone-now-copy">
      <p class="phone-now-label">${playing ? "PLAYING" : music.track ? "PAUSED" : "NO TRACK"}</p>
      <strong>${escapeHtml(trackLabel(music.track))}</strong>
    </div>
    <div class="phone-now-actions">
      <button type="button" class="phone-transport" data-phone-music-action="toggle" ${music.track ? "" : "disabled"} aria-pressed="${playing}">${playing ? "II" : ">"}</button>
      <button type="button" class="phone-transport quiet" data-phone-music-action="stop" ${music.track ? "" : "disabled"}>■</button>
    </div>
  </section>`;
}

function chiptuneMarkup(state) {
  const music = state.ui.phoneMusic || {};
  const mode = music.mode || "suggestions";
  const starred = state.user?.starredTracks || [];
  const tabs = `<nav class="phone-music-tabs" aria-label="Chiptune sources">
    ${MUSIC_TABS.map(tab => `<button type="button" class="${mode === tab.id ? "selected" : ""}" data-phone-music-action="mode" data-mode="${tab.id}" aria-pressed="${mode === tab.id}">${tab.label}</button>`).join("")}
  </nav>`;
  let content = "";
  if (music.loading) content = `<p class="phone-empty">DIALING...</p>`;
  else if (music.error) content = `<p class="phone-empty phone-error">${escapeHtml(music.error)}</p>`;
  else if (mode === "starred") {
    const items = starred.map(track => ({ id: track.song, title: track.label || track.song, subtitle: "You starred this", kind: "file" }));
    content = trackListMarkup(items, state, "NO STARRED TRACKS", { canStar: false });
  } else if (mode === "search") {
    content = trackListMarkup(music.items || [], state, "NO MATCHES");
  } else if (mode === "browse") {
    content = `<div class="phone-crumbs">
      <button type="button" class="phone-crumb" data-phone-music-action="browse" data-phone-music-path="${escapeHtml(parentPath(music.path))}" ${music.path ? "" : "disabled"}>UP</button>
      <span>${escapeHtml(music.path || "CATALOG")}</span>
    </div>${trackListMarkup(music.items || [], state, "EMPTY FOLDER")}`;
  } else {
    content = `<section class="phone-music-section">
      <h4>TOP TRACKS</h4>
      ${trackListMarkup(music.top || [], state, "TOP LIST UNAVAILABLE")}
    </section>
    <section class="phone-music-section">
      <h4>STARRED BY PEEPS</h4>
      ${trackListMarkup(music.community || [], state, "NOBODY HAS STARRED YET")}
    </section>`;
  }
  return `<div class="phone-app-body phone-chiptune">
    ${nowPlayingMarkup(music)}
    <form class="phone-search" data-phone-music-search>
      <input type="search" name="query" value="${escapeHtml(music.query || "")}" maxlength="120" placeholder="SEARCH" aria-label="Search chiptune.app">
      <button type="submit">GO</button>
    </form>
    ${tabs}
    ${content}
    <footer class="phone-music-footer">
      <span>Personal player. Room music is off.</span>
      <a href="https://chiptune.app/" target="_blank" rel="noopener noreferrer">chiptune.app</a>
    </footer>
  </div>`;
}

function appMarkup(state) {
  const app = APP_LABELS[state.ui?.phoneApp] ? state.ui.phoneApp : "apps";
  if (app === "friends") return friendsAppMarkup(state);
  if (app === "chiptune") return chiptuneMarkup(state);
  return homeMarkup(state);
}

function appHeaderMarkup(state) {
  const app = APP_LABELS[state.ui?.phoneApp] ? state.ui.phoneApp : "apps";
  if (app === "apps") return "";
  return `<header class="phone-app-header">
    <button type="button" class="phone-back" data-phone-home="1" aria-label="Back to apps">‹</button>
    <img class="phone-app-mark" src="${withBase(APP_ICONS[app])}" alt="" width="20" height="20">
    <h3>${escapeHtml(APP_LABELS[app].toUpperCase())}</h3>
  </header>`;
}

function softKeysMarkup(state) {
  const app = APP_LABELS[state.ui?.phoneApp] ? state.ui.phoneApp : "apps";
  return `<footer class="phone-softkeys">
    <button type="button" data-phone-home="1">APPS</button>
    <span>${app === "apps" ? "SELECT" : "OK"}</span>
  </footer>`;
}

function lidSvgMarkup() {
  return `<svg class="phone-lid-art" viewBox="0 0 300 340" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="phoneLidBlue" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#1d4c8f"/>
        <stop offset=".45" stop-color="#0d2b5c"/>
        <stop offset="1" stop-color="#07152f"/>
      </linearGradient>
      <linearGradient id="phoneLidSilver" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fbfdfd"/>
        <stop offset=".32" stop-color="#c9d1d3"/>
        <stop offset=".62" stop-color="#8c999d"/>
        <stop offset="1" stop-color="#e7edef"/>
      </linearGradient>
      <linearGradient id="phoneLidChrome" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#59666b"/>
        <stop offset=".25" stop-color="#f2f6f7"/>
        <stop offset=".5" stop-color="#9aa7ab"/>
        <stop offset=".75" stop-color="#ffffff"/>
        <stop offset="1" stop-color="#4c585d"/>
      </linearGradient>
      <linearGradient id="phoneLidBezel" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#1f2529"/>
        <stop offset=".5" stop-color="#090c0f"/>
        <stop offset="1" stop-color="#252b2f"/>
      </linearGradient>
      <pattern id="phoneLidBrush" width="5" height="5" patternUnits="userSpaceOnUse">
        <path d="M0 1h5M0 4h5" stroke="#ffffff" stroke-opacity=".16" stroke-width=".6"/>
      </pattern>
    </defs>
    <rect x="1.5" y="1.5" width="297" height="337" rx="23" fill="#061021" stroke="#02070f" stroke-width="3"/>
    <rect x="7" y="7" width="286" height="326" rx="19" fill="url(#phoneLidBlue)" stroke="#c9d8dd" stroke-width="1.3"/>
    <rect x="13" y="13" width="274" height="314" rx="15" fill="url(#phoneLidSilver)" stroke="#f4f8f8" stroke-width="1"/>
    <rect x="13" y="13" width="274" height="314" rx="15" fill="url(#phoneLidBrush)" opacity=".5"/>
    <rect x="22" y="30" width="256" height="270" rx="7" fill="url(#phoneLidBezel)" stroke="#454f55" stroke-width="2"/>
    <rect x="26" y="34" width="248" height="262" rx="4" fill="#080b0e" stroke="url(#phoneLidChrome)" stroke-width="1.2"/>
    <rect x="30" y="38" width="240" height="252" fill="#010203"/>
    <rect x="123" y="15" width="54" height="7" rx="3.5" fill="#252b2f" stroke="#778287" stroke-width=".7"/>
    <rect x="1.5" y="88" width="4.5" height="42" rx="2" fill="url(#phoneLidChrome)" opacity=".9"/>
    <rect x="294" y="118" width="4.5" height="56" rx="2" fill="url(#phoneLidChrome)" opacity=".9"/>
    <path d="M20 322h260" stroke="#f7fbfb" stroke-width="1.2" opacity=".55"/>
  </svg>`;
}

function baseSvgMarkup() {
  return `<svg class="phone-base-art" viewBox="0 0 300 220" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="phoneBaseBlue" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#1d4c8f"/>
        <stop offset=".5" stop-color="#0d2b5c"/>
        <stop offset="1" stop-color="#07152f"/>
      </linearGradient>
      <linearGradient id="phoneBaseSilver" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fbfdfd"/>
        <stop offset=".38" stop-color="#c9d1d3"/>
        <stop offset=".7" stop-color="#909ca0"/>
        <stop offset="1" stop-color="#e9eff1"/>
      </linearGradient>
      <linearGradient id="phoneBaseChrome" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#59666b"/>
        <stop offset=".22" stop-color="#f4f8f9"/>
        <stop offset=".48" stop-color="#98a5a9"/>
        <stop offset=".72" stop-color="#ffffff"/>
        <stop offset="1" stop-color="#4b575c"/>
      </linearGradient>
      <linearGradient id="phoneKey" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#f2f6f7"/>
        <stop offset=".55" stop-color="#c8d0d2"/>
        <stop offset="1" stop-color="#8f9a9e"/>
      </linearGradient>
      <pattern id="phoneBaseBrush" width="5" height="5" patternUnits="userSpaceOnUse">
        <path d="M0 1h5M0 4h5" stroke="#ffffff" stroke-opacity=".15" stroke-width=".6"/>
      </pattern>
    </defs>
    <rect x="1.5" y="1.5" width="297" height="217" rx="23" fill="#061021" stroke="#02070f" stroke-width="3"/>
    <rect x="7" y="7" width="286" height="206" rx="19" fill="url(#phoneBaseBlue)" stroke="#c9d8dd" stroke-width="1.3"/>
    <rect x="13" y="11" width="274" height="198" rx="15" fill="url(#phoneBaseSilver)" stroke="#f5f9f9" stroke-width="1"/>
    <rect x="13" y="11" width="274" height="198" rx="15" fill="url(#phoneBaseBrush)" opacity=".5"/>
    <rect x="24" y="0" width="252" height="27" rx="13.5" fill="url(#phoneBaseChrome)" stroke="#3d484d" stroke-width="1.2"/>
    <rect x="36" y="5" width="228" height="4" rx="2" fill="#f7fbfb" opacity=".5"/>
    <rect x="28" y="34" width="70" height="15" rx="7" fill="url(#phoneKey)" stroke="#5e6a6f" stroke-width="1"/>
    <rect x="202" y="34" width="70" height="15" rx="7" fill="url(#phoneKey)" stroke="#5e6a6f" stroke-width="1"/>
    <circle cx="150" cy="66" r="30" fill="url(#phoneBaseChrome)" stroke="#4d595e" stroke-width="1.4"/>
    <circle cx="150" cy="66" r="17" fill="url(#phoneKey)" stroke="#68747a" stroke-width="1"/>
    <path d="M150 54l5 7h-10zM150 78l-5-7h10zM138 66l7-5v10zM162 66l-7 5V61z" fill="#5e6a6f" opacity=".85"/>
    <rect x="132" y="203" width="36" height="4" rx="2" fill="#3b454a"/>
    <rect x="1.5" y="78" width="4.5" height="42" rx="2" fill="url(#phoneBaseChrome)" opacity=".9"/>
    <rect x="294" y="108" width="4.5" height="52" rx="2" fill="url(#phoneBaseChrome)" opacity=".9"/>
  </svg>`;
}

function phoneKeypadMarkup(state) {
  const music = state.ui?.phoneMusic || {};
  const playing = Boolean(music.enabled && music.track);
  const starred = music.track ? starredSongs(state.user).has(music.track.song) : false;
  const hasFriends = (state.user?.friends?.friends || []).length > 0;
  return `<div class="phone-keypad" role="group" aria-label="Phone keypad">
    <button type="button" class="phone-key" data-phone-key="music-prev" aria-label="Previous track" title="Previous track">⏮</button>
    <button type="button" class="phone-key" data-phone-key="music-toggle" aria-label="${playing ? "Pause" : "Play"}" aria-pressed="${playing}" title="${playing ? "Pause" : "Play"}">${playing ? "❚❚" : "▶"}</button>
    <button type="button" class="phone-key" data-phone-key="music-next" aria-label="Next track" title="Next track">⏭</button>
    <button type="button" class="phone-key" data-phone-key="volume-up" aria-label="Volume up" title="Volume is fixed while chiptune.app runs in its own frame" disabled>VOL+</button>
    <button type="button" class="phone-key" data-phone-key="volume-down" aria-label="Volume down" title="Volume is fixed while chiptune.app runs in its own frame" disabled>VOL−</button>
    <button type="button" class="phone-key" data-phone-key="music-star" aria-label="${starred ? "Unstar current track" : "Star current track"}" aria-pressed="${starred}" title="Star the current track">★</button>
    <button type="button" class="phone-key" data-phone-key="friend-prev" aria-label="Previous friend" title="Previous friend"${hasFriends ? "" : " disabled"}>◀</button>
    <button type="button" class="phone-key" data-phone-key="messages" aria-label="Messages" title="Messages are not available yet" disabled>✉</button>
    <button type="button" class="phone-key" data-phone-key="friend-next" aria-label="Next friend" title="Next friend"${hasFriends ? "" : " disabled"}>▶</button>
  </div>`;
}

export function phoneView(state) {
  const app = APP_LABELS[state.ui?.phoneApp] ? state.ui.phoneApp : "apps";
  return `<section class="board-modal phone-view" role="dialog" aria-modal="false" aria-label="Phone">
    <div class="phone-stage">
      <div class="phone-device" data-phone-screen-app="${app}">
        <div class="phone-lid">
          ${lidSvgMarkup()}
          <div class="phone-screen">
            <div class="phone-lcd">
              ${statusBarMarkup()}
              ${appHeaderMarkup(state)}
              <div class="phone-app-scroll" tabindex="0">${appMarkup(state)}</div>
              ${softKeysMarkup(state)}
            </div>
          </div>
        </div>
        <div class="phone-base">
          ${baseSvgMarkup()}
          ${phoneKeypadMarkup(state)}
          <button type="button" class="phone-hardkey phone-close" data-close-view="1" aria-label="Close phone" title="Close phone">✕</button>
        </div>
      </div>
    </div>
  </section>`;
}
