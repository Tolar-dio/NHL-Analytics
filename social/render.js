// Read the Ice: Instagram graphics, rendered from the live site's data.
//   node social/render.js [outdir]
// Pulls tonight.json and team_profiles.json from readtheice.app, then writes:
//   profile.png (1080x1080), brand.png (1080x1350), scorers.png, luck.png, feature.png (1080x1350, 4:5 feed),
//   story-sleepers.png (1080x1920). Team colors only (no logos, no player photos: both are licensed).
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const OUT = path.resolve(process.argv[2] || "social/out");
const SITE = "https://readtheice.app/data/";
const B = { navy: "#0e1b2a", panel: "#15263a", line: "#22374d", ice: "#eef3f7", muted: "#8ea3b7", red: "#f0475e", blue: "#5b8deb" };
const FONTS = `<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800;900&family=Barlow:wght@400;500;600;700&display=swap" rel="stylesheet">`;
const NAMES = { ANA: "Ducks", BOS: "Bruins", BUF: "Sabres", CAR: "Hurricanes", CBJ: "Blue Jackets", CGY: "Flames", CHI: "Blackhawks", COL: "Avalanche", DAL: "Stars", DET: "Red Wings", EDM: "Oilers", FLA: "Panthers", LAK: "Kings", MIN: "Wild", MTL: "Canadiens", NJD: "Devils", NSH: "Predators", NYI: "Islanders", NYR: "Rangers", OTT: "Senators", PHI: "Flyers", PIT: "Penguins", SEA: "Kraken", SJS: "Sharks", STL: "Blues", TBL: "Lightning", TOR: "Maple Leafs", UTA: "Mammoth", VAN: "Canucks", VGK: "Golden Knights", WSH: "Capitals", WPG: "Jets" };

// team colors from the site (dark-theme column reads best on navy)
const appjs = fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8");
const TC = {};
for (const m of appjs.matchAll(/([A-Z]{3}): \["(#[0-9A-Fa-f]{6})", "(#[0-9A-Fa-f]{6})"\]/g)) if (!TC[m[1]]) TC[m[1]] = m[3];
const tc = (t) => TC[t] || B.blue;

const mark = (s = 1) => `<svg viewBox="0 0 40 40" width="${40 * s}" height="${40 * s}"><circle cx="20" cy="20" r="13" fill="none" stroke="${B.ice}" stroke-width="3"/><rect x="18.5" y="3" width="3" height="34" rx="1.5" fill="${B.red}"/><circle cx="20" cy="20" r="5" fill="${B.blue}"/></svg>`;
const wordmark = (h = 40) => `<div class="wm" style="font-size:${h}px">${mark(h / 40 * 1.1)}<span><b>READ</b> the <b>ICE</b></span></div>`;
const fair = (p) => (p >= 0.5 ? `${Math.round((-100 * p) / (1 - p))}` : `+${Math.round((100 * (1 - p)) / p)}`);
const pct = (p) => `${Math.round(p * 100)}%`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const dayLabel = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });

const BASE = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: ${B.navy}; color: ${B.ice}; font-family: Barlow, sans-serif; -webkit-font-smoothing: antialiased; }
  .card { position: relative; overflow: hidden; background: ${B.navy}; }
  .wm { display: flex; align-items: center; gap: .35em; font-family: "Big Shoulders Display"; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: ${B.ice}; }
  .wm b { font-weight: 900; }
  .kicker { font-family: "Big Shoulders Display"; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; color: ${B.red}; font-size: 30px; }
  h1 { font-family: "Big Shoulders Display"; font-weight: 900; text-transform: uppercase; line-height: .92; letter-spacing: .01em; }
  .muted { color: ${B.muted}; }
  .foot { position: absolute; left: 72px; right: 72px; bottom: 54px; display: flex; justify-content: space-between; align-items: flex-end; font-size: 22px; color: ${B.muted}; }
  .rink { position: absolute; border: 3px solid ${B.line}; border-radius: 50%; }
  .card > div:not(.rink):not(.foot) { position: relative; }
  .foot { z-index: 2; }
