// Species: the list of every bird the feeders have caught, and one species'
// page. On a phone the page replaces the list. On a wide screen they sit side
// by side and the page shows the top row until you pick another.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import { SpeciesView } from "./SpeciesView.jsx";
import { createSpecies } from "./data.js";
import { useSpeciesAccent } from "./accent.js";
import { fetchSpeciesSightings, fmtSeen, fmtSince, isUnknown, usualTime } from "./speciesData.js";
import "./species.css";

// Matches the side-by-side breakpoint in species.css.
const WIDE = "(min-width: 900px)";

const ORDERS = [["recent", "Recent"], ["count", "Most seen"], ["name", "A to Z"]];

export function sortSpecies(list, order) {
  const time = (s) => s.lastSeenAt?.getTime() ?? 0;
  return [...list].sort((a, b) => {
    if (order === "count") return b.count - a.count || a.common.localeCompare(b.common);
    if (order === "name") return a.common.localeCompare(b.common);
    return time(b) - time(a);
  });
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
    for (const s of data.SIGHTINGS) {
      if (feeder != null && s.device.id !== feeder) continue;
      if (s.hasImage && !by.has(s.species.id)) by.set(s.species.id, s);
    }
    return by;
  }, [data.SIGHTINGS, feeder]);
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

function SpeciesRow({ s, photo, active, onOpen }) {
  const accent = useSpeciesAccent(s);
  const when = usualTime(s.peakHours);
  return (
    <li>
      <button className={`sp-row ${active ? "on" : ""}`} onClick={() => onOpen(s)}
        aria-current={active ? "true" : undefined} style={accent}>
        <Thumb species={s} photo={photo} />
        <span className="sp-text">
          <span className="sp-name">{s.common}</span>
          <span className="sp-meta">
            {fmtSeen(s.lastSeenAt)} · <span className="tnum">{s.count.toLocaleString()}</span>{" "}
            {s.count === 1 ? "visit" : "visits"}
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
  const [openId, setOpenId] = useState(null);
  const [adding, setAdding] = useState(false);
  const listScroll = useRef(0);

  const unknown = data.SPECIES_COUNTS.find(isUnknown);
  const named = useMemo(() => data.SPECIES_COUNTS.filter((s) => !isUnknown(s)), [data.SPECIES_COUNTS]);
  const sorted = useMemo(() => sortSpecies(named, order), [named, order]);
  const photoRows = useMemo(() => (unknown ? [unknown, ...sorted] : sorted), [unknown, sorted]);
  const photoOf = useLatestPhotos(photoRows, data, feeder);
  const where = data.DEVICES.find((d) => d.id === feeder)?.name ?? "your feeders";

  const since = named.reduce((min, s) => (s.firstSeenAt && (!min || s.firstSeenAt < min) ? s.firstSeenAt : min), null);
  const shown = named.find((s) => s.id === openId) ?? (wide ? sorted[0] : null);

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
            {named.length.toLocaleString()} at {where}{since ? ` since ${fmtSince(since)}` : ""}
          </p>
        </div>
        <button className="icon-btn sp-add" onClick={() => setAdding(true)} aria-label="Add a species" title="Add a species">
          <Icon name="plus" className="" />
        </button>
      </div>
      <div className="segmented sp-sort" role="group" aria-label="Sort species">
        {ORDERS.map(([id, label]) => (
          <button key={id} className={order === id ? "active" : ""} aria-pressed={order === id}
            onClick={() => setOrder(id)}>{label}</button>
        ))}
      </div>
      <ul className="sp-rows">
        {unknown && (
          <NeedsName s={unknown} photo={photoOf(unknown.id)}
            onOpen={() => go("history", { species: unknown.id })} />
        )}
        {sorted.map((s) => (
          <SpeciesRow key={s.id} s={s} photo={photoOf(s.id)} active={wide && shown?.id === s.id} onOpen={open} />
        ))}
      </ul>
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
