import { escapeHtml } from "../presentation.js";
import { modalShell } from "./view-helpers.js";

export function propDetailsView(state) {
  const prop = (state.views?.propId ? state.room?.props.find(entry => entry.id === state.views.propId) : null) || state.room?.props[0];
  if (!prop) return modalShell({ ariaLabel: "Prop Details", title: "Prop Details", body: '<div class="empty-state">No prop selected.</div>' });
  const surfaceSummary = prop.renderKind === "sign"
    ? `<p class="surface-prop-content">${escapeHtml(prop.surface?.content?.text || "New sign")}</p>`
    : prop.renderKind === "whiteboard"
      ? `<p class="surface-prop-content">${(prop.surface?.content?.strokes || []).length} strokes · ${(prop.surface?.content?.texts || []).length} notes</p>`
      : "";
  const isBuiltinExit = prop.renderKind === "door" || prop.renderKind === "arrow" || prop.renderKind === "stairs";
  return modalShell({
    extraClass: "prop-details-view",
    ariaLabel: "Prop Details",
    title: prop.label,
    subtitleHtml: `<p>${escapeHtml(prop.description)}</p>`,
    body: `
      <div class="prop-details-body">
        ${prop.text ? `<p class="text-prop-content">${escapeHtml(prop.text.content)}</p>` : prop.renderKind === "sign" || prop.renderKind === "whiteboard" ? surfaceSummary : isBuiltinExit ? `<p class="surface-prop-content">${escapeHtml(prop.label)} (procedural exit marker)</p>` : `<canvas class="prop-preview-canvas" data-prop-model="${escapeHtml(prop.modelUrl || "")}" data-prop-scale="${escapeHtml(prop.scale)}" data-prop-interactive="true" aria-label="${escapeHtml(prop.label)} model. Drag to rotate."></canvas>`}
        <dl class="details-metrics">
          <div><dt>Type</dt><dd>${prop.behavior ? escapeHtml(prop.behavior) : (prop.quickActions.length ? "Interactive" : "Decorative")}</dd></div>
          <div><dt>Animation</dt><dd>${escapeHtml(prop.animation || "None")}</dd></div>
        </dl>
      </div>
    `,
  });
}