`;
const page = (w, h, body, css = "") => `<!doctype html><html><head><meta charset="utf-8">${FONTS}<style>${BASE}${css} .card{width:${w}px;height:${h}px}</style></head><body><div class="card">${body}</div></body></html>`;
const footer = (left = "For information and entertainment. 21+. Gambling problem? 1-800-GAMBLER") => `<div class="foot"><span>${left}</span><span style="color:${B.ice};font-weight:600">readtheice.app</span></div>`;
// faint center-ice circle in the background, the brand's one decorative element
const rinkBg = (x, y, r) => `<div class="rink" style="left:${x - r}px;top:${y - r}px;width:${2 * r}px;height:${2 * r}px"></div><div style="position:absolute;left:${x - 3}px;top:${y - r - 60}px;height:${2 * r + 120}px;width:6px;background:${B.red};opacity:.18"></div>`;

// ---------------------------------------------------------------- cards
function profile() {
  // the mark sits inside the circle Instagram crops to, with room to breathe
  return page(1080, 1080, `<div style="position:absolute;inset:0;display:grid;place-items:center">${mark(17)}</div>`);
}

function brand() {
  const sw = (c, n, use) => `<div class="sw"><div style="background:${c};${c === B.navy ? `border:3px solid ${B.line}` : ""}"></div><b>${n}</b><span>${c}</span><em>${use}</em></div>`;
  return page(1080, 1350, `
    <div style="padding:72px">
      ${wordmark(46)}
      <div class="kicker" style="margin-top:70px">Brand sheet</div>
      <h1 style="font-size:96px;margin-top:10px">Learn to read the ice</h1>
      <div class="grid">${sw(B.navy, "Navy", "Background")}${sw(B.ice, "Ice", "Text, rink lines")}${sw(B.red, "Goal red", "Goals and accents only")}${sw(B.blue, "Puck blue", "Our numbers, highlights")}${sw(B.panel, "Boards", "Panels")}${sw(B.muted, "Fog", "Secondary text")}</div>
      <div class="type">
        <div><span class="muted">Display</span><h1 style="font-size:72px">Big Shoulders</h1></div>
        <div><span class="muted">Body</span><p style="font-size:40px;font-weight:600">Barlow, for everything you read</p></div>
      </div>
      <p class="muted" style="font-size:26px;margin-top:40px;line-height:1.4">Team colors, never logos. No player photos. Red means goal. Every post names its sample and ends with readtheice.app.</p>
    </div>`, `
    .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:28px; margin-top:56px; }
    .sw div { height:150px; border-radius:18px; margin-bottom:14px; }
    .sw b { display:block; font-size:30px; } .sw span { display:block; color:${B.muted}; font-size:24px; font-family:monospace; } .sw em { display:block; font-style:normal; font-size:22px; color:${B.muted}; margin-top:4px; }
    .type { display:grid; gap:24px; margin-top:56px; padding-top:40px; border-top:3px solid ${B.line}; }
    .type span { font-size:22px; text-transform:uppercase; letter-spacing:.1em; }`);
}

function scorers(T) {
  const started = new Set(); // keep every game: the post goes up before puck drop
  const top = [...T.props].filter((p) => p.lineup !== "returning").sort((a, b) => b.p_goal - a.p_goal).slice(0, 5);
  const rows = top.map((p, i) => `
    <div class="row">
      <div class="n">${i + 1}</div>
      <div class="chip" style="background:${tc(p.team)}"></div>
      <div class="who"><b>${esc(p.name)}</b><span>${p.team} vs ${p.opp} · ${Math.round(p.proj_toi)} min · ${p.g | 0} G in ${p.gp} GP</span></div>
      <div class="p"><b>${pct(p.p_goal)}</b><span>fair ${fair(p.p_goal)}</span></div>
    </div>`).join("");
  return page(1080, 1350, `
    ${rinkBg(1000, 150, 230)}
    <div style="padding:72px 72px 0">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:48px">${dayLabel(T.date)}</div>
      <h1 style="font-size:96px;margin-top:8px">Tonight's likeliest<br>goal scorers</h1>
      <p class="muted" style="font-size:28px;margin-top:22px">Our chance each player scores, from his chances, ice time, linemates and tonight's goalie.</p>
      <div class="rows">${rows}</div>
    </div>
    ${footer()}`, `
    .rows { margin-top:36px; display:grid; gap:14px; }
    .row { display:grid; grid-template-columns:56px 14px 1fr auto; align-items:center; gap:24px; background:${B.panel}; border-radius:20px; padding:18px 32px; }
    .n { font-family:"Big Shoulders Display"; font-weight:900; font-size:56px; color:${B.muted}; }
    .chip { width:14px; height:76px; border-radius:7px; }
    .who b { display:block; font-size:42px; font-weight:700; line-height:1.1; } .who span { font-size:24px; color:${B.muted}; }
    .p { text-align:right; } .p b { display:block; font-family:"Big Shoulders Display"; font-weight:900; font-size:72px; color:${B.blue}; line-height:1; } .p span { font-size:22px; color:${B.muted}; }`);
}

function luck(P) {
  const teams = Object.values(P).filter((t) => t.gp >= 5).map((t) => ({ t: t.team, x: t.xgf60 / (t.xgf60 + t.xga60), y: t.gf_pg / (t.gf_pg + t.ga_pg), gp: t.gp }));
  const W = 920, H = 640, all = teams.flatMap((d) => [d.x, d.y]); const lo = Math.floor((Math.min(...all) - 0.02) * 50) / 50, hi = Math.ceil((Math.max(...all) + 0.02) * 50) / 50;
  const sx = (v) => ((v - lo) / (hi - lo)) * W, sy = (v) => H - ((v - lo) / (hi - lo)) * H;
  const lucky = [...teams].sort((a, b) => (b.y - b.x) - (a.y - a.x));
  const callout = new Set([...lucky.slice(0, 3), ...lucky.slice(-3)].map((d) => d.t));
  const ticks = [];
  for (let v = Math.ceil(lo * 20) / 20; v <= hi + 1e-9; v += 0.05) ticks.push(+v.toFixed(2));
  const svg = `<svg width="${W}" height="${H}" style="overflow:visible">
    <polygon points="0,${H} ${W},0 ${W},${H}" fill="${B.blue}" opacity=".05"/>
    ${ticks.map((v) => `<line x1="${sx(v)}" y1="0" x2="${sx(v)}" y2="${H}" stroke="${B.line}" stroke-width="2"/><line x1="0" y1="${sy(v)}" x2="${W}" y2="${sy(v)}" stroke="${B.line}" stroke-width="2"/>
      <text x="${sx(v)}" y="${H + 36}" fill="${B.muted}" font-size="22" text-anchor="middle">${Math.round(v * 100)}%</text><text x="-14" y="${sy(v) + 8}" fill="${B.muted}" font-size="22" text-anchor="end">${Math.round(v * 100)}%</text>`).join("")}
    <line x1="0" y1="${H}" x2="${W}" y2="0" stroke="${B.muted}" stroke-width="2" stroke-dasharray="8 8"/>
    ${teams.map((d) => `<circle cx="${sx(d.x)}" cy="${sy(d.y)}" r="${callout.has(d.t) ? 15 : 11}" fill="${tc(d.t)}" stroke="${B.navy}" stroke-width="4" opacity="${callout.has(d.t) ? 1 : 0.55}"/>`).join("")}
    ${teams.filter((d) => callout.has(d.t)).map((d) => `<text x="${sx(d.x) + 22}" y="${sy(d.y) + 9}" fill="${B.ice}" font-size="26" font-weight="700">${d.t}</text>`).join("")}
    <text x="16" y="36" fill="${B.muted}" font-size="22">Results ahead of the chances</text>
    <text x="${W - 10}" y="${H - 20}" fill="${B.muted}" font-size="22" text-anchor="end">Chances ahead of the results</text>
  </svg>`;
  const n = teams[0] ? Math.round(teams.reduce((s, d) => s + d.gp, 0) / teams.length) : 0;
  return page(1080, 1350, `
    <div style="padding:72px 72px 0">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:56px">Luck check</div>
      <h1 style="font-size:96px;margin-top:8px">Who's earning it?</h1>
      <p class="muted" style="font-size:27px;margin-top:16px;line-height:1.35">Share of the goals (up) against share of the expected goals, the quality of chances (across). Above the line, finishing and goaltending are outrunning the chances.</p>
      <div style="margin:40px 0 0 56px">${svg}</div>
    </div>
    ${footer(`All situations · about ${n} games per team · xG: our model and MoneyPuck.com`)}`);
}

function feature({ kicker, title, dek, team }) {
  return page(1080, 1350, `
    <div style="position:absolute;left:0;top:0;bottom:0;width:28px;background:${tc(team)}"></div>
    ${rinkBg(1010, 1230, 360)}
    <div style="padding:72px 72px 0 104px">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:300px">${esc(kicker)}</div>
      <h1 style="font-size:132px;margin-top:14px">${esc(title)}</h1>
      <p style="font-size:38px;line-height:1.3;margin-top:36px;max-width:820px">${esc(dek)}</p>
      <p class="muted" style="font-size:28px;margin-top:40px">Read it on readtheice.app</p>
    </div>
    ${footer("Written with AI from our data")}`);
}

function storySleepers(T) {
  const S = T.games.flatMap((g) => g.sleepers || []).slice(0, 4);
  const cards = S.map((s) => `
    <div class="sl">
      <div class="chip" style="background:${tc(s.team)}"></div>
      <div><span class="tag">${s.kind === "depth" ? "Depth goal" : "Point"}</span><b>${esc(s.name)}</b><span class="muted">${s.team} vs ${s.opp}</span></div>
      <div class="p"><b>${pct(s.kind === "depth" ? s.p_goal : s.p_1pt)}</b><span>${s.kind === "depth" ? "to score" : "for a point"}</span></div>
    </div>`).join("");
  return page(1080, 1920, `
    ${rinkBg(540, 1720, 360)}
    <div style="padding:200px 72px 0">
      ${wordmark(40)}
      <div class="kicker" style="margin-top:90px">${dayLabel(T.date)}</div>
      <h1 style="font-size:150px;margin-top:10px">Sleepers</h1>
      <p class="muted" style="font-size:34px;margin-top:20px;line-height:1.35">Under-the-radar players our numbers like tonight. Every one has a reason, and we grade them in public.</p>
      <div style="display:grid;gap:22px;margin-top:64px">${cards}</div>
      <p style="font-size:30px;margin-top:48px">The reasons for each are on <b>readtheice.app</b></p>
    </div>
    <div class="foot" style="bottom:240px"><span>For information and entertainment. 21+. 1-800-GAMBLER</span></div>`, `
    .sl { display:grid; grid-template-columns:16px 1fr auto; gap:28px; align-items:center; background:${B.panel}; border-radius:24px; padding:34px 36px; }
    .chip { width:16px; height:110px; border-radius:8px; }
    .sl b { display:block; font-size:48px; font-weight:700; } .sl .muted { font-size:28px; }
    .tag { font-family:"Big Shoulders Display"; font-weight:800; letter-spacing:.1em; text-transform:uppercase; color:${B.red}; font-size:26px; }
    .p { text-align:right; } .p b { display:block; font-family:"Big Shoulders Display"; font-weight:900; font-size:84px; color:${B.blue}; line-height:1; } .p span { font-size:24px; color:${B.muted}; }`);
}

// ---------------------------------------------------------------- render
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const get = async (f) => (await fetch(SITE + f)).json();
  const [T, P] = await Promise.all([get("tonight.json"), get("team_profiles.json")]);
  const jobs = [
    ["profile.png", 1080, 1080, profile()],
    ["brand.png", 1080, 1350, brand()],
    ["scorers.png", 1080, 1350, scorers(T)],
    ["luck.png", 1080, 1350, luck(P)],
    ["feature.png", 1080, 1350, feature({ kicker: "Team deep dive", team: "DET", title: "The Larkin standoff", dek: "Detroit's captain won't play until he's traded. The team he left behind is better than its record says." })],
    ["story-sleepers.png", 1080, 1920, storySleepers(T)],
  ];
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const [f, w, h, html] of jobs) {
    await p.setViewportSize({ width: w, height: h });
    await p.setContent(html, { waitUntil: "networkidle" });
    await p.evaluate(() => document.fonts.ready);
    await p.screenshot({ path: path.join(OUT, f), clip: { x: 0, y: 0, width: w, height: h } });
    console.log("wrote", f);
  }
  await b.close();
})();
