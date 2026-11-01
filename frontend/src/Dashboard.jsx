// Home — the latest bird, full bleed, then the rest of today. On a quiet day the
// strip falls back to recent visits, and a line sums up yesterday.
import React, { useEffect, useState } from "react";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { Empty } from "./Empty.jsx";
import { useData } from "./DataContext.jsx";
import { SIGHTING_WINDOW, fetchSpeciesCountsBetween, isBirdSighting } from "./data.js";
import { useSpeciesAccent } from "./accent.js";
import {
  DAY_END_HOUR, DAY_START_HOUR, RECENT_BELOW, RECENT_COUNT, fmtClock, heroWhen, isToday, isUnknown,
  statusLine, stripLabel, timelinePos, yesterdayBounds, yesterdayLine,
} from "./home.js";
import { isTier2Paused, useTier2 } from "./tier2.js";
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

// Yesterday's counts come from the backend, because the loaded window can stop
// partway through a busy yesterday. Asked again at midnight, and when a loaded
// visit from yesterday arrives late, changes species or is deleted.
function useYesterday(sightings, now, feeder) {
  const { start, end } = yesterdayBounds(now);
  const from = start.getTime();
  const to = end.getTime();
  const loaded = sightings
    .filter(s => s.datetime.getTime() >= from && s.datetime.getTime() <= to)
    .map(s => `${s.id}:${s.species.id}`)
    .join(",");
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let live = true;
    fetchSpeciesCountsBetween(new Date(from), new Date(to), feeder)
      .then(r => { if (live) setRows(r); })
      // Home still works without the line, so a failed count just leaves it out.
      .catch(() => { if (live) setRows(null); });
    return () => { live = false; };
  }, [from, to, loaded, feeder]);
  return rows;
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

function StripVisit({ s, now, onOpen, selected }) {
  const unnamed = isUnknown(s.species);
  const name = unnamed ? "Unnamed bird" : s.species.common;
  // Today's visits say the time. An older one in "Recent visits" says its day,
  // and its full day and time go in the name and the tooltip.
  const today = isToday(s.datetime, now);
  const when = today ? fmtClock(s.datetime) : heroWhen(s.datetime, now);
  return (
    <button type="button" className={`home-visit ${unnamed ? "unnamed" : ""}`}
      aria-current={selected ? "true" : undefined}
      aria-label={today ? `${name} at ${when}` : `${name}, ${when}`}
      title={today ? undefined : when}
      onClick={() => onOpen(s)}>
      <span className="home-thumb"><SightingImage sighting={s} /></span>
      <span className="home-visit-label">{unnamed ? "Name?" : stripLabel(s.datetime, now)}</span>
    </button>
  );
}

function YesterdayLine({ line, onOpen }) {
  return (
    <button type="button" className="home-yday" onClick={onOpen}>
      <span className="home-sec-head">
        <span className="section-title">Yesterday</span>
        <span className="home-yday-count">{line.visits} <Icon name="chev" className="" /></span>
      </span>
      <span className="home-yday-line">{line.species}</span>
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
  const { data, feeder } = useData();
  // The newest visits in the feeder scope, or on every feeder for all.
  const { SCOPED_SIGHTINGS: SIGHTINGS, DEVICES } = data;
  const now = useNow();
  // Home is about birds. A squirrel visit stays in History but never takes the
  // hero, the strip, or today's count. The feeder filter here covers the
  // moment after the picker moves, before that feeder's list arrives.
  const birds = SIGHTINGS.filter(s => isBirdSighting(s) && (feeder == null || s.device.id === feeder));
  // The stream inserts by capture time, so the first row is the newest bird.
  const hero = birds[0];
  const accent = useSpeciesAccent(hero?.species);
  const yesterday = useYesterday(birds, now, feeder);
  const tier2 = useTier2();

  if (!hero) return <HomeEmpty hasFeeders={DEVICES.length > 0} go={go} />;

  // Counted in local time from the loaded window. When every loaded row is from
  // today, the window has cut the day short, so the count says "100+".
  const today = birds.filter(s => isToday(s.datetime, now));
  const capped = SIGHTINGS.length >= SIGHTING_WINDOW
    && SIGHTINGS.every(s => isToday(s.datetime, now));
  // A quiet day has too little of its own to fill the strip, so it shows the
  // latest visits from any day instead. The hero is never repeated there.
  const recent = today.length < RECENT_BELOW;
  const strip = recent ? birds.slice(1, 1 + RECENT_COUNT) : today.slice(1);
  const yday = yesterday && yesterdayLine(yesterday);
  const tier2Down = DEVICES.some(d => (feeder == null || d.id === feeder) && d.tierMix?.tier2Down);
  const tier2Paused = isTier2Paused(tier2.status?.state);
  const { quiet, count, warning } = statusLine(hero, today, { now, capped, tier2Down, tier2Paused });

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
          {strip.length > 0 && (
            <section className="home-sec">
              <div className="home-sec-head">
                <h2 className="section-title">{recent ? "Recent visits" : "Earlier today"}</h2>
                <HistoryLink go={go} />
              </div>
              <ol className="home-strip">
                {strip.map(s => (
                  <li key={s.id}>
                    <StripVisit s={s} now={now} onOpen={openSighting} selected={s.id === selectedId} />
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
        <section className="home-sec home-today">
          <div className="home-sec-head">
            <h2 className="section-title">Today</h2>
            {strip.length === 0 && <HistoryLink go={go} />}
          </div>
          <Timeline visits={today} now={now} />
          {yday && (
            <YesterdayLine line={yday}
              onOpen={() => go("history", { day: yesterdayBounds(now).start, device: feeder })} />
          )}
        </section>
      </div>
    </div>
  );
}
