// The 24-hour dial on the species page. Noon sits at the top and midnight at
// the bottom, so the day reads clockwise from the left. Each local hour with a
// visit gets a petal, sized and shaded by its count against the busiest hour.
import React from "react";
import { fmtHour } from "./speciesData.js";

const SIZE = 200;
const C = SIZE / 2;
const R = C - 16; // face radius, leaving room for the labels
const P0 = 26; // petals start here, so the centre stays clear

// The shaded night wedge is a fixed cue, 6 pm to 7 am, as in the mockup. It
// marks roughly where dark falls. It is not a sunset time.
const NIGHT = [18, 7];

const LABELS = [[12, "NOON"], [18, "6P"], [0, "12A"], [6, "6A"]];

/** The point at radius `r` for clock hour `h`, which may be fractional. */
export function dialPoint(r, h) {
  const t = ((h - 12) / 24) * 2 * Math.PI;
  return [C + r * Math.sin(t), C - r * Math.cos(t)];
}

const fmt = ([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`;

function sector(r, from, to) {
  const span = (((to - from) % 24) + 24) % 24;
  const large = span > 12 ? 1 : 0;
  return `M${C} ${C}L${fmt(dialPoint(r, from))}A${r} ${r} 0 ${large} 1 ${fmt(dialPoint(r, to))}Z`;
}

/**
 * The petal for hour `h`, out to radius `r`. It fills the hour's slice, h:00 to
 * h:59, with a small gap either side.
 */
export function petalPath(h, r) {
  const a = h + 0.08;
  const b = h + 0.92;
  return `M${fmt(dialPoint(P0, a))}L${fmt(dialPoint(r, a))}A${r} ${r} 0 0 1 ${fmt(dialPoint(r, b))}L${fmt(dialPoint(P0, b))}Z`;
}

export function HourDial({ counts, busiest, loading = false }) {
  const max = Math.max(0, ...(counts || []));
  const label = max === 0
    ? "Visits by hour of day. No visits in this period."
    : `Visits by hour of day. Busiest at ${fmtHour(busiest)}.`;

  return (
    <svg className={`sv-dial ${loading ? "loading" : ""}`} viewBox={`0 0 ${SIZE} ${SIZE}`}
      role="img" aria-label={label}>
      <circle cx={C} cy={C} r={R} fill="var(--face)" stroke="var(--line)" />
      <path d={sector(R, NIGHT[0], NIGHT[1])} fill="var(--night)" />
      {Array.from({ length: 24 }, (_, h) => {
        const major = h % 6 === 0;
        const [x1, y1] = dialPoint(R, h);
        const [x2, y2] = dialPoint(R - (major ? 8 : 4), h);
        return (
          <line key={h} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="var(--mu)" strokeWidth={major ? 2 : 1} opacity={0.6} />
        );
      })}
      {LABELS.map(([h, text]) => {
        const [x, y] = dialPoint(R + 9, h);
        return (
          <text key={h} x={x} y={y} textAnchor="middle" dominantBaseline="middle"
            fill="var(--mu)" fontSize={9} fontWeight={700}>{text}</text>
        );
      })}
      {max > 0 && counts.map((v, h) => {
        if (v === 0) return null;
        const r = P0 + ((R - P0 - 3) * v) / max;
        return (
          <path key={h} className="sv-petal" d={petalPath(h, r)}
            fill="var(--acc)" opacity={0.3 + (0.7 * v) / max}>
            <title>{`${fmtHour(h)}: ${v.toLocaleString()} ${v === 1 ? "visit" : "visits"}`}</title>
          </path>
        );
      })}
    </svg>
  );
}
