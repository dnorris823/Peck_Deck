// Chart primitives for the Insights section.
//
// Built to fixed mark specs so every chart in the app reads as one system:
//   line 2px round-cap · markers r>=4 with a 2px surface ring · bars capped at
//   24px with a 4px rounded data-end and a square baseline · adjacent bars
//   separated by a 2px surface gap (not a stroke) · area fill ~10% wash ·
//   hairline solid gridlines, recessive.
//
// Colours come from --chart-data / --chart-accent, which are the brand hues
// snapped into the charting lightness band and validated for CVD separation
// and >=3:1 surface contrast in both themes. See styles.css.
//
// Every chart ships a hover layer (crosshair for continuous X, per-mark for
// categorical) plus keyboard focus with the same readout, and every chart has
// a table view so no value is gated behind a pointer.
import React, { useId, useMemo, useRef, useState } from "react";

// ── Tooltip ────────────────────────────────────────────────────────────────
// Values lead, labels follow: the number is the strong element, the label is
// secondary — the legend's hierarchy inverted, because the reader already knows
// the series and wants the value.
function Tooltip({ x, y, rows, title, width }) {
  if (!rows) return null;
  const flip = x > width * 0.6;
  return (
    <div
      className="chart-tip"
      style={{ left: x, top: y, transform: `translate(${flip ? "-100%" : "0"}, -50%)`, marginLeft: flip ? -10 : 10 }}
      role="status"
      aria-live="polite"
    >
      <div className="chart-tip-title">{title}</div>
      {rows.map((r) => (
        <div className="chart-tip-row" key={r.label}>
          <span className="chart-tip-key" style={{ background: r.color }} />
          <span className="chart-tip-value tnum">{r.value}</span>
          <span className="chart-tip-label">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

// Round an axis maximum up to a clean number so ticks read 0 / 5 / 10.
// Forced even so the midpoint tick is a whole number — otherwise a max of 25
// labels its middle gridline "13" while the line itself sits at 12.5.
function niceMax(value) {
  if (value <= 0) return 2;
  const mag = Math.pow(10, Math.floor(Math.log10(value)));
  for (const step of [1, 2, 2.5, 5, 10]) {
    const candidate = step * mag;
    if (candidate >= value) return candidate % 2 === 0 ? candidate : candidate + 1;
  }
  return 10 * mag;
}

function TableToggle({ open, onToggle, id }) {
  return (
    <button
      type="button"
      className="btn ghost sm chart-table-toggle"
      aria-expanded={open}
      aria-controls={id}
      onClick={onToggle}
    >
      {open ? "Hide table" : "View as table"}
    </button>
  );
}

function DataTable({ id, open, caption, columns, rows }) {
  if (!open) return null;
  return (
    <div className="chart-table-wrap" id={id}>
      <table className="chart-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (
                j === 0 ? <th key={j} scope="row">{cell}</th> : <td key={j} className="tnum">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Line / area over a continuous X ────────────────────────────────────────
// Crosshair finds the X: readers aim at a date, never at a 2px line.
export function TrendChart({ labels, values, caption, valueLabel = "visits", height = 180 }) {
  const [hover, setHover] = useState(null);
  const [tableOpen, setTableOpen] = useState(false);
  const tableId = useId();
  const wrapRef = useRef(null);

  const W = 720;
  const H = height;
  const pad = { top: 18, right: 16, bottom: 26, left: 34 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const max = niceMax(Math.max(...values, 1));
  const xAt = (i) => pad.left + (values.length === 1 ? plotW / 2 : (i / (values.length - 1)) * plotW);
  const yAt = (v) => pad.top + plotH - (v / max) * plotH;

  const line = values.map((v, i) => `${xAt(i)},${yAt(v)}`).join(" ");
  const area = `${pad.left},${pad.top + plotH} ${line} ${xAt(values.length - 1)},${pad.top + plotH}`;
  const ticks = [0, max / 2, max];

  // Label only the peak and the endpoint — a number on every point is chaos.
  const peakIdx = values.indexOf(Math.max(...values));
  const lastIdx = values.length - 1;

  const onMove = (e) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const rel = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((rel - pad.left) / plotW) * (values.length - 1));
    const idx = Math.max(0, Math.min(values.length - 1, i));
    setHover({ idx, px: (xAt(idx) / W) * rect.width, py: (yAt(values[idx]) / H) * rect.height });
  };

  return (
    <figure className="chart-figure">
      <div className="chart-wrap" ref={wrapRef}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img" aria-label={caption}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={W - pad.right} y1={yAt(t)} y2={yAt(t)} className="chart-grid-line" />
              <text x={pad.left - 8} y={yAt(t) + 3} className="chart-axis-text" textAnchor="end">
                {Math.round(t)}
              </text>
            </g>
          ))}

          <polyline points={area} fill="var(--chart-fill)" stroke="none" />
          <polyline
            points={line}
            fill="none"
            stroke="var(--chart-data)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* End marker: r>=4 with a 2px surface ring so it stays legible. */}
          <circle cx={xAt(lastIdx)} cy={yAt(values[lastIdx])} r="4.5"
            fill="var(--chart-data)" stroke="var(--chart-surface)" strokeWidth="2" />

          {peakIdx !== lastIdx && values[peakIdx] > 0 && (
            <text x={xAt(peakIdx)} y={yAt(values[peakIdx]) - 10} className="chart-value-label" textAnchor="middle">
              {values[peakIdx]}
            </text>
          )}
          {values[lastIdx] > 0 && (
            <text x={xAt(lastIdx)} y={yAt(values[lastIdx]) - 12} className="chart-value-label" textAnchor="end">
              {values[lastIdx]}
            </text>
          )}

          {[0, Math.floor(labels.length / 2), labels.length - 1].map((i) => (
            <text key={i} x={xAt(i)} y={H - 8} className="chart-axis-text"
              textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"}>
              {labels[i]?.slice(5)}
            </text>
          ))}

          {hover && (
            <line x1={xAt(hover.idx)} x2={xAt(hover.idx)} y1={pad.top} y2={pad.top + plotH}
              className="chart-crosshair" />
          )}
        </svg>

        {hover && (
          <Tooltip
            x={hover.px}
            y={hover.py}
            width={wrapRef.current?.clientWidth ?? W}
            title={labels[hover.idx]}
            rows={[{ label: valueLabel, value: values[hover.idx], color: "var(--chart-data)" }]}
          />
        )}
      </div>

      <figcaption className="chart-caption">
        <span>{caption}</span>
        <TableToggle open={tableOpen} onToggle={() => setTableOpen((v) => !v)} id={tableId} />
      </figcaption>
      <DataTable
        id={tableId}
        open={tableOpen}
        caption={caption}
        columns={["Date", valueLabel]}
        rows={labels.map((l, i) => [l, values[i]])}
      />
    </figure>
  );
}

// ── Columns over a categorical X ───────────────────────────────────────────
// The mark is the hit target; no crosshair.
export function ColumnChart({ labels, values, caption, valueLabel = "visits", emphasisIdx, height = 170 }) {
  const [hover, setHover] = useState(null);
  const [tableOpen, setTableOpen] = useState(false);
  const tableId = useId();
  const wrapRef = useRef(null);

  const W = 720;
  const H = height;
  const pad = { top: 20, right: 12, bottom: 24, left: 34 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const max = niceMax(Math.max(...values, 1));
  const band = plotW / values.length;
  // Cap thickness and reserve a 2px surface gap; leftover band is air.
  const barW = Math.min(24, band - 2);
  const xAt = (i) => pad.left + i * band + (band - barW) / 2;
  const yAt = (v) => pad.top + plotH - (v / max) * plotH;

  return (
    <figure className="chart-figure">
      <div className="chart-wrap" ref={wrapRef}>
        <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img" aria-label={caption}>
          {[0, max / 2, max].map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={W - pad.right} y1={yAt(t)} y2={yAt(t)} className="chart-grid-line" />
              <text x={pad.left - 8} y={yAt(t) + 3} className="chart-axis-text" textAnchor="end">
                {Math.round(t)}
              </text>
            </g>
          ))}

          {values.map((v, i) => {
            const h = Math.max(0, plotH - (yAt(v) - pad.top));
            const emphasised = i === emphasisIdx && v > 0;
            return (
              <g key={i}>
                {/* Hit target spans the full band and full height — bigger than
                    the mark, so short bars are still easy to reach. */}
                <rect
                  x={pad.left + i * band} y={pad.top} width={band} height={plotH}
                  fill="transparent"
                  tabIndex={0}
                  role="button"
                  aria-label={`${labels[i]}: ${v} ${valueLabel}`}
                  onPointerEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                  onBlur={() => setHover(null)}
                />
                {h > 0 && (
                  <rect
                    x={xAt(i)} y={yAt(v)} width={barW} height={h}
                    rx="4" ry="4"
                    className={`chart-bar${hover === i ? " is-hover" : ""}`}
                    fill={emphasised ? "var(--chart-accent)" : "var(--chart-data)"}
                    pointerEvents="none"
                  />
                )}
                {/* Square off the baseline end: only the data-end is rounded. */}
                {h > 4 && (
                  <rect x={xAt(i)} y={pad.top + plotH - 4} width={barW} height="4"
                    fill={emphasised ? "var(--chart-accent)" : "var(--chart-data)"} pointerEvents="none" />
                )}
              </g>
            );
          })}

          {emphasisIdx != null && values[emphasisIdx] > 0 && (
            <text x={xAt(emphasisIdx) + barW / 2} y={yAt(values[emphasisIdx]) - 8}
              className="chart-value-label" textAnchor="middle">
              {values[emphasisIdx]}
            </text>
          )}

          {labels.map((l, i) => (
            i % Math.ceil(labels.length / 8) === 0 ? (
              <text key={i} x={xAt(i) + barW / 2} y={H - 8} className="chart-axis-text" textAnchor="middle">
                {l}
              </text>
            ) : null
          ))}
        </svg>

        {hover != null && (
          <Tooltip
            x={((xAt(hover) + barW / 2) / W) * (wrapRef.current?.clientWidth ?? W)}
            y={(yAt(values[hover]) / H) * (wrapRef.current?.clientHeight ?? H)}
            width={wrapRef.current?.clientWidth ?? W}
            title={labels[hover]}
            rows={[{
              label: valueLabel,
              value: values[hover],
              color: hover === emphasisIdx ? "var(--chart-accent)" : "var(--chart-data)",
            }]}
          />
        )}
      </div>

      <figcaption className="chart-caption">
        <span>{caption}</span>
        <TableToggle open={tableOpen} onToggle={() => setTableOpen((v) => !v)} id={tableId} />
      </figcaption>
      <DataTable
        id={tableId}
        open={tableOpen}
        caption={caption}
        columns={["Hour", valueLabel]}
        rows={labels.map((l, i) => [l, values[i]])}
      />
    </figure>
  );
}

// ── Horizontal bars for a small named set ──────────────────────────────────
// Identity lives on the axis, so one hue — colouring each row would imply a
// categorical encoding the reader doesn't need.
export function BarList({ items, caption, valueLabel = "visits" }) {
  const [tableOpen, setTableOpen] = useState(false);
  const tableId = useId();
  const max = useMemo(() => Math.max(...items.map((i) => i.value), 1), [items]);

  return (
    <figure className="chart-figure">
      <div className="barlist">
        {items.map((item) => (
          <div className="barlist-row" key={item.label}>
            <span className="barlist-label">{item.label}</span>
            <span className="barlist-track">
              <span
                className="barlist-fill"
                style={{ width: `${Math.max(2, (item.value / max) * 100)}%` }}
              />
            </span>
            <span className="barlist-value tnum">{item.value}</span>
          </div>
        ))}
      </div>
      <figcaption className="chart-caption">
        <span>{caption}</span>
        <TableToggle open={tableOpen} onToggle={() => setTableOpen((v) => !v)} id={tableId} />
      </figcaption>
      <DataTable
        id={tableId}
        open={tableOpen}
        caption={caption}
        columns={["Station", valueLabel]}
        rows={items.map((i) => [i.label, i.value])}
      />
    </figure>
  );
}
