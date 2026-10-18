export const GRADE_COUNT = 8;
export const STARTING_GRADE = 1;

export function normalizeGrade(value, gradeCount = GRADE_COUNT) {
  const grade = Number.parseInt(value, 10);
  if (!Number.isFinite(grade)) return STARTING_GRADE;
  return Math.min(Math.max(grade, STARTING_GRADE), gradeCount);
}

export function gradeName(grade) {
  return `Grade ${normalizeGrade(grade)}`;
}

export function floorsOf(doors, gradeCount = GRADE_COUNT) {
  const floors = Array.from({ length: gradeCount }, () => []);
  for (const door of Array.isArray(doors) ? doors : []) {
    if (!door) continue;
    floors[normalizeGrade(door.grade, gradeCount) - 1].push(door);
  }
  return floors;
}

export function isAcquirable(grade) {
  return normalizeGrade(grade) === STARTING_GRADE;
}
