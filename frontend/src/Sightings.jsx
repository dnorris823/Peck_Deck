// Sightings gallery — filters + day-grouped photo grid. The detail view is
// SightingDetail.jsx.
import React, { useState, useMemo } from "react";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { canDeleteSighting } from "./SightingDetail.jsx";
import {
  confidenceLevel, deleteSightings, downloadExport, fmtDateLabel, fmtDayHeading, fmtTime,
  tierInfo,
} from "./data.js";

// Inclusive lower bound (ms since epoch) for a named range, or 0 for "all time".
export function rangeCutoff(range, now = Date.now()) {
  const DAY = 24 * 60 * 60 * 1000;
  if (range === "today") {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  if (range === "week") return now - 7 * DAY;
  if (range === "month") return now - 30 * DAY;
  return 0; // all
}

// The local calendar day starting at `day`, as [start, next midnight) in ms.
export function dayBounds(day) {
  const start = new Date(day.getFullYear(), day.getMonth(), day.getDate());
  const next = new Date(day.getFullYear(), day.getMonth(), day.getDate() + 1);
  return [start.getTime(), next.getTime()];
}

const RANGES = [
  ["today", "Today"],
  ["week", "7 days"],
  ["month", "30 days"],
  ["all", "All"],
];

// Score plus a plain-words verdict. Each tier is judged against its own
// threshold, because 70% from the GPU tier and 70% from the Pi mean different
// things.
export function ConfidenceChip({ s, long = false }) {
  const level = confidenceLevel(s);
  const tier = tierInfo(s.tier);
  const pct = `${Math.round(s.confidence * 100)}%`;
  const title = level === "sure"
    ? `${pct} from ${tier.long}, above its ${Math.round(tier.threshold * 100)}% bar`
    : `${pct} from ${tier.long}, below the bar for this tier. Treat it as a guess.`;
  return (
    <span className={`conf conf-${level}`} title={title}>
      {pct}{level === "unsure" && <span className="conf-flag">{long ? " · unsure" : "?"}</span>}
    </span>
  );
}

// `selected` is null outside select mode. In select mode a click toggles the
// tile instead of opening it, and `disabled` marks one the user cannot delete.
export function SightingTile({ s, onClick, showDate = false, selected = null, disabled = false }) {
  const selecting = selected !== null;
  return (
    <button type="button" className={`tile${selecting ? " selecting" : ""}${selected ? " selected" : ""}`}
      onClick={() => onClick(s)} disabled={disabled} aria-pressed={selecting ? selected : undefined}
      aria-label={`${s.species.common}, ${fmtTime(s.datetime)}`}>
      <div className="tile-img">
        <SightingImage sighting={s} />
        {selecting && !disabled && <span className="tile-check" aria-hidden="true">{selected ? "✓" : ""}</span>}
        <span className="tile-badge tile-badge-l">{fmtTime(s.datetime)}</span>
        <span className="tile-badge tile-badge-r"><ConfidenceChip s={s} /></span>
      </div>
      <div className="tile-body">
        <div className="tile-name">{s.species.common}</div>
        <div className="tile-foot">
          <span>{showDate ? `${fmtDateLabel(s.datetime)} · ` : ""}{s.device.name}</span>
          <span>{tierInfo(s.tier).short}{s.provisional ? " · provisional" : ""}</span>
        </div>
      </div>
    </button>
  );
}

// Downloads every sighting the signed-in user can see as CSV. The endpoint needs
// the Bearer token, so this fetches a blob and clicks a temporary link.
function ExportCsvButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await downloadExport({ fmt: "csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message || "Export failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn sm" disabled={busy} onClick={run}>
        <Icon name="download" className="" /> {busy ? "Preparing…" : "Export CSV"}
      </button>
      {error && <div className="field-help field-error" role="alert">{error}</div>}
    </>
  );
}

// The bar shown in select mode. Deletes only the selected tiles that the
// filters still show, so a hidden tile never goes by surprise.
function SelectBar({ chosen, selectable, onSelectAll, onClear, onCancel, onDone }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const n = chosen.length;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await deleteSightings(chosen.map(s => s.id));
      await onDone();
    } catch (e) {
      setError(e.message || "Delete failed.");
      setBusy(false);
    }
  }

  return (
    <div className="select-bar card" role="region" aria-label="Selected sightings">
      {confirming ? (
        <>
          <span>Delete {n} sighting{n === 1 ? "" : "s"} and {n === 1 ? "its photo" : "their photos"}? This cannot be undone.</span>
          <span className="select-bar-actions">
            <button className="btn sm" onClick={() => setConfirming(false)}>Keep</button>
            <button className="btn danger sm" onClick={submit} disabled={busy}>
              {busy ? "Deleting…" : `Delete ${n}`}
            </button>
          </span>
        </>
      ) : (
        <>
          <span className="tnum">{n} selected</span>
          <span className="select-bar-actions">
            <button className="btn ghost sm" onClick={onSelectAll} disabled={selectable === 0}>
              Select all shown ({selectable})
            </button>
            {n > 0 && <button className="btn ghost sm" onClick={onClear}>Clear</button>}
            <button className="btn sm" onClick={onCancel}>Cancel</button>
            <button className="btn danger sm" onClick={() => setConfirming(true)} disabled={n === 0}>
              Delete {n}…
            </button>
          </span>
        </>
      )}
      {error && <div className="field-help field-error" role="alert">{error}</div>}
    </div>
  );
}

