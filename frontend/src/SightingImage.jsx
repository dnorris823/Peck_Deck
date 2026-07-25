// Lazily-loaded capture photo — FLEDGE Phase 7.
//
// The gallery used to show only the stylized species plate, so the actual camera
// frame the Pi uploaded was never visible in the app. This shows it, and shows
// it lazily, which on a phone is the whole point: a full "all time" gallery is
// ~100 sightings, and eagerly fetching 100 × ~300 KB JPEGs over cellular to fill
// a screen that holds six of them is most of a data plan.
//
// `loading="lazy"` can't do this job. `GET /sightings/{id}/image` requires a user
// JWT and an <img src> cannot carry an Authorization header, so the bytes have to
// come through fetch — which means the laziness has to be ours too. An
// IntersectionObserver starts the fetch just before the tile scrolls into view.
//
// The plate stays underneath as the placeholder, so a tile is never an empty box
// while loading, and a sighting with no stored image (or a failed fetch) simply
// keeps showing the plate.
import React, { useEffect, useRef, useState } from "react";
import { BirdPlate } from "./BirdPlate.jsx";
import { apiObjectUrl } from "./api.js";

// Start fetching this far before the tile reaches the viewport, so the image is
// usually decoded by the time it's actually on screen.
const PREFETCH_MARGIN = "300px";

export function SightingImage({ sighting, large = false, alt }) {
  const holder = useRef(null);
  const [visible, setVisible] = useState(false);
  const [src, setSrc] = useState(null);

  // Arm the observer. Without IntersectionObserver (older browsers, jsdom in the
  // test suite) fall back to loading immediately — degraded, but never blank.
  useEffect(() => {
    if (!sighting?.hasImage) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const node = holder.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect(); // one-shot: the image is cached from here on
        }
      },
      { rootMargin: PREFETCH_MARGIN }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [sighting?.hasImage]);

  useEffect(() => {
    if (!visible || !sighting?.hasImage) return;
    let url = null;
    let cancelled = false;

    apiObjectUrl(`/sightings/${sighting.id}/image`)
      .then((objectUrl) => {
        url = objectUrl;
        if (cancelled) URL.revokeObjectURL(objectUrl);
        else setSrc(objectUrl);
      })
      .catch(() => {
        /* Keep the plate. A missing photo is not worth an error state. */
      });

    return () => {
      cancelled = true;
      // Revoking on unmount is what keeps a long scroll from retaining every
      // JPEG it passed.
      if (url) URL.revokeObjectURL(url);
    };
  }, [visible, sighting?.hasImage, sighting?.id]);

  return (
    <div className="capture" ref={holder}>
      <BirdPlate species={sighting.species} showLabel={false} large={large} />
      {src && (
        <img
          className="capture-img"
          src={src}
          alt={alt || `Photo of ${sighting.species.common}`}
          loading="lazy"
          decoding="async"
        />
      )}
    </div>
  );
}
