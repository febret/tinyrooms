function resolveBackgroundUrl(backgroundPath) {
  if (!backgroundPath) return "";
  if (backgroundPath.startsWith("/") || backgroundPath.startsWith("http://") || backgroundPath.startsWith("https://")) {
    return backgroundPath;
  }
  return "/world/images/" + backgroundPath;
}

function resolveAssetUrl(assetPath) {
  if (!assetPath) return "";
  if (assetPath.startsWith("/") || assetPath.startsWith("http://") || assetPath.startsWith("https://")) {
    return assetPath;
  }
  return "/world/" + assetPath;
}

// Attach or detach drag handlers on a DOM node for a given entity.
// beginDrag and beginTouchDrag are defined in stage.js.
function configureDragHandlers(node, entityType, entityId, isEnabled) {
  node.draggable = !!isEnabled;
  node.ondragstart = null;
  node.onpointerdown = null;
  node.style.touchAction = isEnabled ? "none" : "";
  if (!isEnabled) return;
  node.ondragstart = ev => beginDrag(ev, entityType, entityId);
  node.onpointerdown = ev => beginTouchDrag(ev, entityType, entityId);
}