// Newest-first sightings split into local calendar days.
function groupByDay(sightings) {
  const groups = [];
  for (const s of sightings) {
    const key = s.datetime.toDateString();
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(s);
    else groups.push({ key, date: s.datetime, items: [s] });
  }
  return groups;
}

// `initialDay` opens History on one local day, as Home's yesterday line does.
// That day shows as its own choice before the named ranges.
export function Sightings({ openSighting, initialSpecies = "all", initialDay = null }) {
  const { data, reload } = useData();
  const { SIGHTINGS, SPECIES, DEVICES, ME } = data;
  // Null outside select mode, else the ids ticked so far.
  const [selected, setSelected] = useState(null);
  const [device, setDevice] = useState("all");
  const [species, setSpecies] = useState(initialSpecies);
  // Coming from a species page, start wide: that species' visits may be old.
  const [range, setRange] = useState(initialDay ? "day" : initialSpecies === "all" ? "week" : "all");
  const ranges = initialDay ? [["day", fmtDayHeading(initialDay)], ...RANGES] : RANGES;

  const filtered = useMemo(() => {
    const [from, to] = range === "day" ? dayBounds(initialDay) : [rangeCutoff(range), Infinity];
    return SIGHTINGS.filter(s =>
      (device === "all" || s.device.id === device) &&
      (species === "all" || s.species.id === species) &&
      s.datetime.getTime() >= from && s.datetime.getTime() < to
    );
  }, [SIGHTINGS, device, species, range, initialDay]);

  const groups = useMemo(() => groupByDay(filtered), [filtered]);
  const canDelete = s => canDeleteSighting(s, ME);
  const deletable = filtered.filter(canDelete);
  const chosen = selected ? filtered.filter(s => selected.has(s.id)) : [];

  function clickTile(s) {
    if (!selected) return openSighting(s);
    setSelected(sel => {
      const next = new Set(sel);
      if (next.has(s.id)) next.delete(s.id); else next.add(s.id);
      return next;
    });
  }
  const hasAny = SIGHTINGS.length > 0;
  // Only species that appear in the loaded sightings are worth filtering by.
  const seenSpecies = useMemo(() => {
    const ids = new Set(SIGHTINGS.map(s => s.species.id));
    return SPECIES.filter(s => ids.has(s.id)).sort((a, b) => a.common.localeCompare(b.common));
  }, [SIGHTINGS, SPECIES]);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">Every visit</div>
          <h1 className="page-title">History</h1>
        </div>
        <div className="page-meta">
          <span className="page-meta-num tnum">{filtered.length}</span>
          <span className="label">shown</span>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Time range">
          {ranges.map(([id, label]) => (
            <button key={id} className={range === id ? "active" : ""} aria-pressed={range === id}
              onClick={() => setRange(id)}>{label}</button>
          ))}
        </div>

        {DEVICES.length > 1 && (
          <select value={device} aria-label="Filter by feeder" className="toolbar-select"
            onChange={e => setDevice(e.target.value === "all" ? "all" : Number(e.target.value))}>
            <option value="all">All feeders</option>
            {DEVICES.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        )}

        <select value={species} aria-label="Filter by species" className="toolbar-select"
          onChange={e => setSpecies(e.target.value === "all" ? "all" : Number(e.target.value))}>
          <option value="all">All species</option>
          {seenSpecies.map(s => <option key={s.id} value={s.id}>{s.common}</option>)}
        </select>

        <span className="toolbar-end">
          {!selected && SIGHTINGS.some(canDelete) && (
            <button type="button" className="btn sm" onClick={() => setSelected(new Set())}>Select</button>
          )}
          <ExportCsvButton />
        </span>
      </div>

      {selected && (
        <SelectBar
          chosen={chosen}
          selectable={deletable.length}
          onSelectAll={() => setSelected(new Set(deletable.map(s => s.id)))}
          onClear={() => setSelected(new Set())}
          onCancel={() => setSelected(null)}
          onDone={async () => { await reload(); setSelected(null); }}
        />
      )}

      {groups.length > 0 ? (
        groups.map(g => (
          <section key={g.key} className="day-group">
            <h2 className="day-head">
              <span>{fmtDayHeading(g.date)}</span>
              <span className="label tnum">{g.items.length} visit{g.items.length === 1 ? "" : "s"}</span>
            </h2>
            <div className="gallery">
              {g.items.map(s => (
                <SightingTile key={s.id} s={s} onClick={clickTile}
                  selected={selected ? selected.has(s.id) : null}
                  disabled={!!selected && !canDelete(s)} />
              ))}
            </div>
          </section>
        ))
      ) : hasAny ? (
        <Empty
          icon="🔍"
          title="No sightings match"
          hint="Try a wider time range, or clear the feeder and species filters."
          action={<button className="btn sm" onClick={() => { setRange("all"); setDevice("all"); setSpecies("all"); }}>
            Show everything
          </button>}
        />
      ) : (
        <Empty
          title="No sightings yet"
          hint="When a feeder spots a bird, its photo shows up here."
        />
      )}
    </>
  );
}
