const GO_EXIT_COMMAND = /^\.go\s+(?:@way:)?(\S+)/;

function actionCommands(actions) {
  return (Array.isArray(actions) ? actions : [])
    .map(action => (Array.isArray(action) ? action[1] : action?.command))
    .filter(command => typeof command === "string");
}

function exitIdForCommand(command) {
  const match = GO_EXIT_COMMAND.exec(String(command).trim());
  return match ? match[1] : null;
}

function definitionById(catalog) {
  return new Map((catalog?.props || [])
    .filter(entry => entry && typeof entry.id === "string")
    .map(entry => [entry.id, entry]));
}

function propExitIds(room, catalog) {
  const definitions = definitionById(catalog);
  const covered = new Set();
  for (const instance of Object.values(room?.props || {})) {
    if (!instance || typeof instance !== "object") continue;
    if (typeof instance.exit_to === "string" && instance.exit_to) covered.add(instance.exit_to);
    for (const command of actionCommands(instance.actions)) {
      const exitId = exitIdForCommand(command);
      if (exitId) covered.add(exitId);
    }
    const definition = definitions.get(instance.prop);
    for (const command of actionCommands(definition?.default_actions)) {
      const exitId = exitIdForCommand(command);
      if (exitId) covered.add(exitId);
    }
  }
  return covered;
}

function exitAccessIssues(room, catalog) {
  const exitIds = Object.keys(room?.exits || {});
  if (!exitIds.length) return [];
  const covered = propExitIds(room, catalog);
  const missing = exitIds.filter(exitId => !covered.has(exitId));
  if (!missing.length) return [];
  const label = missing.length === 1 ? "exit" : "exits";
  return [{
    check: "exit-access",
    message: `No prop quick action reaches ${label}: ${missing.join(", ")}`,
    missing,
  }];
}

const ROOM_CHECKS = [exitAccessIssues];

/** List the quality issues for one room; more checks can be added to ROOM_CHECKS. */
export function roomQualityIssues(room, catalog) {
  return ROOM_CHECKS.flatMap(check => check(room, catalog));
}

/** Map every room id to its quality result, derived live from the draft. */
export function roomQualityReport(draft, catalog) {
  const report = {};
  for (const [roomId, room] of Object.entries(draft?.rooms || {})) {
    const issues = roomQualityIssues(room, catalog);
    report[roomId] = { ok: issues.length === 0, issues };
  }
  return report;
}
