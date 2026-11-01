// Species: the list of every bird the feeders have caught, and one species'
// page. On a phone the page replaces the list. On a wide screen they sit side
// by side and the page shows the top row until you pick another.
//
// The year picker turns the list into the year list, and "All time" is the life
// list. They live here rather than on a page of their own, because they are
// this same list with a date range: same rows, photos, feeder scope and page.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import { SpeciesView } from "./SpeciesView.jsx";
import { createSpecies, fetchLifeList } from "./data.js";
import { useSpeciesAccent } from "./accent.js";
import { fetchSpeciesSightings, fmtSeen, fmtSince, isUnknown, usualTime } from "./speciesData.js";
import "./species.css";

// Matches the side-by-side breakpoint in species.css.
const WIDE = "(min-width: 900px)";

const ORDERS = [["recent", "Recent"], ["count", "Most seen"], ["first", "First seen"], ["name", "A to Z"]];

export function sortSpecies(list, order) {
  const time = (s) => s.lastSeenAt?.getTime() ?? 0;
  const first = (s) => s.firstSeenAt?.getTime() ?? 0;
  return [...list].sort((a, b) => {
    if (order === "count") return b.count - a.count || a.common.localeCompare(b.common);
    if (order === "name") return a.common.localeCompare(b.common);
    if (order === "first") return first(b) - first(a) || a.common.localeCompare(b.common);
    return time(b) - time(a);
  });
}

// The life list (`year` null) or one year's, for the picked feeder. It reloads
// when the species counts change, so a streamed sighting shows up here too.
// `rows` is null while the asked year and feeder load. `years` keeps the last
// answer meanwhile, so the picker does not flicker.
function useLifeList(year, feeder, counts) {
  const key = `${year}:${feeder}`;
  const [state, setState] = useState({ key: null, years: [], rows: [] });
  useEffect(() => {
    let live = true;
    fetchLifeList(year, feeder)
      .then((res) => { if (live) setState({ key, ...res }); })
      .catch(() => { if (live) setState((s) => ({ ...s, key, rows: [], failed: true })); });
    return () => { live = false; };
  }, [key, year, feeder, counts]);
  return state.key === key ? state : { ...state, rows: null, failed: false };
}

function useMediaQuery(query) {
  const read = () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches;
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return;
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener?.("change", update);
    return () => mql.removeEventListener?.("change", update);
  }, [query]);
  return matches;
}

// The newest photo per species, from the picked feeder when there is one. The
// loaded feed covers the last 100 visits, so a species seen only before that
// gets one small lookup of its own, once per feeder scope.
function useLatestPhotos(rows, data, feeder) {
  const fromFeed = useMemo(() => {
    const by = new Map();
    for (const s of data.SCOPED_SIGHTINGS) {
      if (feeder != null && s.device.id !== feeder) continue;
      if (s.hasImage && !by.has(s.species.id)) by.set(s.species.id, s);
    }
    return by;
  }, [data.SCOPED_SIGHTINGS, feeder]);
  // Keyed "feeder:species", so another feeder's photo never stands in.
  const [looked, setLooked] = useState(() => new Map());
  const asked = useRef(new Set());
  const key = (id) => `${feeder}:${id}`;

  useEffect(() => {
    for (const sp of rows) {
      const k = `${feeder}:${sp.id}`;
      if (fromFeed.has(sp.id) || asked.current.has(k)) continue;
      asked.current.add(k);
      fetchSpeciesSightings(sp.id, data, { limit: 5, deviceId: feeder })
        .then((list) => {
          const photo = list.find((s) => s.hasImage);
          if (photo) setLooked((m) => new Map(m).set(k, photo));
        })
        .catch(() => { /* The plate stays. A missing thumbnail is not an error. */ });
    }
  }, [rows, fromFeed, data, feeder]);

  return (id) => fromFeed.get(id) ?? looked.get(key(id));
}

function Thumb({ species, photo }) {
  return (
    <span className="sp-thumb">
      {photo ? <SightingImage sighting={photo} alt="" /> : <span className="capture"><BirdPlate species={species} /></span>}
    </span>
  );
}

