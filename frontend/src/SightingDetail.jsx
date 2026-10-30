// Sighting detail — one visit: the photo, the day's strip, and how sure the
// classifier was. A full-screen view on a phone, a side panel on desktop. App
// mounts it and owns the ?sighting=<id> URL. The species picker corrects a
// wrong or missing name.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SightingImage } from "./SightingImage.jsx";
import { Icon } from "./Icon.jsx";
import { FormNote, Modal, TextInput, useDialog } from "./Modal.jsx";
import { useData } from "./DataContext.jsx";
import { apiFetchBinary, apiObjectUrl } from "./api.js";
import {
  SIGHTING_WINDOW, correctSighting, createSpecies, deleteSighting, fetchSpeciesHours,
  fmtDateLabel, fmtTime, startOfToday, tierInfo, confidenceLevel,
} from "./data.js";
import { useSpeciesAccent } from "./accent.js";
import "./sighting-detail.css";

// ── Pure helpers, exported for the tests ──────────────────────────────────

// "Unknown" is what the Pi uploads when no tier named the bird. "Background" is
// Tier 1's no-bird class, which older sightings carry as their species. The
// camera already saw a bird in both, so neither is a name.
const NOT_A_NAME = new Set(["unknown", "background"]);

export function isPlaceholder(species) {
  return NOT_A_NAME.has(species.common.trim().toLowerCase());
}

export function needsName(s) {
  return isPlaceholder(s.species);
}

/** Who corrected the species: "you", a name, or "someone". Null if nobody did. */
export function correctedByName(s, me, users = []) {
  if (s.correctedBy == null) return null;
  if (s.correctedBy === me?.id) return "you";
  return users.find(u => u.id === s.correctedBy)?.name || "someone";
}

/**
 * The species the picker offers for `query`, matched on the common or
 * scientific name. The birds this user sees most come first, then A to Z.
 * Unknown and Background are not answers, so they are left out.
 */
export function pickerOptions(species, counts, query) {
  const seen = new Map(counts.map(c => [c.id, c.count]));
  const q = query.trim().toLowerCase();
  return species
    .filter(x => !isPlaceholder(x))
    .filter(x => !q || x.common.toLowerCase().includes(q) || x.sci.toLowerCase().includes(q))
    .sort((a, b) => (seen.get(b.id) || 0) - (seen.get(a.id) || 0)
      || a.common.localeCompare(b.common));
}

// The device owner or an owner-role user may delete. The route enforces the
// same rule; this only hides a button that would get a 403.
export function canDeleteSighting(s, me) {
  return me.role === "owner" || s.device.ownerId === me.id;
}

const sameDay = (a, b) => a.toDateString() === b.toDateString();

/**
 * The visits from the same feeder on the same local day, newest first, with
 * `s` always among them. A sighting fetched from outside the loaded window has
 * no loaded neighbours, so it would otherwise be missing from its own strip.
 */
export function dayStrip(sightings, s) {
  const strip = sightings.filter(x =>
    x.device.id === s.device.id && sameDay(x.datetime, s.datetime));
  if (!strip.some(x => x.id === s.id)) strip.push(s);
  return strip.sort((a, b) => b.datetime - a.datetime);
}

/**
 * Which visit of its species on its day this is, counting from 1. Null when
 * the loaded window may not reach back to that day's first visit, because a
 * wrong ordinal is worse than none.
 */
export function visitOrdinal(sightings, s) {
  const dayStart = startOfToday(s.datetime).getTime();
  const oldest = sightings[sightings.length - 1];
  const windowFull = sightings.length >= SIGHTING_WINDOW;
  if (windowFull && (!oldest || oldest.datetime.getTime() >= dayStart)) return null;
  if (!sightings.some(x => x.id === s.id)) return null;
  return sightings.filter(x =>
    x.species.id === s.species.id
    && sameDay(x.datetime, s.datetime)
    && x.datetime <= s.datetime).length;
}

export function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

