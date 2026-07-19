// Shared form-validation helpers. Each `check*` returns an error string when the
// value is invalid, or null when it's acceptable — so callers can do
// `const err = checkEmail(v); if (err) …`. Keeping the rules here (not inline in
// each form) means the backend contract is described in one place and is testable.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// E.164: a leading + and 1–15 digits (first digit non-zero).
const E164_RE = /^\+[1-9]\d{1,14}$/;

export const MIN_PASSWORD_LENGTH = 8;

export function checkRequired(value, label = "This field") {
  if (value == null || String(value).trim() === "") return `${label} is required.`;
  return null;
}

export function checkEmail(value, { required = true } = {}) {
  const v = (value ?? "").trim();
  if (!v) return required ? "Email is required." : null;
  if (!EMAIL_RE.test(v)) return "Enter a valid email address.";
  return null;
}

// Phone is optional almost everywhere; only validate the format when present.
export function checkPhone(value, { required = false } = {}) {
  const v = (value ?? "").trim();
  if (!v) return required ? "Phone is required." : null;
  if (!E164_RE.test(v)) return "Use E.164 format, e.g. +15125550123.";
  return null;
}

export function checkPassword(value, { label = "Password" } = {}) {
  const v = value ?? "";
  if (!v) return `${label} is required.`;
  if (v.length < MIN_PASSWORD_LENGTH) {
    return `${label} must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return null;
}

// Run a map of {field: errorOrNull} and return only the truthy entries, so a
// form can `const errs = collect({...}); if (hasErrors(errs)) …`.
export function collect(map) {
  const out = {};
  for (const [k, v] of Object.entries(map)) if (v) out[k] = v;
  return out;
}

export function hasErrors(errs) {
  return Object.keys(errs).length > 0;
}