function SpeciesRow({ s, photo, active, onOpen, firstMeta, newLabel }) {
  const accent = useSpeciesAccent(s);
  const when = usualTime(s.peakHours);
  const visits = <><span className="tnum">{s.count.toLocaleString()}</span> {s.count === 1 ? "visit" : "visits"}</>;
  return (
    <li>
      <button className={`sp-row ${active ? "on" : ""}`} onClick={() => onOpen(s)}
        aria-current={active ? "true" : undefined} style={accent}>
        <Thumb species={s} photo={photo} />
        <span className="sp-text">
          <span className="sp-name">
            {s.common}
            {s.isNew && <span className="sp-new" title={newLabel}>New</span>}
          </span>
          <span className="sp-meta">
            {firstMeta
              ? <>First seen {fmtSince(s.firstSeenAt)}{s.firstFeeder ? ` at ${s.firstFeeder}` : ""} · {visits}</>
              : <>{fmtSeen(s.lastSeenAt)} · {visits}</>}
          </span>
        </span>
        {when && (
          <span className="sp-when" title="When it usually comes, last 30 days">
            <i className="sp-dot" aria-hidden="true" />{when}
          </span>
        )}
      </button>
    </li>
  );
}

function NeedsName({ s, photo, onOpen }) {
  return (
    <li>
      <button className="sp-row needs" onClick={onOpen}>
        <Thumb species={s} photo={photo} />
        <span className="sp-text">
          <span className="sp-name">Needs a name</span>
          <span className="sp-meta">
            <span className="tnum">{s.count.toLocaleString()}</span> {s.count === 1 ? "visit" : "visits"}
            {" · "}{fmtSeen(s.lastSeenAt)}
          </span>
        </span>
      </button>
    </li>
  );
}

