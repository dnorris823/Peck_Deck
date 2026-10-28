import { describe, it, expect, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { OfflineBanner } from "./Offline.jsx";

describe("OfflineBanner", () => {
  it("renders nothing while the browser is online", () => {
    const { container } = render(<OfflineBanner onRetry={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says so when the browser is offline", () => {
    render(<OfflineBanner offline onRetry={vi.fn()} />);
    expect(screen.getByText("You're offline")).toBeInTheDocument();
    expect(screen.getByText(/last data this page loaded/)).toBeInTheDocument();
  });

  it("retries on demand", () => {
    const onRetry = vi.fn();
    render(<OfflineBanner offline onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("disables the retry button while a refresh is already running", () => {
    render(<OfflineBanner offline loading onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Retrying…" })).toBeDisabled();
  });
});
