export const POWER_GLOW_COLORS = Object.freeze({
  admin: "#ffcf5c",
  realtor: "#4ea8ff",
  builder: "#ff9f43",
  moderator: "#5cf29a",
  "game-master": "#c77dff",
});

const DEFAULT_GLOW = Object.freeze({ red: 0, green: 0, blue: 0, radius: 4, alpha: 0.5 });

function parseHex(color) {
  const cleaned = String(color || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(cleaned)) return null;
  return {
    red: parseInt(cleaned.slice(0, 2), 16),
    green: parseInt(cleaned.slice(2, 4), 16),
    blue: parseInt(cleaned.slice(4, 6), 16),
  };
}

/** Combine power colors additively; larger power sets produce a stronger glow. */
export function powerGlow(powers = []) {
  const colors = [...new Set(Array.isArray(powers) ? powers.map(power => String(power)) : [])]
    .map(power => POWER_GLOW_COLORS[power])
    .map(parseHex)
    .filter(Boolean);
  if (!colors.length) return { ...DEFAULT_GLOW };
  const red = Math.min(255, colors.reduce((total, color) => total + color.red, 0));
  const green = Math.min(255, colors.reduce((total, color) => total + color.green, 0));
  const blue = Math.min(255, colors.reduce((total, color) => total + color.blue, 0));
  const strength = colors.length;
  return {
    red,
    green,
    blue,
    radius: 4 + strength * 3,
    alpha: Math.round(Math.min(0.92, 0.48 + strength * 0.18) * 100) / 100,
  };
}

export function powerGlowStyle(powers = []) {
  const glow = powerGlow(powers);
  return `--peep-glow-color: rgb(${glow.red}, ${glow.green}, ${glow.blue}); --peep-glow-blur: ${glow.radius}px; --peep-glow-alpha: ${glow.alpha.toFixed(2)};`;
}
