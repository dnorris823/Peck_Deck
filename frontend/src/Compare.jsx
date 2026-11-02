// Compare — the user's feeders side by side. A card per feeder with its week,
// its year and its busiest hour, and the species only it saw this year. Below,
// each species' first visit of the year at each feeder, so a migrant reaching
// one house before another shows as two dates in one row.
import React, { useEffect, useState } from "react";
import { useData } from "./DataContext.jsx";
import { Empty } from "./Empty.jsx";
import { FormNote } from "./Modal.jsx";
import { browserZone, fetchCompare } from "./data.js";
import { fmtHour } from "./speciesData.js";
import { firstsTable, fmtFirst, onlyAt } from "./compare.js";
import "./compare.css";

function Swatch({ species }) {
  return <i className="compare-swatch" style={{ background: species.palette[0] || "var(--mu)" }} aria-hidden="true" />;
}

function FeederCard({ f, only, year, go }) {
  return (
    <article className="card">
      <div className="card-pad">
        <div className="between">
          <h2 className="device-name">{f.name}</h2>
          <button type="button" className="btn sm" onClick={() => go("history", { device: f.device_id })}>
            History
          </button>
        </div>
        <div className="device-stats">
          <div>
            <div className="device-stat-num tnum">{f.visits_week.toLocaleString()}</div>
            <div className="device-stat-lbl">Bird visits, 7 days</div>
          </div>
          <div>
            <div className="device-stat-num tnum">{f.species_year}</div>
            <div className="device-stat-lbl">Species in {year}</div>
          </div>
          <div>
            <div className="device-stat-num">{f.busiest_hour == null ? "None" : fmtHour(f.busiest_hour)}</div>
            <div className="device-stat-lbl">Busiest, 30 days</div>
          </div>
        </div>
        <h3 className="compare-only-title">Only here in {year}</h3>
        {f.species_year === 0 && <p className="field-help">No birds here yet this year.</p>}
        {f.species_year > 0 && only.length === 0 && (
          <p className="field-help">Every species here was seen at another feeder too.</p>
        )}
        {only.length > 0 && (
          <ul className="compare-only">
            {only.map(s => <li key={s.id}><Swatch species={s} />{s.common_name}</li>)}
          </ul>
        )}
      </div>
    </article>
  );
}

function FirstsTable({ rows, feeders, year }) {
  return (
    <div className="compare-scroll">
      <table className="compare-table">
        <caption className="label">First visit in {year}. Bold marks the feeder that saw it first.</caption>
        <thead>
          <tr>
            <th scope="col">Species</th>
            {feeders.map(f => <th key={f.device_id} scope="col">{f.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.species.id}>
              <th scope="row"><Swatch species={r.species} />{r.species.common_name}</th>
              {r.cells.map((d, i) => (
                <td key={feeders[i].device_id}
                  className={`tnum${r.earliest === feeders[i].device_id ? " compare-earliest" : ""}`}>
                  {d ? fmtFirst(d) : <span aria-label="Not seen">–</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComparePage({ go }) {
  const { data } = useData();
  const deviceKey = data.DEVICES.map(d => d.id).join(",");
  const several = data.DEVICES.length > 1;
  const [compare, setCompare] = useState(null);
  const [error, setError] = useState(null);

  // Refetches when the feeder list changes, such as after a share.
  useEffect(() => {
    if (!several) return undefined;
    let current = true;
    setError(null);
    fetchCompare(browserZone())
      .then(c => { if (current) setCompare(c); })
      .catch(e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [deviceKey, several]);

  const header = (
    <div className="page-header">
      <div>
        <div className="label">Every feeder you can see</div>
        <h1 className="page-title"><em>Compare</em></h1>
      </div>
    </div>
  );

  if (!several) {
    return (
      <>
        {header}
        <Empty title="One feeder to compare"
          hint="Compare puts two or more feeders side by side. Ask a feeder's owner to add you to theirs." />
      </>
    );
  }

  return (
    <>
      {header}
      <FormNote error={error} />
      {!compare ? <div className="field-help" role="status">Loading…</div> : (
        <>
          <section className="station-grid compare-section" aria-label="Feeders">
            {compare.feeders.map(f => (
              <FeederCard key={f.device_id} f={f} year={compare.year} go={go}
                only={onlyAt(compare.species, f.device_id)} />
            ))}
          </section>
          <section className="compare-section" aria-label={`First visits in ${compare.year}`}>
            {compare.species.length === 0
              ? <Empty title={`No birds yet in ${compare.year}`} hint="First visits of the year show up here." />
              : <FirstsTable rows={firstsTable(compare.species, compare.feeders)}
                  feeders={compare.feeders} year={compare.year} />}
          </section>
        </>
      )}
    </>
  );
}
