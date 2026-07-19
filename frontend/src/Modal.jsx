// Small reusable modal + form primitives for the CRUD dialogs.
import React, { useEffect, useId, useRef } from "react";
import { Icon } from "./Icon.jsx";

// Escape-to-close + focus management, shared by every dialog (the reusable Modal
// here plus the bespoke detail modals). On open it focuses the panel (or the
// first focusable control) and restores focus to the previously-focused element
// on close, so keyboard users aren't dumped at the top of the page.
export function useDialog(onClose, panelRef) {
  useEffect(() => {
    const prevFocus = document.activeElement;
    const panel = panelRef.current;
    if (panel) {
      const focusable = panel.querySelector(
        "input, select, textarea, button, [href], [tabindex]:not([tabindex='-1'])"
      );
      (focusable || panel).focus();
    }
    function onKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (prevFocus && prevFocus.focus) prevFocus.focus();
    };
  }, [onClose, panelRef]);
}

export function Modal({ title, subtitle, onClose, children, footer, maxWidth = 460 }) {
  const panelRef = useRef(null);
  const titleId = useId();
  useDialog(onClose, panelRef);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div
        className="modal"
        style={{ maxWidth }}
        onClick={e => e.stopPropagation()}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        tabIndex={-1}
      >
        <button className="modal-close" onClick={onClose} aria-label="Close dialog">
          <Icon name="x" className="" />
        </button>
        <div style={{ padding: "28px 32px" }}>
          {title && <h2 id={titleId} className="display" style={{ fontSize: 30, lineHeight: 1.05, margin: 0 }}>{title}</h2>}
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

export function TextInput({ label, help, value, onChange, type = "text", placeholder, disabled, error, onBlur }) {
  const id = useId();
  const errId = `${id}-err`;
  return (
    <label htmlFor={id} style={{ display: "block" }}>
      <div className="field-label" style={{ marginBottom: 6 }}>{label}</div>
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        onBlur={onBlur}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={error ? errId : undefined}
        style={{ width: "100%", ...(error ? { borderColor: "var(--cardinal)" } : null) }}
      />
      {error
        ? <div id={errId} className="field-help" style={{ marginTop: 4, color: "var(--cardinal)" }}>{error}</div>
        : help && <div className="field-help" style={{ marginTop: 4 }}>{help}</div>}
    </label>
  );
}

export function SelectInput({ label, value, onChange, options }) {
  const id = useId();
  return (
    <label htmlFor={id} style={{ display: "block" }}>
      <div className="field-label" style={{ marginBottom: 6 }}>{label}</div>
      <select id={id} value={value} onChange={e => onChange(e.target.value)} style={{ width: "100%" }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

// Inline error/success line for modal forms.
export function FormNote({ error, note }) {
  if (error) return <div className="field-help" role="alert" style={{ color: "var(--cardinal)" }}>{error}</div>;
  if (note) return <div className="field-help" style={{ color: "var(--forest)" }}>{note}</div>;
  return null;
}
