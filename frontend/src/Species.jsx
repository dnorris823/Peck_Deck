// Species library — gridded specimen plates with counts
import React, { useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { Icon } from "./Icon.jsx";
import { useData } from "./DataContext.jsx";
import { Modal, TextInput, FormNote } from "./Modal.jsx";
import { createSpecies } from "./data.js";

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

function Specimen({ s, idx, onClick }) {
  return (
    <div className="specimen" onClick={() => onClick(s)}>
      <div className="specimen-plate">
        <span className="specimen-no">№ {String(idx + 1).padStart(3, "0")}</span>
        <BirdPlate species={s} showLabel={false} />
      </div>
      <div className="specimen-body">
        <div className="specimen-common">{s.common}</div>
        <div className="specimen-sci">{s.sci}</div>
        <div className="specimen-meta">
          <div>
            Sightings
            <strong className="tnum">{s.count}</strong>
          </div>
          <div style={{ textAlign: "right" }}>
            First seen
            <strong>{s.firstSeen}</strong>
          </div>
        </div>
      </div>
    </div>
  );
}

function SpeciesDetail({ s, onClose }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}><Icon name="x" className="" /></button>
        <div className="modal-grid">
          <div className="modal-img">
            <BirdPlate species={s} showLabel={false} large />
          </div>
          <div className="modal-side">
            <div className="label" style={{ marginBottom: 8 }}>{s.order} · Cataloged 2026</div>
            <h2 className="display" style={{ fontSize: 38, lineHeight: 1, margin: 0 }}>
              {s.common}
            </h2>
            <div className="display-i" style={{ fontSize: 17, color: "var(--ink-soft)", marginTop: 4 }}>
              {s.sci}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--hairline)" }}>
              <div>
                <div className="label">Total visits</div>
                <div className="display-i tnum" style={{ fontSize: 26, marginTop: 4 }}>{s.count}</div>
              </div>
              <div>
                <div className="label">First seen</div>
                <div style={{ marginTop: 6 }}>{s.firstSeen}</div>
              </div>
              <div>
                <div className="label">Stations</div>
                <div style={{ marginTop: 6 }}>3 of 3</div>
              </div>
            </div>

            <p style={{ fontSize: 13.5, color: "var(--ink-soft)", marginTop: 22, lineHeight: 1.55 }}>
              {s.note}
            </p>

            <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
              <a className="btn" href={s.wiki} target="_blank" rel="noopener">
                <Icon name="extlink" className="" /> Wikipedia
              </a>
              <button className="btn">View all sightings</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function SpeciesPage() {
  const { data, reload } = useData();
  const { SPECIES, SPECIES_COUNTS } = data;
  const [order, setOrder] = useState("count");
  const [openSp, setOpenSp] = useState(null);
  const [adding, setAdding] = useState(false);

  const sorted = [...SPECIES_COUNTS].sort((a, b) => {
    if (order === "count") return b.count - a.count;
    if (order === "name") return a.common.localeCompare(b.common);
    if (order === "recent") return a.id - b.id; // proxy
    return 0;
  });

  return (
    <>
      <div className="page-header">
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Recorded by your stations</div>
          <h1 className="page-title">Species <em>library</em></h1>
          <div style={{ marginTop: 10, color: "var(--ink-soft)", maxWidth: "60ch" }}>
            Every species your feeders have catalogued. Tap a plate to read field notes.
          </div>
        </div>
        <div className="page-meta">
          <div className="label">Catalogued</div>
          <div className="page-meta-row">
            <span className="page-meta-num tnum">{SPECIES.length}</span>
            <span className="display-i" style={{ fontSize: 18, color: "var(--ink-soft)" }}>species</span>
          </div>
        </div>
      </div>

      <div className="toolbar">
        <button className={`chip ${order === "count" ? "active" : ""}`} onClick={() => setOrder("count")}>Most frequent</button>
        <button className={`chip ${order === "name" ? "active" : ""}`} onClick={() => setOrder("name")}>A → Z</button>
        <button className={`chip ${order === "recent" ? "active" : ""}`} onClick={() => setOrder("recent")}>Recently added</button>
        <button className="btn primary sm" style={{ marginLeft: "auto" }} onClick={() => setAdding(true)}>
          <Icon name="plus" className="" /> Add species
        </button>
      </div>

      <div className="species-grid">
        {sorted.map((s, i) => <Specimen key={s.id} s={s} idx={i} onClick={setOpenSp} />)}
      </div>

      {openSp && <SpeciesDetail s={openSp} onClose={() => setOpenSp(null)} />}
      {adding && <AddSpeciesModal onClose={() => setAdding(false)} onDone={reload} />}
    </>
  );
}
