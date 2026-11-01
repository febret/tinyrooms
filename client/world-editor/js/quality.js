const ROOM_CHECKS = [];

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
