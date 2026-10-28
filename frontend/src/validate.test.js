import { describe, it, expect } from "vitest";
import {
  checkRequired, checkEmail, checkPassword,
  collect, hasErrors, MIN_PASSWORD_LENGTH,
} from "./validate.js";

describe("checkRequired", () => {
  it("rejects empty/whitespace and accepts real values", () => {
    expect(checkRequired("")).toMatch(/required/);
    expect(checkRequired("   ")).toMatch(/required/);
    expect(checkRequired(null, "Name")).toBe("Name is required.");
    expect(checkRequired("Backyard")).toBeNull();
  });
});

describe("checkEmail", () => {
  it("accepts a well-formed address", () => {
    expect(checkEmail("dom@peck.deck")).toBeNull();
  });
  it("rejects malformed addresses", () => {
    for (const bad of ["dom", "dom@", "@peck.deck", "dom@peck", "a b@c.d"]) {
      expect(checkEmail(bad)).toMatch(/valid email/);
    }
  });
  it("treats empty as required by default, optional when asked", () => {
    expect(checkEmail("")).toMatch(/required/);
    expect(checkEmail("", { required: false })).toBeNull();
  });
});

describe("checkPassword", () => {
  it("requires the minimum length", () => {
    expect(checkPassword("")).toMatch(/required/);
    expect(checkPassword("short")).toMatch(new RegExp(`${MIN_PASSWORD_LENGTH}`));
    expect(checkPassword("longenough1")).toBeNull();
  });
  it("uses the provided label", () => {
    expect(checkPassword("", { label: "New password" })).toBe("New password is required.");
  });
});

describe("collect / hasErrors", () => {
  it("keeps only the truthy entries", () => {
    const errs = collect({ a: "bad", b: null, c: "also bad" });
    expect(errs).toEqual({ a: "bad", c: "also bad" });
    expect(hasErrors(errs)).toBe(true);
    expect(hasErrors(collect({ a: null }))).toBe(false);
  });
});
