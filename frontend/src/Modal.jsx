// Small reusable modal + form primitives for the CRUD dialogs.
import React from "react";
import { Icon } from "./Icon.jsx";

export function Modal({ title, subtitle, onClose, children, footer, maxWidth = 460 }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" style={{ maxWidth }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}><Icon name="x" className="" /></button>
        <div style={{ padding: "28px 32px" }}>
          {title && <h2 className="display" style={{ fontSize: 30, lineHeight: 1.05, margin: 0 }}>{title}</h2>}
          {subtitle && (
            <div className="display-i" style={{ fontSize: 15, color: "var(--ink-soft)", marginTop: 4 }}>
              {subtitle}
            </div>
          )}
          <div style={{ marginTop: 20, display: "grid", gap: 14 }}>{children}</div>
          {footer && (
            <div className="row" style={{ marginTop: 24, justifyContent: "flex-end", gap: 8 }}>
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function TextInput({ label, help, value, onChange, type = "text", placeholder, disabled }) {
  return (
    <label style={{ display: "block" }}>
      <div className="field-label" style={{ marginBottom: 6 }}>{label}</div>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        style={{ width: "100%" }}
      />
      {help && <div className="field-help" style={{ marginTop: 4 }}>{help}</div>}
    </label>
  );
}

export function SelectInput({ label, value, onChange, options }) {
  return (
    <label style={{ display: "block" }}>
      <div className="field-label" style={{ marginBottom: 6 }}>{label}</div>
      <select value={value} onChange={e => onChange(e.target.value)} style={{ width: "100%" }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

// Inline error/success line for modal forms.
export function FormNote({ error, note }) {
  if (error) return <div className="field-help" style={{ color: "var(--cardinal)" }}>{error}</div>;
  if (note) return <div className="field-help" style={{ color: "var(--forest)" }}>{note}</div>;
  return null;
}
