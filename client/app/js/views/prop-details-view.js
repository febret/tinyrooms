import { isExitProp } from "../exit-props.js";
import { escapeHtml } from "../presentation.js";
import { entityDetailsBody } from "./entity-details-view.js";
import { modalShell } from "./view-helpers.js";

export function propDetailsView(state) {
  const prop = (state.views?.propId ? state.room?.props.find(entry => entry.id === state.views.propId) : null) || state.room?.props[0];
  if (!prop) return modalShell({ ariaLabel: "Prop Details", title: "Prop Details", body: '<div class="empty-state">No prop selected.</div>' });
  const isBuiltinExit = isExitProp(prop);
  const preview = prop.renderKind === "sign"
    ? { imageUrl: "", modelUrl: "", description: prop.surface?.content?.text || "New sign" }
    : prop.renderKind === "whiteboard"
      ? { imageUrl: prop.surface?.content?.image_url || prop.surface?.content?.image || "", modelUrl: "", description: prop.description }
      : prop.text
        ? { imageUrl: "", modelUrl: "", description: prop.text.content }
        : isBuiltinExit
          ? { imageUrl: "", modelUrl: "", description: prop.description }
          : { imageUrl: "", modelUrl: prop.modelUrl || "", scale: prop.scale, description: prop.description };
  return modalShell({
    extraClass: "prop-details-view entity-details-view",
    ariaLabel: "Prop Details",
    title: prop.label,
    subtitleHtml: `<p class="entity-details-description">${escapeHtml(preview.description || prop.description)}</p>`,
    body: entityDetailsBody({
      title: prop.label,
      description: "",
      imageUrl: preview.imageUrl,
      modelUrl: preview.modelUrl,
      scale: preview.scale,
    }),
  });
}
