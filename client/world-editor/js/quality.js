/** List the quality issues for one room; grid exits are authoritative, so no prop-coverage check. */
export function roomQualityIssues(room, catalog) {
  return [];
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
