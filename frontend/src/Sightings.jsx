// Sightings gallery — filters + tile grid + detail modal
import React, { useState, useMemo } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { SIGHTINGS, SPECIES, SPECIES_COUNTS, DEVICES, fmtTime, fmtDateLabel } from "./data.js";

function SightingTile({ s, onClick }) {
  const conf = s.confidence;
  const cls = conf >= 0.9 ? "conf-high" : conf >= 0.78 ? "conf-mid" : "conf-low";
  return (
    <div className="tile" onClick={() => onClick(s)}>
      <div className="tile-img">
        <BirdPlate species={s.species} showLabel={false} />
        <span className="corner">{fmtTime(s.datetime)}</span>
        <span className={`corner corner-r feed-conf ${cls}`} style={{ background: undefined, padding: "3px 6px" }}>
          {Math.round(conf * 100)}%
        </span>
        {s.hasVideo && (
          <span className="corner" style={{ top: "auto", bottom: 8, left: 8 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Icon name="play" className="" /> CLIP
            </span>
          </span>
        )}
      </div>
      <div className="tile-body">
        <div className="tile-name">{s.species.common}</div>
        <div className="tile-foot">
          <span className="tile-time">{fmtDateLabel(s.datetime)} · {s.device.name}</span>
          <span className="tile-time" style={{ color: "var(--ink-soft)" }}>{s.tier.toUpperCase()}</span>
        </div>
      </div>
    </div>
  );
}

export function SightingDetail({ s, onClose }) {
  if (!s) return null;
  const conf = s.confidence;
  const cls = conf >= 0.9 ? "conf-high" : conf >= 0.78 ? "conf-mid" : "conf-low";
  const speciesCount = SPECIES_COUNTS.find(x => x.id === s.species.id)?.count || 1;
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}><Icon name="x" className="" /></button>
        <div className="modal-grid">
          <div className="modal-img">
            <BirdPlate species={s.species} showLabel={false} large />
            <div style={{ position: "absolute", bottom: 14, left: 16, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.16em", color: "rgba(28,38,32,0.75)", textTransform: "uppercase" }}>
              Plate № {String(s.id).padStart(4, "0")}
            </div>
            {s.hasVideo && (
              <button className="btn primary sm" style={{ position: "absolute", bottom: 14, right: 16 }}>
                <Icon name="play" className="" /> Play 7s clip
              </button>
            )}
          </div>
          <div className="modal-side">
            <div className="label" style={{ marginBottom: 8 }}>Sighting · {s.tier.toUpperCase()} tier</div>
            <h2 className="display" style={{ fontSize: 38, lineHeight: 1, margin: 0 }}>
              {s.species.common}
            </h2>
            <div className="display-i" style={{ fontSize: 17, color: "var(--ink-soft)", marginTop: 4 }}>
              {s.species.sci}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--hairline)" }}>
              <div>
                <div className="label">Confidence</div>
                <div className={`feed-conf ${cls}`} style={{ marginTop: 6, fontSize: 12 }}>
                  {Math.round(conf * 100)}% · {s.tier === "local" ? "iNatVision TFLite" : s.tier === "gpu" ? "EfficientNet-B4 GPU" : "Claude Sonnet 4.5"}
                </div>
              </div>
              <div>
                <div className="label">Captured</div>
                <div style={{ marginTop: 6 }}>{fmtDateLabel(s.datetime)} · {fmtTime(s.datetime)}</div>
              </div>
              <div>
                <div className="label">Station</div>
                <div style={{ marginTop: 6 }}>{s.device.name}</div>
              </div>
              <div>
                <div className="label">Visits this species</div>
                <div className="display-i" style={{ marginTop: 4, fontSize: 22 }}>{speciesCount}</div>
              </div>
            </div>

            <p style={{ fontSize: 13.5, color: "var(--ink-soft)", marginTop: 22, lineHeight: 1.55 }}>
              {s.species.note}
            </p>

            <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
              <a className="btn" href={s.species.wiki} target="_blank" rel="noopener">
                <Icon name="extlink" className="" /> Wikipedia
              </a>
              <button className="btn"><Icon name="download" className="" /> Download</button>
              <button className="btn ghost" style={{ marginLeft: "auto" }}>Misidentified?</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Sightings({ openSighting }) {
  const [device, setDevice] = useState("all");
  const [species, setSpecies] = useState("all");
  const [range, setRange] = useState("week");

  const filtered = useMemo(() => {
    return SIGHTINGS.filter(s =>
      (device === "all" || s.device.id === device) &&
      (species === "all" || s.species.id === species)
    );
  }, [device, species]);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Field Records</div>
          <h1 className="page-title">All <em>sightings</em></h1>
        </div>
        <div className="page-meta">
          <div className="label">Showing</div>
          <div className="page-meta-row">
            <span className="page-meta-num tnum">{filtered.length}</span>
            <span className="display-i" style={{ fontSize: 18, color: "var(--ink-soft)" }}>
              of {SIGHTINGS.length}
            </span>
          </div>
        </div>
      </div>

      <div className="toolbar">
        <button className={`chip ${range === "today" ? "active" : ""}`} onClick={() => setRange("today")}>Today</button>
        <button className={`chip ${range === "week" ? "active" : ""}`} onClick={() => setRange("week")}>This week</button>
        <button className={`chip ${range === "month" ? "active" : ""}`} onClick={() => setRange("month")}>This month</button>
        <button className={`chip ${range === "all" ? "active" : ""}`} onClick={() => setRange("all")}>All time</button>

        <span style={{ width: 1, height: 22, background: "var(--hairline-strong)", margin: "0 4px" }} />

        <button className={`chip ${device === "all" ? "active" : ""}`} onClick={() => setDevice("all")}>
          <Icon name="device" className="" /> All stations
        </button>
        {DEVICES.map(d => (
          <button key={d.id} className={`chip ${device === d.id ? "active" : ""}`} onClick={() => setDevice(d.id)}>
            {d.name}
          </button>
        ))}

        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <select value={species} onChange={e => setSpecies(e.target.value === "all" ? "all" : Number(e.target.value))}
            style={{ width: 200 }}>
            <option value="all">All species</option>
            {SPECIES.map(s => <option key={s.id} value={s.id}>{s.common}</option>)}
          </select>
          <button className="btn sm"><Icon name="download" className="" /> Export</button>
        </span>
      </div>

      <div className="gallery">
        {filtered.map(s => <SightingTile key={s.id} s={s} onClick={openSighting} />)}
      </div>
    </>
  );
}
