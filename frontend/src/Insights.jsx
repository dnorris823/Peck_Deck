// Insights — analytics over a selectable window (FLEDGE Phase 6).
//
// Filters live in one row above the charts and scope everything below them, so
// every number on screen describes the same slice. While a new range loads the
// previous render is held at reduced opacity rather than replaced by a skeleton
// — no layout jump, no flash.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { BarList, ColumnChart, TrendChart } from "./Charts.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { downloadExport, loadInsights } from "./data.js";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const HOUR_LABELS = Array.from({ length: 24 }, (_, h) =>
  h === 0 ? "12a" : h === 12 ? "12p" : h > 12 ? `${h - 12}p` : `${h}a`
);

function fmtHour(h) {
  if (h == null) return "—";
  return HOUR_LABELS[h];
}

function StatLine({ label, value, detail }) {
  return (
    <div className="insight-stat">
      <div className="label">{label}</div>
      <div className="insight-stat-value tnum">{value}</div>
      {detail && <div className="insight-stat-detail">{detail}</div>}
    </div>
  );
}

export function Insights() {
  const { DEVICES } = useData().data;
  const [days, setDays] = useState(30);
  const [deviceId, setDeviceId] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadInsights({ days, deviceId })
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || "Couldn't load insights.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, deviceId]);

  const onExport = useCallback(
    async (fmt) => {
      setExporting(true);
      try {
        const { blob, filename } = await downloadExport({ fmt, deviceId, days });
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
        setExporting(false);
      }
    },
    [deviceId, days]
  );

  const deviceName = useMemo(() => {
    const map = new Map(DEVICES.map((d) => [d.id, d.name]));
    return (id) => map.get(id) || `Station ${id}`;
  }, [DEVICES]);

  const scope = deviceId == null ? "all stations" : deviceName(deviceId);

  return (
    <section aria-labelledby="insights-heading">
      <div className="section-head">
        <div>
          <div className="section-title" id="insights-heading">Insights</div>
          <div className="section-sub">
            Last {days} days · {scope}
          </div>
        </div>
      </div>

      <div className="insights-filters">
        <div className="row" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.days}
              type="button"
              className={`btn sm ${days === r.days ? "" : "ghost"}`}
              aria-pressed={days === r.days}
              onClick={() => setDays(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>

        <label className="sr-only" htmlFor="insights-device">Station</label>
        <select
          id="insights-device"
          className="input sm"
          value={deviceId ?? ""}
          onChange={(e) => setDeviceId(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">All stations</option>
          {DEVICES.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>

        <span className="spacer" />

        <button type="button" className="btn ghost sm" disabled={exporting}
          onClick={() => onExport("csv")}>
          {exporting ? "Preparing…" : "Export CSV"}
        </button>
        <button type="button" className="btn ghost sm" disabled={exporting}
          onClick={() => onExport("json")}>
          Export JSON
        </button>
      </div>

      {error && <div className="card card-pad" role="alert">{error}</div>}

      {!error && !data && loading && (
        <div className="card card-pad" style={{ color: "var(--ink-mute)" }}>Loading insights…</div>
      )}

      {!error && data && data.total_sightings === 0 && (
        <div className="card">
          <Empty
            title="Nothing in this range"
            hint="Try a longer time range, or a different station."
          />
        </div>
      )}

      {!error && data && data.total_sightings > 0 && (
        <div className={loading ? "insights-loading" : undefined}>
          <div className="insights-grid">
            <div className="card card-pad">
              <TrendChart
                labels={data.day_labels}
                values={data.per_day}
                caption={`Visits per day — last ${days} days, ${scope}`}
                valueLabel="visits"
              />
            </div>

            <div className="card card-pad insight-stats">
              <StatLine label="Total visits" value={data.total_sightings} />
              <StatLine label="Species seen" value={data.distinct_species} />
              <StatLine
                label="Busiest hour"
                value={fmtHour(data.busiest_hour)}
                detail={data.busiest_day ? `Busiest day ${data.busiest_day.slice(5)}` : null}
              />
              <StatLine
                label="Longest streak"
                value={`${data.longest_streak}d`}
                detail={`${data.active_days} active day${data.active_days === 1 ? "" : "s"}`}
              />
            </div>
          </div>

          <div style={{ height: 24 }} />

          <div className="insights-grid">
            <div className="card card-pad">
              <ColumnChart
                labels={HOUR_LABELS}
                values={data.hours}
                emphasisIdx={data.busiest_hour}
                caption={`Visits by hour of day — ${scope}`}
                valueLabel="visits"
              />
            </div>

            <div className="card card-pad">
              <BarList
                items={(data.per_device.length
                  ? data.per_device
                  : []
                ).map((d) => ({ label: deviceName(d.device_id), value: d.count }))}
                caption="Visits by station"
                valueLabel="visits"
              />
            </div>
          </div>

          <div style={{ height: 24 }} />

          <div className="insights-grid">
            <div className="card card-pad">
              <TrendChart
                labels={data.day_labels}
                values={data.diversity}
                caption={`Species diversity — cumulative, last ${days} days`}
                valueLabel="species"
                height={160}
              />
            </div>

            <div className="card card-pad">
              <div className="section-title" style={{ fontSize: 15, marginBottom: 4 }}>
                New arrivals
              </div>
              <div className="section-sub" style={{ marginBottom: 10 }}>
                First recorded in this range
              </div>
              {data.new_species.length === 0 ? (
                <div style={{ color: "var(--ink-mute)", fontSize: 13 }}>
                  No new species in this range.
                </div>
              ) : (
                <ul className="arrivals">
                  {data.new_species.slice(0, 8).map((s) => (
                    <li key={s.id}>
                      <span className="arrivals-name">{s.common_name}</span>
                      <span className="arrivals-date tnum">{s.first_seen.slice(5, 10)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
