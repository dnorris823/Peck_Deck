// Bird plate SVGs — stylized field-guide silhouettes.
// Each plate uses the species' palette and a silhouette type.
import React from "react";

const SILHOUETTES = {
  songbird: (
    <path d="M 60 110 C 50 95 50 80 65 72 C 75 67 90 65 105 70 C 115 60 130 55 145 60 L 158 55 L 168 62 L 162 70 C 165 80 160 92 150 100 C 145 108 138 113 128 115 C 125 130 115 138 105 138 L 100 132 L 92 142 L 88 132 L 78 138 L 78 128 C 70 125 62 120 60 110 Z M 152 64 L 158 64" />
  ),
  finch: (
    <path d="M 60 108 C 55 92 60 78 75 72 C 90 65 110 65 125 70 C 138 62 152 60 165 65 L 172 62 L 178 68 L 172 75 C 174 86 168 96 158 102 C 152 112 142 118 130 118 C 124 130 112 136 102 134 L 96 128 L 88 138 L 86 128 L 76 134 L 76 122 C 66 118 60 114 60 108 Z" />
  ),
  jay: (
    <path d="M 50 115 C 45 95 55 78 75 72 C 88 65 105 65 118 72 L 130 55 L 138 58 L 134 72 C 148 70 162 75 168 85 L 178 78 L 182 88 L 172 92 C 175 105 168 116 155 120 C 150 132 138 138 125 136 L 118 128 L 108 142 L 104 130 L 92 140 L 92 124 C 78 122 62 122 50 115 Z" />
  ),
  tit: (
    <path d="M 70 105 C 65 92 72 80 88 75 C 100 70 115 72 125 78 C 138 72 152 75 160 85 L 168 80 L 172 88 L 164 92 C 165 102 158 110 148 113 C 142 122 132 126 122 124 L 116 118 L 108 128 L 106 118 L 96 124 L 96 113 C 84 110 74 110 70 105 Z" />
  ),
  woodpecker: (
    <g>
      <path d="M 80 125 C 72 110 76 92 90 82 C 88 70 95 60 108 58 C 118 55 128 60 132 70 L 145 65 L 152 70 L 148 78 L 138 80 C 142 90 138 100 128 105 L 132 120 C 130 132 122 140 112 138 L 108 128 L 100 138 L 96 128 L 88 134 L 88 124 Z" />
      <circle cx="115" cy="68" r="3" opacity="0.6" />
    </g>
  ),
  dove: (
    <path d="M 45 110 C 40 95 50 82 70 78 C 90 72 115 72 138 80 C 155 72 175 75 188 85 L 200 80 L 205 88 L 195 95 C 195 108 182 118 165 120 L 130 130 C 110 135 88 132 72 122 L 62 130 L 58 122 L 48 128 L 48 116 Z" />
  ),
  nuthatch: (
    <path d="M 75 100 C 70 90 78 78 92 75 C 105 70 120 72 130 78 L 145 70 L 152 75 L 148 84 C 156 88 158 96 152 104 C 148 114 138 120 128 118 L 122 124 C 116 128 108 128 102 122 L 96 130 L 92 122 L 84 128 L 84 116 C 78 112 75 106 75 100 Z" />
  ),
  wren: (
    <path d="M 80 110 C 72 95 80 82 95 78 C 110 72 128 75 138 82 L 152 78 L 156 88 L 148 92 C 152 102 145 112 132 115 L 128 128 L 120 124 L 112 132 L 108 122 L 98 128 L 100 116 C 88 114 82 113 80 110 Z" />
  ),
  sparrow: (
    <path d="M 70 108 C 65 92 75 80 92 75 C 108 70 125 73 135 80 C 148 75 160 80 165 90 L 172 88 L 175 96 L 165 98 C 165 108 156 116 145 118 C 138 128 126 132 116 130 L 110 124 L 100 134 L 98 124 L 88 130 L 88 118 C 78 116 72 114 70 108 Z" />
  ),
};

export function BirdPlate({ species, large = false, showLabel = true, no }) {
  const [c1, c2, c3] = species.palette;
  const sil = SILHOUETTES[species.silhouette] || SILHOUETTES.songbird;
  return (
    <svg className="bird-plate" viewBox="0 0 240 160" preserveAspectRatio="xMidYMid slice">
      <defs>
        <pattern id={`grain-${species.id}`} width="2" height="2" patternUnits="userSpaceOnUse">
          <rect width="2" height="2" fill={c3} />
          <circle cx="0.5" cy="0.5" r="0.3" fill={c2} opacity="0.04" />
        </pattern>
        <linearGradient id={`bg-${species.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={c3} stopOpacity="0.9" />
          <stop offset="100%" stopColor={c3} stopOpacity="0.55" />
        </linearGradient>
        <radialGradient id={`vig-${species.id}`} cx="50%" cy="50%" r="60%">
          <stop offset="60%" stopColor="rgba(0,0,0,0)" />
          <stop offset="100%" stopColor="rgba(28,38,32,0.18)" />
        </radialGradient>
      </defs>

      <rect width="240" height="160" fill={`url(#bg-${species.id})`} />
      <rect width="240" height="160" fill={`url(#grain-${species.id})`} opacity="0.5" />

      {/* horizon line / branch */}
      <line x1="0" y1="138" x2="240" y2="138" stroke={c2} strokeOpacity="0.18" strokeWidth="1" strokeDasharray="2 3" />
      <path d={`M 0 138 Q 80 130 240 134`} stroke={c2} strokeOpacity="0.35" strokeWidth="2" fill="none" strokeLinecap="round" />

      {/* feet */}
      <path d="M 100 138 L 100 130 M 110 138 L 110 130" stroke={c2} strokeWidth="1.2" strokeLinecap="round" />

      {/* silhouette */}
      <g fill={c2} stroke={c1} strokeWidth="0.5" transform="translate(0, 0)">
        {sil}
      </g>

      {/* accent dot for eye */}
      <circle cx="155" cy="70" r="1.4" fill={c3} />

      {/* vignette */}
      <rect width="240" height="160" fill={`url(#vig-${species.id})`} />

      {/* corner number */}
      {no && (
        <text x="14" y="22" fill={c2} opacity="0.55"
          fontFamily="'Geist Mono', monospace" fontSize="9" letterSpacing="2">
          {no}
        </text>
      )}

      {showLabel && (
        <g transform="translate(14, 148)">
          <text fill={c2} fontFamily="'Newsreader', serif" fontSize="11" fontStyle="italic" opacity="0.7">
            {species.sci}
          </text>
        </g>
      )}
    </svg>
  );
}
