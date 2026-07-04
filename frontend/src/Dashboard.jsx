// Dashboard — recent feed, stats, device status, activity heatmap
import React from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { fmtTime, fmtRelative } from "./data.js";

function Sparkline({ data, color = "var(--forest)" }) {
  const w = 88, h = 32;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / (max - min || 1)) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg className="stat-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      {data.map((v, i) => {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((v - min) / (max - min || 1)) * (h - 4) - 2;
        return i === data.length - 1 ? <circle key={i} cx={x} cy={y} r="2" fill={color} /> : null;
      })}
    </svg>
  );
}

function StatCard({ label, value, em, trend, trendDir, spark, accent, isText }) {
  return (
    <div className="stat">
      <div className="stat-label label">
        <span style={{ width: 4, height: 4, background: accent, borderRadius: "50%" }} />
        {label}
      </div>
      <div className={`stat-value ${isText ? "text" : "tnum"}`}>
        {em ? <em>{value}</em> : value}
      </div>
      {trend && (
        <div className={`stat-trend ${trendDir === "up" ? "trend-up" : trendDir === "down" ? "trend-down" : ""}`}>
          {trendDir === "up" ? "↑" : trendDir === "down" ? "↓" : "·"} {trend}
        </div>
      )}
      {spark && <Sparkline data={spark} color={accent} />}
    </div>
  );
}

function FeedItem({ s, onClick }) {
  const conf = s.confidence;
  const cls = conf >= 0.9 ? "conf-high" : conf >= 0.78 ? "conf-mid" : "conf-low";
  return (
    <div className="feed-item" onClick={() => onClick(s)}>
      <div className="feed-thumb">
        <BirdPlate species={s.species} showLabel={false} />
      </div>
      <div>
        <div className="feed-time">
          <span>{fmtTime(s.datetime)}</span>
          <span>·</span>
          <span>{fmtRelative(s.datetime)}</span>
          <span>·</span>
          <span>{s.device.name}</span>
        </div>
        <div className="feed-name">{s.species.common}</div>
        <div className="feed-sci">{s.species.sci}</div>
      </div>
      <div className="feed-meta">
        <span className={`feed-conf ${cls}`}>{Math.round(conf * 100)}%</span>
        <div style={{ marginTop: 6 }}>{s.tier.toUpperCase()}</div>
      </div>
    </div>
  );
}

function DeviceCard({ d }) {
  const pct = Math.round(d.battery * 100);
  const batColor = pct > 50 ? "var(--forest)" : pct > 20 ? "var(--yolk)" : "var(--cardinal)";
  const dotCls = d.status === "online" ? "on" : d.status === "warn" ? "warn" : "off";
  const statusLabel = d.status === "online" ? "Online" : d.status === "warn" ? "Low signal" : "Offline";
  return (
    <div className="device-card">
      <div className="device-row">
        <div>
          <div className="device-name">{d.name}</div>
          <div className="device-loc">{d.city}, {d.state} · {d.feed}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="device-status">
            <span className={`dot ${dotCls}`} />
            {statusLabel}
          </div>
          <div className="battery" style={{ marginTop: 6 }}>
            <span className="bat-bar"><span className="bat-fill" style={{ width: `${pct}%`, background: batColor }} /></span>
            <span className="tnum">{pct}%</span>
          </div>
        </div>
      </div>
      <div className="device-stats">
        <div>
          <div className="device-stat-num tnum">{d.todaySightings}</div>
          <div className="device-stat-lbl">Today</div>
        </div>
        <div>
          <div className="device-stat-num tnum">{d.weekSightings}</div>
          <div className="device-stat-lbl">This week</div>
        </div>
        <div>
          <div className="device-stat-num tnum">{d.allTime.toLocaleString()}</div>
          <div className="device-stat-lbl">All time</div>
        </div>
      </div>
    </div>
  );
}

function ActivityHeatmap() {
  const { HEATMAP } = useData().data;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 8, marginTop: 6 }}>
        <div />
        <div className="heat-axis">
          {[0, 6, 12, 18].map(h => (
            <span key={h} style={{ gridColumn: `span 6`, textAlign: "left" }}>
              {h === 0 ? "12a" : h === 12 ? "12p" : h > 12 ? `${h - 12}p` : `${h}a`}
            </span>
          ))}
        </div>
      </div>
      {HEATMAP.map((row, di) => (
        <div key={di} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 8, marginTop: 3, alignItems: "center" }}>
          <div className="label" style={{ fontSize: 9, padding: 0 }}>{days[di]}</div>
          <div className="heatmap" style={{ marginTop: 0 }}>
            {row.map((v, hi) => (
              <div key={hi} className={`heat-cell ${v > 0 ? `heat-${v}` : ""}`} title={`${days[di]} ${hi}:00 — ${v} sightings`} />
            ))}
          </div>
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-mute)", letterSpacing: "0.06em" }}>
        <span>FEWER</span>
        <span className="heat-cell" style={{ width: 12, height: 12, aspectRatio: "auto" }} />
        <span className="heat-cell heat-1" style={{ width: 12, height: 12, aspectRatio: "auto" }} />
        <span className="heat-cell heat-2" style={{ width: 12, height: 12, aspectRatio: "auto" }} />
        <span className="heat-cell heat-3" style={{ width: 12, height: 12, aspectRatio: "auto" }} />
        <span className="heat-cell heat-4" style={{ width: 12, height: 12, aspectRatio: "auto" }} />
        <span>MORE</span>
      </div>
    </div>
  );
}

