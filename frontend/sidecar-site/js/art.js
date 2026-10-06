/* Icons + illustrations */
const ICON = {
  heat: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5" fill="currentColor" fill-opacity=".25"/><rect x="3" y="14" width="7" height="7" rx="1.5" fill="currentColor" fill-opacity=".55"/><rect x="14" y="14" width="7" height="7" rx="1.5" fill="currentColor" fill-opacity=".9"/>',
  hub: '<circle cx="12" cy="12" r="3"/><circle cx="4.5" cy="5" r="1.8"/><circle cx="19.5" cy="5" r="1.8"/><circle cx="4.5" cy="19" r="1.8"/><circle cx="19.5" cy="19" r="1.8"/><path d="M6 6.2l4.2 4M18 6.2l-4.2 4M6 17.8l4.2-4M18 17.8l-4.2-4"/>',
  therm: '<path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
  gavel: '<path d="M14 4l6 6-3 3-6-6z"/><path d="M8.5 10.5L3 16l5 5 5.5-5.5"/><path d="M3 21h9"/>',
  route: '<circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="6" r="2.2"/><path d="M7 18h7a3.5 3.5 0 0 0 0-7H10a3.5 3.5 0 0 1 0-7h7"/>',
  explain: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/><path d="M8 9.5h5M8 12.5h3"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  truck: '<path d="M2 6h11v10H2zM13 9h4.5l3 3.5V16H13z"/><circle cx="6.5" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20c.8-4 4-6 7.500-6s6.700 2 7.500 6"/>',
  map: '<path d="M9 4l-6 2v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>',
  chart: '<path d="M4 20V4M4 20h16"/><path d="M8 16l4-5 3 3 5-7"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  pin: '<path d="M12 21s-6.500-6-6.500-11a6.500 6.500 0 0 1 13 0c0 5-6.500 11-6.500 11z"/><circle cx="12" cy="10" r="2.400"/>',
  wallet: '<rect x="3" y="6" width="18" height="13" rx="3"/><path d="M16 12.500h2.500M3 9.500h15"/>',
  arch: '<rect x="3" y="3" width="18" height="5" rx="1.500"/><rect x="3" y="10" width="8" height="5" rx="1.500"/><rect x="13" y="10" width="8" height="5" rx="1.500"/><rect x="3" y="17" width="18" height="4" rx="1.500"/>',
  home: '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/>',
  out: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 16l-4-4 4-4M6 12h10"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.900 4.900l1.400 1.400M17.700 17.700l1.400 1.400M4.900 19.100l1.400-1.400M17.700 6.300l1.400-1.400"/>',
  moon: '<path d="M20 14.500A8 8 0 0 1 9.500 4 8 8 0 1 0 20 14.500z"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  db: '<ellipse cx="12" cy="5.500" rx="7.500" ry="3"/><path d="M4.500 5.500v13c0 1.700 3.400 3 7.500 3s7.500-1.300 7.500-3v-13M4.500 12c0 1.700 3.400 3 7.500 3s7.500-1.300 7.500-3"/>',
  cloud: '<path d="M7 18a4 4 0 0 1-.5-8A5.500 5.500 0 0 1 17 8.500 4.500 4.500 0 0 1 17 18z"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
};
const ic = (n, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;

const LOGO = `<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="2" y="13" width="20" height="14" rx="4" fill="currentColor"/><rect x="10" y="4" width="18" height="14" rx="4" fill="var(--accent)" stroke="var(--hero-a, var(--bg))" stroke-width="2"/><circle cx="8" cy="27" r="0" fill="none"/></svg>`;

/* Truck group — side view, cab on the left */
const TRUCK = (id) => `
<g id="${id}">
  <ellipse cx="290" cy="262" rx="300" ry="16" fill="#3a2a1a" opacity=".22"/>
  <rect x="176" y="24" width="392" height="176" rx="10" fill="#F7EEDC" stroke="#CDB98F" stroke-width="2"/>
  ${[210, 250, 290, 330, 370, 410, 450, 490, 530].map(x => `<line x1="${x}" y1="32" x2="${x}" y2="192" stroke="#E2D2AE" stroke-width="2"/>`).join("")}
  <rect x="176" y="150" width="392" height="10" fill="#8C5A34" opacity=".9"/>
  <text x="372" y="104" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="600" font-size="34" letter-spacing="8" fill="#2B2118">MAARG</text>
  <text x="372" y="128" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="400" font-size="13" letter-spacing="3" fill="#7a6650">THE PATH HOME · SPARE CAPACITY</text>
  <rect x="8" y="198" width="560" height="18" rx="4" fill="#3A2E24"/>
  <path d="M4 200 L4 96 Q4 76 24 70 L100 22 Q108 18 118 18 L172 18 L172 200 Z" fill="#7B4A36"/>
  <path d="M22 96 L100 46 L100 96 Z" fill="#DCE7E6" stroke="#5c3a2a" stroke-width="3"/>
  <path d="M112 46 L160 46 L160 96 L112 96 Z" fill="#DCE7E6" stroke="#5c3a2a" stroke-width="3"/>
  <path d="M112 46 L160 46 L112 96Z" fill="#fff" opacity=".35"/>
  <rect x="4" y="122" width="26" height="14" rx="4" fill="#F5DE9A"/>
  <rect x="4" y="150" width="30" height="34" rx="4" fill="#4A3324"/>
  ${[156, 162, 168, 174].map(y => `<line x1="8" y1="${y}" x2="30" y2="${y}" stroke="#7B5A3E" stroke-width="2"/>`).join("")}
  <rect x="150" y="2" width="9" height="60" rx="3" fill="#3A2E24"/>
  <rect x="112" y="108" width="52" height="7" rx="3" fill="#5c3a2a"/>
  ${[[72, 236], [360, 236], [430, 236], [500, 236]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="34" fill="#2A2018"/><circle cx="${x}" cy="${y}" r="18" fill="#DDC9A2"/><circle cx="${x}" cy="${y}" r="7" fill="#8C6D46"/>`).join("")}
