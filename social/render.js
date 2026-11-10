// Read the Ice: Instagram graphics, rendered from the live site's data.
//   node social/render.js [outdir]
// Pulls tonight.json and team_profiles.json from readtheice.app, then writes:
//   profile.png (1080x1080), brand.png (1080x1350), scorers.png, luck.png (1080x1350, 4:5 feed), plus feature.png and
//   stat.png when social/today.json has a `feature` or `stat` entry (the day's one-off cards),
//   sleepers.png, cover-players.png, and with today.json `games`: cover-games.png and a card per game (all 1080x1350).
//   STORY=1 also writes story-sleepers.png (1080x1920). PINNED=1 writes only the pinned how-it-works slides
//   (pinned-N.png) from social/pinned.json; its numbers are typed in there, so refresh them from model.json. Team colors only (no logos, no player photos: both are licensed).
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const OUT = path.resolve(process.argv[2] || "social/out");
const SITE = "https://readtheice.app/data/";
// The site stays off the graphics until Tolar says otherwise (Nov 9, 2026: "not trying to show my hand just yet").
// SHOW_SITE=1 puts readtheice.app back in the footers and calls to action.
const LINK = process.env.SHOW_SITE === "1" ? "readtheice.app" : "";
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
const footer = (left = "For information and entertainment. 21+. Gambling problem? 1-800-GAMBLER") => `<div class="foot"><span>${left}</span><span style="color:${B.ice};font-weight:600">${LINK}</span></div>`;
// faint center-ice circle in the background, the brand's one decorative element
const rinkBg = (x, y, r, line = true) => `<div class="rink" style="left:${x - r}px;top:${y - r}px;width:${2 * r}px;height:${2 * r}px"></div>` + (!line ? "" : `<div style="position:absolute;left:${x - 3}px;top:${y - r - 60}px;height:${2 * r + 120}px;width:6px;background:${B.red};opacity:.18"></div>`);

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
      <p class="muted" style="font-size:26px;margin-top:40px;line-height:1.4">Team colors, never logos. No player photos. Red means goal. Every post names its sample.</p>
    </div>`, `
    .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:28px; margin-top:56px; }
    .sw div { height:150px; border-radius:18px; margin-bottom:14px; }
    .sw b { display:block; font-size:30px; } .sw span { display:block; color:${B.muted}; font-size:24px; font-family:monospace; } .sw em { display:block; font-style:normal; font-size:22px; color:${B.muted}; margin-top:4px; }
    .type { display:grid; gap:24px; margin-top:56px; padding-top:40px; border-top:3px solid ${B.line}; }
    .type span { font-size:22px; text-transform:uppercase; letter-spacing:.1em; }`);
}

function scorers(T, notes = {}) {
  const started = new Set(); // keep every game: the post goes up before puck drop
  const top = [...T.props].filter((p) => p.lineup !== "returning").sort((a, b) => b.p_goal - a.p_goal).slice(0, 5);
  const rows = top.map((p, i) => `
    <div class="row">
      <div class="n">${i + 1}</div>
      <div class="chip" style="background:${tc(p.team)}"></div>
      <div class="who"><b>${esc(p.name)}</b><span>${p.team} vs ${p.opp} · ${Math.round(p.proj_toi)} min · ${p.g | 0} G in ${p.gp} GP</span>${notes[p.id] ? `<em>${esc(notes[p.id])}</em>` : ""}</div>
      <div class="p"><b>${pct(p.p_goal)}</b><span>fair ${fair(p.p_goal)}</span></div>
    </div>`).join("");
  return page(1080, 1350, `
    ${rinkBg(1000, 150, 230)}
    <div style="padding:72px 72px 0">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:48px">${dayLabel(T.date)}</div>
      <h1 style="font-size:84px;margin-top:6px">Tonight's likeliest<br>goal scorers</h1>
      <p class="muted" style="font-size:26px;margin-top:16px">Our chance each player scores, from his chances, ice time, linemates and tonight's goalie.</p>
      <div class="rows">${rows}</div>
    </div>
    ${footer()}`, `
    .rows { margin-top:24px; display:grid; gap:11px; }
    .row { display:grid; grid-template-columns:56px 14px 1fr auto; align-items:center; gap:24px; background:${B.panel}; border-radius:20px; padding:13px 32px; }
    .n { font-family:"Big Shoulders Display"; font-weight:900; font-size:56px; color:${B.muted}; }
    .chip { width:14px; height:76px; border-radius:7px; }
    .who b { display:block; font-size:42px; font-weight:700; line-height:1.1; } .who span { font-size:24px; color:${B.muted}; } .who em { display:block; font-style:normal; font-size:25px; color:${B.ice}; margin-top:4px; }
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
      ${LINK ? `<p class="muted" style="font-size:28px;margin-top:40px">Read it on ${LINK}</p>` : ""}
    </div>
    ${footer("Written with AI from our data")}`);
}

// one card per game: a headline and the story (written by hand in today.json), with our numbers under it
const etTime = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) + " ET";
const sgn = (v) => (v >= 0 ? "+" : "\u2212") + Math.abs(v).toFixed(1);
function gameCard(G, C) {
  const a = G.away, h = G.home, ph = G.market?.model_p_home ?? 0.5, pa = 1 - ph;
  const ca = tc(a), ch = tc(h) === tc(a) ? B.ice : tc(h);
  const ga = G.goalies?.[a], gh = G.goalies?.[h];
  const goalie = (g, c, right) => !g ? "" : `<div class="gl" style="${right ? "text-align:right" : ""}"><span>In net</span><b>${esc(g.name)}</b><i style="color:${g.gsax >= 0 ? B.blue : B.red}">${sgn(g.gsax)}</i></div>`;
  return page(1080, 1350, `
    <div style="position:absolute;left:0;top:0;height:20px;width:50%;background:${ca}"></div><div style="position:absolute;right:0;top:0;height:20px;width:50%;background:${ch}"></div>
    <div style="padding:76px 72px 0">
      ${wordmark(34)}
      <div class="kicker" style="margin-top:44px;font-size:28px">${NAMES[a]} at ${NAMES[h]} · ${etTime(G.start)}${G.away_b2b || G.home_b2b ? ` · ${G.away_b2b ? a : h} on a back-to-back` : ""}</div>
      <h1 style="font-size:${C.size || 96}px;margin-top:10px">${esc(C.title)}</h1>
      <p style="font-size:33px;line-height:1.32;margin-top:22px">${esc(C.dek)}</p>
      <div class="threads">${C.threads.map((t) => `<p>${t}</p>`).join("")}</div>
      <div class="wp"><div class="wl"><b style="color:${ca}">${a} ${pct(pa)}</b><span>Our win chance</span><b style="color:${ch}">${pct(ph)} ${h}</b></div>
        <div class="bar"><div style="width:${pa * 100}%;background:${ca}"></div><div style="flex:1;background:${ch}"></div></div></div>
      <div class="gls">${goalie(ga, ca)}<div class="mid">goals saved<br>above expected</div>${goalie(gh, ch, true)}</div>
      <div class="hunch"><span>Our hunch</span><p>${esc(C.hunch)}</p></div>
    </div>
    ${footer("For information and entertainment. 21+. 1-800-GAMBLER")}`, `
    .threads { margin-top:34px; display:grid; gap:18px; }
    .threads p { font-size:30px; line-height:1.3; color:${B.ice}; padding-left:26px; border-left:5px solid ${B.red}; }
    .threads p b { color:${B.blue}; }
    .wp { margin-top:44px; } .wl { display:flex; justify-content:space-between; align-items:baseline; font-family:"Big Shoulders Display"; }
    .wl b { font-weight:900; font-size:46px; } .wl span { font-family:Barlow; font-size:22px; color:${B.muted}; text-transform:uppercase; letter-spacing:.1em; }
    .bar { display:flex; gap:6px; height:22px; margin-top:8px; } .bar div { border-radius:11px; }
    .gls { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:20px; margin-top:30px; background:${B.panel}; border-radius:18px; padding:20px 28px; }
    .gl span { display:block; font-size:20px; color:${B.muted}; text-transform:uppercase; letter-spacing:.1em; } .gl b { font-size:30px; font-weight:700; margin-right:12px; } .gl i { font-style:normal; font-family:"Big Shoulders Display"; font-weight:900; font-size:38px; }
    .mid { font-size:19px; color:${B.muted}; text-align:center; line-height:1.25; }
    .hunch { margin-top:30px; border:3px solid ${B.line}; border-radius:18px; padding:16px 28px 18px; }
    .hunch span { font-family:"Big Shoulders Display"; font-weight:800; letter-spacing:.12em; text-transform:uppercase; color:${B.red}; font-size:24px; }
    .hunch p { font-size:28px; line-height:1.3; margin-top:4px; }`);
}

// the first slide of a carousel: the date, big enough to read in the profile grid, and what's inside
// rows: [{ colors: [..], title, sub, right }]
function cover(T, { kicker, line, rows }) {
  const d = new Date(T.date + "T12:00:00Z");
  const mon = d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }), day = d.getUTCDate();
  const wk = d.toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
  const dense = rows.length > 5;
  const html = rows.map((r) => `
    <div class="g">
      <div class="chips">${r.colors.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
      <div><b>${esc(r.title)}</b>${r.sub && !dense ? `<span>${esc(r.sub)}</span>` : ""}</div>
      <em>${esc(r.right || "")}</em>
    </div>`).join("");
  return page(1080, 1350, `
    ${rinkBg(880, 330, 300)}
    <div style="padding:72px 72px 0">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:${dense ? 40 : 90}px">${wk} · ${esc(kicker)}</div>
      <h1 style="font-size:${dense ? 240 : 330}px;line-height:.84;margin-top:6px">${mon} <span style="color:${B.blue}">${day}</span></h1>
      <p style="font-size:40px;font-weight:600;margin-top:${dense ? 16 : 30}px">${esc(line)}</p>
      <div class="gs" style="margin-top:${dense ? 22 : 44}px;gap:${dense ? 8 : 16}px">${html}</div>
    </div>
    <div class="foot"><span>For information and entertainment. 21+. 1-800-GAMBLER</span><span style="color:${B.ice};font-weight:700;font-size:26px">Swipe &#8594;</span></div>`, `
    .gs { display:grid; }
    .g { display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:24px; background:${B.panel}; border-radius:20px; padding:${dense ? "10px 28px" : "20px 30px"}; }
    .chips { display:flex; gap:6px; } .chips i { width:12px; height:${dense ? 40 : 64}px; border-radius:6px; display:block; }
    .g b { display:block; font-size:${dense ? 30 : 38}px; font-weight:700; line-height:1.15; } .g span { display:block; font-size:25px; color:${B.muted}; margin-top:2px; }
    .g em { font-style:normal; font-family:"Big Shoulders Display"; font-weight:800; font-size:${dense ? 30 : 36}px; color:${B.ice}; white-space:nowrap; }`);
}
const COUNT = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
function gamesCover(T, GAMES) {
  const titles = Object.fromEntries(GAMES.map(([G, C]) => [G.id, C.title]));
  const n = T.games.length;
  return cover(T, { kicker: "Game night", line: `${COUNT[n] || n} game${n === 1 ? "" : "s"} tonight. The story, our numbers and a hunch for each.`,
    rows: T.games.map((g) => ({ colors: [tc(g.away), tc(g.home) === tc(g.away) ? B.ice : tc(g.home)], title: `${NAMES[g.away]} at ${NAMES[g.home]}`, sub: titles[g.id], right: etTime(g.start) })) });
}
// the players carousel: likeliest scorers, sleepers, and the day's stat card if there is one
function playersCover(T, TODAY) {
  const top = [...T.props].filter((p) => p.lineup !== "returning").sort((a, b) => b.p_goal - a.p_goal)[0];
  const S = T.games.flatMap((g) => g.sleepers || []).slice(0, 4);
  const rows = [{ colors: [tc(top.team)], title: "Likeliest goal scorers", sub: `${top.name} leads the night`, right: pct(top.p_goal) }];
  if (S.length) rows.push({ colors: S.map((x) => tc(x.team)).filter((c, i, a) => a.indexOf(c) === i).slice(0, 3), title: "Sleepers", sub: `${COUNT[S.length]} under-the-radar name${S.length === 1 ? "" : "s"}, each with a reason`, right: `${S.length}` });
  if (TODAY.stat) rows.push({ colors: [tc(TODAY.stat.team)], title: TODAY.stat.cover || TODAY.stat.title, sub: TODAY.stat.cover_sub || "", right: TODAY.stat.big });
  const parts = ["who scores", S.length ? "who surprises" : "", TODAY.stat ? "and one number worth knowing" : ""].filter(Boolean);
  return cover(T, { kicker: "Players to watch", line: `Tonight by our numbers: ${parts.join(", ").replace(", and", " and")}.`, rows });
}

// one big number and the sentence that explains it (a streak, a milestone, a record)
function stat({ kicker, big, unit, title, lines, team, note }) {
  return page(1080, 1350, `
    <div style="position:absolute;left:0;top:0;bottom:0;width:28px;background:${tc(team)}"></div>
    ${rinkBg(1010, 1230, 360)}
    <div style="padding:72px 72px 0 104px">
      ${wordmark(36)}
      <div class="kicker" style="margin-top:120px">${esc(kicker)}</div>
      <div style="display:flex;align-items:baseline;gap:24px;margin-top:4px"><h1 style="font-size:420px;color:${B.blue};line-height:.86">${esc(big)}</h1><span style="font-family:'Big Shoulders Display';font-weight:800;font-size:64px;text-transform:uppercase;line-height:1">${unit}</span></div>
      <h1 style="font-size:84px;margin-top:28px">${esc(title)}</h1>
      <div style="margin-top:32px;display:grid;gap:14px;max-width:840px">${lines.map((l) => `<p style="font-size:36px;line-height:1.3">${l}</p>`).join("")}</div>
    </div>
    ${footer(note)}`);
}

function sleepers(T, notes = {}, story = false) {
  const S = T.games.flatMap((g) => g.sleepers || []).slice(0, 4);
  const cards = S.map((s) => `
    <div class="sl">
      <div class="chip" style="background:${tc(s.team)}"></div>
      <div><span class="tag">${s.kind === "depth" ? "Depth goal" : "Point"}</span><b>${esc(s.name)}</b><span class="muted">${s.team} vs ${s.opp}</span>${notes[s.id] ? `<em>${esc(notes[s.id])}</em>` : ""}</div>
      <div class="p"><b>${pct(s.kind === "depth" ? s.p_goal : s.p_1pt)}</b><span>${s.kind === "depth" ? "to score" : "for a point"}</span></div>
    </div>`).join("");
  const k = story ? 1 : 0.8;   // the feed card is the same design, tightened to 4:5
  return page(1080, story ? 1920 : 1350, `
    ${story ? rinkBg(540, 1760, 330, false) : rinkBg(1000, 150, 230)}
    <div style="padding:${story ? 160 : 72}px 72px 0">
      ${wordmark(story ? 40 : 36)}
      <div class="kicker" style="margin-top:${story ? 60 : 48}px">${dayLabel(T.date)}</div>
      <h1 style="font-size:${story ? 124 : 96}px;margin-top:${story ? 10 : 8}px">Sleepers</h1>
      <p class="muted" style="font-size:${story ? 34 : 26}px;margin-top:${story ? 20 : 12}px;line-height:1.35;max-width:${story ? 940 : 760}px">Under-the-radar players our numbers like tonight. Every one has a reason${story ? ", and we grade them in public" : ""}.</p>
      <div style="display:grid;gap:${story ? 20 : 13}px;margin-top:${story ? 44 : 26}px">${cards}</div>
    </div>
    <div class="foot" ${story ? 'style="bottom:200px"' : ""}><span>For information and entertainment. 21+. 1-800-GAMBLER</span></div>`, `
    .sl { display:grid; grid-template-columns:16px 1fr auto; gap:28px; align-items:center; background:${B.panel}; border-radius:24px; padding:${story ? 26 : 15}px 36px; }
    .chip { width:16px; height:${110 * k}px; border-radius:8px; }
    .sl b { display:block; font-size:${story ? 48 : 40}px; font-weight:700; line-height:1.15; } .sl .muted { font-size:${story ? 28 : 23}px; } .sl em { display:block; font-style:normal; font-size:${story ? 28 : 25}px; line-height:1.28; margin-top:${story ? 10 : 5}px; }
    .tag { font-family:"Big Shoulders Display"; font-weight:800; letter-spacing:.1em; text-transform:uppercase; color:${B.red}; font-size:${story ? 26 : 22}px; }
    .p { text-align:right; } .p b { display:block; font-family:"Big Shoulders Display"; font-weight:900; font-size:${story ? 84 : 70}px; color:${B.blue}; line-height:1; } .p span { font-size:${story ? 24 : 21}px; color:${B.muted}; }`);
}

// the pinned "how it works" carousel (social/pinned.json): one idea per slide, set like a monograph
// (serif body, numbered sections, hairline rules; Tolar, Nov 9, 2026: sober and academic, not playful)
const SERIF = `<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">`;
function pitch(S, i, n) {
  const big = S.big ? `<h1 class="big">${esc(S.big)}</h1>${S.unit ? `<p class="unit">${esc(S.unit)}</p>` : ""}` : "";
  const list = S.list ? `<div class="pl">${S.list.map((x, k) => `<div><i>${k + 1}</i><span>${esc(x)}</span></div>`).join("")}</div>` : "";
  const rows = S.rows ? `<div class="pr"><div class="hd"><span>Stated probability</span><span>Observed frequency</span><span>Player-games</span></div>${S.rows.map((r) => `<div><b>${r[0]}</b><b style="color:${B.blue}">${r[1]}</b><em>${r[2]}</em></div>`).join("")}</div>` : "";
  return page(1080, 1350, `
    <div style="padding:72px 84px 0">
      <div style="display:flex;justify-content:space-between;align-items:center">${wordmark(32)}<span class="num">${i} / ${n}</span></div>
      <div class="rule" style="margin-top:36px"></div>
      <div style="margin-top:${S.top ?? 150}px">
        ${S.kicker ? `<div class="sec">${esc(S.kicker)}</div>` : ""}
        ${big}
        ${S.title ? `<h1 class="ti" style="font-size:${S.size || 84}px;margin-top:${S.big ? 44 : 22}px">${S.title}</h1>` : ""}
        <div class="pb">${(S.body || []).map((t) => `<p>${t}</p>`).join("")}</div>
        ${list}${rows}
        ${S.after ? `<p class="pa">${S.after}</p>` : ""}
      </div>
    </div>
    <div class="foot" style="left:84px;right:84px"><span>${esc(S.note || "For information and entertainment. 21+. 1-800-GAMBLER")}</span></div>`, `
    .num { font-family:"Source Serif 4",serif; font-size:26px; color:${B.muted}; letter-spacing:.06em; }
    .rule { height:2px; background:${B.line}; }
    .sec { font-family:"Big Shoulders Display"; font-weight:700; letter-spacing:.22em; text-transform:uppercase; color:${B.muted}; font-size:26px; }
    .ti { font-weight:800; letter-spacing:.015em; line-height:1.0; }
    .big { font-size:${S.bigSize || 210}px; color:${B.ice}; line-height:.9; margin-top:26px; font-weight:800; }
    .unit { font-family:"Big Shoulders Display"; font-weight:700; font-size:40px; letter-spacing:.14em; text-transform:uppercase; color:${B.blue}; margin-top:30px; }
    .pb { margin-top:40px; display:grid; gap:26px; max-width:880px; } .pb p { font-family:"Source Serif 4",serif; font-size:38px; line-height:1.42; color:${B.ice}; }
    .pb i, .pa i { font-style:italic; } .pb b { font-weight:600; }
    .pa { font-family:"Source Serif 4",serif; font-size:32px; line-height:1.42; margin-top:40px; color:${B.muted}; max-width:880px; }
    .pl { margin-top:36px; border-top:2px solid ${B.line}; } .pl div { display:flex; align-items:baseline; gap:28px; padding:17px 4px; border-bottom:2px solid ${B.line}; }
    .pl i { font-style:normal; font-family:"Source Serif 4",serif; font-size:26px; color:${B.muted}; width:28px; flex:none; } .pl span { font-family:"Source Serif 4",serif; font-size:35px; }
    .pr { margin-top:40px; border-top:2px solid ${B.ice}; border-bottom:2px solid ${B.ice}; } .pr div { display:grid; grid-template-columns:1fr 1fr .8fr; align-items:baseline; padding:16px 4px; border-top:2px solid ${B.line}; }
    .pr .hd { border-top:none; padding:14px 4px; } .pr .hd span { font-family:"Big Shoulders Display"; font-weight:700; letter-spacing:.14em; text-transform:uppercase; font-size:22px; color:${B.muted}; }
    .pr b { font-family:"Source Serif 4",serif; font-weight:600; font-size:60px; line-height:1; } .pr em { font-style:normal; font-family:"Source Serif 4",serif; font-size:34px; color:${B.muted}; }`).replace("</head>", SERIF + "</head>");
}

// ---------------------------------------------------------------- render
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const get = async (f) => (await fetch(SITE + f)).json();
  const [T, P] = await Promise.all([get("tonight.json"), get("team_profiles.json")]);
  const tf = path.join(__dirname, "today.json");
  const TODAY = fs.existsSync(tf) ? JSON.parse(fs.readFileSync(tf, "utf8")) : {};
  const GAMES = [];
  for (const [id, C] of Object.entries(TODAY.games || {})) GAMES.push([await get(`previews/${id}.json`), C]);
  const pf = path.join(__dirname, "pinned.json");
  const PIN = process.env.PINNED === "1" && fs.existsSync(pf) ? JSON.parse(fs.readFileSync(pf, "utf8")) : [];
  const jobs = process.env.PINNED === "1" ? PIN.map((S, i) => [`pinned-${i + 1}.png`, 1080, 1350, pitch(S, i + 1, PIN.length)]) : [
    ["profile.png", 1080, 1080, profile()],
    ["brand.png", 1080, 1350, brand()],
    ["scorers.png", 1080, 1350, scorers(T, TODAY.scorer_notes || {})],
    ["luck.png", 1080, 1350, luck(P)],
    ...(TODAY.feature ? [["feature.png", 1080, 1350, feature(TODAY.feature)]] : []),
    ...(TODAY.stat ? [["stat.png", 1080, 1350, stat(TODAY.stat)]] : []),
    ...(GAMES.length ? [["cover-games.png", 1080, 1350, gamesCover(T, GAMES)]] : []),
    ...GAMES.map(([G, C]) => [`game-${G.away}-${G.home}.png`, 1080, 1350, gameCard(G, C)]),
    ["cover-players.png", 1080, 1350, playersCover(T, TODAY)],
    ["sleepers.png", 1080, 1350, sleepers(T, TODAY.sleeper_notes || {})],
    ...(process.env.STORY === "1" ? [["story-sleepers.png", 1080, 1920, sleepers(T, TODAY.sleeper_notes || {}, true)]] : []),
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
