// Species library — gridded specimen plates with counts
import React, { useMemo, useRef, useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote, useDialog } from "./Modal.jsx";
import { Empty } from "./Empty.jsx";
import { SightingImage } from "./SightingImage.jsx";
import { createSpecies, fmtRelative } from "./data.js";

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
      subtitle="Catalogue a bird by hand. Field-guide art is generated from defaults."
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

// The card leads with this species' newest photo when the loaded window has
// one, and falls back to the field-guide plate.
function Specimen({ s, idx, photo, onClick }) {
  return (
    <button type="button" className="specimen" onClick={() => onClick(s)}>
      <div className="specimen-plate">
        {photo ? <SightingImage sighting={photo} /> : <BirdPlate species={s} showLabel={false} />}
        <span className="tile-badge tile-badge-l">№ {String(idx + 1).padStart(3, "0")}</span>
      </div>
      <div className="specimen-body">
        <div className="specimen-common">{s.common}</div>
        <div className="specimen-sci">{s.sci}</div>
        <div className="specimen-meta">
          <div>
            Visits
            <strong className="tnum">{s.count.toLocaleString()}</strong>
          </div>
          <div className="specimen-meta-r">
            First seen
            <strong>{s.firstSeen}</strong>
          </div>
        </div>
      </div>
    </button>
  );
}

function SpeciesDetail({ s, photo, lastSeen, onClose, onViewSightings }) {
  const panelRef = useRef(null);
  useDialog(onClose, panelRef);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}
        ref={panelRef} role="dialog" aria-modal="true" aria-label={`${s.common} details`} tabIndex={-1}>
        <button className="modal-close" onClick={onClose} aria-label="Close dialog"><Icon name="x" className="" /></button>
        <div className="modal-grid">
          <div className={`modal-img ${photo ? "" : "modal-img-plate"}`}>
            {photo ? <SightingImage sighting={photo} large /> : <BirdPlate species={s} showLabel={false} large />}
          </div>
          <div className="modal-side">
            <div className="label">{s.order !== "—" ? s.order : "Species"}</div>
            <h2 className="modal-title">{s.common}</h2>
            <div className="modal-sci">{s.sci}</div>

            <dl className="facts">
              <div>
                <dt className="label">Total visits</dt>
                <dd className="tnum">{s.count.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="label">First seen</dt>
                <dd>{s.firstSeen}</dd>
              </div>
              {lastSeen && (
                <div>
                  <dt className="label">Last seen</dt>
                  <dd>{fmtRelative(lastSeen)}</dd>
                </div>
              )}
            </dl>

            {s.note && <p className="modal-note">{s.note}</p>}

            <div className="modal-actions">
              <button className="btn primary" onClick={onViewSightings}>
                View sightings <Icon name="arrow" className="" />
              </button>
              {s.wiki && (
                <a className="btn ghost" href={s.wiki} target="_blank" rel="noopener noreferrer">
                  <Icon name="extlink" className="" /> Wikipedia
                </a>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function SpeciesPage({ go }) {
  const { data, reload } = useData();
  const { SPECIES_COUNTS, SIGHTINGS } = data;
  // Newest sighting per species (any), and newest with a photo.
  const { latestBy, photoBy } = useMemo(() => {
    const latestBy = new Map();
    const photoBy = new Map();
    for (const s of SIGHTINGS) {
      if (!latestBy.has(s.species.id)) latestBy.set(s.species.id, s);
      if (s.hasImage && !photoBy.has(s.species.id)) photoBy.set(s.species.id, s);
    }
    return { latestBy, photoBy };
  }, [SIGHTINGS]);
  const [order, setOrder] = useState("count");
  const [openSp, setOpenSp] = useState(null);
  const [adding, setAdding] = useState(false);

  const sorted = [...SPECIES_COUNTS].sort((a, b) => {
    if (order === "count") return b.count - a.count;
    if (order === "name") return a.common.localeCompare(b.common);
    if (order === "recent") {
      // Species with a visit in the loaded window first, newest visit first.
      const ta = latestBy.get(a.id)?.datetime.getTime() ?? 0;
      const tb = latestBy.get(b.id)?.datetime.getTime() ?? 0;
      return tb - ta;
    }
    return 0;
  });

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label">Recorded by your stations</div>
          <h1 className="page-title">Species <em>library</em></h1>
          <p className="page-lede">Every species your feeders have caught on camera. Open one for field notes.</p>
        </div>
        <div className="page-meta">
          <span className="page-meta-num tnum">{SPECIES_COUNTS.length}</span>
          <span className="label">species seen</span>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Sort species">
          {[["count", "Most visits"], ["recent", "Recently seen"], ["name", "A to Z"]].map(([id, label]) => (
            <button key={id} className={order === id ? "active" : ""} aria-pressed={order === id}
              onClick={() => setOrder(id)}>{label}</button>
          ))}
        </div>
        <span className="toolbar-end">
          <button className="btn sm" onClick={() => setAdding(true)}>
            <Icon name="plus" className="" /> Add species
          </button>
        </span>
      </div>

      {sorted.length > 0 ? (
        <div className="species-grid">
          {sorted.map((s, i) => (
            <Specimen key={s.id} s={s} idx={i} photo={photoBy.get(s.id)} onClick={setOpenSp} />
          ))}
        </div>
      ) : (
        <Empty
          icon="📖"
          title="No species catalogued yet"
          hint="Species appear here as your stations identify them — or add one by hand."
          action={<button className="btn primary sm" onClick={() => setAdding(true)}>
            <Icon name="plus" className="" /> Add species
          </button>}
        />
      )}

      {openSp && (
        <SpeciesDetail s={openSp} photo={photoBy.get(openSp.id)}
          lastSeen={latestBy.get(openSp.id)?.datetime}
          onClose={() => setOpenSp(null)}
          onViewSightings={() => go("sightings", { species: openSp.id })} />
      )}
      {adding && <AddSpeciesModal onClose={() => setAdding(false)} onDone={reload} />}
    </>
  );
}