function AddSpeciesModal({ onClose, onDone }) {
  const [form, setForm] = useState({ common_name: "", genus: "", species_name: "", order_name: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  async function submit() {
    if (!form.common_name || !form.genus || !form.species_name) {
      setError("Common name, genus, and species are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createSpecies({
        common_name: form.common_name, genus: form.genus,
        species_name: form.species_name, order_name: form.order_name || null,
      });
      await onDone();
      onClose();
    } catch (e) {
      setError(e.status === 409 ? "That species is already catalogued." : e.message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Add a species"
      subtitle="Catalogue a bird by hand."
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={submit} disabled={busy}>{busy ? "Adding…" : "Add species"}</button>
      </>}
    >
      <TextInput label="Common name" value={form.common_name} onChange={set("common_name")} />
      <TextInput label="Genus" value={form.genus} onChange={set("genus")} />
      <TextInput label="Species" value={form.species_name} onChange={set("species_name")} />
      <TextInput label="Order" help="Optional (e.g. Passeriformes)." value={form.order_name} onChange={set("order_name")} />
      <FormNote error={error} />
    </Modal>
  );
}

export function SpeciesPage({ go, openSighting }) {
  const { data, reload, feeder } = useData();
  const wide = useMediaQuery(WIDE);
  const [order, setOrder] = useState("recent");
  const [year, setYear] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [adding, setAdding] = useState(false);
  const listScroll = useRef(0);

  const life = useLifeList(year, feeder, data.SPECIES_COUNTS);
  // "Unknown" names no species, so it has no year and stays off a year list.
  const unknown = year == null ? data.SPECIES_COUNTS.find(isUnknown) : null;
  const named = useMemo(() => data.SPECIES_COUNTS.filter((s) => !isUnknown(s)), [data.SPECIES_COUNTS]);
  // All time keeps the live counts and takes the first feeder and "new" from
  // the life list. A year takes its rows from the year list.
  const listed = useMemo(() => {
    if (year != null) return life.rows || [];
    const byId = new Map((life.rows || []).map((r) => [r.id, r]));
    return named.map((s) => {
      const l = byId.get(s.id);
      return l ? { ...s, firstFeeder: l.firstFeeder, isNew: l.isNew } : s;
    });
  }, [year, named, life.rows]);
  const sorted = useMemo(() => sortSpecies(listed, order), [listed, order]);
  const photoRows = useMemo(() => (unknown ? [unknown, ...sorted] : sorted), [unknown, sorted]);
  const photoOf = useLatestPhotos(photoRows, data, feeder);
  const where = data.DEVICES.find((d) => d.id === feeder)?.name ?? "your feeders";
  // A year the picked feeder never saw stays in the picker, so the choice holds.
  const years = year == null || life.years.includes(year) ? life.years : [year, ...life.years];
  const newCount = listed.filter((s) => s.isNew).length;
  const thisYear = new Date().getFullYear();
  const newIn = year == null || year === thisYear ? "this year" : `in ${year}`;

  const since = named.reduce((min, s) => (s.firstSeenAt && (!min || s.firstSeenAt < min) ? s.firstSeenAt : min), null);
  // The species page always covers all time, so a year row opens the same page.
  const pick = (id) => named.find((s) => s.id === id) ?? listed.find((s) => s.id === id) ?? null;
  const shown = (openId != null && pick(openId)) || (wide && sorted[0] ? pick(sorted[0].id) : null);

  function open(s) {
    if (!wide) listScroll.current = window.scrollY || 0;
    setOpenId(s.id);
    window.scrollTo?.(0, 0);
  }
  function back() {
    setOpenId(null);
    // Wait for the list to render before restoring where it was.
    requestAnimationFrame(() => window.scrollTo?.(0, listScroll.current));
  }

  if (data.SPECIES_COUNTS.length === 0) {
    return (
      <>
        <Empty
          icon="🪶"
          title="No species yet"
          hint="Species appear here as your feeders identify them. You can also add one by hand."
          action={<button className="btn primary sm" onClick={() => setAdding(true)}>
            <Icon name="plus" className="" /> Add species
          </button>}
        />
        {adding && <AddSpeciesModal onClose={() => setAdding(false)} onDone={reload} />}
      </>
    );
  }

  const list = (
    <nav className="sp-list" aria-label="Species">
      <div className="sp-top">
        <div>
          <h1 className="sp-title">Species</h1>
          <p className="sp-sub">
            {year == null
              ? <>{named.length.toLocaleString()} at {where}{since ? ` since ${fmtSince(since)}` : ""}</>
              : life.rows == null
                ? <>Loading {year}…</>
                : <>{listed.length.toLocaleString()} at {where} in {year}</>}
            {newCount > 0 && <> · {newCount.toLocaleString()} new {newIn}</>}
          </p>
        </div>
        <button className="icon-btn sp-add" onClick={() => setAdding(true)} aria-label="Add a species" title="Add a species">
          <Icon name="plus" className="" />
        </button>
      </div>
      {years.length > 0 && (
        <select className="toolbar-select sp-year" aria-label="Year" value={year ?? "all"}
          onChange={(e) => setYear(e.target.value === "all" ? null : Number(e.target.value))}>
          <option value="all">All time</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      )}
      <div className="segmented sp-sort" role="group" aria-label="Sort species">
        {ORDERS.map(([id, label]) => (
          <button key={id} className={order === id ? "active" : ""} aria-pressed={order === id}
            onClick={() => setOrder(id)}>{label}</button>
        ))}
      </div>
      <ul className="sp-rows">
        {unknown && (
          <NeedsName s={unknown} photo={photoOf(unknown.id)}
            onOpen={() => go("history", { species: unknown.id, device: feeder })} />
        )}
        {sorted.map((s) => (
          <SpeciesRow key={s.id} s={s} photo={photoOf(s.id)} active={wide && shown?.id === s.id} onOpen={open}
            firstMeta={year != null || order === "first"} newLabel={`First seen ${newIn}`} />
        ))}
      </ul>
      {year != null && life.rows != null && sorted.length === 0 && (
        <p className="sp-sub sp-none">
          {life.failed ? `The ${year} list did not load.` : `No birds at ${where} in ${year}.`}
        </p>
      )}
    </nav>
  );

  const page = shown && (
    <SpeciesView key={shown.id} species={shown} go={go} openSighting={openSighting}
      onBack={wide ? null : back} />
  );

  return (
    <div className="sp-layout">
      {wide ? <>{list}{page}</> : (page || list)}
      {adding && <AddSpeciesModal onClose={() => setAdding(false)} onDone={reload} />}
    </div>
  );
}