function TopVisitors() {
  const { SPECIES_COUNTS } = useData().data;
  const top = SPECIES_COUNTS.slice(0, 5);
  if (top.length === 0) {
    return <div style={{ color: "var(--ink-mute)", fontSize: 13, padding: "8px 0" }}>No sightings yet.</div>;
  }
  const max = top[0].count;
  return (
    <div>
      {top.map((s, i) => (
        <div key={s.id} style={{ padding: "10px 0", borderTop: i === 0 ? "none" : "1px dashed var(--hairline)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
            <div>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-mute)", marginRight: 8 }}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <span style={{ fontFamily: "var(--display)", fontStyle: "italic", fontSize: 17 }}>{s.common}</span>
            </div>
            <span className="tnum" style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-soft)" }}>
              {s.count}
            </span>
          </div>
          <div style={{ height: 4, background: "var(--paper-2)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{
              height: "100%", width: `${(s.count / max) * 100}%`,
              background: s.palette[0], borderRadius: 2
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function greeting(now) {
  const h = now.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
function abbrevName(name) {
  if (!name) return "—";
  const parts = name.split(/\s+/);
  return parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : name;
}

export function Dashboard({ openSighting }) {
  const { SIGHTINGS, DEVICES, DASHBOARD } = useData().data;
  const now = new Date();
  const d = DASHBOARD;
  const sparkSightings = d.spark_sightings?.length ? d.spark_sightings : [0];
  const sparkSpecies = d.spark_species?.length ? d.spark_species : [0];
  const sparkConf = d.spark_confidence?.length ? d.spark_confidence.map(v => Math.round(v * 100)) : [0];
  const sightingsTrend = sparkSightings.length > 1
    ? sparkSightings[sparkSightings.length - 1] - sparkSightings[sparkSightings.length - 2] : 0;
  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>
            {now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "2-digit", year: "numeric" })}
          </div>
          <h1 className="page-title">{greeting(now)}, <em>Dominic.</em></h1>
          <div style={{ marginTop: 10, color: "var(--ink-soft)", maxWidth: "60ch" }}>
            {DEVICES.length} station{DEVICES.length === 1 ? " is" : "s are"} listening.{" "}
            <strong style={{ color: "var(--ink)" }}>{d.today_sightings} bird{d.today_sightings === 1 ? "" : "s"}</strong> stopped
            by today{d.most_frequent ? <> — your most frequent visitor is the{" "}
            <em style={{ color: "var(--cardinal)" }}>{d.most_frequent}</em>.</> : "."}
          </div>
        </div>
        <div className="page-meta">
          <div className="label">Species this week</div>
          <div className="page-meta-row">
            <span className="display-i" style={{ fontSize: 32 }}>{d.species_this_week}</span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-mute)" }}>
              OF {d.total_species} CATALOGUED
            </span>
          </div>
        </div>
      </div>

      <div className="stats-grid">
        <StatCard label="Today's sightings" value={d.today_sightings} accent="var(--cardinal)"
          trend={sightingsTrend >= 0 ? `+${sightingsTrend} vs. yesterday` : `${sightingsTrend} vs. yesterday`}
          trendDir={sightingsTrend > 0 ? "up" : sightingsTrend < 0 ? "down" : ""} spark={sparkSightings} />
        <StatCard label="Species this week" value={d.species_this_week} em accent="var(--forest)"
          trend={`${d.total_species} catalogued`} trendDir="" spark={sparkSpecies} />
        <StatCard label="Most frequent" value={abbrevName(d.most_frequent)} accent="var(--cardinal)" isText
          trend={`${d.most_frequent_count} visits all-time`} trendDir="" />
        <StatCard label="Avg. confidence"
          value={d.avg_confidence != null ? `${Math.round(d.avg_confidence * 100)}%` : "—"}
          accent="var(--yolk-deep)" trend="last 7 days" trendDir="" spark={sparkConf} />
      </div>

      <div className="dash-grid">
        <div>
          <div className="section-head">
            <div>
              <div className="section-title">Recent visits</div>
              <div className="section-sub">Most recent · {DEVICES.length} station{DEVICES.length === 1 ? "" : "s"}</div>
            </div>
            <div className="row">
              <button className="btn ghost sm">Today</button>
              <button className="btn ghost sm">Week</button>
              <button className="btn sm">All</button>
            </div>
          </div>
          <div className="card" style={{ padding: "0 18px" }}>
            <div className="feed">
              {SIGHTINGS.slice(0, 6).map(s => (
                <FeedItem key={s.id} s={s} onClick={openSighting} />
              ))}
            </div>
          </div>
        </div>

        <div>
          <div className="section-head">
            <div>
              <div className="section-title">Stations</div>
              <div className="section-sub">{DEVICES.length} registered</div>
            </div>
            <button className="btn ghost sm"><Icon name="plus" className="" /> Add</button>
          </div>
          {DEVICES.map(d => <DeviceCard key={d.id} d={d} />)}
        </div>
      </div>

      <div style={{ height: 36 }} />

      <div className="dash-grid" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <div>
          <div className="section-head">
            <div>
              <div className="section-title">Activity, last 7 days</div>
              <div className="section-sub">Sightings per hour, all stations</div>
            </div>
            <span className="label">UTC −05:00</span>
          </div>
          <div className="card card-pad">
            <ActivityHeatmap />
          </div>
        </div>

        <div>
          <div className="section-head">
            <div>
              <div className="section-title">Top visitors</div>
              <div className="section-sub">All time · sorted by count</div>
            </div>
          </div>
          <div className="card card-pad">
            <TopVisitors />
          </div>
        </div>
      </div>
    </>
  );
}
