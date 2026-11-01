// One species: hero photo, totals, the 24-hour dial and its recent visits.
// The page takes its accent from this species, not from the latest visitor.
import React, { useEffect, useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { SightingImage } from "./SightingImage.jsx";
import { HourDial } from "./HourDial.jsx";
import { useData } from "./DataContext.jsx";
import { useSpeciesAccent } from "./accent.js";
import {
  fetchHours, fetchSpeciesSightings, speciesLinks,
  fmtClock, fmtHour, fmtSeen, fmtSince, fmtVisit, fmtVisitFull,
} from "./speciesData.js";

const RANGES = [[30, "30 days"], [0, "All time"]];

// Runs `load` when `key` changes and keeps the last result while the next one
// loads, so switching range doesn't flash an empty dial.
function useLoad(load, key) {
  const [state, setState] = useState({ value: null, error: null, loading: true });
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    load().then(
      (value) => !cancelled && setState({ value, error: null, loading: false }),
      (e) => !cancelled && setState((s) => ({ ...s, error: e.message || "Request failed", loading: false })),
    );
    return () => { cancelled = true; };
    // `key` stands for everything `load` closes over.
  }, [key]);
  return state;
}

// One visit has the same earliest and latest time, so it shows once.
function spanText(h) {
  if (!h?.earliest) return "—";
  if (h.earliest === h.latest) return fmtClock(h.earliest);
  return `${fmtClock(h.earliest)} · ${fmtClock(h.latest)}`;
}

function WhenItVisits({ species }) {
  const { feeder } = useData();
  const [days, setDays] = useState(30);
  // The count is in the key, so a streamed visit redraws the dial.
  const hours = useLoad(
    () => fetchHours(species.id, { days, deviceId: feeder }),
    `${species.id}:${days}:${species.count}:${feeder}`,
  );
  const h = hours.value;
  const empty = h && h.total === 0;

  return (
    <section aria-labelledby="sv-when-h">
      <div className="sv-sec">
        <h2 id="sv-when-h">When it visits</h2>
        <div className="segmented sv-range" role="group" aria-label="Period">
          {RANGES.map(([d, label]) => (
            <button key={d} className={days === d ? "active" : ""} aria-pressed={days === d}
              onClick={() => setDays(d)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="sv-when">
        <HourDial counts={h?.counts} busiest={h?.peak_hours?.[0]} loading={hours.loading} />
        {hours.error && !h ? (
          <p className="sv-note" role="alert">Couldn't load visits by hour. {hours.error}</p>
        ) : empty ? (
          <p className="sv-note">
            {days ? <>
              No visits in the last {days} days.{" "}
              <button className="sv-link" onClick={() => setDays(0)}>Show all time</button>
            </> : "No visits yet."}
          </p>
        ) : (
          <dl className="sv-facts">
            <div>
              <dt>Busiest</dt>
              <dd>{h?.peak_hours?.length ? fmtHour(h.peak_hours[0]) : "—"}</dd>
            </div>
            {h?.peak_hours?.length > 1 && (
              <div>
                <dt>Second peak</dt>
                <dd>{fmtHour(h.peak_hours[1])}</dd>
              </div>
            )}
            <div>
              <dt>{h?.total === 1 ? "Only visit" : "Earliest · latest"}</dt>
              <dd>{spanText(h)}</dd>
            </div>
          </dl>
        )}
      </div>
    </section>
  );
}

function RecentVisits({ species, visits, onAll, openSighting }) {
  return (
    <section aria-labelledby="sv-recent-h">
      <div className="sv-sec">
        <h2 id="sv-recent-h">Recent</h2>
        <button className="sv-link" onClick={onAll}>
          All {species.count.toLocaleString()} ›
        </button>
      </div>
      {visits.error && !visits.value && (
        <p className="sv-note" role="alert">Couldn't load recent visits. {visits.error}</p>
      )}
      {visits.value?.length > 0 && (
        <ul className="sv-film">
          {visits.value.map((s) => (
            <li key={s.id}>
              <button className="sv-visit" onClick={() => openSighting(s)}
                aria-label={`${s.species.common}, ${fmtVisitFull(s.datetime)}`}>
                <span className="sv-visit-img"><SightingImage sighting={s} alt="" /></span>
                <span className="sv-visit-time">{fmtVisit(s.datetime)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LearnMore({ species }) {
  const links = speciesLinks(species);
  if (links.length === 0) return null;
  return (
    <section aria-labelledby="sv-more-h">
      <div className="sv-sec">
        <h2 id="sv-more-h">Learn more</h2>
      </div>
      <ul className="sv-more">
        {links.map((l) => (
          <li key={l.label}>
            <a href={l.href} target="_blank" rel="noopener noreferrer">
              <span className="sv-more-name">{l.label} ›</span>
              <span className="sv-more-hint">{l.hint}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SpeciesView({ species, onBack, go, openSighting }) {
  const { data, feeder } = useData();
  const accent = useSpeciesAccent(species);
  const visits = useLoad(
    () => fetchSpeciesSightings(species.id, data, { deviceId: feeder }),
    `${species.id}:${species.count}:${feeder}`,
  );
  const hero = visits.value?.find((s) => s.hasImage);
  const onAll = () => go("history", { species: species.id });

  return (
    <article className="sv" style={accent} aria-label={species.common}>
      <header className="sv-hero">
        {hero
          ? <SightingImage sighting={hero} large alt={`Photo of ${species.common}`} />
          : <div className="capture"><BirdPlate species={species} /></div>}
        {onBack && (
          <button className="sv-back" onClick={onBack}>‹ Species</button>
        )}
        <div className="sv-hero-text">
          <h1>{species.common}</h1>
          <p>{species.sci}</p>
        </div>
      </header>

      <div className="sv-cols">
        <div>
          <dl className="sv-stats">
            <div>
              <dt>{species.count === 1 ? "visit" : "visits"}</dt>
              <dd className="tnum">{species.count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>first seen</dt>
              <dd>{fmtSince(species.firstSeenAt)}</dd>
            </div>
            <div>
              <dt>last seen</dt>
              <dd>{fmtSeen(species.lastSeenAt, new Date(), { short: true })}</dd>
            </div>
          </dl>
          <WhenItVisits key={species.id} species={species} />
        </div>
        <div>
          <RecentVisits species={species} visits={visits} onAll={onAll} openSighting={openSighting} />
          <LearnMore species={species} />
        </div>
      </div>
    </article>
  );
}
