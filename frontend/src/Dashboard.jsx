// Dashboard — latest visitor, day summary, recent photos, activity, stations
import React, { useMemo } from "react";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { ConfidenceChip, SightingTile } from "./Sightings.jsx";
import { DeviceStatus } from "./Devices.jsx";
import { countToday, fmtRelative, fmtTime, tierInfo, toLocalGrid } from "./data.js";
import { accentStyle } from "./accent.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function hourLabel(h) {
  if (h === 0) return "12a";
  if (h === 12) return "12p";
  return h > 12 ? `${h - 12}p` : `${h}a`;
}

function ActivityHeatmap() {
  const { HEATMAP } = useData().data;
  // The backend buckets by UTC; shift into the viewer's own hours.
  const grid = useMemo(() => toLocalGrid(HEATMAP), [HEATMAP]);
  const busiest = useMemo(() => {
    const byHour = Array(24).fill(0);
    grid.forEach(row => row.forEach((v, h) => { byHour[h] += v; }));
    const max = Math.max(...byHour);
    return max > 0 ? byHour.indexOf(max) : null;
  }, [grid]);
  return (
    // One label for the grid; 168 cell tooltips are noise to a screen reader.
    <div className="heat" role="img"
      aria-label={busiest != null ? `Visits by hour over the last 7 days. Busiest around ${hourLabel(busiest)}.` : "No visits in the last 7 days."}>
      <div className="heat-row">
        <span />
        <div className="heat-axis">
          {[0, 6, 12, 18].map(h => <span key={h}>{hourLabel(h)}</span>)}
        </div>
      </div>
      {grid.map((row, di) => (
        <div key={di} className="heat-row">
          <span className="heat-day">{DAYS[di]}</span>
          <div className="heatmap">
            {row.map((v, hi) => (
              <div key={hi} className={`heat-cell ${v > 0 ? `heat-${v}` : ""}`}
                title={`${DAYS[di]} ${hourLabel(hi)}: ${v >= 4 ? "4+" : v} sighting${v === 1 ? "" : "s"}`} />
            ))}
          </div>
        </div>
      ))}
      <div className="heat-foot">
        <span className="heat-legend">
          Fewer
          {[0, 1, 2, 3, 4].map(v => <span key={v} className={`heat-cell ${v ? `heat-${v}` : ""}`} />)}
          More
        </span>
        {busiest != null && <span>Busiest around {hourLabel(busiest)}</span>}
      </div>
    </div>
  );
}

