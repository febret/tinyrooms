/** Health-based wear tiers shown on sidebar peep markers. */

export const DAMAGE_THRESHOLDS = Object.freeze([
  Object.freeze([0.05, 4]),
  Object.freeze([0.10, 3]),
  Object.freeze([0.25, 2]),
  Object.freeze([0.50, 1]),
]);

/** Map a peep counter payload to a wear tier 0-4 (0 = pristine). */
export function peepDamageTier(counters) {
  const health = Number(counters?.health);
  const maximum = Number(counters?.maxHealth);
  if (!Number.isFinite(health) || !Number.isFinite(maximum) || maximum <= 0) return 0;
  const ratio = health / maximum;
  for (const [threshold, tier] of DAMAGE_THRESHOLDS) {
    if (ratio < threshold) return tier;
  }
  return 0;
}
