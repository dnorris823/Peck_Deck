// Animals — daily animal visits on one feeder, stacked by group, with a marker
// at each measure the owner logged, and a card per measure saying what changed
// after it. One feeder has no control group, so the cards say "after".
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useData } from "./DataContext.jsx";
import { Empty } from "./Empty.jsx";
import { FormNote, SelectInput, TextInput } from "./Modal.jsx";
import { canManageFeeder } from "./feederAccess.js";
import {
  browserZone, createMeasure, deleteMeasure, fetchAnimalStats, updateMeasure,
} from "./data.js";
import { birdLine, dayIndex, groupColor, groupLabel, measureLine, stackDays } from "./animals.js";
import "./animals.css";

const CHART_H = 160;

function Chart({ stats, zone }) {
  const bars = useMemo(() => stackDays(stats.days, stats.groups), [stats]);
  const top = Math.max(1, ...bars.map(b => b.total));
  const n = bars.length;
  const w = 100 / n;
  const total = bars.reduce((s, b) => s + b.total, 0);
  const label = `${total} animal visits from ${stats.from_date} to ${stats.to_date}`
    + (stats.measures.length ? `, with ${stats.measures.length} measures marked` : "");
  return (
    <figure className="animals-chart">
      <svg viewBox={`0 0 100 ${CHART_H}`} preserveAspectRatio="none" role="img" aria-label={label}>
        {bars.map((b, i) => b.segments.map(s => (
          <rect key={`${b.date}-${s.group}`} x={i * w + w * 0.1} width={w * 0.8}
            y={CHART_H - (s.to / top) * CHART_H} height={((s.to - s.from) / top) * CHART_H}
            fill={groupColor(s.group)}>
            <title>{`${b.date}: ${s.to - s.from} ${groupLabel(s.group).toLowerCase()}`}</title>
          </rect>
        )))}
        {stats.measures.map(m => {
          const i = dayIndex(stats.days, m.started_at, zone);
          return i == null ? null : (
            <line key={m.id} className="animals-marker" x1={i * w} x2={i * w} y1="0" y2={CHART_H}
              vectorEffect="non-scaling-stroke" />
          );
        })}
      </svg>
      <figcaption className="animals-legend">
        {stats.groups.map(g => (
          <span key={g}><i style={{ background: groupColor(g) }} aria-hidden="true" />{groupLabel(g)}</span>
        ))}
        {stats.measures.length > 0 && <span><i className="animals-legend-marker" aria-hidden="true" />Measure starts</span>}
      </figcaption>
    </figure>
  );
}