function TopVisitors() {
  const { SPECIES_COUNTS } = useData().data;
  const top = SPECIES_COUNTS.slice(0, 5);
  if (top.length === 0) {
    return <div className="muted-note">No sightings yet.</div>;
  }
  const max = top[0].count;
  return (
    <ol className="rank">
      {top.map((s, i) => (
        <li key={s.id} style={accentStyle(s)}>
          <div className="rank-line">
            <span className="rank-no tnum">{String(i + 1).padStart(2, "0")}</span>
            <span className="rank-name">{s.common}</span>
            <span className="rank-count tnum">{s.count.toLocaleString()}</span>
          </div>
          <div className="rank-bar">
            <span style={{ width: `${(s.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ol>
  );
}

// The newest capture, big. A feeder app is a photo app: this is what someone
// opens it to see.
function LatestVisit({ s, onOpen }) {
  return (
    <button type="button" className="hero" onClick={() => onOpen(s)}>
      <div className="hero-img">
        <SightingImage sighting={s} large />
      </div>
      <div className="hero-body">
        <div className="label">Latest visitor · {fmtRelative(s.datetime)}</div>
        <div className="hero-name">{s.species.common}</div>
        <div className="hero-sci">{s.species.sci}</div>
        <div className="hero-meta">
          <ConfidenceChip s={s} long />
          <span>{fmtTime(s.datetime)}</span>
          <span>{s.device.name}</span>
          <span>{tierInfo(s.tier).long}</span>
        </div>
        <span className="hero-open">View sighting <Icon name="arrow" className="" /></span>
      </div>
    </button>
  );
}

function Stat({ label, value, sub, text = false }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className={`stat-value ${text ? "text" : "tnum"}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

function StationRow({ d }) {
  return (
    <div className="station-row">
      <div className="station-main">
        <div className="station-name">{d.name}</div>
        <div className="station-sub">
          {[d.city !== "—" && [d.city, d.state].filter(Boolean).join(", "), `seen ${d.lastSeen}`]
            .filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="station-counts tnum">
        <span><strong>{d.todaySightings}</strong> today</span>
        <span><strong>{d.weekSightings}</strong> week</span>
      </div>
      <DeviceStatus d={d} />
    </div>
  );
}

function greeting(now) {
  const h = now.getHours();
  if (h < 5) return "Good night";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function Dashboard({ openSighting, go }) {
  const { data } = useData();
  const { SIGHTINGS, DEVICES, DASHBOARD: d, ME } = data;
  const now = new Date();
  const firstName = (ME.name || "").trim().split(/\s+/)[0];
  // Counted locally: the backend's "today" is the UTC day, which on the west
  // coast ends at 5 pm.
  const today = countToday(SIGHTINGS, now);
  const week = (d.spark_sightings || []).reduce((a, b) => a + b, 0);
  const [latest, ...rest] = SIGHTINGS;
  const recent = rest.slice(0, 8);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">
            {now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </div>
          <h1 className="page-title">{greeting(now)}{firstName && <>, <em>{firstName}.</em></>}</h1>
          <p className="page-lede">
            {today === 0
              ? "No visits yet today."
              : <><strong>{today} visit{today === 1 ? "" : "s"}</strong> so far today.</>}
            {latest && <> The last was {/^[aeiou]/i.test(latest.species.common) ? "an" : "a"}{" "}
              <em>{latest.species.common}</em>, {fmtRelative(latest.datetime)}.</>}
          </p>
        </div>
      </div>

      {latest ? (
        <LatestVisit s={latest} onOpen={openSighting} />
      ) : (
        <Empty title="No visits yet" hint="Your stations are watching. The first bird will show up here." />
      )}

      <div className="stats-strip">
        <Stat label="Today" value={today} sub="local time" />
        <Stat label="Last 7 days" value={week} sub={`${d.species_this_week} species`} />
        <Stat label="Catalogued" value={d.total_species} sub="species, all time" />
        <Stat label="Top visitor" value={d.most_frequent || "—"} text
          sub={d.most_frequent ? `${d.most_frequent_count.toLocaleString()} visits` : null} />
      </div>

      {recent.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">Recent visits</h2>
            <button className="btn link sm" onClick={() => go("history")}>
              History <Icon name="arrow" className="" />
            </button>
          </div>
          <div className="gallery gallery-compact">
            {recent.map(s => <SightingTile key={s.id} s={s} onClick={openSighting} showDate />)}
          </div>
        </section>
      )}

      <div className="dash-grid">
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">Activity, last 7 days</h2>
            <span className="label">By hour, your time</span>
          </div>
          <div className="card card-pad"><ActivityHeatmap /></div>
        </section>
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">Top visitors</h2>
            <span className="label">All time</span>
          </div>
          <div className="card card-pad"><TopVisitors /></div>
        </section>
      </div>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Feeders</h2>
          <button className="btn link sm" onClick={() => go("feeders")}>
            Manage <Icon name="arrow" className="" />
          </button>
        </div>
        {DEVICES.length > 0 ? (
          <div className="card">{DEVICES.map(dv => <StationRow key={dv.id} d={dv} />)}</div>
        ) : (
          <Empty icon="📡" title="No feeders yet" hint="Register a feeder under Feeders to start."
            action={<button className="btn primary sm" onClick={() => go("feeders")}>Register a feeder</button>} />
        )}
      </section>
    </>
  );
}