function hourName(h) {
  return `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;
}

/**
 * Plain words for the peak hours from GET /stats/hours. Two neighbouring hours
 * read as one span: [17, 18] is "5 to 7 pm". Two apart read as two times.
 */
export function busyPhrase(peaks) {
  if (!peaks?.length) return null;
  const [a, b] = peaks;
  // "5 to 7 pm" when both ends share am or pm, "11 am to 1 pm" when not.
  const range = (from, hours) => {
    const to = (from + hours) % 24;
    return (from < 12) === (to < 12)
      ? `${from % 12 || 12} to ${hourName(to)}`
      : `${hourName(from)} to ${hourName(to)}`;
  };
  if (b == null) return range(a, 1);
  if ((a + 1) % 24 === b) return range(a, 2);
  if ((b + 1) % 24 === a) return range(b, 2);
  return `around ${hourName(Math.min(a, b))} and ${hourName(Math.max(a, b))}`;
}

/** "5th visit today. Busiest 5 to 7 pm over the last 30 days." Either half may be missing. */
export function contextLine(s, nth, peaks, now = new Date()) {
  const parts = [];
  if (nth) {
    const days = Math.round((startOfToday(now) - startOfToday(s.datetime)) / 86400000);
    const when = days === 0 ? "today" : days === 1 ? "yesterday" : "that day";
    parts.push(`${ordinal(nth)} visit ${when}.`);
  }
  const busy = busyPhrase(peaks);
  if (busy) parts.push(`Busiest ${busy} over the last 30 days.`);
  return parts.join(" ");
}

const pct = (x) => `${Math.round(x * 100)}%`;

/**
 * One chip per tier for the tiers row. From `tierTrace` when the Pi sent one,
 * with a tier missing from the chain shown as off. Without a trace, only the
 * tier that answered.
 */
export function tierChips(s) {
  const answer = (tier) => tier === s.tier;
  if (!s.tierTrace) {
    if (s.tier === "none") return [{ tier: "none", label: "No tier answered", state: "off" }];
    const short = tierInfo(s.tier).short;
    // A tier that answered "Background" gave no name, however sure it was. On a
    // corrected sighting that is the tier's species, not the person's.
    if (isPlaceholder(s.originalSpecies || s.species)) return [{ tier: s.tier, label: `${short}, no name`, state: "low" }];
    const sure = confidenceLevel(s) === "sure";
    return [{
      tier: s.tier,
      label: sure ? `${short} ✓` : `${short} ${pct(s.confidence)}`,
      state: sure ? "ok" : "low",
    }];
  }
  const chips = s.tierTrace.map(a => {
    const short = tierInfo(a.tier).short;
    if (a.outcome === "accepted") return { tier: a.tier, label: `${short} ✓`, state: "ok" };
    if (a.outcome === "below_threshold") {
      return {
        tier: a.tier,
        label: `${short} ${pct(a.confidence ?? 0)}`,
        state: answer(a.tier) ? "low" : "off",
        title: `Below its ${pct(a.threshold)} bar`,
      };
    }
    if (a.outcome === "failed") return { tier: a.tier, label: `${short} failed`, state: "off" };
    return { tier: a.tier, label: `${short} skipped`, state: "off" };
  });
  for (const tier of ["gpu", "local", "cloud"]) {
    if (!s.tierTrace.some(a => a.tier === tier)) {
      chips.push({ tier, label: `${tierInfo(tier).short} off`, state: "off" });
    }
  }
  return chips;
}

/** The answering tier's bar: the Pi's own from the trace, else the default. */
export function thresholdFor(s) {
  const traced = s.tierTrace?.find(a => a.tier === s.tier)?.threshold;
  if (typeof traced === "number") return traced;
  const fallback = tierInfo(s.tier).threshold;
  return Number.isFinite(fallback) ? fallback : null;
}

function fmtWhen(d) {
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day}, ${fmtTime(d)}`;
}

// ── Pieces ────────────────────────────────────────────────────────────────

function ConfidenceBar({ s }) {
  const threshold = thresholdFor(s);
  const width = Math.max(0, Math.min(1, s.confidence)) * 100;
  return (
    <span className="sd-conf">
      <span className="sd-bar" aria-hidden="true">
        <i style={{ width: `${width}%` }} />
        {threshold != null && <u style={{ left: `${threshold * 100}%` }} />}
      </span>
      <span title={threshold != null ? `This tier's bar is ${pct(threshold)}` : undefined}>
        {pct(s.confidence)}
      </span>
    </span>
  );
}

// Fetches the photo as a File before the tap, because Safari only lets
// navigator.share run straight off a user gesture, and a network round trip in
// between would use that gesture up.
function useShareFile(s) {
  const [file, setFile] = useState(null);
  const { id, hasImage } = s;
  const name = photoName(s);
  useEffect(() => {
    setFile(null);
    if (!hasImage || !navigator.share) return;
    let cancelled = false;
    apiFetchBinary(`/sightings/${id}/image`, { failure: "Image" })
      .then(res => res.blob())
      .then(blob => {
        if (!cancelled) setFile(new File([blob], name, { type: blob.type || "image/jpeg" }));
      })
      .catch(() => { /* Share still works, with text only. */ });
    return () => { cancelled = true; };
  }, [id, hasImage, name]);
  return file;
}

