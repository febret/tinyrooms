import { COPY } from "./tiny-mag-copy.js";

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function candidateDescription(candidate) {
  return String(candidate.description || candidate.headline || "");
}

function candidateCard(candidate, index, ctx, { lead = false } = {}) {
  const labels = COPY.labels;
  return `
    <article class="roommate-profile${lead ? " roommate-profile-lead" : ""}">
      <figure class="roommate-portrait">
        <img src="${ctx.image(candidate.avatar_url)}" alt="${ctx.escape(candidate.name)}"${lead ? "" : ' loading="lazy"'}>
        <figcaption>
          <span>${COPY.roommates.applicantLabel} ${String(index).padStart(2, "0")}</span>
          <em>Portrait</em>
        </figcaption>
      </figure>
      <div class="roommate-copy">
        <p class="eyebrow">${COPY.roommates.applicantLabel} ${String(index).padStart(2, "0")}</p>
        <h3>${ctx.escape(candidate.name)}</h3>
        <p class="roommate-quote">“${ctx.escape(candidate.headline || "")}”</p>
        <p class="roommate-description">${ctx.escape(candidateDescription(candidate))}</p>
        <div class="actions">
          <button type="button" class="mag-btn" data-action="invite" data-id="${ctx.escape(candidate.id)}">
            ${labels.invite}
          </button>
        </div>
      </div>
    </article>
  `;
}

function residentCard(npc, ctx) {
  const labels = COPY.labels;
  const place = [npc.room_label, npc.action_label].filter(Boolean).join(" · ");
  return `
    <article class="resident-profile">
      <figure class="resident-portrait">
        <img src="${ctx.image(npc.avatar_url)}" alt="${ctx.escape(npc.name)}" loading="lazy">
      </figure>
      <div class="resident-copy">
        <p class="eyebrow">${ctx.escape(place || COPY.roommates.residentLabel)}</p>
        <h3>${ctx.escape(npc.name)}</h3>
        <p class="roommate-description">${ctx.escape(candidateDescription(npc))}</p>
        <div class="actions">
          <button type="button" class="mag-btn quiet" data-action="remove-npc" data-id="${ctx.escape(npc.id)}">${labels.moveOut}</button>
        </div>
      </div>
    </article>
  `;
}

export function renderRoommateLeft(data, ctx) {
  const candidates = data?.candidates || [];
  const lead = candidates[0];
  return `
    <p class="eyebrow">${COPY.roommates.eyebrow}</p>
    <h2 class="page-title">${COPY.roommates.title.map(line => ctx.escape(line)).join("<br>")}</h2>
    <p class="dek dropcap">${COPY.roommates.dek}</p>
    ${lead
      ? candidateCard(lead, 1, ctx, { lead: true })
      : `<div class="empty">${COPY.roommates.applicantsEmpty}</div>`}
    <div class="note">${COPY.roommates.note}</div>
    <span class="section-stamp">${COPY.roommates.stamp}</span>
  `;
}

export function renderRoommateRight(data, ctx) {
  if (!data) return `<p class="empty">The classified desk is checking its files.</p>`;
  const candidates = (data.candidates || []).slice(1);
  const npcs = data.npcs || [];
  return `
    <p class="kicker">${COPY.roommates.rightKicker}</p>
    <h2 class="page-title">${COPY.roommates.rightTitle}</h2>
    <div class="roommate-board">
      ${candidates.length
        ? candidates.map((candidate, index) => candidateCard(candidate, index + 2, ctx)).join("")
        : `<div class="empty">${COPY.roommates.applicantsEmpty}</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">${COPY.roommates.atHome}</p>
    <div class="resident-board">
      ${npcs.length
        ? npcs.map(npc => residentCard(npc, ctx)).join("")
        : `<div class="empty">${COPY.roommates.atHomeEmpty}</div>`}
    </div>
  `;
}

export function renderHomeChoices(houses, ctx) {
  if (!houses.length) return `<div class="empty">${COPY.dialog.noHouse}</div>`;
  return houses.map(house => {
    const residents = number(house.resident_count);
    const capacity = number(house.max_residents, 4);
    const full = residents >= capacity;
    return `
      <button type="button" class="home-choice" data-action="assign-home" data-id="${ctx.escape(house.id)}" ${full ? "disabled" : ""}>
        <span class="home-choice-name">${ctx.escape(house.label)}</span>
        <span class="home-choice-meta">${ctx.escape(house.district_label)} · ${residents} of ${capacity} residents</span>
        <span class="home-choice-state">${full ? COPY.dialog.full : COPY.dialog.open}</span>
      </button>
    `;
  }).join("");
}
