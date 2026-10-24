/* Read the Ice front end. Plain JS, no build step. Data comes from data/*.json,
   rebuilt every morning by site/build.py. */
"use strict";

const D = {};                       // loaded data
const S = {                         // UI state
  game: null, pos: "all", q: "", sleepOnly: false, mkt: "p_goal", sort: { key: "p_goal", dir: -1 },
  goalies: {}, tLimit: 40, pSort: { key: "pts", dir: -1 }, pPos: "all", pTeam: "all", pMin: 3, pLimit: 60,
};
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v === "" || v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} },
};

// ------------------------------------------------------------------ number helpers
const pct = (p, d = 0) => (p == null ? "–" : (100 * p).toFixed(d) + "%");
const num = (x, d = 1) => (x == null ? "–" : Number(x).toFixed(d));
const signed = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
function fair(p) {
  if (!p || p <= 0 || p >= 1) return "–";
  return p < 0.5 ? "+" + Math.round((100 * (1 - p)) / p) : String(Math.round((-100 * p) / (1 - p)));
}
function decimalOdds(s) {
  const o = parseFloat(String(s).replace(/[^\d.+-]/g, ""));
  if (!isFinite(o) || Math.abs(o) < 100) return null;
  return o > 0 ? 1 + o / 100 : 1 + 100 / -o;
}
const dateLabel = (iso) => {
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-US", { weekday: "short" }) + " " + d.getDate();
};
// game times in the visitor's own time zone ("7:00 PM EDT")
const gameTime = (utc) => (utc ? new Date(utc).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZoneName: "short" }) : "");

// ------------------------------------------------------------------ teams, your team, players you follow
const TEAM_NAME = { ANA: "Anaheim Ducks", BOS: "Boston Bruins", BUF: "Buffalo Sabres", CAR: "Carolina Hurricanes", CBJ: "Columbus Blue Jackets",
  CGY: "Calgary Flames", CHI: "Chicago Blackhawks", COL: "Colorado Avalanche", DAL: "Dallas Stars", DET: "Detroit Red Wings", EDM: "Edmonton Oilers",
  FLA: "Florida Panthers", LAK: "Los Angeles Kings", MIN: "Minnesota Wild", MTL: "Montréal Canadiens", NJD: "New Jersey Devils",
  NSH: "Nashville Predators", NYI: "New York Islanders", NYR: "New York Rangers", OTT: "Ottawa Senators", PHI: "Philadelphia Flyers",
  PIT: "Pittsburgh Penguins", SEA: "Seattle Kraken", SJS: "San Jose Sharks", STL: "St. Louis Blues", TBL: "Tampa Bay Lightning",
  TOR: "Toronto Maple Leafs", UTA: "Utah Mammoth", VAN: "Vancouver Canucks", VGK: "Vegas Golden Knights", WPG: "Winnipeg Jets", WSH: "Washington Capitals" };
const DIVISIONS = [["Atlantic", "BOS BUF DET FLA MTL OTT TBL TOR"], ["Metropolitan", "CAR CBJ NJD NYI NYR PHI PIT WSH"],
  ["Central", "CHI COL DAL MIN NSH STL UTA WPG"], ["Pacific", "ANA CGY EDM LAK SEA SJS VAN VGK"]].map(([d, t]) => [d, t.split(" ")]);
const teamName = (abbr) => TEAM_NAME[abbr] || abbr;
// the visitor's team and the players they follow live in this browser only
const myTeam = () => { const t = store.get("ice-team"); return t && TEAM_NAME[t] ? t : null; };
const FOLLOW_KEY = "ice-follow";
const follows = {
  list() { try { const v = JSON.parse(store.get(FOLLOW_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; } },
  has(id) { return this.list().some((x) => x.id === +id); },
  toggle(x) {
    const l = this.list(), i = l.findIndex((y) => y.id === +x.id);
    if (i >= 0) l.splice(i, 1); else l.push({ id: +x.id, kind: x.kind, name: x.name, team: x.team });
    store.set(FOLLOW_KEY, l.length ? JSON.stringify(l) : "");
    return i < 0;
  },
};
// a Follow button for player and goalie pages
function followBtn(x) {
  const on = follows.has(x.id);
  return `<button type="button" class="follow ${on ? "on" : ""}" data-follow="${x.id}" data-kind="${x.kind}" data-name="${esc(x.name)}" data-team="${esc(x.team || "")}"
    aria-pressed="${on}">${on ? "Following" : "Follow"}</button>`;
}
document.addEventListener("click", (e) => {
  if (e.target.closest?.("[data-pickteam]")) { openTeamPicker(); return; }
  const b = e.target.closest?.("[data-follow]");
  if (!b) return;
  const on = follows.toggle({ id: b.dataset.follow, kind: b.dataset.kind, name: b.dataset.name, team: b.dataset.team });
  b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); b.textContent = on ? "Following" : "Follow";
});
function setMyTeam(t) {
  store.set("ice-team", t || "");
  applyTeamButton();
}
function applyTeamButton() {
  const b = $("#teamBtn"), t = myTeam();
  if (!b) return;
  b.textContent = t ? t : "Your team";
  b.classList.toggle("set", !!t);
  b.setAttribute("aria-label", t ? `Your team: ${teamName(t)}. Change it` : "Pick your team");
}
// the team picker: a dialog of all 32 teams by division
function openTeamPicker(after) {
  let dlg = $("#teamDlg");
  if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "teamDlg"; dlg.className = "team-dlg"; document.body.appendChild(dlg); }
  const cur = myTeam();
  dlg.innerHTML = `<form method="dialog" class="td-head"><h2>Pick your team</h2><button class="chip" value="close" aria-label="Close">Close</button></form>
    <p class="note">We'll put your team first on Tonight, highlight it on the league chart, and open it when you tap Teams. It's saved in this browser only.</p>
    <div class="td-grid">${DIVISIONS.map(([d, ts]) => `<div><h3>${d}</h3>${ts.map((t) => `<button type="button" class="td-team ${t === cur ? "on" : ""}" data-myteam="${t}">
      <b>${t}</b><span>${esc(TEAM_NAME[t])}</span></button>`).join("")}</div>`).join("")}</div>
    ${cur ? `<p class="note"><button type="button" class="linkish" data-myteam="">Clear my team</button></p>` : ""}`;
  dlg.onclick = (e) => {
    const b = e.target.closest("[data-myteam]");
    if (b) { setMyTeam(b.dataset.myteam); dlg.close(); if (after) after(b.dataset.myteam); else route(); return; }
    if (e.target === dlg) dlg.close();   // click on the backdrop
  };
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
}

// Poisson helpers for client-side recomputation when a goalie is swapped
function poisPmf(l, n) { const out = [Math.exp(-l)]; for (let k = 1; k <= n; k++) out.push((out[k - 1] * l) / k); return out; }
function totalDist(la, lb) {
  const N = 15, a = poisPmf(la, N), b = poisPmf(lb, N), out = new Array(2 * N + 2).fill(0);
  for (let i = 0; i <= N; i++) for (let j = 0; j <= N; j++) out[i + j + (i === j ? 1 : 0)] += a[i] * b[j];
  return out;
}

// ------------------------------------------------------------------ tooltip
const tip = $("#tip");
function showTip(target, x, y) {
  tip.innerHTML = target.dataset.tip;
  tip.hidden = false;
  placeTip(x, y);
}
function placeTip(x, y) {
  const r = tip.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tip.style.left = Math.max(8, left) + "px";
  tip.style.top = Math.max(8, top) + "px";
}
document.addEventListener("pointermove", (e) => {
  const t = e.target.closest?.("[data-tip]");
  if (t && e.pointerType === "mouse") showTip(t, e.clientX, e.clientY);
  else if (e.pointerType === "mouse" && !e.target.closest?.(".shotmap svg")) tip.hidden = true;
});
document.addEventListener("click", (e) => {
  const t = e.target.closest?.("[data-tip]");
  if (t && !t.closest("a,button")) { const r = t.getBoundingClientRect(); showTip(t, r.left + r.width / 2, r.top); }
  else tip.hidden = true;
});
addEventListener("scroll", () => (tip.hidden = true), { passive: true });

