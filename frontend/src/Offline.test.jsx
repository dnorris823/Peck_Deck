import { describe, it, expect, vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { OfflineBanner, PullToRefresh } from "./Offline.jsx";

describe("OfflineBanner", () => {
  it("renders nothing while data is live", () => {
    const { container } = render(<OfflineBanner stale={null} onRetry={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says so when the browser is offline even though the load succeeded", () => {
    // With the service worker installed an offline load is answered from cache,
    // so nothing in the data layer knows anything is wrong — only navigator does.
    render(<OfflineBanner stale={null} offline onRetry={vi.fn()} />);
    expect(screen.getByText("You're offline")).toBeInTheDocument();
    expect(screen.getByText(/last data this device loaded/)).toBeInTheDocument();
  });

  it("says how old the shown data is", () => {
    const savedAt = Date.now() - 3 * 60 * 60 * 1000;
    render(<OfflineBanner stale={{ savedAt }} onRetry={vi.fn()} />);
    expect(screen.getByText("Showing saved data")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("retries on demand", () => {
    const onRetry = vi.fn();
    render(<OfflineBanner stale={{ savedAt: Date.now() }} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("disables the retry button while a refresh is already running", () => {
    render(<OfflineBanner stale={{ savedAt: Date.now() }} loading onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Retrying…" })).toBeDisabled();
  });
});

/** Drive a vertical touch drag over `distance` px, ending with a release. */
function drag(distance, { release = true } = {}) {
  act(() => {
    fireEvent.touchStart(window, { touches: [{ clientY: 0 }] });
    fireEvent.touchMove(window, { touches: [{ clientY: distance }] });
  });
  if (release) act(() => { fireEvent.touchEnd(window, {}); });
}

describe("PullToRefresh", () => {
  it("renders nothing until a pull starts", () => {
    const { container } = render(<PullToRefresh onRefresh={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("ignores a short pull", () => {
    const onRefresh = vi.fn();
    render(<PullToRefresh onRefresh={onRefresh} />);
    // 60px of finger travel is 30px of pull after resistance — under threshold.
    drag(60);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("refreshes when the pull is released past the threshold", () => {
    const onRefresh = vi.fn();
    render(<PullToRefresh onRefresh={onRefresh} />);
    drag(200);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("invites the release once the threshold is crossed", () => {
    render(<PullToRefresh onRefresh={vi.fn()} />);
    drag(200, { release: false });
    expect(screen.getByText("Release to refresh")).toBeInTheDocument();
  });

  it("does not arm mid-list, where the gesture is an ordinary scroll", () => {
    const onRefresh = vi.fn();
    render(<PullToRefresh onRefresh={onRefresh} />);
    window.scrollY = 400;
    try {
      drag(200);
      expect(onRefresh).not.toHaveBeenCalled();
    } finally {
      window.scrollY = 0;
    }
  });

  it("abandons the gesture if the finger reverses upward", () => {
    const onRefresh = vi.fn();
    render(<PullToRefresh onRefresh={onRefresh} />);
    act(() => {
      fireEvent.touchStart(window, { touches: [{ clientY: 100 }] });
      fireEvent.touchMove(window, { touches: [{ clientY: 300 }] }); // 200 down
      fireEvent.touchMove(window, { touches: [{ clientY: 50 }] });  // back up
    });
    act(() => { fireEvent.touchEnd(window, {}); });
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("shows a spinner label while the refresh runs", () => {
    render(<PullToRefresh onRefresh={vi.fn()} busy />);
    expect(screen.getByText("Refreshing…")).toBeInTheDocument();
  });

  it("does not start a second refresh while one is in flight", () => {
    const onRefresh = vi.fn();
    render(<PullToRefresh onRefresh={onRefresh} busy />);
    drag(200);
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
