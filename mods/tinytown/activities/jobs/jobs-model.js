const OUTCOME_LABELS = [
  { label: "Shift went sideways", stamp: "SHIFT WENT SIDEWAYS" },
  { label: "You survived", stamp: "SHIFT SURVIVED" },
  { label: "Not bad, actually", stamp: "SHIFT COMPLETE" },
  { label: "A very good day", stamp: "SHIFT EXCELLENT" },
  { label: "Employee of the day", stamp: "EMPLOYEE OF THE DAY" },
];

export const MAX_HELPERS = 3;

export function outcomeFor(stepsPassed) {
  const pass = Math.max(0, Math.min(4, Number(stepsPassed) || 0));
  return OUTCOME_LABELS[pass];
}

export function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-US");
}

export function signed(value) {
  const number = Number(value) || 0;
  return number > 0 ? `+${number}` : String(number);
}

export function jobStatusLabel(status) {
  if (status === "completed") return "Filed";
  if (status === "abandoned") return "Walked out";
  if (status === "active") return "In progress";
  return "Open shift";
}

export function toggleHelper(selected, helperId, max = MAX_HELPERS) {
  const current = new Set(selected);
  if (current.has(helperId)) {
    current.delete(helperId);
    return [...current];
  }
  if (current.size >= max) return [...current];
  current.add(helperId);
  return [...current];
}

const ENVIRONMENT_LABELS = { night: "Night", dawn: "Dawn", day: "Daytime", dusk: "Dusk" };

/** Mirror of server.content.lighting.phase_to_environment. */
export function environmentFor(phase) {
  const wrapped = ((Number(phase) % 1) + 1) % 1;
  if (wrapped < 0.2 || wrapped >= 0.9) return "night";
  if (wrapped < 0.3) return "dawn";
  if (wrapped < 0.7) return "day";
  return "dusk";
}

export function formatCountdown(seconds) {
  const total = Math.max(0, Math.ceil(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

/** Describe the board's cycle: "Dusk · new shifts in 3:41". */
export function cycleLabel(remainingSeconds, cycleSeconds) {
  const total = Number(cycleSeconds) || 0;
  if (!total) return "Shift board";
  const remaining = Math.max(0, Math.min(total, Number(remainingSeconds) || 0));
  const environment = ENVIRONMENT_LABELS[environmentFor(1 - remaining / total)];
  return `${environment} · new shifts in ${formatCountdown(remaining)}`;
}
