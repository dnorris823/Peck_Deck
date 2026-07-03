// === Mock data — Peck Deck ===
// Field guide-inspired species data with per-bird color palettes for SVG plates.
// Ported from the Claude Design prototype to ES modules (Milestone 5).
// TODO(M5): replace these fixtures with live calls to the Litestar backend
//           (GET /species, /devices, /users, /sightings).

export const SPECIES = [
  {
    id: 1, common: "Northern Cardinal", sci: "Cardinalis cardinalis", order: "Passeriformes",
    palette: ["#b8412c", "#5a1810", "#e5b89c"], silhouette: "songbird",
    wiki: "https://en.wikipedia.org/wiki/Northern_cardinal",
    note: "Year-round resident. Males vivid red with black mask; females buff-brown with red wash. Frequent feeder visitor."
  },
  {
    id: 2, common: "Black-capped Chickadee", sci: "Poecile atricapillus", order: "Passeriformes",
    palette: ["#1c2620", "#d4cdb8", "#7a6f5a"], silhouette: "tit",
    wiki: "https://en.wikipedia.org/wiki/Black-capped_chickadee",
    note: "Tiny, curious. Black cap and bib, white cheeks. Often the first to find a new feeder."
  },
  {
    id: 3, common: "American Goldfinch", sci: "Spinus tristis", order: "Passeriformes",
    palette: ["#d4a23a", "#1c1810", "#8a6f1f"], silhouette: "finch",
    wiki: "https://en.wikipedia.org/wiki/American_goldfinch",
    note: "Brilliant yellow in summer; olive-buff in winter. Strict vegetarian — loves nyjer and sunflower hearts."
  },
  {
    id: 4, common: "Tufted Titmouse", sci: "Baeolophus bicolor", order: "Passeriformes",
    palette: ["#7a8a8c", "#2a3032", "#d4cdb8"], silhouette: "tit",
    wiki: "https://en.wikipedia.org/wiki/Tufted_titmouse",
    note: "Slate-gray crested songbird with rusty flanks. Acrobatic; takes one seed at a time."
  },
  {
    id: 5, common: "House Finch", sci: "Haemorhous mexicanus", order: "Passeriformes",
    palette: ["#bf6952", "#5e3530", "#d8c2a8"], silhouette: "finch",
    wiki: "https://en.wikipedia.org/wiki/House_finch",
    note: "Males raspberry-red on head and breast. Originally Western; now coast to coast."
  },
  {
    id: 6, common: "Blue Jay", sci: "Cyanocitta cristata", order: "Passeriformes",
    palette: ["#3f6e89", "#15263a", "#d4cdb8"], silhouette: "jay",
    wiki: "https://en.wikipedia.org/wiki/Blue_jay",
    note: "Loud, intelligent, bossy. Crested with vivid blue back, white underparts, black necklace."
  },
  {
    id: 7, common: "Downy Woodpecker", sci: "Dryobates pubescens", order: "Piciformes",
    palette: ["#1c2620", "#ece4d2", "#b8412c"], silhouette: "woodpecker",
    wiki: "https://en.wikipedia.org/wiki/Downy_woodpecker",
    note: "Smallest North American woodpecker. Black and white checkered; males with red nape patch."
  },
  {
    id: 8, common: "Mourning Dove", sci: "Zenaida macroura", order: "Columbiformes",
    palette: ["#a89d80", "#5a4f3f", "#d4cdb8"], silhouette: "dove",
    wiki: "https://en.wikipedia.org/wiki/Mourning_dove",
    note: "Slim, long-tailed; soft mournful coo. Ground-feeder beneath the tray."
  },
  {
    id: 9, common: "White-breasted Nuthatch", sci: "Sitta carolinensis", order: "Passeriformes",
    palette: ["#5a6a78", "#1c2028", "#ece4d2"], silhouette: "nuthatch",
    wiki: "https://en.wikipedia.org/wiki/White-breasted_nuthatch",
    note: "Walks down trunks headfirst. Slate above, white below, black cap."
  },
  {
    id: 10, common: "Carolina Wren", sci: "Thryothorus ludovicianus", order: "Passeriformes",
    palette: ["#a86530", "#52301a", "#e5d4b8"], silhouette: "wren",
    wiki: "https://en.wikipedia.org/wiki/Carolina_wren",
    note: "Bold rusty-brown wren with white eyebrow. Loud teakettle song."
  },
  {
    id: 11, common: "Red-bellied Woodpecker", sci: "Melanerpes carolinus", order: "Piciformes",
    palette: ["#b8412c", "#1c2620", "#e5d4b8"], silhouette: "woodpecker",
    wiki: "https://en.wikipedia.org/wiki/Red-bellied_woodpecker",
    note: "Zebra-backed, with a red cap (males) or nape (females). Pale belly tinged red."
  },
  {
    id: 12, common: "Dark-eyed Junco", sci: "Junco hyemalis", order: "Passeriformes",
    palette: ["#4a4a4a", "#222222", "#ece4d2"], silhouette: "sparrow",
    wiki: "https://en.wikipedia.org/wiki/Dark-eyed_junco",
    note: "Slate above, white belly. Ground-feeder; nicknamed 'snowbird' for winter arrivals."
  },
];