// ------------------------------------------------------------------ SVG building blocks
const mainW = (max, min = 320) => Math.max(min, Math.min(max, ($("#view").clientWidth || 1000) - 32));
function ticks(lo, hi, n = 5) {
  const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function rinkSVG(shots, opts = {}) {
  // half rink in feet: centre red line x=0, blue line x=25, goal line x=89, boards x=100
  return `<svg class="chart rink" viewBox="-1 -43.5 102 87" role="img" aria-label="${esc(opts.label || "Shot map")}">
    <path class="boards" d="M0,-42.5 L72,-42.5 A28,28 0 0 1 100,-14.5 L100,14.5 A28,28 0 0 1 72,42.5 L0,42.5 Z"/>
    <rect class="redline" x="-0.5" y="-42.5" width="1" height="85"/>
    <rect class="blueline" x="25" y="-42.5" width="1" height="85"/>
    <circle class="dot" cx="20" cy="-22" r="0.6"/><circle class="dot" cx="20" cy="22" r="0.6"/>
    <text class="zone-label" x="1.5" y="41">Center line</text><text class="zone-label" x="26.5" y="41">Blue line</text>
    <circle class="circle" cx="69" cy="-22" r="15"/><circle class="circle" cx="69" cy="22" r="15"/>
    <circle class="dot" cx="69" cy="-22" r="0.6"/><circle class="dot" cx="69" cy="22" r="0.6"/>
    <line class="goalline" x1="89" y1="-36.7" x2="89" y2="36.7"/>
    <path class="crease" d="M89,-4 L85.5,-4 A6,6 0 0 0 85.5,4 L89,4 Z"/>
    <rect class="net" x="89" y="-3" width="3.3" height="6" rx="0.8"/>
    ${shotDots(shots, opts.scale || 1, 0.7, 3.4)}
  </svg>`;
}

// ------------------------------------------------------------------ shot maps: tap or click a dot for its details
// Every shot map is wrapped by shotMap(): the dots carry their index, a tap picks the nearest dot (so small
// ones are easy to hit on a phone), the picked dot gets a ring and its details show in a panel under the
// map, which stays put however the page is zoomed. Mouse hover shows a short label.
const SHOT_TYPE = { w: "Wrist shot", s: "Snap shot", l: "Slap shot", b: "Backhand", t: "Tip-in", d: "Deflection", r: "Wraparound",
  p: "Poke", a: "Batted puck", x: "Between-the-legs shot", c: "Lacrosse-style shot" };
const STATE_NAME = { PP: "power play", SH: "shorthanded", EN: "into an empty net", EA: "with the extra attacker" };
const SHOTMAPS = {};
let smSeq = 0, smPointer = "mouse";
function shotDots(shots, scale, base, k) {
  const marks = shots.map((s, i) => {
    const [x, y, xg, g] = s, rr = (base + Math.sqrt(xg / 1000) * k) * scale;
    return { g, svg: `<circle class="${g ? "goal" : "shot"}" cx="${x}" cy="${-y}" r="${(g ? Math.max(rr, 1.3) : rr).toFixed(2)}" data-i="${i}"></circle>` };
  });
  marks.sort((a, b) => a.g - b.g);   // goals on top
  return marks.map((m) => m.svg).join("") + `<g class="sm-sel" aria-hidden="true"></g>`;
}
// kind "game": shots carry game fields (see site/games.py); "player"/"team": [x, y, xg, goal, game number, second, type(, shooter)]
function shotMap(svg, shots, ctx) {
  const id = "sm" + ++smSeq;
  for (const k of Object.keys(SHOTMAPS)) if (!document.getElementById(k)) delete SHOTMAPS[k];
  const order = shots.map((s, i) => i).sort((a, b) => (ctx.kind === "game" ? shots[a][5] - shots[b][5] : (shots[a][4] - shots[b][4]) || (shots[a][5] - shots[b][5])));
  SHOTMAPS[id] = { shots, ctx, order, sel: -1 };
  const hint = shots.length ? `Tap a dot for the shot's details, or <button type="button" class="linkish" data-sm-first="goal">start with the first goal</button>.` : "No shots yet.";
  return `<div class="shotmap" id="${id}">${svg}<div class="shot-info" aria-live="polite"><p class="si-hint">${hint}</p></div></div>`;
}
const smClock = (sec) => {
  const per = Math.min(Math.floor(sec / 1200) + 1, 4), t = sec - (per - 1) * 1200;
  return `${["1st", "2nd", "3rd", "OT"][per - 1]}, ${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")} in`;
};
function smNearest(map, svg, e, maxPx) {
  const ctm = svg.getScreenCTM();
  if (!ctm) return -1;
  const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
  let best = -1, bd = Infinity;
  map.shots.forEach((s, i) => { const d = Math.hypot(s[0] - pt.x, -s[1] - pt.y) - (s[3] ? 0.6 : 0); if (d < bd) { bd = d; best = i; } });
  return bd * Math.hypot(ctm.a, ctm.b) <= maxPx ? best : -1;
}
function smLabel(map, i) {
  const s = map.shots[i], c = map.ctx, nm = c.kind === "game" ? c.names[s[6]] : c.kind === "team" ? c.names[s[8]] : c.name;
  return `${s[3] ? "<b>Goal</b>" : "Shot"}${nm ? ` by ${esc(nm)}` : ""}, ${(s[2] / 10).toFixed(1)}% chance<br><span class="dim">Click for details</span>`;
}
function smSelect(box, i) {
  const map = SHOTMAPS[box.id];
  if (!map) return;
  const svg = box.querySelector("svg"), layer = svg.querySelector(".sm-sel"), info = box.querySelector(".shot-info");
  map.sel = i;
  box.classList.toggle("has-sel", i >= 0);
  if (i < 0) { layer.innerHTML = ""; return; }
  const s = map.shots[i], dot = svg.querySelector(`circle[data-i="${i}"]`), r = dot ? +dot.getAttribute("r") : 1.5;
  // the picked dot is redrawn on top with a ring around it
  const vb = svg.viewBox.baseVal, ring = r + Math.max(2.4, vb.width / 60);
  layer.innerHTML = `<line class="sm-cross" x1="${vb.x}" x2="${vb.x + vb.width}" y1="${-s[1]}" y2="${-s[1]}"/>
    <line class="sm-cross" x1="${s[0]}" x2="${s[0]}" y1="${vb.y}" y2="${vb.y + vb.height}"/>
    <circle class="sm-ring" cx="${s[0]}" cy="${-s[1]}" r="${ring.toFixed(2)}"/>
    <circle class="${s[3] ? "goal" : "shot"} sm-on" cx="${s[0]}" cy="${-s[1]}" r="${r}"/>`;
  const pos = map.order.indexOf(i);
  info.innerHTML = `${smDescribe(map, i)}
    <div class="si-nav"><button type="button" class="chip" data-sm-step="-1" ${pos <= 0 ? "disabled" : ""} aria-label="Previous shot">‹ Earlier</button>
      <span class="dim">${pos + 1} of ${map.order.length}</span>
      <button type="button" class="chip" data-sm-step="1" ${pos >= map.order.length - 1 ? "disabled" : ""} aria-label="Next shot">Later ›</button>
      <button type="button" class="chip" data-sm-goal="1">Next goal</button>
      <button type="button" class="linkish" data-sm-clear>Clear</button></div>`;
  if (map.ctx.kind !== "game") smGameLine(box, s);
}
// NHL EDGE only publishes each player's ten hardest shots, so most shots have no speed
const speedNote = (mph) => (mph ? ` · <b>${num(mph, 1)} mph</b> <span class="dim">(one of his 10 hardest this season)</span>` : "");
function smDescribe(map, i) {
  const s = map.shots[i], c = map.ctx;
  const type = SHOT_TYPE[c.kind === "game" ? s[8] : s[6]] || "Shot";
  const dist = c.kind === "game" && s[9] != null ? s[9] : Math.round(Math.hypot(89 - Math.abs(s[0]), s[1]));
  const chance = `${(s[2] / 10).toFixed(1)}% chance (xG ${(s[2] / 1000).toFixed(2)})`;
  if (c.kind !== "game") {
    const who = c.kind === "team" ? c.names[s[8]] : c.name, pid = c.kind === "team" ? s[8] : c.id;
    return `<p class="si-head"><b class="${s[3] ? "si-goal" : ""}">${s[3] ? "Goal" : "Shot"}</b>${who ? ` · ${playerLink(pid, who)}` : ""} · <span class="si-game">${smClock(s[5])}</span></p>
      <p class="si-body">${type} from ${dist} ft · ${chance}${speedNote(s[7])}</p>`;
  }
  const team = s[4] ? c.home : c.away, opp = s[4] ? c.away : c.home;
  // score just before this shot, from the shooter's side
  let mine = 0, theirs = 0;
  for (const j of map.order) { if (j === i) break; const q = map.shots[j]; if (q[3]) (q[4] === s[4] ? mine++ : theirs++); }
  const score = mine === theirs ? `tied ${mine}-${theirs}` : `${team} ${mine > theirs ? "up" : "down"} ${mine}-${theirs}`;
  const flags = s[12] || 0, bits = [];
  if (flags & 1) bits.push("rebound");
  if (flags & 2) bits.push("off the rush");
  if (STATE_NAME[s[7]]) bits.push(STATE_NAME[s[7]]);
  const goal = s[3] && c.goals ? c.goals.find((x) => String(x.eid) === String(s[11])) : null;
  const goalie = s[10] ? c.names[s[10]] : "";
  const result = s[3] ? "" : flags & 4 ? (goalie ? `Saved by ${esc(goalie)}` : "On net, saved") : "Missed the net";
  const shooter = s[6] && c.names[s[6]] ? (c.live ? esc(c.names[s[6]]) : playerLink(s[6], c.names[s[6]])) : team;
  return `<p class="si-head"><b class="${s[3] ? "si-goal" : ""}">${s[3] ? "Goal" : "Shot"}</b> · ${shooter} <span class="dim">${team}</span> · ${smClock(s[5])}</p>
    <p class="si-body">${type} from ${dist} ft · ${chance}${speedNote(s[14])}${bits.length ? ` · ${bits.join(", ")}` : ""}</p>
    <p class="si-body">${result ? `${result} · ` : goalie ? `Beat ${esc(goalie)} · ` : ""}${score} before it${s[13] >= 0 ? ` · ${s[13]} s into his shift` : ""}</p>
    ${goal ? `<p class="si-body">${goal.assists && goal.assists.length ? `Assists: ${goal.assists.map((a) => playerLink(a.pid, a.name)).join(", ")}` : "Unassisted"}${goal.num ? ` · his ${ordinal(goal.num)} of the season` : ""}
      ${c.seqs && c.seqs[String(goal.eid)] ? ` · <button type="button" class="linkish" data-replay="${goal.eid}">Replay it</button>` : ""}${goal.clip ? ` · <a href="${esc(goal.clip)}" target="_blank" rel="noopener">Watch on NHL.com</a>` : ""}</p>` : ""}`;
}
async function smGameLine(box, s) {
  try {
    const idx = await getJSON("data/games/index.json");
    const g = idx.find((x) => x.id % 10000 === s[4]);
    const el = box.querySelector(".si-game");
    if (!g || !el) return;
    const team = SHOTMAPS[box.id]?.ctx.team || (D.skaters.find((p) => p.id === (SHOTMAPS[box.id]?.ctx.id ?? s[7]))?.team);
    const opp = team === g.home ? `vs ${g.away}` : team === g.away ? `at ${g.home}` : `${g.away} at ${g.home}`;
    el.innerHTML = `<a href="#game/${g.id}">${shortDate(g.date)} ${opp}</a>, ${smClock(s[5])}`;
  } catch (e) { /* the clock alone is fine */ }
}
// the live page redraws every minute; keep the picked shot (matched by time and shooter)
function smKeep(root) {
  const box = root.querySelector(".shotmap"), m = box && SHOTMAPS[box.id];
  return m && m.sel >= 0 ? m.shots[m.sel].slice(5, 7) : null;
}
function smRestore(root, keep) {
  const box = root.querySelector(".shotmap"), m = box && SHOTMAPS[box.id];
  if (!keep || !m) return;
  const i = m.shots.findIndex((s) => s[5] === keep[0] && String(s[6]) === String(keep[1]));
  if (i >= 0) smSelect(box, i);
}
document.addEventListener("pointerdown", (e) => { smPointer = e.pointerType || "mouse"; }, { capture: true, passive: true });
document.addEventListener("click", (e) => {
  const box = e.target.closest?.(".shotmap");
  if (!box || !SHOTMAPS[box.id]) return;
  const map = SHOTMAPS[box.id], b = e.target.closest("button");
  if (b && b.dataset.smStep) {
    const pos = map.order.indexOf(map.sel) + +b.dataset.smStep;
    if (pos >= 0 && pos < map.order.length) smSelect(box, map.order[pos]);
    return;
  }
  if (b && (b.dataset.smGoal || b.dataset.smFirst)) {
    const from = b.dataset.smFirst ? -1 : map.order.indexOf(map.sel);
    const next = map.order.slice(from + 1).find((j) => map.shots[j][3]) ?? map.order.find((j) => map.shots[j][3]);
    smSelect(box, next ?? map.order[0]);
    return;
  }
  if (b && b.dataset.replay && map.ctx.game && typeof openTheater === "function") {
    history.replaceState(null, "", `#game/${map.ctx.game.id}/${b.dataset.replay}`);
    openTheater(map.ctx.game, b.dataset.replay);
    return;
  }
  if (b && "smClear" in b.dataset) { smSelect(box, -1); box.querySelector(".shot-info").innerHTML = `<p class="si-hint">Tap a dot for the shot's details.</p>`; return; }
  const svg = e.target.closest("svg");
  if (!svg) return;
  const i = smNearest(map, svg, e, smPointer === "mouse" ? 14 : 26);
  if (i >= 0) { tip.hidden = true; smSelect(box, i); }
});
document.addEventListener("pointermove", (e) => {
  if (e.pointerType !== "mouse") return;
  const svg = e.target.closest?.(".shotmap svg"), box = svg && svg.closest(".shotmap");
  if (!box || !SHOTMAPS[box.id]) return;
  const i = smNearest(SHOTMAPS[box.id], svg, e, 14);
  svg.style.cursor = i >= 0 ? "pointer" : "";
  if (i >= 0) { tip.innerHTML = smLabel(SHOTMAPS[box.id], i); tip.hidden = false; placeTip(e.clientX, e.clientY); }
  else tip.hidden = true;
});

function scatterTeams(teams, fav) {
  const W = mainW(1000), H = Math.max(440, Math.round(W * 0.56)), m = { l: 52, r: 24, t: 16, b: 48 };
  const xs = teams.map((t) => t.xgf60), ys = teams.map((t) => t.xga60);
  const pad = 0.12;
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  const X = (v) => m.l + ((v - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => m.t + ((v - y0) / (y1 - y0)) * (H - m.t - m.b);   // fewer allowed = higher on the chart
  const avg = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  const ax = avg(xs), ay = avg(ys);
  const gx = ticks(x0, x1, 6).map((v) => `<line class="grid" x1="${X(v)}" x2="${X(v)}" y1="${m.t}" y2="${H - m.b}"/><text x="${X(v)}" y="${H - m.b + 16}" text-anchor="middle">${v.toFixed(1)}</text>`);
  const gy = ticks(y0, y1, 6).map((v) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(1)}</text>`);
  // place labels right of the dot, else left, else drop them (tooltip still works)
  const placed = [], lw = 30, lh = 14;
  const hit = (b) => placed.some((p) => b.x < p.x + p.w && b.x + b.w > p.x && b.y < p.y + p.h && b.y + b.h > p.y);
  const order = [...teams].sort((a, b) => (b.team === fav) - (a.team === fav));
  order.forEach((t) => placed.push({ x: X(t.xgf60) - 5, y: Y(t.xga60) - 5, w: 10, h: 10 }));
  const labelPos = {};
  order.forEach((t) => {
    const cx = X(t.xgf60), cy = Y(t.xga60);
    for (const [dx, anchor] of [[8, "start"], [-8, "end"]]) {
      const b = { x: anchor === "start" ? cx + dx : cx + dx - lw, y: cy - lh / 2, w: lw, h: lh };
      if (!hit(b) && b.x > m.l && b.x + b.w < W) { placed.push(b); labelPos[t.team] = { dx, anchor }; return; }
    }
  });
  const dots = teams.map((t) => {
    const isFav = t.team === fav, lp = labelPos[t.team];
    const tipTxt = `<b>${t.team}</b> ${t.w}-${t.l}-${t.otl}, ${t.pts} pts<br>Creates ${t.xgf60.toFixed(2)} xG/60, allows ${t.xga60.toFixed(2)}<br>Expected goal share ${t.xg_pct.toFixed(1)}%`;
    // red is reserved for goals site-wide, so the favourite team is the dark dot with a blue ring
    return `<a href="#teams/${t.team}" data-tip="${esc(tipTxt)}"><circle cx="${X(t.xgf60)}" cy="${Y(t.xga60)}" r="12" fill="transparent"/>
      <circle cx="${X(t.xgf60)}" cy="${Y(t.xga60)}" r="${isFav ? 6.5 : 4.5}" fill="${isFav ? "var(--ink)" : "var(--blue)"}" stroke="${isFav ? "var(--blue)" : "var(--sheet)"}" stroke-width="${isFav ? 2.5 : 2}"/>
      ${lp ? `<text class="lbl" x="${X(t.xgf60) + lp.dx}" y="${Y(t.xga60) + 4}" text-anchor="${lp.anchor}" style="${isFav ? "fill:var(--ink);font-weight:700" : ""}">${t.team}</text>` : ""}</a>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Teams by chances created and allowed per 60 minutes">
    ${gx.join("")}${gy.join("")}
    <line class="axis" x1="${X(ax)}" x2="${X(ax)}" y1="${m.t}" y2="${H - m.b}"/>
    <line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${Y(ay)}" y2="${Y(ay)}"/>
    <text x="${W - m.r}" y="${m.t + 12}" text-anchor="end" class="lbl">Outchancing opponents</text>
    <text x="${m.l + 6}" y="${H - m.b - 8}" class="lbl">Getting outchanced</text>
    ${dots.join("")}
    <text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle">Expected goals created per 60 minutes</text>
    <text transform="translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">Expected goals allowed per 60 (fewer is higher)</text>
  </svg>`;
}

function divergingBars(rows, valueKey, labelFn, tipFn, hrefFn) {
  const W = mainW(900), rowH = 24, m = { l: W < 500 ? 150 : 200, r: 44, t: 6 }, H = m.t + rows.length * rowH + 22;
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r[valueKey])), 1);
  const X = (v) => m.l + ((v + maxAbs) / (2 * maxAbs)) * (W - m.l - m.r);
  const bars = rows.map((r, i) => {
    const v = r[valueKey], y = m.t + i * rowH, x0 = X(0), x1 = X(v);
    const left = Math.min(x0, x1), w = Math.max(Math.abs(x1 - x0), 1.5);
    const col = v >= 0 ? "var(--blue)" : "var(--red)";
    const rx = Math.min(4, w / 2);
    const g = `<g data-tip="${esc(tipFn(r))}"><rect x="0" y="${y}" width="${W}" height="${rowH}" fill="transparent"/>
      <text x="${m.l - 8}" y="${y + 15}" text-anchor="end" class="lbl">${esc(W < 500 ? labelFn(r).replace(/^(\S)\S*\s/, "$1. ") : labelFn(r))}</text>
      <rect x="${left}" y="${y + 5}" width="${w}" height="12" rx="${rx}" fill="${col}"/>
      <text x="${v >= 0 ? x1 + 6 : x1 - 6}" y="${y + 15}" text-anchor="${v >= 0 ? "start" : "end"}">${signed(v)}</text></g>`;
    return hrefFn ? `<a href="${hrefFn(r)}">${g}</a>` : g;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Goals saved above expected by goalie">
    <line class="axis" x1="${X(0)}" x2="${X(0)}" y1="0" y2="${H - 18}"/>${bars.join("")}
    <text x="${X(0)}" y="${H - 2}" text-anchor="middle">0 = exactly as many goals as the shots deserved</text></svg>`;
}

function calibrationChart(cal, label) {
  const W = mainW(520), H = Math.round(W * 0.78), m = { l: 52, r: 16, t: 12, b: 44 };
  const top = Math.ceil(Math.max(...cal.map((c) => Math.max(c.pred, c.act))) * 10) / 10 + 0.05;
  const X = (v) => m.l + (v / top) * (W - m.l - m.r), Y = (v) => H - m.b - (v / top) * (H - m.t - m.b);
  const t = ticks(0, top, 4);
  const grid = t.map((v) => `<line class="grid" x1="${X(v)}" x2="${X(v)}" y1="${m.t}" y2="${H - m.b}"/><line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>
    <text x="${X(v)}" y="${H - m.b + 15}" text-anchor="middle">${Math.round(v * 100)}%</text><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text>`);
  const nMax = Math.max(...cal.map((c) => c.n));
  const pts = cal.map((c) => `<g data-tip="${esc(`We said ${pct(c.pred, 1)}, it happened ${pct(c.act, 1)}<br>${c.n.toLocaleString()} player-games`)}">
    <circle cx="${X(c.pred)}" cy="${Y(c.act)}" r="${4 + 6 * Math.sqrt(c.n / nMax)}" fill="var(--blue)" stroke="var(--sheet)" stroke-width="2"/></g>`);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${grid.join("")}
    <line class="axis" x1="${X(0)}" y1="${Y(0)}" x2="${X(top)}" y2="${Y(top)}"/>
    ${pts.join("")}
    <text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle">What we said</text>
    <text transform="translate(11 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">What happened</text></svg>`;
}

const cellBar = (p, max = 0.5) => `<span class="cellbar"><span>${pct(p)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.min(100, (100 * p) / max)}%"></span></span></span>`;
function divCell(v, scale, digits = 1) {
  if (v == null) return `<span class="dim">–</span>`;
  const w = Math.min(50, (Math.abs(v) / scale) * 50);
  const style = v >= 0 ? `left:50%;width:${w}%;background:var(--blue)` : `right:50%;width:${w}%;background:var(--red)`;
  return `<span class="div-cell"><span class="${v >= 0 ? "pos" : "neg"}">${signed(v, digits)}</span><span class="div-track"><span style="${style}"></span></span></span>`;
}

// sortable table: cols = [{key, label, fmt(row), num:true, nosort}]
function table(rows, cols, sort, id) {
  const head = cols.map((c) => `<th data-key="${c.key}" class="${c.nosort ? "nosort" : ""} ${c.cls || ""}" ${sort && sort.key === c.key ? `aria-sort="${sort.dir < 0 ? "descending" : "ascending"}"` : ""} scope="col">${c.label}</th>`).join("");
  const body = rows.map((r) => `<tr data-id="${r.id ?? ""}">${cols.map((c) => `<td class="${c.cls || ""}">${c.fmt ? c.fmt(r) : esc(r[c.key] ?? "–")}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table id="${id}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
function sortRows(rows, sort) {
  return [...rows].sort((a, b) => {
    const va = a[sort.key], vb = b[sort.key];
    if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sort.dir;
  });
}
function bindSort(root, sort, rerender) {
  $$("th[data-key]:not(.nosort)", root).forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.key;
    if (sort.key === k) sort.dir *= -1; else { sort.key = k; sort.dir = -1; }
    rerender();
  }));
}
const ordinal = (n) => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"));
const playerLink = (id, name) => `<a class="who" href="#players/${id}">${esc(name)}</a>`;

// ------------------------------------------------------------------ TONIGHT
function goalieFor(game, side) {
  const pick = S.goalies[game.id]?.[side] ?? probableId(game, side) ?? game[side + "_goalie"];
  const opts = game[side + "_goalies"] || [];
  return opts.find((o) => o.id === pick) || opts[0] || { factor: 1, name: "Unknown" };
}
function liveGame(game) {
  // recompute team expected goals and totals for the chosen goalies
  const dfltA = (game.away_goalies || []).find((o) => o.id === game.away_goalie)?.factor || 1;
  const dfltH = (game.home_goalies || []).find((o) => o.id === game.home_goalie)?.factor || 1;
  const ga = goalieFor(game, "away"), gh = goalieFor(game, "home");
  const away_xg = game.away_xg * (gh.factor / dfltH), home_xg = game.home_xg * (ga.factor / dfltA);
  const dist = totalDist(away_xg, home_xg);
  let tot = 0, o55 = 0, o65 = 0;
  dist.forEach((p, k) => { tot += p * k; if (k >= 6) o55 += p; if (k >= 7) o65 += p; });
  return { ...game, away_xg, home_xg, total: tot, o55, o65, ga, gh };
}
// the props markets, and P(X >= k) for a Poisson mean (gamma-mixed with shape r when the build set one)
const MARKETS = [["p_goal", "Goal"], ["p_1pt", "1+ points"], ["p_2pts", "2+ points"], ["p_3pts", "3+ points"],
  ["p_sog2", "2+ shots"], ["p_sog3", "3+ shots"]];
// the model's correction to 1+ points (P1_CAL in analysis/models.py), reapplied when a goalie change reprices a player
const p1cal = (p) => { const c = D.tonight.p1cal; if (!c) return p; const q = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  return 1 / (1 + Math.exp(-(c[0] + c[1] * Math.log(q / (1 - q))))); };
function nbTail(lam, r, k) {
  let p, tot = 0;
  if (!r) { p = Math.exp(-lam); for (let i = 0; i < k; i++) { tot += p; p *= lam / (i + 1); } }
  else { const q = r / (r + lam); p = Math.pow(q, r); for (let i = 0; i < k; i++) { tot += p; p *= ((r + i) / (i + 1)) * (1 - q); } }
  return 1 - tot;
}
function liveProps() {
  const games = Object.fromEntries(D.tonight.games.map((g) => [g.id, liveGame(g)]));
  return D.tonight.props.map((p) => {
    const g = games[p.game]; if (!g) return p;
    const oppGoalie = p.team === g.away ? g.gh : g.ga;
    const k = oppGoalie.factor / (p.g_f || 1);
    if (k === 1) return p;
    const lg = p.lam_g * k, lp = p.lam_p * k, dp = (D.tonight.disp || {});
    const p2 = nbTail(lp, dp.p, 2);
    return { ...p, p_goal: nbTail(lg, dp.g, 1), p_1pt: Math.max(p1cal(nbTail(lp, dp.p, 1)), p2), p_2pts: p2, p_3pts: nbTail(lp, dp.p, 3) };
  });
}

// the model's game numbers next to DraftKings' (published free by the NHL), so totals are read against the
// market, not a league average: the model's totals have never beaten either
function marketLine(g) {
  const m = g.market, mine = `Our model: ${g.home} ${pct(winHome(g))}, ${g.total.toFixed(1)} goals`;
  if (!m || m.total == null) return `<div class="game-foot" data-tip="${esc("Our game totals haven't beaten a simple league-average guess in testing, so read them as context.")}">${mine}. No sportsbook line yet.</div>`;
  const ml = (o) => (o > 0 ? `+${o}` : `${o}`);
  const tip = `<b>DraftKings, via the NHL</b><br>${g.away} ${ml(m.ml_away)}, ${g.home} ${ml(m.ml_home)} (${pct(m.p_home)} ${g.home} once the margin is removed)<br>Over/under ${m.total}: over ${ml(m.over)}, under ${ml(m.under)}; the over price implies about ${num(m.implied_total, 1)} goals<br><span class="dim">Our totals haven't beaten the sportsbook line or a league-average guess in testing.</span>`;
  return `<div class="game-foot mkt" data-tip="${esc(tip)}"><span><b>Sportsbook</b> ${g.home} ${pct(m.p_home)}, O/U ${m.total}</span><span class="dim">${mine}</span></div>`;
}
function winHome(g) {
  const a = poisPmf(g.away_xg, 15), h = poisPmf(g.home_xg, 15);
  let w = 0, t = 0;
  a.forEach((pa, i) => h.forEach((ph, j) => { if (j > i) w += pa * ph; else if (i === j) t += pa * ph; }));
  return w + t / 2;
}
// Sleepers: our own under-the-radar picks per game (site/sleepers.py), with the reasons
const SLEEPER_KIND = { depth: "Depth scorer", point: "Underrated for a point" };
function sleeperOf(id) {
  for (const g of (D.tonight && D.tonight.games) || []) for (const x of g.sleepers || []) if (x.id === id) return x;
  return null;
}
function sleeperTag(r) {
  if (!r.sleeper) return "";
  const x = sleeperOf(r.id);
  return `<span class="tag tag-sleeper" data-tip="${esc(`<b>${SLEEPER_KIND[r.sleeper] || "Sleeper"}</b><br>${x ? x.why : ""}`)}">Sleeper</span>`;
}
function sleeperCard(x, game) {
  const p = x.kind === "depth" ? `<b>${pct(x.p_goal)}</b> to score <span class="dim">(fair ${x.fair_goal})</span> · ${pct(x.p_1pt)} for a point`
    : `<b>${pct(x.p_1pt)}</b> for a point <span class="dim">(fair ${x.fair_point})</span> · ${pct(x.p_goal)} to score`;
  return `<article class="sleeper"><div class="sl-top"><span class="sleeper-kind">${SLEEPER_KIND[x.kind] || "Sleeper"}</span>
      ${game ? `<a class="sl-game" href="#preview/${game.id}">${game.away} at ${game.home}</a>` : ""}</div>
    <h3>${playerLink(x.id, x.name)} <span class="dim">${x.team} vs ${x.opp}</span></h3>
    <p>${esc(x.why.replace(/\s*We have him at [^.]*\.$/, ""))}</p><p class="sl-odds">${p}</p></article>`;
}
function sleeperSection(games) {
  const all = games.flatMap((g) => (g.sleepers || []).map((x) => [x, g]));
  if (!all.length) return "";
  return `<section class="zone"><h2>Sleepers</h2>
    <p class="lede">Our own under-the-radar picks: never "he's due", always something real. Depth scorers are third- and fourth-liners whose recent shots have been dangerous, facing a defense or goalie that gives chances up. Underrated point picks are players whose chance of a point tonight is clearly above what their season scoring suggests, because their role, line or matchup has changed. They're long shots by design, and we grade every one on the <a href="#model">Track record</a> page.</p>
    <div class="sleepers">${all.map(([x, g]) => sleeperCard(x, g)).join("")}</div></section>`;
}

// first visit: what the site is, and a prompt to pick a team
function welcomeCard() {
  if (store.get("ice-welcome")) return "";
  return `<section class="welcome" id="welcome" aria-label="Welcome">
    <div><h2>Welcome to Read the Ice</h2>
      <p>Every NHL game, explained with the numbers behind it: who's most likely to score tonight, which teams are better or worse than their record says, how every goal happened, and how coaches are using their players. Updated every morning, with live scores at night.</p>
      <p class="row" style="gap:10px;flex-wrap:wrap"><button type="button" class="chip chip-solid" data-welcome="team">${myTeam() ? "Change your team" : "Pick your team"}</button><a class="chip" href="#about">How it works</a></p></div>
    <button type="button" class="welcome-x" data-welcome="close" aria-label="Dismiss">×</button></section>`;
}
function bindWelcome(view) {
  const w = $("#welcome", view);
  if (!w) return;
  w.addEventListener("click", (e) => {
    const b = e.target.closest("[data-welcome]");
    if (!b) return;
    store.set("ice-welcome", "1");
    if (b.dataset.welcome === "team") openTeamPicker(() => route());
    else w.remove();
  });
}
function renderTonight(view) {
  const T = D.tonight, mine = myTeam(), followed = follows.list();
  if (!T.games.length) {
    view.innerHTML = `${welcomeCard()}<section class="zone"><h1>No games today</h1><p class="lede">The next slate appears here on the morning of game day. Meanwhile, every finished game is on the <a href="#games">Games</a> page.</p></section>`;
    bindWelcome(view);
    return;
  }
  // your team's game goes first
  const games = T.games.map(liveGame).sort((a, b) => (mine ? (b.away === mine || b.home === mine) - (a.away === mine || a.home === mine) : 0));
  const maxXg = Math.max(...games.flatMap((g) => [g.away_xg, g.home_xg]), 3.5);
  const gameCard = (g) => {
    const side = (abbr, xg, key) => {
      const opts = g[key + "_goalies"] || [], chosen = goalieFor(g, key);
      return `<div class="side"><span class="abbr">${abbr}</span>
        <span class="bar-track" data-tip="${esc(`${abbr} expected goals tonight: ${xg.toFixed(2)}`)}"><span class="bar-fill" style="width:${(100 * xg) / maxXg}%"></span></span>
        <span class="xg">${xg.toFixed(2)}</span></div>
        <label class="goalie"><select data-game="${g.id}" data-side="${key}" aria-label="${abbr} goalie">
          ${opts.map((o) => `<option value="${o.id}" ${o.id === chosen.id ? "selected" : ""}>${esc(o.name)} (${o.starts} start${o.starts === 1 ? "" : "s"})</option>`).join("")}
        </select><span class="g-src">${esc(goalieSource(g, key))}${g[key + "_b2b"] ? `<span class="tag tag-b2b" data-tip="${esc("Second night of a back-to-back. Last season, teams in that spot got 47.4% of the expected goals (286 games), and our numbers account for it.")}">Back-to-back</span>` : ""}</span></label>`;
    };
    const yours = mine && (g.away === mine || g.home === mine);
    return `<article class="game ${S.game === g.id ? "is-picked" : ""} ${yours ? "is-mine" : ""}">
      <div class="game-time"><span>${gameTime(g.start)}</span><span class="row" style="gap:12px"><a class="preview-link" href="#preview/${g.id}">Preview</a><button type="button" data-pick="${g.id}">${S.game === g.id ? "Show all games" : "Only this game"}</button></span></div>
      ${side(g.away, g.away_xg, "away")}${side(g.home, g.home_xg, "home")}
      ${marketLine(g)}
      <div class="live-line" data-live="${g.id}"></div>
    </article>`;
  };
  view.innerHTML = `${welcomeCard()}
    <section class="zone">
      <h1>${esc(new Date(T.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }))}: ${games.length} game${games.length === 1 ? "" : "s"}</h1>
      <p class="lede">Each bar is how many goals we expect that team to score tonight, based on the chances both teams create and allow and who's in net. Choose a different goalie and every number on this page updates. Scores update live once the puck drops.</p>
      <div class="slate">${games.map(gameCard).join("")}</div>
    </section>
    ${sleeperSection(games)}
    ${(T.headlines || []).length ? `<section class="zone">
      <h2>Tonight's storylines</h2>
      <p class="lede">What's happening around tonight's games. Tap one for the full preview, which also says whether each storyline is factored into our numbers. More on the <a href="#pulse">Pulse</a> page.</p>
      ${storyList(T.headlines.slice(0, 6), { game: true, compact: true })}
    </section>` : ""}
    <section class="zone">
      <h2>Who scores, who stacks points</h2>
      <p class="lede">Every skater's chance to score, to reach 1, 2 or 3+ points, or to put 2 or 3+ shots on goal tonight, with the fair odds each chance works out to. Have a sportsbook price? Type it in and we'll show the expected return. Positive means the book pays more than our number says it should.</p>
      <div class="controls">
        <input type="search" id="q" placeholder="Find a player" value="${esc(S.q)}" aria-label="Find a player">
        <div class="chips" role="group" aria-label="Position">
          ${["all", "F", "D"].map((p) => `<button type="button" class="chip" data-pos="${p}" aria-pressed="${S.pos === p}">${p === "all" ? "All skaters" : p === "F" ? "Forwards" : "Defense"}</button>`).join("")}
        </div>
        <label class="check"><input type="checkbox" id="sleepOnly" ${S.sleepOnly ? "checked" : ""}> Sleepers only</label>
        ${followed.length ? `<label class="check"><input type="checkbox" id="followOnly" ${S.followOnly ? "checked" : ""}> Players I follow</label>` : ""}
      </div>
      <div class="controls"><span class="dim">Market</span>
        <div class="chips" role="group" aria-label="Market">
          ${MARKETS.map(([k, l]) => `<button type="button" class="chip" data-mkt="${k}" aria-pressed="${S.mkt === k}">${l}</button>`).join("")}
        </div></div>
      <div id="propsTable"></div>
      <p class="note">Sleepers are our own under-the-radar picks, explained above. Lineups: everyone who dressed in any of the team's last three games, minus players listed as injured, plus players returning; anyone who missed the last game is tagged, and every number assumes the player dresses. ${esc(T.goalie_note)}</p>
      <p class="note gamble-note">For information and entertainment, not betting advice. Odds you type stay in this browser. If you bet, do it only where it's legal and you're of age. Gambling problem? Call 1-800-GAMBLER.</p>
    </section>`;

  const drawTable = () => {
    let rows = liveProps();
    if (S.game) rows = rows.filter((r) => r.game === S.game);
    if (S.pos !== "all") rows = rows.filter((r) => r.pos === S.pos);
    if (S.sleepOnly) rows = rows.filter((r) => r.sleeper);
    if (S.followOnly && followed.length) { const ids = new Set(followed.map((x) => x.id)); rows = rows.filter((r) => ids.has(r.id)); }
    if (S.q) rows = rows.filter((r) => r.name.toLowerCase().includes(S.q.toLowerCase()));
    // players ESPN lists as out or on IR sink to the bottom (still shown, flagged)
    const out = (r) => { const x = injuryOf(r.name); return x && x.abbr !== "DTD" ? 1 : 0; };
    const all = sortRows(rows, S.sort).sort((a, b) => out(a) - out(b));
    rows = all.slice(0, S.game || S.q || S.sleepOnly || S.followOnly ? 400 : S.tLimit);
    const mk = S.mkt, mkLabel = MARKETS.find(([k]) => k === mk)[1];
    const oddsKey = (id) => (mk === "p_goal" ? `odds:${T.date}:${id}` : `odds:${T.date}:${mk}:${id}`);
    const evCell = (r) => {
      const d = decimalOdds(store.get(oddsKey(r.id)) || "");
      if (!d || r[mk] == null) return `<span class="dim">–</span>`;
      const ev = r[mk] * d - 1;
      return `<span class="${ev >= 0 ? "pos" : "neg"}">${signed(100 * ev, 0)}%</span>`;
    };
    const other = mk === "p_goal" ? ["p_2pts", "2+ points"] : ["p_goal", "Goal chance"];
    const cols = [
      { key: "name", label: "Player", fmt: (r) => `${playerLink(r.id, r.name)}<span class="sub">${r.team} vs ${r.opp}</span>${sleeperTag(r)}${formTag(r)}${injuryTag(r.name)}${lineupTag(r)}` },
      { key: "pos", label: "Pos", cls: "hide-sm" },
      { key: "proj_toi", label: "Proj TOI", fmt: (r) => num(r.proj_toi, 1), cls: "hide-sm" },
      mk === "p_goal" ? { key: "g", label: "Goals (xG)", fmt: (r) => `${r.g} <span class="dim">(${num(r.ixg, 1)})</span>`, cls: "hide-sm" }
        : { key: "pts", label: "Points (GP)", fmt: (r) => `${r.pts} <span class="dim">(${r.gp})</span>`, cls: "hide-sm" },
      { key: mk, label: mk === "p_goal" ? "Goal chance" : `${mkLabel} chance`, fmt: (r) => cellBar(r[mk], mk === "p_1pt" ? 1 : 0.5) },
      { key: "fair_m", label: "Fair odds", nosort: true, fmt: (r) => fair(r[mk]) },
      { key: "odds", label: "Your odds", nosort: true, fmt: (r) => `<input class="odds-in" inputmode="text" data-id="${r.id}" placeholder="odds" value="${esc(store.get(oddsKey(r.id)) || "")}" aria-label="Book odds for ${esc(r.name)}, ${esc(mkLabel)}">` },
      { key: "ev", label: "Return", nosort: true, fmt: evCell, cls: "ev" },
      { key: other[0], label: other[1], fmt: (r) => cellBar(r[other[0]], 0.5), cls: "hide-sm" },
    ];
    $("#propsTable").innerHTML = (rows.length ? table(rows, cols, S.sort, "props") : `<p class="empty">${S.followOnly ? "None of the players you follow are in tonight's games." : "No skaters match. Clear the search or change the filters."}</p>`) +
      (all.length > rows.length ? `<div class="controls" style="margin-top:10px"><button type="button" class="chip" id="tMore">Show ${Math.min(40, all.length - rows.length)} more of ${all.length}</button></div>` : "");
    $("#tMore")?.addEventListener("click", () => { S.tLimit += 40; drawTable(); });
    bindSort($("#propsTable"), S.sort, drawTable);
    $$(".odds-in", view).forEach((inp) => inp.addEventListener("input", () => {
      store.set(oddsKey(inp.dataset.id), inp.value.trim());
      const r = rows.find((x) => String(x.id) === inp.dataset.id);
      inp.closest("tr").querySelector(".ev").innerHTML = evCell(r);
    }));
  };
  drawTable();

  $("#q").addEventListener("input", (e) => { S.q = e.target.value; drawTable(); });
  $("#sleepOnly").addEventListener("change", (e) => { S.sleepOnly = e.target.checked; drawTable(); });
  $("#followOnly")?.addEventListener("change", (e) => { S.followOnly = e.target.checked; drawTable(); });
  bindWelcome(view);
  $$("[data-pos]", view).forEach((b) => b.addEventListener("click", () => { S.pos = b.dataset.pos; renderTonight(view); }));
  $$("[data-mkt]", view).forEach((b) => b.addEventListener("click", () => {
    S.mkt = b.dataset.mkt; S.sort = { key: S.mkt, dir: -1 };
    $$("[data-mkt]", view).forEach((x) => x.setAttribute("aria-pressed", x.dataset.mkt === S.mkt));
    drawTable();
  }));
  $$("[data-pick]", view).forEach((b) => b.addEventListener("click", () => { const id = +b.dataset.pick; S.game = S.game === id ? null : id; renderTonight(view); }));
  fillLiveLines();
  $$("select[data-game]", view).forEach((sel) => sel.addEventListener("change", () => {
    (S.goalies[sel.dataset.game] ||= {})[sel.dataset.side] = +sel.value;
    store.set("goalies:" + T.date, JSON.stringify(S.goalies));
    renderTonight(view);
  }));
}

// ------------------------------------------------------------------ LEAGUE
function renderLeague(view) {
  const teams = D.teams, fav = myTeam();
  const goalies = D.goalies.filter((g) => g.sa >= 60).sort((a, b) => b.gsax - a.gsax);
  const sorted = sortRows(teams.map((t) => ({ ...t, id: t.team })), S.lSort ||= { key: "pts", dir: -1 });
  view.innerHTML = `
    <section class="zone">
      <h1>Who's actually good</h1>
      <p class="lede">Records can flatter a team for a while. Chances don't lie for long. Every team is placed by the quality of the chances it creates (left to right) and allows (fewer is higher), per 60 minutes. Up and to the right is where you want to be. ${fav ? `${esc(teamName(fav))}, your team, is the dark dot.` : `<button type="button" class="linkish" data-pickteam>Pick your team</button> to highlight it.`} Tap any team to open it.</p>
      <div class="figure">${scatterTeams(teams, fav)}</div>
    </section>
    <section class="zone">
      <h2>Standings, with the luck shown</h2>
      <p class="lede">The standings, plus the two things that make a record misleading. Finishing is goals scored minus what the team's chances usually produce. Goaltending is the chances against minus goals allowed, so positive means the goalies are stealing games. Both swing hard over a few weeks and usually drift back toward zero; a team winning on both is due for a cooler stretch.</p>
      <div id="standings"></div>
    </section>
    <section class="zone">
      <h2>Goalies: saves above expected</h2>
      <p class="lede">How many goals each goalie has saved compared with an average goalie facing the same shots. Goalies with at least 60 shots against (blocked shots excluded). Tap one for his full page: save rate by shot danger, rebounds and every shot he has faced.</p>
      <div class="figure">${divergingBars(goalies, "gsax", (g) => `${g.name} ${g.team}`,
        (g) => `<b>${esc(g.name)}</b> ${g.team}<br>${g.gp} GP, ${pct(g.sv_pct, 1)} save rate<br>Allowed ${g.ga} on ${num(g.xga, 1)} expected${g.prev_gsax != null ? `<br>Last season ${signed(g.prev_gsax)}` : ""}<br><span class="dim">Tap for his page</span>`,
        (g) => `#goalie/${g.id}`)}</div>
    </section>`;
  const draw = () => {
    const rows = sortRows(teams.map((t) => ({ ...t, id: t.team, rec: `${t.w}-${t.l}-${t.otl}`, gaLuck: t.xga - t.ga })), S.lSort);
    $("#standings").innerHTML = table(rows, [
      { key: "team", label: "Team", fmt: (r) => `<a class="who" href="#teams/${r.team}">${r.team}</a>` },
      { key: "gp", label: "GP" }, { key: "rec", label: "Record", nosort: true }, { key: "pts", label: "Pts" },
      { key: "xg_pct", label: "xG share", fmt: (r) => pct(r.xg_pct / 100, 1) },
      { key: "gf", label: "GF" }, { key: "ga", label: "GA" },
      { key: "g_minus_xg", label: "Finishing", fmt: (r) => divCell(r.g_minus_xg, 8) },
      { key: "gaLuck", label: "Goaltending", fmt: (r) => divCell(r.gaLuck, 8) },
    ], S.lSort, "standings-t");
    if (fav) $(`#standings tr[data-id="${fav}"]`)?.classList.add("is-mine");
    bindSort($("#standings"), S.lSort, draw);
  };
  draw();
}

// ------------------------------------------------------------------ TEAMS
function skaterCols() {
  return [
    { key: "name", label: "Player", fmt: (r) => playerLink(r.id, r.name) + formTag(r) },
    { key: "pos", label: "Pos" }, { key: "gp", label: "GP" },
    { key: "toi_pg", label: "TOI", fmt: (r) => num(r.toi_pg, 1) },
    { key: "g", label: "G" }, { key: "a", label: "A" }, { key: "pts", label: "P" },
    { key: "ixg", label: "xG", fmt: (r) => num(r.ixg, 1) },
    { key: "g_minus_xg", label: "G − xG", fmt: (r) => divCell(r.g_minus_xg, 4) },
    { key: "xgf5", label: "5v5 xG share", fmt: (r) => (r.xgf5 == null ? "–" : pct(r.xgf5 / 100)) },
    { key: "rel5", label: "Team better with him", fmt: (r) => divCell(r.rel5, 30) },
  ];
}
// One team's season, game by game: xG for above the axis, xG against below, result underneath.
function trendChart(team, idx) {
  const games = idx.filter((x) => x.away === team || x.home === team).sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);
  if (!games.length) return `<p class="note">No games yet.</p>`;
  // draw at the column's real width so text stays at reading size on phones
  const full = mainW(1240), W = Math.round(innerWidth > 860 ? (full - 28) / 2 - 24 : full - 24);
  const H = 210, m = { l: 30, r: 8, t: 10, b: 26 }, mid = m.t + (H - m.t - m.b) / 2;
  const vmax = Math.max(4, ...games.map((x) => Math.max(x.xg_a, x.xg_h))) * 1.05;
  const half = (H - m.t - m.b) / 2, Y = (v) => (v / vmax) * half;
  const step = (W - m.l - m.r) / Math.max(games.length, 8), bw = Math.min(26, step * 0.62);
  const bars = games.map((x, i) => {
    const home = x.home === team, f = home ? x.xg_h : x.xg_a, a = home ? x.xg_a : x.xg_h;
    const gf = home ? x.h : x.a, ga = home ? x.a : x.h, opp = home ? x.away : x.home;
    const res = gf > ga ? "W" : x.end !== "REG" ? "OT" : "L";
    const cx = m.l + step * (i + 0.5);
    const tipTxt = `<b>${home ? "vs" : "at"} ${opp}</b>, ${shortDate(x.date)}<br>${res === "W" ? "Won" : "Lost"} ${gf}-${ga}${x.end !== "REG" ? ` (${x.end})` : ""}<br>Chances ${num(f, 2)} for, ${num(a, 2)} against`;
    return `<a href="#game/${x.id}" data-tip="${esc(tipTxt)}"><rect x="${cx - step / 2}" y="${m.t}" width="${step}" height="${H - m.t - m.b + 18}" fill="transparent"/>
      <rect class="tf" x="${cx - bw / 2}" y="${mid - Y(f)}" width="${bw}" height="${Y(f)}" rx="2"/>
      <rect class="ta" x="${cx - bw / 2}" y="${mid}" width="${bw}" height="${Y(a)}" rx="2"/>
      <text x="${cx}" y="${H - 8}" text-anchor="middle" class="tres tres-${res}">${res}</text></a>`;
  });
  const ticks2 = [2, 4].filter((v) => v < vmax).map((v) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${mid - Y(v)}" y2="${mid - Y(v)}"/><text x="${m.l - 6}" y="${mid - Y(v) + 4}" text-anchor="end">${v}</text>
    <line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${mid + Y(v)}" y2="${mid + Y(v)}"/><text x="${m.l - 6}" y="${mid + Y(v) + 4}" text-anchor="end">${v}</text>`);
  return `<svg class="chart trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="${team} expected goals for and against by game">
    ${ticks2.join("")}<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${mid}" y2="${mid}"/>${bars.join("")}</svg>
    <div class="legend"><span><i style="background:var(--blue)"></i>Chances created (xG)</span><span><i style="background:var(--axis)"></i>Chances allowed</span></div>`;
}

// Teams landing: all 32 by division, with record and share of the chances
function renderTeamsHome(view) {
  const mine = myTeam(), by = Object.fromEntries(D.teams.map((t) => [t.team, t]));
  const card = (abbr) => {
    const t = by[abbr]; if (!t) return "";
    const share = t.xg_pct / 100;
    return `<a class="tcard ${abbr === mine ? "is-mine" : ""}" href="#teams/${abbr}">
      <span class="tc-name">${esc(teamName(abbr))}</span>
      <span class="tc-rec">${t.w}-${t.l}-${t.otl}, <b>${t.pts}</b> pts</span>
      <span class="tc-share" data-tip="${esc(`Share of expected goals: ${pct(share, 1)}<br>Above 50% means they out-chance their opponents`)}"><span class="share-bar"><span style="width:${Math.min(100, Math.max(0, (share - 0.35) / 0.3 * 100))}%"></span></span>${pct(share)}</span></a>`;
  };
  view.innerHTML = `<section class="zone">
      <h1>Teams</h1>
      <p class="lede">Every team's season: record, the chances behind it, shot maps, lines and deployment, special teams, goalies and every game. The bar is each team's share of expected goals; past the middle mark means they out-chance their opponents. ${mine ? "" : `<button type="button" class="linkish" data-pickteam>Pick your team</button> and Teams will open straight to it.`}</p>
      <div class="tgrid">${DIVISIONS.map(([d, ts]) => `<div><h3>${d}</h3>${[...ts].sort((a, b) => (by[b]?.pts ?? 0) - (by[a]?.pts ?? 0) || (by[a]?.gp ?? 0) - (by[b]?.gp ?? 0)).map(card).join("")}</div>`).join("")}</div>
    </section>`;
}
function renderTeams(view, param) {
  if (!param || param === "all" || !TEAM_NAME[param.toUpperCase()]) {
    if (!param && myTeam()) { history.replaceState(null, "", "#teams/" + myTeam()); param = myTeam(); }
    else return renderTeamsHome(view);
  }
  const team = param.toUpperCase(), mine = myTeam();
  const t = D.teams.find((x) => x.team === team);
  const abbrs = D.teams.map((x) => x.team).sort();
  const sk = D.skaters.filter((s) => s.team === team);
  const shots = sk.flatMap((s) => (D.shots[s.id] || []).map((x) => [...x.slice(0, 7), x[7] || 0, s.id]));
  const gl = D.goalies.filter((g) => g.team === team);
  const rank = [...D.teams].sort((a, b) => b.pts - a.pts || a.gp - b.gp).findIndex((x) => x.team === team) + 1;
  const finishing = t ? t.g_minus_xg : 0, keeping = t ? t.xga - t.ga : 0;
  const story = !t ? "" : [
    `${team} is getting ${pct(t.xg_pct / 100)} of the expected goals in its games (50% is an even split of the chances).`,
    Math.abs(finishing) >= 3 ? `Its shooters are ${finishing > 0 ? "running hot" : "running cold"}: ${signed(finishing)} goals compared with what their chances usually produce.` : `Its shooters are scoring about what their chances usually produce.`,
    Math.abs(keeping) >= 3 ? `Its goalies are ${keeping > 0 ? "stealing goals" : "letting in extra goals"} (${signed(keeping)} against the shots they've faced).` : `Its goaltending is about average for the shots faced.`,
  ].join(" ");
  S.tSort ||= { key: "pts", dir: -1 };
  view.innerHTML = `
    <section class="zone">
      <div class="controls"><a class="crumbs-a" href="#teams/all">All teams</a>
        <select id="teamPick" aria-label="Team">${abbrs.map((a) => `<option value="${a}" ${a === team ? "selected" : ""}>${esc(teamName(a))}</option>`).join("")}</select>
        ${mine === team ? `<span class="tag tag-mine">Your team</span>` : `<button type="button" class="follow" data-setteam="${team}">Make this my team</button>`}</div>
      <h1>${esc(teamName(team))}</h1>
      <p class="lede">${t ? `<b>${t.w}-${t.l}-${t.otl}, ${t.pts} points</b>, ${ordinal(rank)} in the league. ` : ""}${story}</p>
      <div id="teamStory"></div>
      <div class="stat-row" id="teamTiles"></div>
    </section>
    <section class="zone grid-2">
      <div class="figure"><h3>Every unblocked shot this season</h3><p class="note">Bigger dots were better chances. Red dots went in. Tap one for who, when and how.</p>
        ${shotMap(rinkSVG(shots, { label: `${team} shot map`, scale: 0.7 }), shots, { kind: "team", team, names: Object.fromEntries(sk.map((s) => [s.id, s.name])) })}
        <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      <div><h3>Game by game</h3><p class="note">Chances created above the line, chances allowed below, every game in order. Hover or tap a game for the score.</p>
        <div id="teamTrend" class="figure trend-fig"></div>
        <h3 style="margin-top:20px">Goalies</h3>
        ${gl.length ? table(gl.map((g) => ({ ...g })), [
          { key: "name", label: "Goalie", nosort: true, fmt: (g) => goalieLink(g.id, g.name) },
          { key: "gp", label: "GP", nosort: true }, { key: "sv_pct", label: "Save rate", nosort: true, fmt: (g) => pct(g.sv_pct, 1) },
          { key: "gsax", label: "Saves above expected", nosort: true, fmt: (g) => divCell(g.gsax, 8) },
        ], null, "tg") : `<p class="empty">No goalie data yet.</p>`}
      </div>
    </section>
    <section class="zone" id="teamTactics" hidden></section>
    <section class="zone"><h2>Skaters</h2><p class="lede">Tap a column to sort. xG is the expected goals from a player's own shots. "Team better with him" compares the team's share of five-on-five chances with him on the ice to its share without him: +5 means five points better.</p><div id="teamSk"></div></section>
    <div id="teamNews"></div>`;
  const draw = () => { $("#teamSk").innerHTML = table(sortRows(sk, S.tSort), skaterCols(), S.tSort, "tsk"); bindSort($("#teamSk"), S.tSort, draw); };
  draw();
  const here = location.hash;
  Promise.all([getJSON("data/team_profiles.json").catch(() => ({})), getJSON("data/games/index.json")]).then(([prof, idx]) => {
    if (location.hash !== here) return;
    const P = prof[team] || {}, tile = (v, label, sub) => `<div class="stat"><b>${v}</b><span>${label}</span>${sub ? `<small>${sub}</small>` : ""}</div>`;
    const lg = (k) => { const v = Object.values(prof).map((x) => x[k]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const vsLg = (k, hib) => { const a = lg(k); if (a == null || P[k] == null) return ""; const d = P[k] - a; return `${hib ? (d >= 0 ? "better" : "worse") : (d <= 0 ? "better" : "worse")} than average (${num(a, 2)})`; };
    $("#teamTiles").innerHTML = t ? [
      tile(pct(t.xg_pct / 100), "Share of expected goals", "all situations"),
      tile(P.xg5_share == null ? "–" : pct(P.xg5_share), "At five on five"),
      tile(num(P.pp_xg_pg, 2), "Power play xG a game", vsLg("pp_xg_pg", true)),
      tile(num(P.pk_xga_pg, 2), "Penalty kill xG allowed", vsLg("pk_xga_pg", false)),
      tile(`${num(P.pen_taken_pg, 1)} / ${num(P.pen_drawn_pg, 1)}`, "Penalties taken / drawn", "per game"),
      tile(signed(t.g_minus_xg), "Finishing", "goals minus expected"),
      tile(signed(t.xga - t.ga), "Goaltending", "goals saved above expected"),
    ].join("") : "";
    $("#teamTrend").innerHTML = trendChart(team, idx);
    if ((P.story || []).length) $("#teamStory").innerHTML = `<h3 class="kicker">Storylines</h3><ul class="notes team-notes">${P.story.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    getJSON("data/features.json").then((fs) => {   // the latest deep dive on this team
      const f = (fs || []).find((x) => x.kind === "team" && x.subject && x.subject.team === team);
      if (f && location.hash === here && $("#teamStory")) $("#teamStory").insertAdjacentHTML("beforeend", featureLink(f));
    }).catch(() => {});
  }).catch(() => {});
  teamNews(team).then((r) => {
    const el = $("#teamNews");
    if (location.hash !== here || !el) return;
    el.outerHTML = r ? r.html : "";
    const blk = view.querySelector(".media-block"); if (r && blk) bindMedia(blk, r.listen);
  }).catch(() => {});
  teamLog(team).then((html) => { if (location.hash === here) view.insertAdjacentHTML("beforeend", html); }).catch(() => {});
  renderTactics($("#teamTactics"), team).catch(() => {});
  getJSON("data/depth.json").then((dj) => {   // injured regulars and who's getting their minutes (site/depthchart.py)
    const outs = Object.values(dj.players || {}).filter((x) => x.team === team && x.status && x.text);
    if (!outs.length || location.hash !== here || !$("#teamStory")) return;
    $("#teamStory").insertAdjacentHTML("afterend", `<div class="ripples"><h3 class="kicker">Who's out, and who's filling in</h3>
      <ul class="notes">${outs.map((x) => `<li><b>${playerLink(x.id, x.name)}</b> <span class="dim">(${esc(x.status)}; ${esc(x.role)})</span>. ${esc(x.text)}</li>`).join("")}</ul></div>`);
  }).catch(() => {});
  $("#teamPick").addEventListener("change", (e) => (location.hash = "#teams/" + e.target.value));
  $("[data-setteam]", view)?.addEventListener("click", (e) => { setMyTeam(e.target.dataset.setteam); route(); });
}

// ------------------------------------------------------------------ PLAYERS
function verdictFor(p) {
  const bits = [];
  if (p.g_minus_xg >= 2) bits.push(`He has scored ${num(p.g_minus_xg, 1)} more goals than his chances usually produce, so expect fewer to go in from here.`);
  else if (p.g_minus_xg <= -1.5) bits.push(`He has ${num(-p.g_minus_xg, 1)} fewer goals than his chances usually produce, so goals should come if the chances keep coming.`);
  if (p.oi_luck >= 4) bits.push(`His team has scored ${num(p.oi_luck, 1)} more goals than expected while he's on the ice, which tends not to last.`);
  if (p.oi_luck <= -4) bits.push(`His team has been unlucky with him on the ice, ${num(-p.oi_luck, 1)} goals worse than the chances say.`);
  if (p.rel5 != null && Math.abs(p.rel5) >= 10) bits.push(`At five on five his team's share of the chances is ${Math.round(Math.abs(p.rel5))} points ${p.rel5 > 0 ? "higher" : "lower"} with him on the ice than without him.`);
  return bits.length ? bits.join(" ") : "Nothing unusual yet: his results line up with how he's playing.";
}
// NHL EDGE extras for one skater: where his shots come from (the NHL's 17 tracked areas) and his hardest shots
function edgeBlock(ed, log) {
  const areas = (ed.areas || []).filter((a) => a.sog > 0);
  const total = areas.reduce((t, a) => t + a.sog, 0);
  const vsOf = Object.fromEntries((log || []).map((x) => [x.id, `${x.home ? "vs" : "@"} ${x.opp}`]));
  const areaRows = areas.slice(0, 6).map((a) => `<tr><td>${esc(a.area)}</td><td>${a.sog} <span class="dim">(${pct(a.sog / total)})</span></td><td>${a.g}</td>
    <td>${a.sh == null ? "–" : pct(a.sh, 0)}</td></tr>`).join("");
  const hard = (ed.hard || []).map((h) => `<li><b>${num(h.mph, 1)} mph</b> <a href="#game/${h.game}">${shortDate(h.date)} ${esc(vsOf[h.game] || "")}</a>, ${["1st", "2nd", "3rd"][h.period - 1] || "OT"} ${esc(h.t)}</li>`).join("");
  return `${areas.length ? `<h3 style="margin-top:22px">Where his shots on goal come from</h3>
      <div class="table-wrap"><table class="mini"><thead><tr><th>Area</th><th>Shots</th><th>Goals</th><th>Sh%</th></tr></thead><tbody>${areaRows}</tbody></table></div>
      <p class="note">The NHL's own tracked shot locations (EDGE), his six busiest areas this season. A handful of shots per area is noise; it settles over a few months.</p>` : ""}
    ${hard ? `<h3 style="margin-top:18px">Hardest shots</h3><ul class="plist">${hard}</ul>` : ""}`;
}
// search over skaters and goalies; used on the Players landing and on every player page
function bindPlayerSearch(view) {
  const q = $("#pq", view), sugg = $("#sugg", view);
  if (!q) return;
  q.addEventListener("input", () => {
    const t = q.value.trim().toLowerCase();
    if (t.length < 2) { sugg.hidden = true; return; }
    const hits = D.skaters.filter((s) => s.name.toLowerCase().includes(t)).map((s) => ({ ...s, kind: "players" }))
      .concat((D.goalies || []).filter((g) => (g.name || "").toLowerCase().includes(t)).map((g) => ({ ...g, kind: "goalie" }))).slice(0, 8);
    sugg.innerHTML = hits.map((s) => `<li><button type="button" data-go="${s.kind}/${s.id}">${esc(s.name)} <span class="dim">${s.team}${s.kind === "goalie" ? ", G" : ""}</span></button></li>`).join("") || `<li><button type="button" disabled>No player by that name has played this season</button></li>`;
    sugg.hidden = false;
    $$("[data-go]", sugg).forEach((b) => b.addEventListener("click", () => (location.hash = "#" + b.dataset.go)));
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") $("[data-go]", sugg)?.click(); });
}
const searchBox = (ph = "Search any skater or goalie") => `<div class="controls"><input type="search" id="pq" placeholder="${ph}" aria-label="${ph}" autocomplete="off"></div>
      <ul class="suggest" id="sugg" hidden></ul>`;

// Players landing: search, the players you follow, league leaders, and the full skater table
function renderPlayersHome(view) {
  const fl = follows.list(), props = Object.fromEntries((D.tonight.props || []).map((x) => [x.id, x]));
  const gl = Object.fromEntries((D.goalies || []).map((g) => [g.id, g]));
  const sk = Object.fromEntries(D.skaters.map((x) => [x.id, x]));
  const followCard = (f) => {
    const x = f.kind === "goalie" ? gl[f.id] : sk[f.id], tn = props[f.id];
    const href = f.kind === "goalie" ? `#goalie/${f.id}` : `#players/${f.id}`;
    const line = !x ? "No games this season" : f.kind === "goalie" ? `${x.gp} GP, ${pct(x.sv_pct, 1)}, ${signed(x.gsax)} saved above expected` : `${x.g} G, ${x.a} A in ${x.gp} GP`;
    return `<a class="fcard" href="${href}"><b>${esc(f.name)}</b> <span class="dim">${esc(x?.team || f.team || "")}</span><span>${line}</span>
      ${tn ? `<span class="fc-tonight">Tonight vs ${tn.opp}: ${pct(tn.p_goal)} to score</span>` : ""}</a>`;
  };
  const min = Math.max(1, Math.round((D.meta.games_played || 0) / 32 * 0.4));   // about 40% of team games
  const qual = D.skaters.filter((x) => x.gp >= min);
  const board = (title, rows, val, note) => `<div class="board"><h3>${title}</h3><ol>${rows.map((r) => `<li>${playerLink(r.id, r.name)} <span class="dim">${r.team}</span><b>${val(r)}</b></li>`).join("")}</ol>${note ? `<p class="note">${note}</p>` : ""}</div>`;
  const top = (arr, k, n = 5, dir = -1) => [...arr].filter((x) => x[k] != null).sort((a, b) => (a[k] - b[k]) * dir).slice(0, n);
  const goalies = (D.goalies || []).filter((g) => g.sa >= 60).sort((a, b) => b.gsax - a.gsax).slice(0, 5);
  view.innerHTML = `<section class="zone">
      <h1>Players</h1>
      <p class="lede">Every skater and goalie in the league: shot maps, game logs, how they're used, how they defend and what they're worth. Search for anyone, or start with the leaders.</p>
      ${searchBox()}
    </section>
    <section class="zone"><h2>Players you follow</h2>
      ${fl.length ? `<div class="fgrid">${fl.map(followCard).join("")}</div>` : `<p class="lede">Tap <b>Follow</b> on any player's page and they'll show up here, with tonight's numbers when they play. You can also filter Tonight's table to them. Saved in this browser only.</p>`}
    </section>
    <section class="zone"><h2>Leaders</h2>
      <div class="boards">
        ${board("Points", top(D.skaters, "pts"), (r) => r.pts)}
        ${board("Goals", top(D.skaters, "g"), (r) => r.g)}
        ${board("Most dangerous shooters", top(D.skaters, "ixg"), (r) => num(r.ixg, 1), "Expected goals from their own shots: the quality and number of their chances.")}
        ${board("Due for more goals", top(qual, "g_minus_xg", 5, 1), (r) => signed(r.g_minus_xg), "Goals minus expected goals. The chances are there; the goals usually follow.")}
        ${board("Goalies", goalies, (r) => signed(r.gsax), "Goals saved above what an average goalie would allow on the same shots.")}
      </div>
    </section>
    <section class="zone"><h2>Every skater</h2>
      <div class="controls">
        <div class="chips" role="group" aria-label="Position">${["all", "F", "D"].map((x) => `<button type="button" class="chip" data-ppos="${x}" aria-pressed="${S.pPos === x}">${x === "all" ? "All" : x === "F" ? "Forwards" : "Defense"}</button>`).join("")}</div>
        <select id="pTeam" aria-label="Team"><option value="all">All teams</option>${D.teams.map((t) => t.team).sort().map((a) => `<option value="${a}" ${S.pTeam === a ? "selected" : ""}>${esc(teamName(a))}</option>`).join("")}</select>
        <label class="check">Min games <input type="text" id="pMin" value="${S.pMin}" style="width:48px" inputmode="numeric"></label>
      </div>
      <div id="allSk"></div><div class="controls" style="margin-top:10px"><button type="button" class="chip" id="more">Show more</button></div>
    </section>`;
  const draw = () => {
    let rows = D.skaters.filter((x) => x.gp >= S.pMin && (S.pPos === "all" || x.pos === S.pPos) && (S.pTeam === "all" || x.team === S.pTeam));
    rows = sortRows(rows, S.pSort).slice(0, S.pLimit);
    const cols = skaterCols(); cols.splice(1, 0, { key: "team", label: "Team" });
    $("#allSk").innerHTML = table(rows, cols, S.pSort, "allsk");
    bindSort($("#allSk"), S.pSort, draw);
  };
  draw();
  $("#more").addEventListener("click", () => { S.pLimit += 100; draw(); });
  $$("[data-ppos]", view).forEach((b) => b.addEventListener("click", () => { S.pPos = b.dataset.ppos; $$("[data-ppos]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); }));
  $("#pTeam").addEventListener("change", (e) => { S.pTeam = e.target.value; draw(); });
  $("#pMin").addEventListener("input", (e) => { S.pMin = +e.target.value || 0; draw(); });
  bindPlayerSearch(view);
}
function renderPlayers(view, param) {
  if (!param) return renderPlayersHome(view);
  const p = D.skaters.find((s) => s.id === +param);
  if (!p) {
    if ((D.goalies || []).some((g) => g.id === +param)) { location.replace("#goalie/" + param); return; }
    view.innerHTML = `<section class="zone"><p class="crumbs"><a href="#players">Players</a></p><h1>Player not found</h1><p class="lede">He hasn't played an NHL game this season. Try the search on the <a href="#players">Players</a> page.</p></section>`;
    return;
  }
  const shots = D.shots[p.id] || [];
  const tile = (v, label, sub) => `<div class="stat"><b>${v}</b><span>${label}</span>${sub ? `<small>${sub}</small>` : ""}</div>`;
  const meter = (label, pctl, val) => pctl == null ? "" : `<div class="meter"><span>${label}</span><span class="bar-track" data-tip="${esc(`${Math.round(100 * pctl)}th percentile in the league`)}"><span class="bar-fill" style="width:${100 * pctl}%"></span></span><span class="val">${val}</span></div>`;
  const last = p.p_gp ? `Last season${p.p_team && p.p_team !== p.team ? ` with ${p.p_team}` : ""}: ${p.p_g} G, ${p.p_pts} P in ${p.p_gp} GP` : "No NHL games last season";
  view.innerHTML = `
    <section class="zone">
      <p class="crumbs"><a href="#players">Players</a></p>
      ${searchBox()}
      <div class="phead">
        <div class="ph-photo"><img src="https://assets.nhle.com/mugs/nhl/${esc(D.meta.season)}/${esc(p.team)}/${p.id}.png" alt="" width="128" height="128"
          onerror="this.parentNode.classList.add('ph-none'); this.remove()">${p.num != null ? `<span class="ph-num">${p.num}</span>` : ""}</div>
        <div class="ph-text"><h1>${esc(p.name)}</h1>
          <div class="meta"><a href="#teams/${p.team}">${esc(teamName(p.team))}</a>, ${p.pos === "D" ? "defense" : "forward"}, ${p.gp} games, ${num(p.toi_pg, 1)} minutes a night</div>
          ${followBtn({ id: p.id, kind: "skater", name: p.name, team: p.team })}</div>
        <div class="meta ph-bio" id="pBio"></div></div>
      <div class="stat-row">
        ${tile(p.g, "Goals", `${num(p.ixg, 1)} expected`)}${tile(p.a, "Assists")}${tile(p.pts, "Points", `${p.ppp} on the power play`)}
        ${tile(signed(p.g_minus_xg), "Goals vs chances", p.g_minus_xg >= 0 ? "scoring above" : "scoring below")}
        ${tile(p.xgf5 == null ? "–" : pct(p.xgf5 / 100), "5v5 xG share", p.rel5 == null ? "" : `${signed(p.rel5, 0)} vs without him`)}
        ${tile(p.sog, "Shots", `${p.hits} hits, ${p.blk} blocks`)}
      </div>
      <p class="verdict">${esc(verdictFor(p))}</p>
      <div id="pStory"></div>
    </section>
    <section class="zone grid-2 grid-top">
      <div class="figure"><h3>Shot map</h3><p class="note">${shots.length} unblocked shots this season. Bigger dots were better chances; red went in. Tap one for the details.</p>
        ${shotMap(rinkSVG(shots, { label: `${p.name} shot map` }), shots, { kind: "player", id: p.id, name: p.name })}
        <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      <div>
        <h3>What we expect from him</h3>
        <p class="note">${esc(last)}.</p>
        ${meter("Our estimate", Math.min(1, (p.m_ixg60 || 0) / 1.6), `${num(p.m_ixg60, 2)} xG/60`)}
        ${meter("This season", Math.min(1, (p.ixg60 || 0) / 1.6), `${num(p.ixg60, 2)} xG/60`)}
        ${meter("Last season", p.p_ixg60 == null ? null : Math.min(1, p.p_ixg60 / 1.6), `${num(p.p_ixg60, 2)} xG/60`)}
        <p class="note">Expected goals from his own shots per 60 minutes. Our estimate is what tonight's odds use: this season's rate, pulled toward last season and his role, because a few weeks of games is too few to trust on their own.</p>
        <h3 style="margin-top:22px">Skating and shooting, tracked</h3>
        ${p.max_speed_pctile == null ? `<p class="note">No NHL Edge tracking for him yet.</p>` : `
          ${meter("Top speed", p.max_speed_pctile, `${num(p.max_speed_mph, 1)} mph`)}
          ${meter("20+ mph bursts", p.bursts_pctile, `${p.bursts_20mph}`)}
          ${meter("Hardest shot", p.top_shot_pctile, `${num(p.top_shot_mph, 1)} mph`)}
          ${meter("Distance skated", p.distance_pctile, `${Math.round(100 * p.distance_pctile)}th pct`)}
          <p class="note">From the NHL's player tracking (EDGE). Bars show his percentile among all NHL skaters this season.</p>`}
        <div id="pEdge"></div>
      </div>
    </section>
    <section class="zone plays" id="pValue" hidden></section>
    <section class="zone plays" id="pDef" hidden></section>
    <section class="zone plays" id="pPlays" hidden></section>
    <section class="zone" id="pReel" hidden></section>
    <section class="zone"><h2>Game by game</h2><p class="lede">Every game this season, newest first. xG is the expected goals from his own shots; on-ice xG ± is chances for minus chances against while he was on the ice. Tap a game to open it.</p>
      <div id="pLog"><p class="note">Loading his games…</p></div></section>
    <div id="pMedia"></div>`;

  const here = location.hash;
  getJSON(`data/players/${p.id}.json`).then((file) => {
    if (location.hash !== here || !$("#pLog")) return;
    const rows = Array.isArray(file) ? file : file.log || [], ed = Array.isArray(file) ? null : file.edge;
    if (ed && $("#pEdge")) $("#pEdge").innerHTML = edgeBlock(ed, rows);
    if (!Array.isArray(file) && file.story && $("#pBio")) $("#pBio").innerHTML = playerBio(file.story);
    if (!Array.isArray(file) && file.eh && $("#pValue")) renderValue($("#pValue"), file.eh, p.id).catch(() => {});
    if (!Array.isArray(file) && file.defense && $("#pDef")) renderDefense($("#pDef"), { ...file.defense, name: p.name }, p.id, { eh: file.eh, a3z: file.a3z }).catch(() => {});
    if (!Array.isArray(file) && file.a3z && $("#pPlays")) renderPlays($("#pPlays"), file.a3z, p.id, p.name).catch(() => {});
    if ($("#pReel")) renderReel($("#pReel"), Array.isArray(file) ? [] : file.reel, rows, p.name).catch(() => {});
    if (!Array.isArray(file) && file.story && $("#pStory")) $("#pStory").innerHTML = playerStory(file.story);
    getJSON("data/features.json").then((fs) => {   // a deep dive on him, if there is one
      const f = (fs || []).find((x) => x.kind === "player" && x.subject && x.subject.id === p.id);
      if (f && location.hash === here && $("#pStory")) $("#pStory").insertAdjacentHTML("beforeend", featureLink(f));
    }).catch(() => {});
    const anyMiles = rows.some((x) => x.miles != null), anyMph = rows.some((x) => x.mph);
    const res = (x) => `<b class="res res-${x.res}">${x.res}</b>`;
    $("#pLog").innerHTML = rows.length ? table([...rows].reverse().map((x) => ({ ...x, pm: (x.xgf ?? 0) - (x.xga ?? 0), pts: x.g + x.a })), [
      { key: "date", label: "Game", nosort: true, fmt: (x) => `<a href="#game/${x.id}">${shortDate(x.date)} ${x.home ? "vs" : "@"} ${x.opp}</a>` },
      { key: "res", label: "Result", nosort: true, fmt: (x) => `${res(x)} <span class="sub">${x.gf}-${x.ga}</span>` },
      { key: "toi", label: "TOI", nosort: true, fmt: (x) => num(x.toi, 1) },
      { key: "g", label: "G", nosort: true }, { key: "a", label: "A", nosort: true },
      { key: "sog", label: "Shots", nosort: true },
      { key: "ixg", label: "xG", nosort: true, fmt: (x) => num(x.ixg, 2) },
      { key: "pm", label: "On-ice xG ±", nosort: true, fmt: (x) => divCell(x.pm, 1.5, 2), cls: "hide-sm" },
      ...(anyMiles ? [{ key: "miles", label: "Miles", nosort: true, fmt: (x) => (x.miles == null ? `<span class="dim">–</span>` : num(x.miles, 2)), cls: "hide-sm" }] : []),
      ...(anyMph ? [{ key: "mph", label: "Top shot", nosort: true, fmt: (x) => (x.mph ? `${num(x.mph, 1)}` : `<span class="dim">–</span>`), cls: "hide-sm" }] : []),
    ], null, "plog") + (anyMiles || anyMph ? `<p class="note hide-sm">Miles skated and shot speeds are NHL EDGE tracking. The public feed only covers each player's last ten games and his ten hardest shots, so earlier games and slower shots show a dash.</p>` : "")
      : `<p class="note">No games yet this season.</p>`;
  }).catch(() => { const el = $("#pLog"); if (el) el.innerHTML = `<p class="note">Game log unavailable.</p>`; });
  relatedMedia(null, p.id, `${p.name} in the news`).then((r) => {
    const el = $("#pMedia");
    if (location.hash !== here || !el) return;
    el.outerHTML = r ? r.html : "";
    const blk = view.querySelector(".media-block"); if (r && blk) bindMedia(blk, r.listen);
  }).catch(() => {});
  bindPlayerSearch(view);
}

// ------------------------------------------------------------------ FANTASY
// My team is published encrypted (see write_fantasy in build.py). The password never leaves the browser:
// it derives the AES key with PBKDF2, and only that key is remembered on this device after a successful unlock.
const FKEY = "ice-fantasy-key";
const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const b64e = (u8) => btoa(String.fromCharCode(...new Uint8Array(u8)));
async function fantasyKeyFromPassword(pw, L) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: b64d(L.salt), iterations: L.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
}
async function fantasyOpen(key, L) {
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(L.iv) }, key, b64d(L.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
function showFantasyTab(on) {
  const a = $('.tabs a[data-tab="fantasy"]');
  if (a) a.hidden = !on;
}
async function renderFantasy(view) {
  view.innerHTML = `<p class="empty">Opening…</p>`;
  let L;
  try { L = await getJSON("data/fantasy.lock.json"); } catch (e) {
    view.innerHTML = `<section class="zone"><h1>Nothing here</h1><p class="lede">This page isn't published. <a href="#tonight">Back to tonight</a>.</p></section>`;
    return;
  }
  if (!(window.crypto && crypto.subtle)) { view.innerHTML = `<p class="empty">This browser can't unlock the page.</p>`; return; }
  const saved = store.get(FKEY);
  if (saved) {
    try {
      const key = await crypto.subtle.importKey("raw", b64d(saved), "AES-GCM", false, ["decrypt"]);
      drawFantasy(view, await fantasyOpen(key, L));
      showFantasyTab(true);
      return;
    } catch (e) { store.set(FKEY, ""); }   // password changed since this device unlocked
  }
  showFantasyTab(false);
  view.innerHTML = `<section class="zone lock">
      <h1>Private</h1>
      <p class="lede">This page is locked. Enter the password to open it on this device.</p>
      <form class="controls" id="unlock" autocomplete="off">
        <input type="password" id="fpw" aria-label="Password" placeholder="Password" autocomplete="current-password" required>
        <button type="submit" class="chip chip-solid">Unlock</button>
      </form>
      <p class="note" id="fmsg" role="status"></p>
    </section>`;
  $("#unlock").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("#fmsg");
    msg.textContent = "Checking…";
    try {
      const key = await fantasyKeyFromPassword($("#fpw").value, L);
      const F = await fantasyOpen(key, L);
      store.set(FKEY, b64e(await crypto.subtle.exportKey("raw", key)));
      showFantasyTab(true);
      drawFantasy(view, F);
    } catch (e) {
      msg.textContent = "That password didn't work.";
      $("#fpw").select();
    }
  });
  $("#fpw").focus();
}

function drawFantasy(view, F) {
  const today = D.tonight.date;
  const props = Object.fromEntries((D.tonight.props || []).map((p) => [p.id, p]));
  const sk = Object.fromEntries(D.skaters.map((s) => [s.id, s]));
  const days = F.days, wk = days.slice(0, 7);
  const rows = F.roster.map((r) => {
    const s = sk[r.id] || {};
    return { ...r, gp: s.gp, pts: s.pts, g: s.g, ixg: s.ixg, gmx: s.g_minus_xg, luck: s.oi_luck, rel5: s.rel5,
             games7: wk.filter((d) => r.sched[d]).length, tonight: props[r.id]?.p_goal };
  });
  const perDay = days.map((d) => rows.filter((r) => r.slot !== "G" && r.sched[d]).length);
  const head = `<tr><th class="nosort">Player</th>${days.map((d) => `<th class="nosort ${d === today ? "today" : ""}">${dateLabel(d)}</th>`).join("")}<th class="nosort">Next 7</th></tr>`;
  const body = rows.map((r) => `<tr><td><span class="slot">${r.slot}</span>${playerLink(r.id, r.name || "")}<span class="sub">${r.team || ""}</span>${injuryTag(r.name)}</td>
     ${days.map((d) => `<td class="${r.sched[d] ? "game-day" : "off"} ${d === today ? "today" : ""}">${r.sched[d] ? esc(r.sched[d]) : "·"}</td>`).join("")}<td>${r.games7}</td></tr>`).join("");
  const foot = `<tr><td><b>Skaters playing</b></td>${perDay.map((n, i) => `<td class="${days[i] === today ? "today" : ""}"><b>${n}</b></td>`).join("")}<td></td></tr>`;
  const sells = rows.filter((r) => r.slot !== "G" && ((r.gmx ?? 0) >= 2 || (r.luck ?? 0) >= 4));
  const buys = rows.filter((r) => r.slot !== "G" && (r.gmx ?? 0) <= -1.2);
  const flag = (r, why) => `<li>${playerLink(r.id, r.name)}: ${why}</li>`;
  view.innerHTML = `
    <section class="zone">
      <h1>${esc(F.team_name)}</h1>
      <p class="lede">${esc(F.league)} roster, the next ten days of games, and who's running lucky. The bottom row counts how many of your skaters play each day, so days with more games than lineup spots are where bench players need to slide in.</p>
      <div class="table-wrap"><table class="sched"><thead>${head}</thead><tbody>${body}${foot}</tbody></table></div>
    </section>
    <section class="zone grid-2">
      <div><h3>Running hot, sell before it cools</h3>
        ${sells.length ? `<ul>${sells.map((r) => flag(r, `${signed(r.gmx)} goals vs chances, on-ice luck ${signed(r.luck)}`)).join("")}</ul>` : `<p class="note">Nobody on your roster is far above their underlying numbers.</p>`}</div>
      <div><h3>Due for goals, hold or buy</h3>
        ${buys.length ? `<ul>${buys.map((r) => flag(r, `${r.g} goals on ${num(r.ixg, 1)} expected`)).join("")}</ul>` : `<p class="note">Nobody is far below their chances yet.</p>`}</div>
    </section>
    <section class="zone"><h2>Tonight's odds for your guys</h2>
      ${(() => { const t = rows.filter((r) => r.tonight != null).sort((a, b) => b.tonight - a.tonight);
        return t.length ? table(t, [
          { key: "name", label: "Player", nosort: true, fmt: (r) => playerLink(r.id, r.name) },
          { key: "slot", label: "Slot", nosort: true },
          { key: "tonight", label: "Goal chance", nosort: true, fmt: (r) => cellBar(r.tonight, 0.5) },
          { key: "p2", label: "2+ points", nosort: true, fmt: (r) => cellBar(props[r.id].p_2pts, 0.5) },
        ], null, "ft") : `<p class="note">None of your players are in tonight's games.</p>`; })()}
      <p class="note">Unlocked on this device. <button type="button" class="linkish" id="relock">Lock it again</button></p>
    </section>`;
  $("#relock").addEventListener("click", () => { store.set(FKEY, ""); showFantasyTab(false); location.hash = "#tonight"; });
}

// ------------------------------------------------------------------ MODEL
// The prices this site actually showed, frozen at puck drop and graded the next morning (analysis/track.py).
// Unlike the backtest, these had to guess lineups and goalies.
function liveRecord(L) {
  const head = `<h2>Live record</h2>`;
  if (!L || !L.nights) return `<section class="zone">${head}<p class="lede">Since October 16, every number on the Tonight page is saved at puck drop, along with the lineups and goalies we expected, and graded here the next morning. The season replay above knew the real lineups and starting goalies; this record doesn't, so it's the tougher test.</p></section>`;
  const pc = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "–");
  const lu = L.lineup, small = L.nights < 14;
  return `<section class="zone">${head}
    <p class="lede">Every number on the Tonight page is saved at puck drop, with the lineups and goalies we expected, and graded the next morning. So far: ${L.nights} night${L.nights === 1 ? "" : "s"} (${shortDate(L.first)} to ${shortDate(L.last)}), ${L.games} games, ${L.player_games.toLocaleString()} player-games.${small ? " That's a small sample: one hot night swings these numbers." : ""}</p>
    <div class="grid-3">
      <div><div class="bignum">${L.goal.pred.toFixed(0)} <span class="dim">vs</span> ${L.goal.act}</div><p>goal scorers predicted vs actual. We beat a simple baseline (league scoring rates times ice time) on ${L.goal.nights_beat} of ${L.nights} nights. Error score (log loss, lower is better): ${L.goal.ll.toFixed(4)} vs ${L.goal.ll_base.toFixed(4)}.</p></div>
      <div><div class="bignum">${pc(lu.last.dressed, lu.last.priced)}</div><p>of players from each team's last lineup dressed. Of the ones tagged as missing the last game, ${pc(lu.recent.dressed, lu.recent.priced)} played${lu.returning.priced ? `; of those coming back, ${pc(lu.returning.dressed, lu.returning.priced)}` : ""}. ${lu.unpriced} dressed without a projection.</p></div>
      <div><div class="bignum">${pc(L.goalies.hits, L.goalies.n)}</div><p>of starting goalies called right (${L.goalies.espn_n ? `${pc(L.goalies.espn_hits, L.goalies.espn_n)} when ESPN had posted a probable starter` : "no ESPN probables yet"}).</p></div>
    </div>
    <p class="note">Two or more points: ${L.pts.pred.toFixed(0)} predicted, ${L.pts.act} actual.${L.pts1 ? ` One or more: ${L.pts1.pred.toFixed(0)} predicted, ${L.pts1.act} actual. Three or more: ${L.pts3.pred.toFixed(0)} predicted, ${L.pts3.act} actual.` : ""}${L.sog ? ` Shots on goal (tracked since Oct 18): ${L.sog.exp.toFixed(0)} expected, ${L.sog.act} taken; two or more ${L.sog.p2.toFixed(0)} predicted, ${L.sog.act2} actual; three or more ${L.sog.p3.toFixed(0)} predicted, ${L.sog.act3} actual.` : ""} Game totals missed by ${L.totals.mae} goals on average (projected ${L.totals.mean_pred}, actual ${L.totals.mean_act}).</p>
    ${L.sleepers ? `<p class="note"><b>Sleepers</b> (since Oct 20)${L.sleepers.depth ? `: depth scorers ${L.sleepers.depth.act} goals from ${L.sleepers.depth.n} picks, ${L.sleepers.depth.pred.toFixed(1)} expected` : ""}${L.sleepers.point ? `${L.sleepers.depth ? ";" : ":"} underrated point picks ${L.sleepers.point.act} of ${L.sleepers.point.n} got a point, ${L.sleepers.point.pred.toFixed(1)} expected` : ""}. Long shots by design; the honest test is whether hits keep pace with what we said.</p>` : ""}
    ${L.market && L.market.games ? `<p class="note"><b>Against the sportsbook</b> (DraftKings game lines published by the NHL, ${L.market.games} games): totals missed by ${L.market.total_mae_model} goals for us vs ${L.market.total_mae_market} for the book; over/under log loss ${L.market.over_ll_model.toFixed(3)} vs ${L.market.over_ll_market.toFixed(3)}; winner Brier score ${L.market.win_brier_model.toFixed(3)} vs ${L.market.win_brier_market.toFixed(3)}. Lower is better on all three; the sportsbook is the bar to clear.</p>` : ""}
  </section>`;
}
function renderModel(view) {
  const M = D.model, ts = M.this_season;
  view.innerHTML = `
    <section class="zone">
      <h1>Can you trust these numbers?</h1>
      <p class="lede">We'd rather show you than tell you. We replayed all of ${esc(M.season)} the honest way, predicting each night using only the games played before it, and checked every prediction against what happened. Since this season began we also grade everything we publish, the morning after.</p>
      <div class="grid-3">
        <div><div class="bignum">${M.goal.pred.toLocaleString()}</div><p>goal scorers predicted across ${M.player_games.toLocaleString()} player-games. ${M.goal.act.toLocaleString()} actually scored.</p></div>
        <div><div class="bignum">${M.pts.pred.toLocaleString()}</div><p>two-point games predicted. ${M.pts.act.toLocaleString()} actually happened.</p></div>
        <div><div class="bignum">${M.totals.corr.toFixed(2)}</div><p>correlation between our projected game totals and the actual totals over ${M.games.toLocaleString()} games. That's close to no signal, so we show totals as context, not as a prediction.</p></div>
      </div>
    </section>
    ${liveRecord(M.live)}
    <section class="zone grid-2">
      <div class="figure narrow"><h3>Goal chances</h3><p class="note">Each dot groups player-games by the chance we gave. On the diagonal means that when we said 20%, it happened about 20% of the time. Bigger dots hold more games.</p>${calibrationChart(M.goal.cal, "Goal probability calibration")}</div>
      <div class="figure narrow"><h3>Two or more points</h3><p class="note">Same check for multi-point games.</p>${calibrationChart(M.pts.cal, "Two point probability calibration")}</div>
    </section>
    <section class="zone">
      <h2>What this does and doesn't prove</h2>
      <p class="lede">Our player numbers beat a simple baseline (league scoring rates times ice time) in every month of last season, and they're well calibrated. That's the floor, not the finish line. Sportsbooks are much sharper than a baseline, and the free odds we can check against cover game lines only, not player markets. Read our numbers as an honest starting point and compare them with the price you're offered.</p>
      ${ts ? `<p class="lede">This season so far: ${ts.goal_pred} scorers predicted and ${ts.goal_actual} actual across ${ts.player_games.toLocaleString()} player-games.</p>` : ""}
    </section>`;
}

// ------------------------------------------------------------------ router
const ROUTES = { tonight: renderTonight, games: renderGames, game: renderGame, preview: renderPreview, goals: renderGoals, live: renderLive, news: renderNews, feature: renderFeature, pulse: renderPulse, league: renderLeague,
  teams: renderTeams, players: renderPlayers, goalie: renderGoalie, fantasy: renderFantasy, model: renderModel, about: renderAbout };
const TAB_OF = { game: "games", goals: "games", preview: "tonight", live: "tonight", feature: "news", goalie: "players" };
function route(e) {
  const rerender = e === "resize";
  const keepY = scrollY;
  const [tab, param] = (location.hash.slice(1) || "tonight").split("/");
  const fn = ROUTES[tab] || renderTonight;
  const active = TAB_OF[tab] || (ROUTES[tab] ? tab : "tonight");
  $$(".tabs a").forEach((a) => (a.dataset.tab === active ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const view = $("#view");
  view.onclick = view.onkeydown = view.onchange = null;   // pages that delegate events set these; start clean
  const p = fn(view, param);
  if (p && p.catch) p.catch((e) => (view.innerHTML = `<p class="empty">This page didn't load (${esc(e.message)}). Reload to try again.</p>`));
  tip.hidden = true;
  if (rerender) {
    // Same page at a new width: put the reader back where they were once the async render settles.
    Promise.resolve(p).then(() => requestAnimationFrame(() => scrollTo(0, keepY)));
  } else if (tab === "about" && param) requestAnimationFrame(() => document.getElementById("about-" + param)?.scrollIntoView());
  else scrollTo(0, 0);   // a new page starts at the top
}

function applyThemeLabel() {
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#themeToggle").textContent = dark ? "Light" : "Dark";
}
$("#themeToggle").addEventListener("click", () => {
  const dark = $("#themeToggle").textContent === "Dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  store.set("ice-theme", dark ? "dark" : "light");
  applyThemeLabel();
});

// Charts are drawn at the container's width, so redraw when the WIDTH changes (rotation, desktop window resize).
// Phone browsers fire "resize" whenever the address bar slides in or out while scrolling; that only changes
// the height, and redrawing on it is what kept throwing phones back to the top of the page.
let rz, lastW = innerWidth;
addEventListener("resize", () => {
  clearTimeout(rz);
  rz = setTimeout(() => {
    if (innerWidth === lastW || !D.meta || document.activeElement?.matches("input,select")) return;
    lastW = innerWidth;
    route("resize");
  }, 250);
});
async function boot() {
  applyThemeLabel();
  const files = ["meta", "teams", "goalies", "skaters", "shots", "tonight", "model"];
  try {
    const got = await Promise.all(files.map((f) => fetch(`data/${f}.json`, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(f); return r.json(); })));
    files.forEach((f, i) => (D[f] = got[i]));
  } catch (e) {
    $("#view").innerHTML = `<p class="empty">We couldn't load today's data (${esc(e.message)}). We may be mid-update; try again in a few minutes.</p>`;
    return;
  }
  try { S.goalies = JSON.parse(store.get("goalies:" + D.tonight.date) || "{}"); } catch (e) { S.goalies = {}; }
  const up = D.meta.updated_utc ? new Date(D.meta.updated_utc) : null;
  const upTxt = up && !isNaN(up) ? up.toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short" }) : `${D.meta.updated} MT`;
  $("#freshness").textContent = `Updated ${upTxt} · results through ${dateLabel(D.meta.last_game)}`;
  applyTeamButton();
  $("#teamBtn").addEventListener("click", () => openTeamPicker());
  showFantasyTab(!!store.get(FKEY));
  addEventListener("hashchange", route);
  route();
  liveStart();      // ESPN scoreboard: live scores and probable goalies
  liveInjuries();   // ESPN injury report: flags on the odds
}
boot();
