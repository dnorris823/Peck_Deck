import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { HourDial, dialPoint } from "./HourDial.jsx";

const hours = (pairs) => {
  const counts = Array(24).fill(0);
  for (const [h, v] of Object.entries(pairs)) counts[h] = v;
  return counts;
};

describe("HourDial", () => {
  it("puts noon at the top and midnight at the bottom", () => {
    const [nx, ny] = dialPoint(50, 12);
    const [mx, my] = dialPoint(50, 0);
    expect(nx).toBeCloseTo(100);
    expect(ny).toBeCloseTo(50);
    expect(mx).toBeCloseTo(100);
    expect(my).toBeCloseTo(150);
  });

  it("draws one petal for a species with one visit", () => {
    const { container } = render(<HourDial counts={hours({ 8: 1 })} busiest={8} />);
    const petals = container.querySelectorAll(".sv-petal");
    expect(petals).toHaveLength(1);
    expect(petals[0].textContent).toBe("8 am: 1 visit");
    expect(screen.getByRole("img")).toHaveAccessibleName("Visits by hour of day. Busiest at 8 am.");
  });

  it("sizes petals by count against the busiest hour", () => {
    const { container } = render(<HourDial counts={hours({ 8: 10, 17: 5 })} busiest={8} />);
    const [morning, evening] = container.querySelectorAll(".sv-petal");
    expect(Number(morning.getAttribute("opacity"))).toBeCloseTo(1);
    expect(Number(evening.getAttribute("opacity"))).toBeCloseTo(0.65);
  });

  it("draws an empty face with no visits, or before the counts arrive", () => {
    const { container, rerender } = render(<HourDial counts={Array(24).fill(0)} />);
    expect(container.querySelectorAll(".sv-petal")).toHaveLength(0);
    expect(screen.getByRole("img")).toHaveAccessibleName("Visits by hour of day. No visits in this period.");
    rerender(<HourDial counts={undefined} loading />);
    expect(container.querySelectorAll(".sv-petal")).toHaveLength(0);
  });
});
