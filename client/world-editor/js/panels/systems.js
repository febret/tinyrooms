import { escapeHtml, selectOptions } from "../util.js";

function header(title, subtitle) {
  return `<header class="properties-head"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(subtitle || "")}</p></header>`;
}

function field(label, input) {
  return `<label class="field"><span>${escapeHtml(label)}</span>${input}</label>`;
}

function text(value, attrs) {
  return `<input type="text" ${attrs} value="${escapeHtml(value ?? "")}">`;
}

function area(value, attrs, rows = 3) {
  return `<textarea ${attrs} rows="${rows}">${escapeHtml(value ?? "")}</textarea>`;
}

export function renderTasks(draft) {
  const tasks = draft.tasks || {};
  const entries = Object.entries(tasks);
  return `
    ${header("Tasks", "Ordered steps and rewards")}
    <div class="properties-body">
      ${entries.map(([taskId, task]) => {
        const reward = task.reward && typeof task.reward === "object" ? task.reward : {};
        return `
          <fieldset class="subgroup">
            <legend><code>${escapeHtml(taskId)}</code></legend>
            ${field("Title", text(task.title, `data-task-field="${escapeHtml(taskId)}:title"`))}
            ${field("Description", area(task.description, `data-task-field="${escapeHtml(taskId)}:description"`, 2))}
            ${field("Scope", `<select data-task-field="${escapeHtml(taskId)}:scope">${selectOptions(["personal", "shared"], task.scope || "personal")}</select>`)}
            ${field("Revision", `<input type="number" data-task-field="${escapeHtml(taskId)}:revision" value="${escapeHtml(task.revision ?? 1)}">`)}
            ${field("Memory tags (comma)", text((task.memory_tags || []).join(", "), `data-task-field="${escapeHtml(taskId)}:memory_tags"`))}
            ${field("Reward kudos", `<input type="number" data-task-field="${escapeHtml(taskId)}:reward.kudos" value="${escapeHtml(reward.kudos ?? 0)}">`)}
            ${field("Reward cards (comma)", text((reward.cards || []).join(", "), `data-task-field="${escapeHtml(taskId)}:reward.cards"`))}
            ${field("Steps (JSON)", area(JSON.stringify(task.steps || [], null, 2), `data-task-field="${escapeHtml(taskId)}:steps"`, 5))}
            <button type="button" class="negative" data-task-delete="${escapeHtml(taskId)}">Delete task</button>
          </fieldset>
        `;
      }).join("") || '<p class="empty-state">No tasks.</p>'}
      <button type="button" class="quiet" data-task-add>Add task</button>
    </div>
  `;
}

export function renderRecipes(draft) {
  const recipes = draft.recipes || {};
  const entries = Object.entries(recipes);
  return `
    ${header("Recipes", "Ingredients and outputs")}
    <div class="properties-body">
      ${entries.map(([recipeId, recipe]) => `
        <fieldset class="subgroup">
          <legend><code>${escapeHtml(recipeId)}</code></legend>
          ${field("Label", text(recipe.label, `data-recipe-field="${escapeHtml(recipeId)}:label"`))}
          ${field("Description", area(recipe.description, `data-recipe-field="${escapeHtml(recipeId)}:description"`, 2))}
          ${field("Energy cost", `<input type="number" data-recipe-field="${escapeHtml(recipeId)}:energy_cost" value="${escapeHtml(recipe.energy_cost ?? 0)}">`)}
          ${field("Ingredients (JSON)", area(JSON.stringify(recipe.ingredients || {}, null, 2), `data-recipe-field="${escapeHtml(recipeId)}:ingredients"`, 4))}
          ${field("Output (JSON)", area(JSON.stringify(recipe.output || {}, null, 2), `data-recipe-field="${escapeHtml(recipeId)}:output"`, 3))}
          <button type="button" class="negative" data-recipe-delete="${escapeHtml(recipeId)}">Delete recipe</button>
        </fieldset>
      `).join("") || '<p class="empty-state">No recipes.</p>'}
      <button type="button" class="quiet" data-recipe-add>Add recipe</button>
    </div>
  `;
}

export function renderActivities(draft) {
  const activities = draft.activities || {};
  const entries = Object.entries(activities);
  return `
    ${header("Activities", "World activity definitions")}
    <div class="properties-body">
      ${entries.map(([activityId, activity]) => `
        <fieldset class="subgroup">
          <legend><code>${escapeHtml(activityId)}</code></legend>
          ${field("Title", text(activity.title, `data-activity-field="${escapeHtml(activityId)}:title"`))}
          <label class="mini-check"><input type="checkbox" data-activity-field="${escapeHtml(activityId)}:room_bound"${activity.room_bound ? " checked" : ""}> room bound</label>
          ${field("Rooms (comma)", text((activity.rooms || []).join(", "), `data-activity-field="${escapeHtml(activityId)}:rooms"`))}
          ${field("Aliases (comma)", text((activity.aliases || []).join(", "), `data-activity-field="${escapeHtml(activityId)}:aliases"`))}
          ${field("Required feature", text(activity.required_feature || "", `data-activity-field="${escapeHtml(activityId)}:required_feature"`))}
          <button type="button" class="negative" data-activity-delete="${escapeHtml(activityId)}">Delete activity</button>
        </fieldset>
      `).join("") || '<p class="empty-state">No world activities.</p>'}
      <button type="button" class="quiet" data-activity-add>Add activity</button>
    </div>
  `;
}

export function renderEnvironment(draft) {
  const rooms = draft.rooms || {};
  return `
    ${header("Environment", "Per-room visual overrides and auras")}
    <div class="properties-body">
      ${Object.entries(rooms).map(([roomId, room]) => {
        const environment = room.editor && Array.isArray(room.editor.environment) ? room.editor.environment : [];
        return `
          <fieldset class="subgroup">
            <legend><code>${escapeHtml(roomId)}</code></legend>
            <label class="mini-check"><input type="checkbox" data-env-room="${escapeHtml(roomId)}" data-env-key="palette"${environment.includes("palette") ? " checked" : ""}> palette</label>
            <label class="mini-check"><input type="checkbox" data-env-room="${escapeHtml(roomId)}" data-env-key="board_image_style"${environment.includes("board_image_style") ? " checked" : ""}> board_image_style</label>
            ${field("Aura (JSON list)", area(JSON.stringify(room.aura || [], null, 2), `data-env-aura="${escapeHtml(roomId)}"`, 3))}
          </fieldset>
        `;
      }).join("")}
      <p class="note">Core gameplay values (juice, levels, bops, stats, statuses) are read-only in the editor.</p>
    </div>
  `;
}
