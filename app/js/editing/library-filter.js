import { escapeHtml } from "../presentation.js";

const SHOW_ALL = "";

const libraryFilter = createLibraryFilter();

function tagsOfEntry(entry) {
  return Array.isArray(entry?.tags) ? entry.tags : [];
}

function matchesQuery(entry, query) {
  if (!query) return true;
  const haystack = [entry.label, entry.description, ...tagsOfEntry(entry)].join(" ").toLowerCase();
  return haystack.includes(query);
}

/** Pure predicate over a normalized library entry and the active criteria. */
export function filterLibrary(entries, criteria = libraryFilter.getCriteria()) {
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
  libraryFilter.setQuery(query);
}

export function setLibrarySource(source) {
  libraryFilter.setSource(source);
}

export function toggleLibraryTag(tag) {
  libraryFilter.toggleTag(tag);
}

export function resetLibraryFilter() {
  libraryFilter.reset();
}

/**
 * Bind the search, source prop set, and tag controls, then apply the filter.
 *
 * Filtering mutates the compatibility controller and syncs only library markup, so
 * typing in the search box never triggers a store render (and never steals
 * focus or scroll).
 */
export function bindEditorLibrary(root, library) {
  libraryFilter.bind(root, library);
}

/** Apply the compatibility controller's criteria to already-rendered markup. */
export function syncEditorLibrary(root, library) {
  libraryFilter.sync(root, library);
}

/** Independent criteria and DOM bindings for an editor or shared library dock. */
export function createLibraryFilter() {
  const criteria = { query: "", source: SHOW_ALL, tags: new Set() };

  function setQuery(query) {
    criteria.query = String(query || "");
  }

  function setSource(source) {
    criteria.source = String(source || SHOW_ALL);
  }

  function toggleTag(tag) {
    const value = String(tag || "");
    setTag(criteria.tags.has(value) ? "" : value);
  }

  function setTag(tag) {
    criteria.tags.clear();
    if (tag) criteria.tags.add(String(tag));
  }

  function reset() {
    criteria.query = "";
    criteria.source = SHOW_ALL;
    criteria.tags.clear();
  }

  // Return a snapshot so callers cannot accidentally mutate controller state.
  function getCriteria() {
    return { ...criteria, tags: new Set(criteria.tags) };
  }

  function filter(entries) {
    return filterLibrary(entries, criteria);
  }

  function bind(root, library) {
    if (!root) return;
    const list = Array.isArray(library) ? library : [];
    const search = root.querySelector("[data-edit-search]");
    if (search) {
      search.oninput = () => {
        setQuery(search.value);
        sync(root, list);
      };
      search.onkeydown = event => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        search.blur();
      };
    }
    root.querySelectorAll("[data-edit-propset]").forEach(button => {
      button.onclick = () => {
        setSource(button.dataset.editPropset || "");
        sync(root, list);
      };
    });
    const tagSearch = root.querySelector("[data-edit-tag-search]");
    if (tagSearch) {
      tagSearch.oninput = () => {
        const value = tagSearch.value.trim().toLowerCase();
        const tag = tagsOf(list, criteria.source).find(entry => entry.toLowerCase() === value);
        if (value && !tag) return;
        setTag(tag || "");
        sync(root, list);
      };
      tagSearch.onchange = () => {
        const value = tagSearch.value.trim().toLowerCase();
        setTag(tagsOf(list, criteria.source).find(entry => entry.toLowerCase() === value) || "");
        sync(root, list);
      };
      tagSearch.onkeydown = event => {
        if (event.key === "Escape") {
          event.stopPropagation();
          tagSearch.blur();
        }
      };
    }
    sync(root, list);
  }

  /** Apply criteria without re-rendering, preserving search focus and scroll. */
  function sync(root, library) {
    if (!root) return;
    const entries = Array.isArray(library) ? library : [];
    const tags = tagsOf(entries, criteria.source);
    for (const tag of [...criteria.tags]) {
      if (!tags.includes(tag)) criteria.tags.delete(tag);
    }
    const visible = filter(entries);
    const visibleIds = new Set(visible.map(entry => entry.propId));

    const search = root.querySelector("[data-edit-search]");
    if (search && search.value !== criteria.query) search.value = criteria.query;

    root.querySelectorAll(".editor-library-item").forEach(item => {
      item.hidden = !visibleIds.has(item.dataset.editAdd);
    });
    root.querySelectorAll("[data-edit-propset]").forEach(button => {
      const active = (button.dataset.editPropset || "") === (criteria.source || "");
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const tagSearch = root.querySelector("[data-edit-tag-search]");
    if (tagSearch) tagSearch.value = [...criteria.tags][0] || "";
    const options = root.querySelector("[data-edit-tag-options]");
    const markup = tags.map(tag => `<option value="${escapeHtml(tag)}"></option>`).join("");
    if (options && options.innerHTML !== markup) options.innerHTML = markup;

    const count = root.querySelector(".editor-library-count");
    if (count) count.textContent = `${visible.length} of ${entries.length} props`;
    const empty = root.querySelector(".editor-library-empty");
    if (empty) empty.hidden = visible.length > 0;
  }

  return { bind, sync, reset, setQuery, setSource, setTag, toggleTag, getCriteria, filter };
}