// The numbers behind the chart, one tap away.
function DayTable({ stats }) {
  const shown = stats.days.filter(d => d.birds || Object.keys(d.animals).length).reverse();
  return (
    <table className="animals-table">
      <thead>
        <tr><th>Day</th>{stats.groups.map(g => <th key={g}>{groupLabel(g)}</th>)}<th>Birds</th></tr>
      </thead>
      <tbody>
        {shown.map(d => (
          <tr key={d.date}>
            <td>{d.date}</td>
            {stats.groups.map(g => <td key={g} className="tnum">{d.animals[g] || 0}</td>)}
            <td className="tnum">{d.birds}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MeasureCard({ m, canEdit, onEnd, onDelete, busy }) {
  const e = m.effect;
  const groups = Object.entries(e.groups);
  return (
    <article className="card animals-measure">
      <div className="card-pad">
        <div className="between">
          <h3>{m.name}</h3>
          <span className="label">
            {new Date(m.started_at).toLocaleDateString()}
            {m.ended_at ? ` to ${new Date(m.ended_at).toLocaleDateString()}` : ", in place"}
          </span>
        </div>
        {m.note && <p className="field-help">{m.note}</p>}
        {groups.length === 0
          ? <p>No animal visits in the 14 days before or after.</p>
          : <ul>{groups.map(([g, rr]) => <li key={g}>{measureLine(g, rr, m, e)}</li>)}</ul>}
        <p className="field-help">{birdLine(e.birds)}</p>
        {canEdit && (
          <div className="row" style={{ gap: 8 }}>
            {!m.ended_at && <button type="button" className="btn" disabled={busy} onClick={() => onEnd(m)}>End it now</button>}
            <button type="button" className="btn" disabled={busy} onClick={() => onDelete(m)}>Delete</button>
          </div>
        )}
      </div>
    </article>
  );
}

function AddMeasure({ deviceId, onAdded }) {
  const [name, setName] = useState("");
  const [day, setDay] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function add(e) {
    e.preventDefault();
    if (!name.trim()) { setError("Name the measure, such as Baffle on the pole."); return; }
    setBusy(true);
    setError(null);
    try {
      // Local noon on the chosen day, or now for today, so it lands on that day.
      const today = day === new Date().toLocaleDateString("en-CA");
      const started = today ? new Date() : new Date(`${day}T12:00:00`);
      await createMeasure(deviceId, { name: name.trim(), started_at: started.toISOString(), note: note.trim() || null });
      setName("");
      setNote("");
      onAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card animals-add" onSubmit={add}>
      <div className="card-pad">
        <h3>Log a measure</h3>
        <TextInput label="What you did" value={name} onChange={setName} placeholder="Baffle on the pole" disabled={busy} />
        <TextInput label="Started" type="date" value={day} onChange={setDay} disabled={busy} />
        <TextInput label="Note" value={note} onChange={setNote} placeholder="Optional" disabled={busy} />
        <FormNote error={error} />
        <button type="submit" className="btn primary" disabled={busy}>{busy ? "Saving…" : "Add measure"}</button>
      </div>
    </form>
  );
}

export function AnimalsPage() {
  const { data } = useData();
  const devices = data.DEVICES;
  const zone = browserZone();
  const [deviceId, setDeviceId] = useState(devices[0]?.id ?? null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const [busy, setBusy] = useState(false);
  const device = devices.find(d => d.id === deviceId);

  const load = useCallback(() => {
    if (deviceId == null) return;
    setError(null);
    fetchAnimalStats(deviceId, zone).then(setStats).catch(e => setError(e.message));
  }, [deviceId, zone]);
  useEffect(load, [load]);

  if (!devices.length) {
    return <Empty title="No feeders yet" hint="Register a feeder to see animal visits." />;
  }
  const canEdit = device && canManageFeeder(device, data.ME);

  async function act(fn) {
    setBusy(true);
    try { await fn(); load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">Squirrels, raccoons and the rest</div>
          <h1 className="page-title"><em>Animals</em></h1>
        </div>
        {devices.length > 1 && (
          <SelectInput label="Feeder" value={String(deviceId)}
            onChange={v => setDeviceId(Number(v))}
            options={devices.map(d => [String(d.id), d.name])} />
        )}
      </div>
      <FormNote error={error} />
      {!stats ? <div className="field-help" role="status">Loading…</div> : (
        <>
          {stats.groups.length === 0 && !stats.measures.length
            ? <Empty icon="🐿" title="No animal visits in the last 60 days"
                hint="Squirrels and other animals Tier 2 names show up here." />
            : (
              <section className="animals-section" aria-label="Animal visits per day">
                <Chart stats={stats} zone={zone} />
                <button type="button" className="btn" onClick={() => setShowTable(v => !v)}
                  aria-expanded={showTable}>
                  {showTable ? "Hide the numbers" : "Show the numbers"}
                </button>
                {showTable && <DayTable stats={stats} />}
              </section>
            )}
          {stats.measures.length > 0 && (
            <section className="animals-section" aria-label="Measures">
              <p className="field-help">
                Each card compares visits per camera-up hour in the 14 days before a measure with the days after.
                Offline hours are left out. One feeder has no control group, and animals come and go with the
                season, so read it as what happened after, not proof of why.
              </p>
              {stats.measures.map(m => (
                <MeasureCard key={m.id} m={m} canEdit={canEdit} busy={busy}
                  onEnd={x => act(() => updateMeasure(deviceId, x.id, { ended_at: new Date().toISOString() }))}
                  onDelete={x => act(() => deleteMeasure(deviceId, x.id))} />
              ))}
            </section>
          )}
          {canEdit && <AddMeasure deviceId={deviceId} onAdded={load} />}
        </>
      )}
    </>
  );
}
