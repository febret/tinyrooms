import { escapeHtml } from "../presentation.js";
import { modalShell } from "./view-helpers.js";

export function propDetailsView(state) {
  const prop = state.room?.props.find(entry => entry.id === state.selection.id) || state.room?.props[0];
  if (!prop) return modalShell({ ariaLabel: "Prop Details", title: "Prop Details", body: '<div class="empty-state">No prop selected.</div>' });
  return modalShell({
    extraClass: "prop-details-view",
    ariaLabel: "Prop Details",
    title: escapeHtml(prop.label),
    subtitle: `<p>${escapeHtml(prop.description)}</p>`,
    body: `
      <div class="prop-details-body">
        <canvas class="prop-preview-canvas" data-prop-model="${escapeHtml(prop.modelUrl || "")}" data-prop-scale="${escapeHtml(prop.scale)}" data-prop-interactive="true" aria-label="${escapeHtml(prop.label)} model. Drag to rotate."></canvas>
        <dl class="details-metrics">
          <div><dt>Type</dt><dd>${prop.behavior ? escapeHtml(prop.behavior) : (prop.quickActions.length ? "Interactive" : "Decorative")}</dd></div>
          <div><dt>Animation</dt><dd>${escapeHtml(prop.animation || "None")}</dd></div>
        </dl>
        ${prop.quickActions.length ? `<div class="action-pills">${prop.quickActions.map(action => `<button type="button" class="quiet" data-prop-command="${escapeHtml(action.command)}">${escapeHtml(action.label)}</button>`).join("")}</div>` : ""}
      </div>
    `,
  });
}
