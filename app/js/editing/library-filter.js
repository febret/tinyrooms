const SHOW_ALL = "";

const libraryFilter = {
  query: "",
  source: SHOW_ALL,
  tags: new Set(),
};

function tagsOfEntry(entry) {
  return Array.isArray(entry?.tags) ? entry.tags : [];
}

function matchesQuery(entry, query) {
  if (!query) return true;
  const haystack = [entry.label, entry.description, ...tagsOfEntry(entry)].join(" ").toLowerCase();
  return haystack.includes(query);
}

/** Pure predicate over a normalized library entry and the active criteria. */
export function filterLibrary(entries, criteria = libraryFilter) {
  const query = String(criteria.query || "").trim().toLowerCase();
  const source = String(criteria.source || "");
  const tags = criteria.tags instanceof Set ? criteria.tags : new Set(criteria.tags || []);
  return (Array.isArray(entries) ? entries : []).filter(entry => {
    if (source && entry.source !== source) return false;
    if (tags.size && ![...tags].every(tag => tagsOfEntry(entry).includes(tag))) return false;
    return matchesQuery(entry, query);
  });
}

/** Distinct source prop set names present in the library, sorted. */
export function sourcesOf(entries) {
  const sources = new Set();
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (entry?.source) sources.add(entry.source);
  }
  return [...sources].sort();
}

/** Distinct tags available for a source prop set (all sources when empty), sorted. */
export function tagsOf(entries, source = "") {
  const tags = new Set();
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (source && entry?.source !== source) continue;
    for (const tag of tagsOfEntry(entry)) tags.add(tag);
  }
  return [...tags].sort();
}

export function setLibraryQuery(query) {
  libraryFilter.query = String(query || "");
}

export function setLibrarySource(source) {
  libraryFilter.source = String(source || SHOW_ALL);
}

export function toggleLibraryTag(tag) {
  const value = String(tag || "");
  if (!value) return;
  if (libraryFilter.tags.has(value)) libraryFilter.tags.delete(value);
  else libraryFilter.tags.add(value);
}

export function resetLibraryFilter() {
  libraryFilter.query = "";
  libraryFilter.source = SHOW_ALL;
  libraryFilter.tags.clear();
}

/**
 * Bind the search, source prop set, and tag controls, then apply the filter.
 *
 * Filtering mutates this module's state and syncs only the library markup, so
 * typing in the search box never triggers a store render (and never steals
 * focus or scroll).
 */
export function bindEditorLibrary(root, library) {
  if (!root) return;
  const list = Array.isArray(library) ? library : [];
  const search = root.querySelector("[data-edit-search]");
  if (search) {
    search.oninput = () => {
      setLibraryQuery(search.value);
      syncEditorLibrary(root, list);
    };
    search.onkeydown = event => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      search.blur();
    };
  }
  root.querySelectorAll("[data-edit-propset]").forEach(button => {
    button.onclick = () => {
      setLibrarySource(button.dataset.editPropset || "");
      syncEditorLibrary(root, list);
    };
  });
  root.querySelectorAll("[data-edit-tag]").forEach(pill => {
    pill.onclick = () => {
      toggleLibraryTag(pill.dataset.editTag || "");
      syncEditorLibrary(root, list);
    };
  });
  syncEditorLibrary(root, list);
}

/**
 * Apply the active filter to the already-rendered editor markup.
 *
 * The library chrome is rendered independently of the filter so typing in the
 * search box never re-renders (and therefore never steals focus or scroll).
 */
export function syncEditorLibrary(root, library) {
  if (!root) return;
  const entries = Array.isArray(library) ? library : [];
  const tags = tagsOf(entries, libraryFilter.source);
  for (const tag of [...libraryFilter.tags]) {
    if (!tags.includes(tag)) libraryFilter.tags.delete(tag);
  }
  const visible = filterLibrary(entries, libraryFilter);
  const visibleIds = new Set(visible.map(entry => entry.propId));

  const search = root.querySelector("[data-edit-search]");
  if (search && search.value !== libraryFilter.query) search.value = libraryFilter.query;

  root.querySelectorAll(".editor-library-item").forEach(item => {
    item.hidden = !visibleIds.has(item.dataset.editAdd);
  });
  root.querySelectorAll("[data-edit-propset]").forEach(button => {
    const active = (button.dataset.editPropset || "") === (libraryFilter.source || "");
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  root.querySelectorAll("[data-edit-tag]").forEach(pill => {
    const tag = pill.dataset.editTag || "";
    const available = tags.includes(tag);
    pill.hidden = !available;
    const active = available && libraryFilter.tags.has(tag);
    pill.classList.toggle("is-active", active);
    pill.setAttribute("aria-pressed", active ? "true" : "false");
  });

  const count = root.querySelector(".editor-library-count");
  if (count) count.textContent = `${visible.length} of ${entries.length} props`;
  const empty = root.querySelector(".editor-library-empty");
  if (empty) empty.hidden = visible.length > 0;
}