function photoName(s) {
  return `peck-deck-${s.id}-${s.species.common.replace(/\W+/g, "-").toLowerCase()}.jpg`;
}

// Web Share with the photo where the browser supports it, and a download where
// it has no share sheet at all (Firefox on desktop).
function ShareButton({ s, title }) {
  const file = useShareFile(s);
  const [busy, setBusy] = useState(false);

  async function share() {
    const text = `${title} · ${fmtWhen(s.datetime)} · ${s.device.name}`;
    const files = file ? [file] : null;
    try {
      if (files && navigator.canShare?.({ files })) await navigator.share({ title, text, files });
      else await navigator.share({ title, text });
    } catch {
      /* Cancelling the share sheet rejects too; nothing to report. */
    }
  }

  async function save() {
    setBusy(true);
    try {
      const url = await apiObjectUrl(`/sightings/${s.id}/image`);
      const a = document.createElement("a");
      a.href = url;
      a.download = photoName(s);
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      /* The button stays; a second try is the only useful recovery. */
    } finally {
      setBusy(false);
    }
  }

  if (typeof navigator !== "undefined" && navigator.share) {
    return <button type="button" className="sd-act" onClick={share}>Share</button>;
  }
  if (!s.hasImage) return null;
  return (
    <button type="button" className="sd-act" onClick={save} disabled={busy}>
      {busy ? "Saving…" : "Save photo"}
    </button>
  );
}

const PICKER_LIMIT = 40;