</g>`;

function heroArt() {
  const hubsA = [[800, 235, "Pune"], [1180, 215, "Nagpur"]];
  return `<svg class="hero-art" viewBox="0 0 1440 760" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--hero-a)"/><stop offset=".72" stop-color="var(--hero-b)"/></linearGradient>
    <radialGradient id="sun" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#FFF6E2" stop-opacity=".95"/><stop offset=".55" stop-color="#FBE6BB" stop-opacity=".55"/><stop offset="1" stop-color="#FBE6BB" stop-opacity="0"/></radialGradient>
    <linearGradient id="road" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6a5440"/><stop offset="1" stop-color="#4b3a2b"/></linearGradient>
  </defs>
  <rect width="1440" height="760" fill="url(#sky)"/>
  <circle cx="1010" cy="330" r="330" fill="url(#sun)"/>
  <circle cx="1010" cy="330" r="92" fill="#FFF3D9" opacity=".8"/>
  <path d="M0 470 Q180 410 360 450 T720 440 T1080 430 T1440 450 L1440 560 L0 560Z" fill="#D8BC8D" opacity=".75"/>
  <path d="M0 500 Q240 450 460 490 T900 480 T1440 495 L1440 600 L0 600Z" fill="#C7A574"/>
  <path d="M0 540 Q300 505 620 535 T1440 530 L1440 640 L0 640Z" fill="#B48F5F"/>
  <g fill="none" stroke="var(--hero-ink)" stroke-opacity=".5" stroke-width="2" stroke-dasharray="2 9" stroke-linecap="round"><path d="M800 235 Q990 150 1180 215"/><path d="M1180 215 Q1300 270 1400 220"/></g>
  ${hubsA.map(([x, y, n]) => `<g transform="translate(${x} ${y})"><circle r="16" fill="none" stroke="var(--hero-ink)" stroke-opacity=".35"/><circle r="6" fill="var(--hero-ink)"/><text y="-26" text-anchor="middle" font-family="Outfit,sans-serif" font-size="15" font-weight="500" fill="var(--hero-ink)">${n}</text></g>`).join("")}
  <g transform="translate(886 96)"><rect width="196" height="42" rx="21" fill="#FFFDF8" opacity=".92"/><circle cx="21" cy="21" r="6" fill="#8C5A34"/><text x="38" y="26" font-family="Outfit,sans-serif" font-size="13.5" font-weight="500" fill="#2B2118">85 kg spare · bounty ₹480</text></g>
  <path d="M0 585 L1440 545 L1440 760 L0 760Z" fill="url(#road)"/>
  <path d="M0 592 L1440 552" stroke="#F3E5C7" stroke-width="5" opacity=".9"/>
  <path d="M0 740 L1440 700" stroke="#F3E5C7" stroke-width="5" opacity=".7"/>
  <path d="M0 668 L1440 626" stroke="#F3E5C7" stroke-width="5" stroke-dasharray="46 40" opacity=".85"/>
  <g transform="translate(730 312)">${TRUCK("heroTruck")}</g>
  </svg>`;
}

function aboutArt() {
  return `<svg viewBox="0 0 640 480" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs><linearGradient id="ab" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--hero-a)"/><stop offset="1" stop-color="var(--hero-b)"/></linearGradient></defs>
  <rect width="640" height="480" fill="url(#ab)"/>
  <circle cx="470" cy="120" r="52" fill="#FFF3D9" opacity=".75"/>
  <path d="M0 330 Q160 290 320 320 T640 305 L640 480 L0 480Z" fill="#C7A574"/>
  <rect y="392" width="640" height="88" fill="#5a4636"/><path d="M0 424 H640" stroke="#F3E5C7" stroke-width="4" stroke-dasharray="34 26" opacity=".8"/>
  <g transform="translate(70 40)"><path d="M0 330 L0 300 L70 300 L70 330Z" fill="#8C5A34"/><rect x="24" y="40" width="22" height="262" fill="#B08048"/><path d="M35 46 L330 100" stroke="#B08048" stroke-width="16" stroke-linecap="round"/><path d="M35 60 L300 108" stroke="#8C5A34" stroke-width="3"/><line x1="322" y1="104" x2="322" y2="150" stroke="#2B2118" stroke-width="3"/><line x1="322" y1="104" x2="290" y2="150" stroke="#2B2118" stroke-width="2"/><line x1="322" y1="104" x2="354" y2="150" stroke="#2B2118" stroke-width="2"/></g>
  <g transform="translate(330 176)"><rect x="-38" y="0" width="150" height="70" rx="8" fill="#EDE0C5" stroke="#8C5A34" stroke-width="3"/><rect x="-18" y="16" width="30" height="24" rx="3" fill="#DCE7E6" stroke="#8C5A34" stroke-width="2"/><rect x="32" y="16" width="30" height="24" rx="3" fill="#DCE7E6" stroke="#8C5A34" stroke-width="2"/><text x="87" y="42" text-anchor="middle" font-family="Outfit,sans-serif" font-size="11" font-weight="600" letter-spacing="1" fill="#5F513F">S204</text></g>
  <g transform="translate(120 190) scale(.78)">${TRUCK("aboutTruck")}</g>
  </svg>`;
}

function stepThumb(i) {
  const s = [
    /* Predict — heat cells */
    `<rect width="118" height="100" fill="#EFE5D0"/>${[0, 1, 2, 3, 4].map(r => [0, 1, 2, 3, 4].map(c => { const v = (Math.sin(r * 1.7 + c * 2.1) + 1) / 2; return `<rect x="${8 + c * 20}" y="${6 + r * 18}" width="18" height="16" rx="3" fill="#B8663A" opacity="${(.12 + v * .8).toFixed(2)}"/>`; }).join("")).join("")}`,
    /* Price — lambda */
    `<rect width="118" height="100" fill="#EFE5D0"/><text x="59" y="58" text-anchor="middle" font-family="Outfit,sans-serif" font-size="44" font-weight="300" fill="#2B2118">λ</text><text x="59" y="82" text-anchor="middle" font-family="Outfit,sans-serif" font-size="13" fill="#5F513F">₹190 / hr</text><rect x="20" y="10" width="78" height="6" rx="3" fill="#DDCBA8"/><rect x="20" y="10" width="52" height="6" rx="3" fill="#A8382B"/>`,
    /* Plan — route */
    `<rect width="118" height="100" fill="#EFE5D0"/><path d="M16 78 Q40 20 66 50 T104 22" fill="none" stroke="#8C5A34" stroke-width="3" stroke-dasharray="1 7" stroke-linecap="round"/><circle cx="16" cy="78" r="7" fill="#2B2118"/><circle cx="66" cy="50" r="5" fill="#EFE5D0" stroke="#2B2118" stroke-width="2"/><circle cx="104" cy="22" r="7" fill="#8C5A34"/>`,
    /* Prove — rejected alternatives */
    `<rect width="118" height="100" fill="#EFE5D0"/>${[0, 1, 2].map(k => `<rect x="14" y="${14 + k * 26}" width="90" height="20" rx="6" fill="${k === 0 ? "#DDE8CF" : "#E7DAC0"}"/><rect x="22" y="${21 + k * 26}" width="${k === 0 ? 46 : 60 - k * 12}" height="5" rx="2.500" fill="#5F513F" opacity=".7"/>`).join("")}`,
  ][i];
  return `<svg viewBox="0 0 118 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true">${s}</svg>`;
}
