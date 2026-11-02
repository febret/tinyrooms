import { encode } from "uqr";

/** Render *text* as a compact, CSS-scalable QR SVG. */
export function qrSvg(text, { ecc = "M", border = 2 } = {}) {
  const value = String(text || "");
  if (!value) return "";
  const qr = encode(value, { ecc, border });
  const size = qr.size;
  const segments = [];
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if (!qr.data[y][x]) continue;
      segments.push(`M${x} ${y}h1v1h-1z`);
    }
  }
  return `<svg class="qr-code" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges" aria-hidden="true" focusable="false"><rect width="${size}" height="${size}" fill="#f7f1dc"/><path d="${segments.join("")}" fill="#10242b"/></svg>`;
}
