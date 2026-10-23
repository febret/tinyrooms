/** Escape text and attribute values before adding them to HTML templates. */
export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

/** Position a node by its left/top, writing only changed values to avoid needless style invalidation. */
export function placeAt(node, left, top) {
  if (node.style.left !== left) node.style.left = left;
  if (node.style.top !== top) node.style.top = top;
}

const rendered = new WeakMap();

/** Replace changed markup only, preserving scroll and focus for live updates. */
export function updateMarkup(node, markup) {
  if (rendered.get(node) === markup) return false;
  rendered.set(node, markup);
  const active = node.contains(document.activeElement) ? document.activeElement : null;
  const key = active?.getAttribute("data-focus-key") || active?.getAttribute("name") || active?.id;
  const top = node.scrollTop;
  const left = node.scrollLeft;
  node.innerHTML = markup;
  node.scrollTop = top;
  node.scrollLeft = left;
  if (key) {
    const match = [...node.querySelectorAll("button,input,select,[tabindex]")].find(element =>
      (element.getAttribute("data-focus-key") || element.getAttribute("name") || element.id) === key);
    match?.focus({ preventScroll: true });
  }
  return true;
}
