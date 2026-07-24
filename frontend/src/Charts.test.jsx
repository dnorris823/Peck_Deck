import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BarList, ColumnChart, TrendChart } from "./Charts.jsx";

describe("TrendChart", () => {
  const labels = ["2026-07-01", "2026-07-02", "2026-07-03"];
  const values = [2, 9, 4];

  it("exposes the caption as the accessible name of the plot", () => {
    render(<TrendChart labels={labels} values={values} caption="Visits per day" />);

    expect(screen.getByRole("img", { name: "Visits per day" })).toBeInTheDocument();
  });

  it("labels the peak and the endpoint but not every point", () => {
    const { container } = render(
      <TrendChart labels={labels} values={values} caption="Visits per day" />
    );

    const labelled = [...container.querySelectorAll(".chart-value-label")].map(
      (n) => n.textContent
    );
    // 9 is the peak, 4 is the endpoint; 2 is deliberately unlabelled.
    expect(labelled).toEqual(["9", "4"]);
  });

  it("offers a table view so no value is gated behind hover", async () => {
    const user = userEvent.setup();
    render(<TrendChart labels={labels} values={values} caption="Visits per day" />);

    const toggle = screen.getByRole("button", { name: /view as table/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const table = screen.getByRole("table");
    expect(within(table).getByRole("rowheader", { name: "2026-07-02" })).toBeInTheDocument();
    expect(within(table).getByText("9")).toBeInTheDocument();
  });

  it("survives a flat all-zero series without dividing by zero", () => {
    const { container } = render(
      <TrendChart labels={labels} values={[0, 0, 0]} caption="Quiet" />
    );

    const points = container.querySelector("polyline").getAttribute("points");
    expect(points).not.toMatch(/NaN/);
  });
});

describe("ColumnChart", () => {
  const labels = ["12a", "1a", "2a"];
  const values = [1, 7, 3];

  it("gives every column a focusable, labelled hit target", () => {
    render(<ColumnChart labels={labels} values={values} caption="By hour" />);

    const target = screen.getByRole("button", { name: "1a: 7 visits" });
    expect(target).toHaveAttribute("tabindex", "0");
  });

  it("shows the same readout on keyboard focus as on hover", async () => {
    const user = userEvent.setup();
    render(<ColumnChart labels={labels} values={values} caption="By hour" />);

    await user.tab();
    await user.tab();

    const tip = screen.getByRole("status");
    expect(within(tip).getByText("7")).toBeInTheDocument();
  });

  it("rounds the axis maximum so the midpoint tick is a whole number", () => {
    // max 25 would put the middle gridline at 12.5 and label it 13.
    const { container } = render(
      <ColumnChart labels={["a"]} values={[25]} caption="Odd max" />
    );

    const ticks = [...container.querySelectorAll(".chart-axis-text")]
      .map((n) => Number(n.textContent))
      .filter((n) => !Number.isNaN(n));
    expect(ticks).toContain(13);
    expect(ticks).toContain(26);
  });
});

describe("BarList", () => {
  const items = [
    { label: "Backyard Maple", value: 76 },
    { label: "Cabin Window", value: 20 },
  ];

  it("renders each row with its value", () => {
    render(<BarList items={items} caption="Visits by station" />);

    expect(screen.getByText("Backyard Maple")).toBeInTheDocument();
    expect(screen.getByText("76")).toBeInTheDocument();
  });

  it("keeps a zero-value row visible rather than collapsing it to nothing", () => {
    const { container } = render(
      <BarList items={[{ label: "Quiet", value: 0 }]} caption="Visits by station" />
    );

    const width = container.querySelector(".barlist-fill").style.width;
    expect(parseFloat(width)).toBeGreaterThan(0);
  });
});
