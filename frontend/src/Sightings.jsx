// Sightings gallery — filters + day-grouped photo grid + detail modal
import React, { useRef, useState, useMemo } from "react";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useDialog } from "./Modal.jsx";
import { useData } from "./DataContext.jsx";
import { apiObjectUrl } from "./api.js";
import {
  confidenceLevel, deleteSighting, downloadExport, fmtDateLabel, fmtDayHeading, fmtRelative,
  fmtTime, tierInfo,
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

export function SightingTile({ s, onClick, showDate = false }) {
  return (
    <button type="button" className="tile" onClick={() => onClick(s)}
      aria-label={`${s.species.common}, ${fmtTime(s.datetime)}`}>
      <div className="tile-img">
        <SightingImage sighting={s} />
        <span className="tile-badge tile-badge-l">{fmtTime(s.datetime)}</span>
        <span className="tile-badge tile-badge-r"><ConfidenceChip s={s} /></span>
      </div>
      <div className="tile-body">
        <div className="tile-name">{s.species.common}</div>
        <div className="tile-foot">
          <span>{showDate ? `${fmtDateLabel(s.datetime)} · ` : ""}{s.device.name}</span>
          <span>{tierInfo(s.tier).short}</span>
        </div>
      </div>
    </button>
  );
}

// Saves the original capture. Same reason as the CSV export: the image route
// needs the Bearer token, so it goes through fetch and a temporary link.
function DownloadPhotoButton({ s }) {
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      const url = await apiObjectUrl(`/sightings/${s.id}/image`);
      const a = document.createElement("a");
      a.href = url;
      a.download = `peck-deck-${s.id}-${s.species.common.replace(/\W+/g, "-").toLowerCase()}.jpg`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      /* The button stays; a second try is the only useful recovery. */
    } finally {
      setBusy(false);
    }
  }
  return (
    <button className="btn" onClick={run} disabled={busy}>
      <Icon name="download" className="" /> {busy ? "Saving…" : "Save photo"}
    </button>
  );
}

// The device owner or an owner-role user may delete. The route enforces the
// same rule; this only hides a button that would get a 403.
export function canDeleteSighting(s, me) {
  return me.role === "owner" || s.device.ownerId === me.id;
}

// Two clicks, so a stray tap can't remove a capture. Kept plain on purpose: the
// detail view is due a rebuild, and the route is the part that lasts.
function DeleteSightingButton({ s, onDeleted }) {
  const { applyDeleted } = useData();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await deleteSighting(s.id);
    } catch (e) {
      setError(e.message || "Delete failed.");
      setBusy(false);
      return;
    }
    applyDeleted(s.id);
    onDeleted();
  }

  if (!confirming) {
    return (
      <button type="button" className="btn ghost" onClick={() => setConfirming(true)}>
        Delete
      </button>
    );
  }
  return (
    <>
      <button type="button" className="btn cardinal" onClick={run} disabled={busy}>
        {busy ? "Deleting…" : "Delete this sighting"}
      </button>
      <button type="button" className="btn ghost" onClick={() => setConfirming(false)} disabled={busy}>
        Cancel
      </button>
      {error && <div className="field-help field-error" role="alert">{error}</div>}
    </>
  );
}

