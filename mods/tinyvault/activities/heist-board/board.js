export function normalizeBoard(payload) {
  const board = payload?.board || payload || {};
  return {
    heat: Number(board.heat || 0),
    jobs: Array.isArray(board.jobs) ? board.jobs : [],
    tools: Array.isArray(board.tools) ? board.tools : [],
    bots: Array.isArray(board.bots) ? board.bots : [],
    active: board.active || { active: false },
  };
}

export function jobSummary(job) {
  const guards = Number(job.guard_count || 0);
  const cameras = Number(job.camera_count || 0);
  const lasers = Number(job.laser_count || 0);
  return `${guards} guards · ${cameras} cameras · ${lasers} lasers · ${job.estimated_loot || 0} est. loot`;
}

export function crewSummary(active) {
  if (!active || !active.active) return "No active job.";
  const crew = Array.isArray(active.crew) ? active.crew : [];
  const names = crew.map(member => `${member.username} (${member.status})`).join(", ");
  return `${active.label} · ${active.phase} · alarm ${active.alarm} · crew: ${names || "none"}`;
}
