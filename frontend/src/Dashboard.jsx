// Home — the latest bird, full bleed, then the rest of today
import React, { useEffect, useState } from "react";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { SIGHTING_WINDOW } from "./data.js";
import { useSpeciesAccent } from "./accent.js";
import {
  DAY_END_HOUR, DAY_START_HOUR, fmtClock, heroWhen, isToday, isUnknown, statusLine, timelinePos,
} from "./home.js";
import "./home.css";

// The quiet line and the timeline's "now" mark move with the clock, not only
// when a sighting arrives.
function useNow(every = 30000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), every);
    return () => clearInterval(t);
  }, [every]);
  return now;
}

// The feeder's own status from GET /devices, which the backend derives from its
// heartbeat. The top bar's live pill is a different thing: it says whether this
// browser is receiving /events.
const FEEDER = {
  online: { cls: "on", label: "Live" },
  warn: { cls: "warn", label: "Weak signal" },
  offline: { cls: "off", label: "Offline" },
};

function FeederPill({ device }) {
  const st = FEEDER[device.status] || FEEDER.offline;
  return (
    <span className={`home-pill ${st.cls}`} title={`Last check-in: ${device.lastSeen}`}>
      <span className="home-pill-dot" aria-hidden="true" />
      <span className="home-pill-text">{st.label} · {device.name}</span>
    </span>
  );
}

function HistoryLink({ go }) {
  return (
    <button className="btn link sm" onClick={() => go("history")}>
      History <Icon name="chev" className="" />
    </button>
  );
}

const AXIS = [[6, "6 am"], [12, "noon"], [18, "6 pm"], [21, "9 pm"]];

function Timeline({ visits, now }) {
  const marks = visits
    .map(s => ({ s, at: timelinePos(s.datetime) }))
    .filter(m => m.at != null);
  const nowAt = timelinePos(now);
  const span = DAY_END_HOUR - DAY_START_HOUR;
  return (
    <div className="home-timeline" role="img"
      aria-label={`${marks.length} visit${marks.length === 1 ? "" : "s"} between 6 am and 9 pm today.`}>
      <div className="home-tl-bar">
        {marks.map(({ s, at }) => (
          <span key={s.id} className="home-tl-mark" style={{ left: `${at}%` }}
            title={`${s.species.common}, ${fmtClock(s.datetime)}`} />
        ))}
        {nowAt != null && <span className="home-tl-now" style={{ left: `${nowAt}%` }} />}
      </div>
      <div className="home-tl-axis" aria-hidden="true">
        {AXIS.map(([h, text]) => (
          <span key={h} style={{ left: `${((h - DAY_START_HOUR) / span) * 100}%` }}>{text}</span>
        ))}
      </div>
    </div>
  );
}

function EarlierVisit({ s, onOpen, selected }) {
  const unnamed = isUnknown(s.species);
  const time = fmtClock(s.datetime);
  return (
    <button type="button" className={`home-visit ${unnamed ? "unnamed" : ""}`}
      aria-current={selected ? "true" : undefined}
      aria-label={`${unnamed ? "Unnamed bird" : s.species.common} at ${time}`}
      onClick={() => onOpen(s)}>
      <span className="home-thumb"><SightingImage sighting={s} /></span>
      <span className="home-visit-label">{unnamed ? "Name?" : time}</span>
    </button>
  );
}

function HomeEmpty({ hasFeeders, go }) {
  return (
    <Empty
      title={hasFeeders ? "No visits yet" : "No feeders yet"}
      hint={hasFeeders
        ? "Your feeder is watching. Its first bird shows up here."
        : "Register a feeder, and its first bird shows up here."}
      action={
        <button className="btn primary sm" onClick={() => go("feeders")}>
          {hasFeeders ? "Check your feeders" : "Register a feeder"}
        </button>
      } />
  );
}

// `selectedId` is the visit open in the detail view, if any. Home outlines it in
// the strip so the two sides of the desktop layout agree.
export function Dashboard({ openSighting, go, selectedId = null }) {
  const { data } = useData();
  const { SIGHTINGS, DEVICES } = data;
  const now = useNow();
  // The stream inserts by capture time, so the first row is the newest bird.
  const hero = SIGHTINGS[0];
  const accent = useSpeciesAccent(hero?.species);

  if (!hero) return <HomeEmpty hasFeeders={DEVICES.length > 0} go={go} />;

  // Counted in local time from the loaded window. When every loaded row is from
  // today, the window has cut the day short, so the count says "100+".
  const today = SIGHTINGS.filter(s => isToday(s.datetime, now));
  const capped = SIGHTINGS.length >= SIGHTING_WINDOW && today.length === SIGHTINGS.length;
  const earlier = today.slice(1);
  const tier2Down = DEVICES.some(d => d.tierMix?.tier2Down);
  const { quiet, count, warning } = statusLine(hero, today, { now, capped, tier2Down });

  return (
    <div className="home" style={accent}>
      {/* Keyed on the visit, so a streamed bird remounts the photo instead of
          showing the new name over the old picture while it loads. */}
      <section className="home-hero" key={hero.id} aria-label="Latest visitor">
        <button type="button" className="home-hero-hit" onClick={() => openSighting(hero)}
          aria-label={`Open the ${hero.species.common} visit`}>
          <SightingImage sighting={hero} large />
        </button>
        <FeederPill device={hero.device} />
        <div className="home-hero-text">
          <div className="home-eyebrow">Latest visitor</div>
          <h1 className="home-name">{hero.species.common}</h1>
          <p className="home-when">
            {heroWhen(hero.datetime, now)}
            <span className="home-hero-feeder"> · {hero.device.name}</span>
          </p>
        </div>
      </section>

      <div className="home-under">
        <div className="home-main">
          <p className="home-status">
            {quiet && <b>{quiet}</b>} {count}
            {warning && <span className="home-status-warn"> {warning}</span>}
          </p>
          {earlier.length > 0 && (
            <section className="home-sec">
              <div className="home-sec-head">
                <h2 className="section-title">Earlier today</h2>
                <HistoryLink go={go} />
              </div>
              <ol className="home-strip">
                {earlier.map(s => (
                  <li key={s.id}>
                    <EarlierVisit s={s} onOpen={openSighting} selected={s.id === selectedId} />
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
        <section className="home-sec home-today">
          <div className="home-sec-head">
            <h2 className="section-title">Today</h2>
            {earlier.length === 0 && <HistoryLink go={go} />}
          </div>
          <Timeline visits={today} now={now} />
        </section>
      </div>
    </div>
  );
}
