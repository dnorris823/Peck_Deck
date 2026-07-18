// Icon set — inline SVG glyphs used across the app.
import React from "react";

export function Icon({ name, className = "nav-icon" }) {
  const paths = {
    home: <path d="M3 9 L8 4 L13 9 V13.5 a0.5 0.5 0 0 1 -0.5 0.5 H10 V11 a1 1 0 0 0 -1 -1 H7 a1 1 0 0 0 -1 1 V14 H3.5 a0.5 0.5 0 0 1 -0.5 -0.5 Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round" />,
    feather: <path d="M2.5 13.5 L8.5 7.5 M11.5 2.5 C 7 4 4 7 3 11 L 3 13 L 5 13 C 9 12 12 9 13.5 4.5 Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round" strokeLinecap="round" />,
    book: <path d="M3 3 H7 a2 2 0 0 1 2 2 V14 a1 1 0 0 0 -1 -1 H3 Z M13 3 H9 a2 2 0 0 0 -2 2 V14 a1 1 0 0 1 1 -1 H13 Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round" />,
    device: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"><rect x="3" y="4" width="10" height="7" rx="1.2" /><path d="M5 13 H11 M8 11 V13" /></g>,
    users: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round"><circle cx="6" cy="6" r="2.2" /><circle cx="11.5" cy="7" r="1.6" /><path d="M2 13 c0 -2 2 -3 4 -3 s 4 1 4 3" /><path d="M10 13 c0 -1.5 1 -2.4 2.5 -2.4 s 2 0.8 2 2" /></g>,
    gear: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"><circle cx="8" cy="8" r="2" /><path d="M8 2 V4 M8 12 V14 M2 8 H4 M12 8 H14 M3.5 3.5 L4.9 4.9 M11.1 11.1 L12.5 12.5 M3.5 12.5 L4.9 11.1 M11.1 4.9 L12.5 3.5" /></g>,
    search: <g stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round"><circle cx="7" cy="7" r="4.2" /><path d="M10.5 10.5 L13 13" /></g>,
    bell: <path d="M4 11.5 V8 a 4 4 0 0 1 8 0 V11.5 L13 12.5 H3 Z M6.5 12.5 a 1.5 1.5 0 0 0 3 0" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round" />,
    plus: <path d="M8 3 V13 M3 8 H13" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />,
    filter: <path d="M3 4 H13 L10 8 V12 L6 13.5 V8 Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round" />,
    chev: <path d="M5 4 L9 8 L5 12" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
    download: <path d="M8 2 V11 M4.5 8 L8 11.5 L11.5 8 M3 14 H13" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />,
    play: <path d="M5 3.5 L12 8 L5 12.5 Z" fill="currentColor" />,
    x: <path d="M4 4 L12 12 M12 4 L4 12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />,
    extlink: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3 H13 V7 M13 3 L7 9 M11 9 V12 a1 1 0 0 1 -1 1 H4 a1 1 0 0 1 -1 -1 V6 a1 1 0 0 1 1 -1 H7" /></g>,
    cam: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"><path d="M3 5 H5 L6 4 H10 L11 5 H13 a1 1 0 0 1 1 1 V11 a1 1 0 0 1 -1 1 H3 a1 1 0 0 1 -1 -1 V6 a1 1 0 0 1 1 -1 Z" /><circle cx="8" cy="8.5" r="2" /></g>,
    sun: <g stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round"><circle cx="8" cy="8" r="2.6" /><path d="M8 2 V3.5 M8 12.5 V14 M2 8 H3.5 M12.5 8 H14 M3.5 3.5 L4.6 4.6 M11.4 11.4 L12.5 12.5 M3.5 12.5 L4.6 11.4 M11.4 4.6 L12.5 3.5" /></g>,
  };
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      {paths[name] || null}
    </svg>
  );
}