// The species picker. A pick saves at once, since a wrong pick is fixed the
// same way. A bird the library has never seen can be added from here.
function SpeciesPicker({ s, onClose, onCorrected }) {
  const { data, applyUpdated } = useData();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [sci, setSci] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const options = useMemo(
    () => pickerOptions(data.SPECIES || [], data.SPECIES_COUNTS || [], query),
    [data.SPECIES, data.SPECIES_COUNTS, query],
  );

  async function save(speciesId) {
    setBusy(true);
    setError(null);
    try {
      const raw = await correctSighting(s.id, speciesId);
      await applyUpdated(raw);
      onCorrected?.(raw);
      onClose();
    } catch (e) {
      setError(e.message || "Couldn't save the species.");
      setBusy(false);
    }
  }

  async function addAndSave() {
    const common = query.trim();
    const [genus, ...rest] = sci.trim().split(/\s+/);
    if (!common || !genus || !rest.length) {
      setError("Give the common name and the two-part scientific name.");
      return;
    }
    setBusy(true);
    setError(null);
    let created;
    try {
      created = await createSpecies({ common_name: common, genus, species_name: rest.join(" ") });
    } catch (e) {
      setError(e.status === 409 ? "That species is already in the library." : e.message);
      setBusy(false);
      return;
    }
    await save(created.id);
  }

  const shown = options.slice(0, PICKER_LIMIT);
  // On document.body, because the desktop panel is sticky, and a sticky box
  // would keep the dialog under the top bar.
  return createPortal(
    <Modal title="Which bird is this?" subtitle="The tier's answer stays on the record."
      onClose={onClose}>
      <TextInput label="Search species" value={query} onChange={setQuery}
        placeholder="House Finch" disabled={busy} />
      {adding ? (
        <>
          <TextInput label="Scientific name" value={sci} onChange={setSci}
            placeholder="Haemorhous mexicanus" disabled={busy}
            help={`Adds "${query.trim() || "this bird"}" to the species library.`} />
          <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
            <button type="button" className="btn" onClick={() => setAdding(false)} disabled={busy}>Back</button>
            <button type="button" className="btn primary" onClick={addAndSave} disabled={busy}>
              {busy ? "Saving…" : "Add and save"}
            </button>
          </div>
        </>
      ) : (
        <>
          <ul className="sd-picks" aria-label="Species">
            {shown.map(x => {
              const current = x.id === s.species.id;
              return (
                <li key={x.id}>
                  <button type="button" className="sd-pick" disabled={busy || current}
                    aria-current={current ? "true" : undefined} onClick={() => save(x.id)}>
                    <b>{x.common}</b>
                    {x.sci && <i>{x.sci}</i>}
                    {current && <span className="sd-pick-tag">Current</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {options.length > PICKER_LIMIT && (
            <div className="field-help">Showing {PICKER_LIMIT} of {options.length}. Type to narrow it.</div>
          )}
          {!options.length && <div className="field-help">No species in the library matches.</div>}
          <button type="button" className="btn" onClick={() => setAdding(true)} disabled={busy}>
            Not listed? Add a species
          </button>
        </>
      )}
      <FormNote error={error} />
    </Modal>,
    document.body,
  );
}

// Two taps, so a stray one can't remove a capture. While confirming, the
// confirm pair takes the whole row.
function Actions({ s, title, canDelete, onDeleted, onPickSpecies }) {
  const { applyDeleted } = useData();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Moving along the strip starts the next visit without a pending confirm.
  useEffect(() => { setConfirming(false); setError(null); }, [s.id]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await deleteSighting(s.id);
    } catch (e) {
      setError(e.message || "Delete failed.");
      setBusy(false);
      return;
    }
    setBusy(false);
    applyDeleted(s.id);
    onDeleted();
  }

  return (
    <>
      <div className="sd-acts">
        {confirming ? (
          <>
            <button type="button" className="sd-act danger" onClick={run} disabled={busy}>
              {busy ? "Deleting…" : "Delete this sighting"}
            </button>
            <button type="button" className="sd-act" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <ShareButton s={s} title={title} />
            <button type="button" className="sd-act" onClick={onPickSpecies}>
              {needsName(s) ? "Name it" : "Wrong bird?"}
            </button>
            {canDelete && (
              <button type="button" className="sd-act" onClick={() => setConfirming(true)}>Delete</button>
            )}
          </>
        )}
      </div>
      {error && <div className="field-help field-error sd-error" role="alert">{error}</div>}
    </>
  );
}

function Strip({ strip, current, onPick }) {
  const curRef = useRef(null);
  useEffect(() => {
    curRef.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [current.id]);
  if (strip.length < 2) return null;
  return (
    <div className="sd-strip" role="group" aria-label="Visits from this feeder that day">
      {strip.map(x => (
        <button key={x.id} type="button" className="sd-thumb"
          ref={x.id === current.id ? curRef : undefined}
          aria-current={x.id === current.id ? "true" : undefined}
          aria-label={`${needsName(x) ? "Unnamed bird" : x.species.common}, ${fmtTime(x.datetime)}`}
          onClick={() => onPick(x)}>
          <SightingImage sighting={x} alt="" />
        </button>
      ))}
    </div>
  );
}

// ── The view ──────────────────────────────────────────────────────────────

/**
 * @param s          the sighting on screen
 * @param onClose    closes the view
 * @param onMove     shows another sighting from the strip, in place
 * @param onCorrected  gets the raw row after a species correction saves
 * @param backLabel  the screen the phone's back button returns to
 */
export function SightingDetail({ s, onClose, onMove, onCorrected, backLabel = "Back" }) {
  const { data } = useData();
  const panelRef = useRef(null);
  // The picker is a dialog over this one. Escape and the arrow keys belong to
  // it while it is open. A ref, because this view's key listeners stay put.
  const [picking, setPicking] = useState(false);
  const pickingRef = useRef(false);
  const showPicker = useCallback((open) => {
    pickingRef.current = open;
    setPicking(open);
  }, []);
  const closeUnlessPicking = useCallback(() => {
    if (!pickingRef.current) onClose();
  }, [onClose]);
  useDialog(closeUnlessPicking, panelRef);
  useEffect(() => { showPicker(false); }, [s?.id, showPicker]);
  // useDialog focuses the first control, which on desktop is the phone's
  // hidden back button. Focus the panel itself when that misses.
  useEffect(() => {
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) panel.focus({ preventScroll: true });
  }, []);
  const accent = useSpeciesAccent(s?.species);

  const sightings = data.SIGHTINGS || [];
  const strip = useMemo(() => (s ? dayStrip(sightings, s) : []), [sightings, s]);
  const at = s ? strip.findIndex(x => x.id === s.id) : -1;
  const step = useCallback((by) => {
    const next = strip[at + by];
    if (next && onMove) onMove(next);
  }, [strip, at, onMove]);

  // Arrow keys walk the strip, left toward newer as it is drawn. Not while a
  // form control has focus, since the panel sits beside the History filters.
  useEffect(() => {
    function onKey(e) {
      if (e.altKey || e.ctrlKey || e.metaKey || pickingRef.current) return;
      if (e.target.closest?.("input, select, textarea")) return;
      if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [step]);

  // A horizontal swipe on the photo does the same. Mostly-vertical drags are
  // left alone so the view still scrolls.
  const touch = useRef(null);
  const onTouchStart = (e) => {
    const t = e.touches[0];
    touch.current = { x: t.clientX, y: t.clientY };
  };
  const onTouchEnd = (e) => {
    const start = touch.current;
    touch.current = null;
    if (!start) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  };

  const unnamed = s ? needsName(s) : false;
  const [peaks, setPeaks] = useState(null);
  const speciesId = s?.species.id;
  useEffect(() => {
    setPeaks(null);
    if (speciesId == null || unnamed) return;
    let cancelled = false;
    fetchSpeciesHours(speciesId)
      .then(h => { if (!cancelled) setPeaks(h.peak_hours); })
      .catch(() => { /* The line just leaves the busy hours out. */ });
    return () => { cancelled = true; };
  }, [speciesId, unnamed]);

  if (!s) return null;

  const title = unnamed ? "Needs a name" : s.species.common;
  const context = contextLine(s, visitOrdinal(sightings, s), unnamed ? null : peaks);
  const correctedBy = correctedByName(s, data.ME, data.USERS);
  const tierSaid = s.originalSpecies;

  return (
    <aside className="sd" style={accent} ref={panelRef} role="dialog"
      aria-label={`${title} sighting`} tabIndex={-1}>
      <div className="sd-stage">
        <div className="sd-nav">
          <span className="sd-nav-l">
            <button type="button" className="sd-nav-btn sd-back" onClick={onClose}>‹ {backLabel}</button>
            <span className="sd-steps">
              <button type="button" className="sd-nav-btn" aria-label="Newer visit"
                onClick={() => step(-1)} disabled={at <= 0}>‹</button>
              <button type="button" className="sd-nav-btn" aria-label="Older visit"
                onClick={() => step(1)} disabled={at < 0 || at >= strip.length - 1}>›</button>
            </span>
          </span>
          <span className="sd-nav-title tnum">{fmtTime(s.datetime)}</span>
          <span className="sd-nav-r">
            <button type="button" className="sd-nav-btn sd-close" onClick={onClose} aria-label="Close sighting">
              <Icon name="x" className="" />
            </button>
          </span>
        </div>
        <div className="sd-photo" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
          <SightingImage key={s.id} sighting={s} large />
        </div>
        <Strip strip={strip} current={s} onPick={(x) => onMove?.(x)} />
      </div>

      <div className="sd-sheet">
        <h2 className={`sd-name ${unnamed ? "unnamed" : ""}`}>
          {unnamed ? (
            <button type="button" className="sd-name-btn" onClick={() => showPicker(true)}
              title="Choose the species">
              {title}
            </button>
          ) : title}
        </h2>
        {unnamed
          ? <div className="sd-sci">No tier was sure enough to name this bird.</div>
          : s.species.sci && <div className="sd-sci">{s.species.sci}</div>}
        <div className="sd-meta">{fmtWhen(s.datetime)} · {s.device.name}</div>
        {context && <div className="sd-note">{context}</div>}

        <dl className="sd-details">
          {correctedBy && (
            <div>
              <dt>Named by</dt>
              <dd>{correctedBy === "you" ? "You" : correctedBy}, {fmtDateLabel(s.correctedAt)}</dd>
            </div>
          )}
          {correctedBy && tierSaid && (
            <div>
              <dt>Tier said</dt>
              <dd>{isPlaceholder(tierSaid) ? "No name" : tierSaid.common}</dd>
            </div>
          )}
          <div>
            <dt>Confidence</dt>
            <dd><ConfidenceBar s={s} /></dd>
          </div>
          <div>
            <dt>Tiers</dt>
            <dd className="sd-chain">
              {tierChips(s).map(c => (
                <b key={c.tier} className={c.state} title={c.title}>{c.label}</b>
              ))}
            </dd>
          </div>
          <div>
            <dt>Uploaded</dt>
            <dd>{s.delayed ? "Queued, sent later" : "Live, not queued"}</dd>
          </div>
        </dl>

        <Actions s={s} title={title} canDelete={canDeleteSighting(s, data.ME)} onDeleted={onClose}
          onPickSpecies={() => showPicker(true)} />
      </div>
      {picking && (
        <SpeciesPicker s={s} onClose={() => showPicker(false)} onCorrected={onCorrected} />
      )}
    </aside>
  );
}