export const DEVICES = [
  {
    id: 1, name: "Backyard Maple", city: "Burlington", state: "VT",
    tier: "auto", feed: "Black-oil sunflower",
    status: "online", battery: 0.78, signal: "good",
    lastSeen: "32s ago",
    todaySightings: 14, weekSightings: 89, allTime: 1247
  },
  {
    id: 2, name: "Front Porch", city: "Burlington", state: "VT",
    tier: "gpu", feed: "Nyjer thistle",
    status: "online", battery: 0.42, signal: "good",
    lastSeen: "1m ago",
    todaySightings: 7, weekSightings: 51, allTime: 612
  },
  {
    id: 3, name: "Cabin Window", city: "Stowe", state: "VT",
    tier: "local", feed: "Suet cake",
    status: "warn", battery: 0.18, signal: "weak",
    lastSeen: "14m ago",
    todaySightings: 3, weekSightings: 22, allTime: 188
  },
];

export const USERS = [
  { id: 1, name: "Dominic Norris", email: "dom@peck.deck", role: "owner", phone: "+1 (802) 555-0142", notify_email: true, notify_sms: true, av: "DN", avBg: "var(--cardinal)" },
  { id: 2, name: "Margaret Norris", email: "meg@peck.deck", role: "viewer", phone: "+1 (802) 555-0119", notify_email: true, notify_sms: false, av: "MN", avBg: "var(--forest)" },
  { id: 3, name: "Theo Cole", email: "theo@cole.studio", role: "viewer", phone: "—", notify_email: true, notify_sms: false, av: "TC", avBg: "var(--sky-deep)" },
  { id: 4, name: "Pat Halloran", email: "pat.h@audubon.local", role: "viewer", phone: "+1 (802) 555-0188", notify_email: false, notify_sms: true, av: "PH", avBg: "var(--yolk-deep)" },
];

// Recent sightings — most recent first
function makeSightings() {
  const now = new Date("2026-05-09T16:24:00");
  const items = [
    { sp: 1, dev: 1, mins: 4, conf: 0.96, tier: "gpu" },
    { sp: 3, dev: 2, mins: 18, conf: 0.91, tier: "gpu" },
    { sp: 4, dev: 1, mins: 42, conf: 0.88, tier: "local" },
    { sp: 9, dev: 1, mins: 67, conf: 0.94, tier: "gpu" },
    { sp: 7, dev: 3, mins: 95, conf: 0.72, tier: "local" },
    { sp: 5, dev: 2, mins: 124, conf: 0.83, tier: "local" },
    { sp: 2, dev: 1, mins: 156, conf: 0.97, tier: "local" },
    { sp: 6, dev: 1, mins: 198, conf: 0.99, tier: "gpu" },
    { sp: 11, dev: 2, mins: 248, conf: 0.79, tier: "gpu" },
    { sp: 8, dev: 1, mins: 312, conf: 0.86, tier: "local" },
    { sp: 10, dev: 3, mins: 401, conf: 0.68, tier: "cloud" },
    { sp: 12, dev: 1, mins: 502, conf: 0.91, tier: "local" },
    { sp: 1, dev: 2, mins: 624, conf: 0.94, tier: "gpu" },
    { sp: 3, dev: 1, mins: 718, conf: 0.85, tier: "local" },
    { sp: 4, dev: 2, mins: 822, conf: 0.92, tier: "gpu" },
    { sp: 5, dev: 1, mins: 940, conf: 0.81, tier: "local" },
    { sp: 6, dev: 1, mins: 1080, conf: 0.96, tier: "gpu" },
    { sp: 9, dev: 2, mins: 1240, conf: 0.93, tier: "gpu" },
  ];
  return items.map((it, i) => {
    const d = new Date(now.getTime() - it.mins * 60 * 1000);
    return {
      id: 1000 + i,
      species: SPECIES.find(s => s.id === it.sp),
      device: DEVICES.find(dev => dev.id === it.dev),
      datetime: d,
      confidence: it.conf,
      tier: it.tier,
      hasVideo: i % 3 === 0,
    };
  });
}

export const SIGHTINGS = makeSightings();

// Per-species sighting counts
export const SPECIES_COUNTS = SPECIES.map(s => ({
  ...s,
  count: SIGHTINGS.filter(x => x.species.id === s.id).length + Math.floor(s.id * 7 + (s.id % 4) * 13),
  firstSeen: ["Mar 12, 2026", "Jan 04, 2026", "Apr 19, 2026", "Feb 22, 2026"][s.id % 4],
})).sort((a, b) => b.count - a.count);

// Activity heatmap: 24 hours x 7 days
function makeHeatmap() {
  const days = 7;
  const grid = [];
  for (let d = 0; d < days; d++) {
    const row = [];
    for (let h = 0; h < 24; h++) {
      // Birds active dawn (5-9) and afternoon (15-18)
      let v = 0;
      if (h >= 5 && h <= 9) v = 2 + Math.floor(Math.random() * 3);
      else if (h >= 15 && h <= 18) v = 1 + Math.floor(Math.random() * 3);
      else if (h >= 10 && h <= 14) v = Math.floor(Math.random() * 2);
      else v = 0;
      row.push(Math.min(4, v));
    }
    grid.push(row);
  }
  return grid;
}
export const HEATMAP = makeHeatmap();

export function fmtTime(d) {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}
export function fmtRelative(d) {
  const now = new Date("2026-05-09T16:24:00");
  const diff = (now - d) / 60000; // mins
  if (diff < 1) return "just now";
  if (diff < 60) return `${Math.floor(diff)}m ago`;
  if (diff < 60 * 24) return `${Math.floor(diff / 60)}h ago`;
  return `${Math.floor(diff / (60 * 24))}d ago`;
}
export function fmtDateLabel(d) {
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