export function SightingDetail({ s, onClose }) {
  const { data } = useData();
  const panelRef = useRef(null);
  useDialog(onClose, panelRef);
  if (!s) return null;
  const tier = tierInfo(s.tier);
  const speciesCount = data.SPECIES_COUNTS.find(x => x.id === s.species.id)?.count || 1;
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}
        ref={panelRef} role="dialog" aria-modal="true" aria-label={`${s.species.common} sighting`} tabIndex={-1}>
        <button className="modal-close" onClick={onClose} aria-label="Close dialog"><Icon name="x" className="" /></button>
        <div className="modal-grid">
          <div className="modal-img">
            <SightingImage sighting={s} large />
          </div>
          <div className="modal-side">
            <div className="label">Sighting № {String(s.id).padStart(4, "0")}</div>
            <h2 className="modal-title">{s.species.common}</h2>
            <div className="modal-sci">{s.species.sci}</div>

            <dl className="facts">
              <div>
                <dt className="label">Confidence</dt>
                <dd><ConfidenceChip s={s} long /></dd>
              </div>
              <div>
                <dt className="label">Identified by</dt>
                <dd>{tier.long}</dd>
              </div>
              <div>
                <dt className="label">Captured</dt>
                <dd>{fmtDateLabel(s.datetime)}, {fmtTime(s.datetime)}
                  <span className="facts-sub"> · {fmtRelative(s.datetime)}</span></dd>
              </div>
              <div>
                <dt className="label">Station</dt>
                <dd>{s.device.name}</dd>
              </div>
              <div>
                <dt className="label">Visits, this species</dt>
                <dd className="tnum">{speciesCount.toLocaleString()}</dd>
              </div>
            </dl>

            {s.species.note && <p className="modal-note">{s.species.note}</p>}

            <div className="modal-actions">
              {s.hasImage && <DownloadPhotoButton s={s} />}
              {s.species.wiki && (
                <a className="btn ghost" href={s.species.wiki} target="_blank" rel="noopener noreferrer">
                  <Icon name="extlink" className="" /> Wikipedia
                </a>
              )}
              {canDeleteSighting(s, data.ME) && <DeleteSightingButton s={s} onDeleted={onClose} />}
            </div>
          </div>
        </div>
      </div>
    </div>
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

export function Sightings({ openSighting, initialSpecies = "all" }) {
  const { data } = useData();
  const { SIGHTINGS, SPECIES, DEVICES } = data;
  const [device, setDevice] = useState("all");
  const [species, setSpecies] = useState(initialSpecies);
  // Coming from a species page, start wide: that species' visits may be old.
  const [range, setRange] = useState(initialSpecies === "all" ? "week" : "all");

  const filtered = useMemo(() => {
    const cutoff = rangeCutoff(range);
    return SIGHTINGS.filter(s =>
      (device === "all" || s.device.id === device) &&
      (species === "all" || s.species.id === species) &&
      s.datetime.getTime() >= cutoff
    );
  }, [SIGHTINGS, device, species, range]);

  const groups = useMemo(() => groupByDay(filtered), [filtered]);
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
          <div className="label">Field records</div>
          <h1 className="page-title">All <em>sightings</em></h1>
        </div>
        <div className="page-meta">
          <span className="page-meta-num tnum">{filtered.length}</span>
          <span className="label">shown</span>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Time range">
          {RANGES.map(([id, label]) => (
            <button key={id} className={range === id ? "active" : ""} aria-pressed={range === id}
              onClick={() => setRange(id)}>{label}</button>
          ))}
        </div>

        {DEVICES.length > 1 && (
          <select value={device} aria-label="Filter by station" className="toolbar-select"
            onChange={e => setDevice(e.target.value === "all" ? "all" : Number(e.target.value))}>
            <option value="all">All stations</option>
            {DEVICES.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        )}

        <select value={species} aria-label="Filter by species" className="toolbar-select"
          onChange={e => setSpecies(e.target.value === "all" ? "all" : Number(e.target.value))}>
          <option value="all">All species</option>
          {seenSpecies.map(s => <option key={s.id} value={s.id}>{s.common}</option>)}
        </select>

        <span className="toolbar-end"><ExportCsvButton /></span>
      </div>

      {groups.length > 0 ? (
        groups.map(g => (
          <section key={g.key} className="day-group">
            <h2 className="day-head">
              <span>{fmtDayHeading(g.date)}</span>
              <span className="label tnum">{g.items.length} visit{g.items.length === 1 ? "" : "s"}</span>
            </h2>
            <div className="gallery">
              {g.items.map(s => <SightingTile key={s.id} s={s} onClick={openSighting} />)}
            </div>
          </section>
        ))
      ) : hasAny ? (
        <Empty
          icon="🔍"
          title="No sightings match"
          hint="Try a wider time range, or clear the station and species filters."
          action={<button className="btn sm" onClick={() => { setRange("all"); setDevice("all"); setSpecies("all"); }}>
            Show everything
          </button>}
        />
      ) : (
        <Empty
          title="No sightings yet"
          hint="When a station spots a bird, its photo shows up here."
        />
      )}
    </>
  );
}
