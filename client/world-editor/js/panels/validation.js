import { escapeHtml } from "../util.js";

export function renderValidation(report) {
  if (!report) {
    return '<p class="empty-state">Run Validate to check the draft against the content loaders.</p>';
  }
  if (report.valid) {
    return '<p class="ok">No validation errors. The draft is ready to publish.</p>';
  }
  return `
    <ul class="validation-list">
      ${report.errors.map(error => `
        <li><code>${escapeHtml(error.path)}</code><span>${escapeHtml(error.message)}</span></li>
      `).join("")}
    </ul>
  `;
}
