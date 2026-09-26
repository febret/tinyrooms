import { escapeHtml } from "../presentation.js";
import { sourcesOf, tagsOf } from "./library-filter.js";

function sampleEntries(entries, count) {
  if (!entries.length) return [];
  const total = Math.min(count, entries.length);
  const step = entries.length / total;
  const picked = [];
  for (let index = 0; index < total; index += 1) {
    picked.push(entries[Math.min(entries.length - 1, Math.floor(index * step))]);
  }
  return picked;
}

function thumbnailMarkup(entry, className) {
  return `<img class="${className}" data-thumb-model="${escapeHtml(entry.modelUrl)}"
    data-thumb-scale="${escapeHtml(entry.baseScale)}" alt="" aria-hidden="true">`;
}

function mosaicMarkup(entries) {
  return sampleEntries(entries, 4).map(entry => thumbnailMarkup(entry, "editor-propset-thumb")).join("");
}

function propTile(entry) {
  return `
    <button type="button" class="editor-library-item" role="listitem"
      data-edit-add="${escapeHtml(entry.propId)}" data-library-source="${escapeHtml(entry.source)}"
      data-library-tags="${escapeHtml(entry.tags.join(" "))}"
      aria-label="Add ${escapeHtml(entry.label)}" title="${escapeHtml(entry.label)}">
      ${thumbnailMarkup(entry, "editor-thumb")}
    </button>
  `;
}

function propSetLabel(source) {
  if (!source) return "Show all";
  const name = source.replace(/-base$/, "");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function propSetButton(source, entries) {
  const value = source || "";
  const label = propSetLabel(source);
  return `
    <button type="button" class="editor-propset" data-edit-propset="${escapeHtml(value)}"
      aria-pressed="false" title="Show ${escapeHtml(label)}">
      <span class="editor-propset-art">${mosaicMarkup(entries)}</span>
      <span class="editor-propset-label">${escapeHtml(label)}</span>
    </button>
  `;
}

/** Value signature of a library, so chrome is only rebuilt when the catalog changes. */
function librarySignature(entries) {
  const list = Array.isArray(entries) ? entries : [];
  return list.map(entry => [
    entry.propId, entry.label, entry.modelUrl, entry.baseScale,
    entry.source, entry.locked ? 1 : 0, entry.tags.join(","),
  ].join("\u0001")).join("\u0002");
}

/** Memoize a markup builder by the library signature; the catalog is stable while editing. */
function memo(build) {
  let key = null;
  let html = "";
  return entries => {
    const list = Array.isArray(entries) ? entries : [];
    const signature = librarySignature(list);
    if (signature === key) return html;
    key = signature;
    html = build(list);
    return html;
  };
}

const tagsMarkup = memo(list => tagsOf(list)
  .map(tag => `<button type="button" class="editor-tag" data-edit-tag="${escapeHtml(tag)}" aria-pressed="false">${escapeHtml(tag)}</button>`)
  .join(""));

const propsetsMarkup = memo(list => {
  if (!list.length) return "";
  const sources = sourcesOf(list);
  return [
    propSetButton("", list),
    ...sources.map(source => propSetButton(source, list.filter(entry => entry.source === source))),
  ].join("");
});

const gridMarkup = memo(list => list.map(propTile).join(""));

/** Tag filter pills shown in the editor heading. */
export function libraryTagMarkup(entries) {
  return tagsMarkup(entries);
}

/** Source prop set filter buttons shown as a vertical scrolling list. */
export function libraryPropsetMarkup(entries) {
  return propsetsMarkup(entries);
}

/** The scrollable prop thumbnail grid. */
export function libraryGridMarkup(entries) {
  return gridMarkup(entries);
}
