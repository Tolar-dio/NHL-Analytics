/* Ice Sheet front end. Plain JS, no build step. Data comes from data/*.json,
   rebuilt every morning by site/build.py. */
"use strict";

const D = {};                       // loaded data
const S = {                         // UI state
  game: null, pos: "all", q: "", radar: false, mkt: "p_goal", sort: { key: "p_goal", dir: -1 },
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
const timeMT = (utc) => (utc ? new Date(utc).toLocaleTimeString("en-US", { timeZone: "America/Denver", hour: "numeric", minute: "2-digit" }) + " MT" : "");

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

function divergingBars(rows, valueKey, labelFn, tipFn) {
  const W = mainW(900), rowH = 24, m = { l: W < 500 ? 150 : 200, r: 44, t: 6 }, H = m.t + rows.length * rowH + 22;
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r[valueKey])), 1);
  const X = (v) => m.l + ((v + maxAbs) / (2 * maxAbs)) * (W - m.l - m.r);
  const bars = rows.map((r, i) => {
    const v = r[valueKey], y = m.t + i * rowH, x0 = X(0), x1 = X(v);
    const left = Math.min(x0, x1), w = Math.max(Math.abs(x1 - x0), 1.5);
    const col = v >= 0 ? "var(--blue)" : "var(--red)";
    const rx = Math.min(4, w / 2);
    return `<g data-tip="${esc(tipFn(r))}"><rect x="0" y="${y}" width="${W}" height="${rowH}" fill="transparent"/>
      <text x="${m.l - 8}" y="${y + 15}" text-anchor="end" class="lbl">${esc(W < 500 ? labelFn(r).replace(/^(\S)\S*\s/, "$1. ") : labelFn(r))}</text>
      <rect x="${left}" y="${y + 5}" width="${w}" height="12" rx="${rx}" fill="${col}"/>
      <text x="${v >= 0 ? x1 + 6 : x1 - 6}" y="${y + 15}" text-anchor="${v >= 0 ? "start" : "end"}">${signed(v)}</text></g>`;
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
  const pts = cal.map((c) => `<g data-tip="${esc(`Model said ${pct(c.pred, 1)}, it happened ${pct(c.act, 1)}<br>${c.n.toLocaleString()} player-games`)}">
    <circle cx="${X(c.pred)}" cy="${Y(c.act)}" r="${4 + 6 * Math.sqrt(c.n / nMax)}" fill="var(--blue)" stroke="var(--sheet)" stroke-width="2"/></g>`);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${grid.join("")}
    <line class="axis" x1="${X(0)}" y1="${Y(0)}" x2="${X(top)}" y2="${Y(top)}"/>
    ${pts.join("")}
    <text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle">What the model said</text>
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
const MARKETS = [["p_goal", "Goal"], ["p_1pt", "1+ points"], ["p_2pts", "2+ points"], ["p_3pts", "3+ points"]];
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
    return { ...p, p_goal: nbTail(lg, dp.g, 1), p_1pt: nbTail(lp, dp.p, 1), p_2pts: nbTail(lp, dp.p, 2), p_3pts: nbTail(lp, dp.p, 3) };
  });
}

// the model's game numbers next to DraftKings' (published free by the NHL), so totals are read against the
// market, not a league average: the model's totals have never beaten either
function marketLine(g) {
  const m = g.market, mine = `Model: ${g.home} ${pct(winHome(g))}, total ${g.total.toFixed(1)}`;
  if (!m || m.total == null) return `<div class="game-foot" data-tip="${esc("Game totals did not beat a league-average guess in testing. Context only.")}">${mine}. No market line yet. Context, not a pick.</div>`;
  const ml = (o) => (o > 0 ? `+${o}` : `${o}`);
  const tip = `<b>DraftKings, via the NHL</b><br>${g.away} ${ml(m.ml_away)}, ${g.home} ${ml(m.ml_home)} (${pct(m.p_home)} ${g.home} once the margin is removed)<br>Over/under ${m.total}: over ${ml(m.over)}, under ${ml(m.under)}; the over price implies about ${num(m.implied_total, 1)} goals<br><span class="dim">The model's totals haven't beaten the market or a league average in testing.</span>`;
  return `<div class="game-foot mkt" data-tip="${esc(tip)}"><span><b>Market</b> ${g.home} ${pct(m.p_home)}, O/U ${m.total}</span><span class="dim">${mine}</span></div>`;
}
function winHome(g) {
  const a = poisPmf(g.away_xg, 15), h = poisPmf(g.home_xg, 15);
  let w = 0, t = 0;
  a.forEach((pa, i) => h.forEach((ph, j) => { if (j > i) w += pa * ph; else if (i === j) t += pa * ph; }));
  return w + t / 2;
}
function renderTonight(view) {
  const T = D.tonight;
  if (!T.games.length) {
    view.innerHTML = `<section class="zone"><h1>No games on ${esc(T.date)}</h1><p class="lede">The next slate shows up here the morning of game day.</p></section>`;
    return;
  }
  const games = T.games.map(liveGame);
  const maxXg = Math.max(...games.flatMap((g) => [g.away_xg, g.home_xg]), 3.5);
  const gameCard = (g) => {
    const side = (abbr, xg, key) => {
      const opts = g[key + "_goalies"] || [], chosen = goalieFor(g, key);
      return `<div class="side"><span class="abbr">${abbr}${g[key + "_b2b"] ? `<span class="tag tag-b2b" data-tip="${esc("Second night of a back-to-back. Tired teams averaged 47.4% of the expected goals in 2025-26 (286 games).")}">B2B</span>` : ""}</span>
        <span class="bar-track" data-tip="${esc(`${abbr} expected goals tonight: ${xg.toFixed(2)}`)}"><span class="bar-fill" style="width:${(100 * xg) / maxXg}%"></span></span>
        <span class="xg">${xg.toFixed(2)}</span></div>
        <label class="goalie"><select data-game="${g.id}" data-side="${key}" aria-label="${abbr} goalie">
          ${opts.map((o) => `<option value="${o.id}" ${o.id === chosen.id ? "selected" : ""}>${esc(o.name)} (${o.starts} start${o.starts === 1 ? "" : "s"})</option>`).join("")}
        </select><span class="g-src">${esc(goalieSource(g, key))}</span></label>`;
    };
    return `<article class="game ${S.game === g.id ? "is-picked" : ""}">
      <div class="game-time"><span>${timeMT(g.start)}</span><span class="row" style="gap:12px"><a class="preview-link" href="#preview/${g.id}">Preview</a><button type="button" data-pick="${g.id}">${S.game === g.id ? "Show all games" : "Only this game"}</button></span></div>
      ${side(g.away, g.away_xg, "away")}${side(g.home, g.home_xg, "home")}
      ${marketLine(g)}
      <div class="live-line" data-live="${g.id}"></div>
    </article>`;
  };
  view.innerHTML = `
    <section class="zone">
      <h1>${esc(new Date(T.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }))}: ${games.length} game${games.length === 1 ? "" : "s"}</h1>
      <p class="lede">Bars show each team's expected goals tonight. Goalies follow ESPN's probable starters once they're posted (recent starts until then); switch any of them and every number on this page updates. Live scores update every 30 seconds.</p>
      <div class="slate">${games.map(gameCard).join("")}</div>
    </section>
    <section class="zone">
      <h2>Who scores, who stacks points</h2>
      <p class="lede">Chance of a goal or of 1, 2 or 3+ points, with the fair price. Pick the market your book is offering, type its odds and the return shows; positive means the book is paying more than the model thinks it should.</p>
      <div class="controls">
        <input type="search" id="q" placeholder="Find a player" value="${esc(S.q)}" aria-label="Find a player">
        <div class="chips" role="group" aria-label="Position">
          ${["all", "F", "D"].map((p) => `<button type="button" class="chip" data-pos="${p}" aria-pressed="${S.pos === p}">${p === "all" ? "All skaters" : p === "F" ? "Forwards" : "Defense"}</button>`).join("")}
        </div>
        <label class="check"><input type="checkbox" id="radar" ${S.radar ? "checked" : ""}> Under the radar only</label>
      </div>
      <div class="controls"><span class="dim">Market</span>
        <div class="chips" role="group" aria-label="Market">
          ${MARKETS.map(([k, l]) => `<button type="button" class="chip" data-mkt="${k}" aria-pressed="${S.mkt === k}">${l}</button>`).join("")}
        </div></div>
      <div id="propsTable"></div>
      <p class="note">Under the radar marks players getting real chances whose goal totals lag behind them, outside the night's top dozen favourites. Lineups: everyone who dressed in a team's last three games, minus ESPN's injured list, plus players coming back; anyone who missed the last game is tagged, and every price assumes the player dresses. ${esc(T.goalie_note)}</p>
    </section>`;

  const drawTable = () => {
    let rows = liveProps();
    if (S.game) rows = rows.filter((r) => r.game === S.game);
    if (S.pos !== "all") rows = rows.filter((r) => r.pos === S.pos);
    if (S.radar) rows = rows.filter((r) => r.radar);
    if (S.q) rows = rows.filter((r) => r.name.toLowerCase().includes(S.q.toLowerCase()));
    // players ESPN lists as out or on IR sink to the bottom (still shown, flagged)
    const out = (r) => { const x = injuryOf(r.name); return x && x.abbr !== "DTD" ? 1 : 0; };
    const all = sortRows(rows, S.sort).sort((a, b) => out(a) - out(b));
    rows = all.slice(0, S.game || S.q || S.radar ? 400 : S.tLimit);
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
      { key: "name", label: "Player", fmt: (r) => `${playerLink(r.id, r.name)}<span class="sub">${r.team} vs ${r.opp}</span>${r.radar ? `<span class="tag" title="Under the radar">Radar</span>` : ""}${injuryTag(r.name)}${lineupTag(r)}` },
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
    $("#propsTable").innerHTML = (rows.length ? table(rows, cols, S.sort, "props") : `<p class="empty">No skaters match. Clear the search or switch filters.</p>`) +
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
  $("#radar").addEventListener("change", (e) => { S.radar = e.target.checked; drawTable(); });
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
  const teams = D.teams, fav = D.meta.favorite_team;
  const goalies = D.goalies.filter((g) => g.sa >= 60).sort((a, b) => b.gsax - a.gsax);
  const sorted = sortRows(teams.map((t) => ({ ...t, id: t.team })), S.lSort ||= { key: "pts", dir: -1 });
  view.innerHTML = `
    <section class="zone">
      <h1>Who's actually good</h1>
      <p class="lede">Every team placed by the quality of chances it creates and allows, per 60 minutes. Up and to the right is where you want to be. ${fav} is the dark dot. Tap any team to open it.</p>
      <div class="figure">${scatterTeams(teams, fav)}</div>
    </section>
    <section class="zone">
      <h2>Standings, with the luck shown</h2>
      <p class="lede">Finishing compares goals scored to the chances behind them. Goaltending compares goals allowed to the chances against, so positive means the goalie is stealing. Both swing hard early and tend to drift back toward zero.</p>
      <div id="standings"></div>
    </section>
    <section class="zone">
      <h2>Goalies: saves above expected</h2>
      <p class="lede">Goals the shots deserved minus goals actually allowed. Goalies who have faced at least 60 unblocked shots.</p>
      <div class="figure">${divergingBars(goalies, "gsax", (g) => `${g.name} ${g.team}`,
        (g) => `<b>${esc(g.name)}</b> ${g.team}<br>${g.gp} GP, ${pct(g.sv_pct, 1)} save rate<br>Allowed ${g.ga} on ${num(g.xga, 1)} expected${g.prev_gsax != null ? `<br>Last season ${signed(g.prev_gsax)}` : ""}`)}</div>
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
    bindSort($("#standings"), S.lSort, draw);
  };
  draw();
}

// ------------------------------------------------------------------ TEAMS
function skaterCols() {
  return [
    { key: "name", label: "Player", fmt: (r) => playerLink(r.id, r.name) },
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

function renderTeams(view, param) {
  const fav = D.meta.favorite_team;
  const team = (param || fav).toUpperCase();
  const t = D.teams.find((x) => x.team === team);
  const abbrs = D.teams.map((x) => x.team).sort();
  const sk = D.skaters.filter((s) => s.team === team);
  const shots = sk.flatMap((s) => (D.shots[s.id] || []).map((x) => [...x.slice(0, 7), x[7] || 0, s.id]));
  const gl = D.goalies.filter((g) => g.team === team);
  const rank = [...D.teams].sort((a, b) => b.pts - a.pts || a.gp - b.gp).findIndex((x) => x.team === team) + 1;
  const finishing = t ? t.g_minus_xg : 0, keeping = t ? t.xga - t.ga : 0;
  const story = !t ? "" : [
    `${team} is getting ${pct(t.xg_pct / 100)} of the expected goals in its games.`,
    Math.abs(finishing) >= 3 ? `Its shooters are ${finishing > 0 ? "running hot" : "running cold"}: ${signed(finishing)} goals against what their chances deserved.` : `Its finishing is close to what the chances deserve.`,
    Math.abs(keeping) >= 3 ? `Its goaltending is ${keeping > 0 ? "stealing goals" : "leaking goals"} (${signed(keeping)}).` : `Its goaltending is close to expected.`,
  ].join(" ");
  S.tSort ||= { key: "pts", dir: -1 };
  view.innerHTML = `
    <section class="zone">
      <div class="controls"><label for="teamPick" class="check">Team</label>
        <select id="teamPick">${abbrs.map((a) => `<option ${a === team ? "selected" : ""}>${a}</option>`).join("")}</select></div>
      <h1>${team}${t ? `: ${t.w}-${t.l}-${t.otl}, ${t.pts} points` : ""}</h1>
      <p class="lede">${t ? `${ordinal(rank)} in the league by points. ` : ""}${story}</p>
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
          { key: "name", label: "Goalie", nosort: true, fmt: (g) => esc(g.name) },
          { key: "gp", label: "GP", nosort: true }, { key: "sv_pct", label: "Save rate", nosort: true, fmt: (g) => pct(g.sv_pct, 1) },
          { key: "gsax", label: "Saves above expected", nosort: true, fmt: (g) => divCell(g.gsax, 8) },
        ], null, "tg") : `<p class="empty">No goalie data yet.</p>`}
      </div>
    </section>
    <section class="zone"><h2>Skaters</h2><p class="lede">"Team better with him" is how much larger a share of 5v5 expected goals the team gets with this player on the ice than without him.</p><div id="teamSk"></div></section>
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
  }).catch(() => {});
  teamNews(team).then((r) => {
    const el = $("#teamNews");
    if (location.hash !== here || !el) return;
    el.outerHTML = r ? r.html : "";
    const blk = view.querySelector(".media-block"); if (r && blk) bindMedia(blk, r.listen);
  }).catch(() => {});
  teamLog(team).then((html) => { if (location.hash === here) view.insertAdjacentHTML("beforeend", html); }).catch(() => {});
  $("#teamPick").addEventListener("change", (e) => (location.hash = "#teams/" + e.target.value));
}

// ------------------------------------------------------------------ PLAYERS
function verdictFor(p) {
  const bits = [];
  if (p.g_minus_xg >= 2) bits.push(`He has scored ${signed(p.g_minus_xg)} more goals than his chances usually produce, so expect fewer to go in.`);
  else if (p.g_minus_xg <= -1.5) bits.push(`He has ${signed(p.g_minus_xg)} fewer goals than his chances deserve, so goals should come if the chances keep coming.`);
  if (p.oi_luck >= 4) bits.push(`His team has outscored expectations by ${signed(p.oi_luck)} goals while he's on the ice, which tends not to last.`);
  if (p.oi_luck <= -4) bits.push(`His team has been unlucky with him on the ice (${signed(p.oi_luck)} goals against expectation).`);
  if (p.rel5 != null && Math.abs(p.rel5) >= 10) bits.push(`At 5v5 his team gets ${signed(p.rel5, 0)} points more of the expected goal share with him on the ice than without him.`);
  return bits.length ? bits.join(" ") : "Nothing unusual yet: his results line up with his underlying play.";
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
function renderPlayers(view, param) {
  const byPts = [...D.skaters].sort((a, b) => b.pts - a.pts);
  const id = param ? +param : (byPts.find((s) => s.team === D.meta.favorite_team) || byPts[0]).id;
  const p = D.skaters.find((s) => s.id === id) || byPts[0];
  const shots = D.shots[p.id] || [];
  const tile = (v, label, sub) => `<div class="stat"><b>${v}</b><span>${label}</span>${sub ? `<small>${sub}</small>` : ""}</div>`;
  const meter = (label, pctl, val) => pctl == null ? "" : `<div class="meter"><span>${label}</span><span class="bar-track" data-tip="${esc(`${Math.round(100 * pctl)}th percentile in the league`)}"><span class="bar-fill" style="width:${100 * pctl}%"></span></span><span class="val">${val}</span></div>`;
  const last = p.p_gp ? `Last season${p.p_team && p.p_team !== p.team ? ` with ${p.p_team}` : ""}: ${p.p_g} G, ${p.p_pts} P in ${p.p_gp} GP` : "No NHL games last season";
  view.innerHTML = `
    <section class="zone">
      <div class="controls"><input type="search" id="pq" placeholder="Search any skater" aria-label="Search any skater" autocomplete="off"></div>
      <ul class="suggest" id="sugg" hidden></ul>
      <div class="card-head"><span class="num">${p.num ?? ""}</span><div><h1>${esc(p.name)}</h1>
        <div class="meta">${p.team}, ${p.pos === "D" ? "defense" : "forward"}, ${p.gp} games, ${num(p.toi_pg, 1)} minutes a night</div></div></div>
      <div class="stat-row">
        ${tile(p.g, "Goals", `${num(p.ixg, 1)} expected`)}${tile(p.a, "Assists")}${tile(p.pts, "Points", `${p.ppp} on the power play`)}
        ${tile(signed(p.g_minus_xg), "Goals vs chances", p.g_minus_xg >= 0 ? "scoring above" : "scoring below")}
        ${tile(p.xgf5 == null ? "–" : pct(p.xgf5 / 100), "5v5 xG share", p.rel5 == null ? "" : `${signed(p.rel5, 0)} vs without him`)}
        ${tile(p.sog, "Shots", `${p.hits} hits, ${p.blk} blocks`)}
      </div>
      <p class="verdict">${esc(verdictFor(p))}</p>
    </section>
    <section class="zone grid-2">
      <div class="figure"><h3>Shot map</h3><p class="note">${shots.length} unblocked shots this season. Bigger dots were better chances; red went in. Tap one for the details.</p>
        ${shotMap(rinkSVG(shots, { label: `${p.name} shot map` }), shots, { kind: "player", id: p.id, name: p.name })}
        <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      <div>
        <h3>What the model believes</h3>
        <p class="note">${esc(last)}.</p>
        ${meter("Shooting threat", Math.min(1, (p.m_ixg60 || 0) / 1.6), `${num(p.m_ixg60, 2)} xG/60`)}
        ${meter("This season", Math.min(1, (p.ixg60 || 0) / 1.6), `${num(p.ixg60, 2)} xG/60`)}
        ${meter("Last season", p.p_ixg60 == null ? null : Math.min(1, p.p_ixg60 / 1.6), `${num(p.p_ixg60, 2)} xG/60`)}
        <p class="note">The top bar is the blend the prop odds use: this season pulled toward last season and his role, because a dozen games is too few to trust on its own.</p>
        <h3 style="margin-top:22px">Skating and shooting, tracked</h3>
        ${p.max_speed_pctile == null ? `<p class="note">No NHL Edge tracking for him yet.</p>` : `
          ${meter("Top speed", p.max_speed_pctile, `${num(p.max_speed_mph, 1)} mph`)}
          ${meter("20+ mph bursts", p.bursts_pctile, `${p.bursts_20mph}`)}
          ${meter("Hardest shot", p.top_shot_pctile, `${num(p.top_shot_mph, 1)} mph`)}
          ${meter("Distance skated", p.distance_pctile, `${Math.round(100 * p.distance_pctile)}th pct`)}
          <p class="note">Bars show his percentile among all NHL skaters this season.</p>`}
        <div id="pEdge"></div>
      </div>
    </section>
    <section class="zone"><h2>Game by game</h2><p class="lede">Every game this season, newest first. xG is his own shots' chances; on-ice ± is chances for minus against while he was out there. Tap a game to open it.</p>
      <div id="pLog"><p class="note">Loading his games…</p></div></section>
    <div id="pMedia"></div>
    <section class="zone"><h2>Every skater</h2>
      <div class="controls">
        <div class="chips" role="group" aria-label="Position">${["all", "F", "D"].map((x) => `<button type="button" class="chip" data-ppos="${x}" aria-pressed="${S.pPos === x}">${x === "all" ? "All" : x === "F" ? "Forwards" : "Defense"}</button>`).join("")}</div>
        <select id="pTeam" aria-label="Team"><option value="all">All teams</option>${D.teams.map((t) => t.team).sort().map((a) => `<option ${S.pTeam === a ? "selected" : ""}>${a}</option>`).join("")}</select>
        <label class="check">Min games <input type="text" id="pMin" value="${S.pMin}" style="width:48px" inputmode="numeric"></label>
      </div>
      <div id="allSk"></div><div class="controls" style="margin-top:10px"><button type="button" class="chip" id="more">Show more</button></div>
    </section>`;

  const draw = () => {
    let rows = D.skaters.filter((s) => s.gp >= S.pMin && (S.pPos === "all" || s.pos === S.pPos) && (S.pTeam === "all" || s.team === S.pTeam));
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
  const here = location.hash;
  getJSON(`data/players/${p.id}.json`).then((file) => {
    if (location.hash !== here || !$("#pLog")) return;
    const rows = Array.isArray(file) ? file : file.log || [], ed = Array.isArray(file) ? null : file.edge;
    if (ed && $("#pEdge")) $("#pEdge").innerHTML = edgeBlock(ed, rows);
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
  const q = $("#pq"), sugg = $("#sugg");
  q.addEventListener("input", () => {
    const t = q.value.trim().toLowerCase();
    if (t.length < 2) { sugg.hidden = true; return; }
    const hits = D.skaters.filter((s) => s.name.toLowerCase().includes(t)).slice(0, 8);
    sugg.innerHTML = hits.map((s) => `<li><button type="button" data-go="${s.id}">${esc(s.name)} <span class="dim">${s.team}</span></button></li>`).join("") || `<li><button type="button" disabled>No skater by that name has played this season</button></li>`;
    sugg.hidden = false;
    $$("[data-go]", sugg).forEach((b) => b.addEventListener("click", () => (location.hash = "#players/" + b.dataset.go)));
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") $("[data-go]", sugg)?.click(); });
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
  if (!L || !L.nights) return `<section class="zone">${head}<p class="lede">Starting with the October 16 slate, every game's prices are saved at puck drop, along with the lineups and goalies the site had to guess, and graded here the next morning. The backtest above was handed the real lineups and starting goalies; this record isn't, so expect it to look a little worse.</p></section>`;
  const pc = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "–");
  const lu = L.lineup, small = L.nights < 14;
  return `<section class="zone">${head}
    <p class="lede">${L.nights} night${L.nights === 1 ? "" : "s"} (${shortDate(L.first)} to ${shortDate(L.last)}), ${L.games} games, ${L.player_games.toLocaleString()} player-games, graded exactly as shown before puck drop.${small ? " That's a small sample: one hot night swings these numbers." : ""}</p>
    <div class="grid-3">
      <div><div class="bignum">${L.goal.pred.toFixed(0)} <span class="dim">vs</span> ${L.goal.act}</div><p>goal scorers predicted vs actual. The model beat the naive guess on ${L.goal.nights_beat} of ${L.nights} nights (log loss ${L.goal.ll.toFixed(4)} vs ${L.goal.ll_base.toFixed(4)}; lower is better).</p></div>
      <div><div class="bignum">${pc(lu.last.dressed, lu.last.priced)}</div><p>of players from each team's last lineup dressed. Of the ones tagged as missing the last game, ${pc(lu.recent.dressed, lu.recent.priced)} played${lu.returning.priced ? `; of those coming back, ${pc(lu.returning.dressed, lu.returning.priced)}` : ""}. ${lu.unpriced} dressed without a price.</p></div>
      <div><div class="bignum">${pc(L.goalies.hits, L.goalies.n)}</div><p>of starting goalies called right (${L.goalies.espn_n ? `${pc(L.goalies.espn_hits, L.goalies.espn_n)} when ESPN had posted a probable starter` : "no ESPN probables yet"}).</p></div>
    </div>
    <p class="note">Two or more points: ${L.pts.pred.toFixed(0)} predicted, ${L.pts.act} actual.${L.pts1 ? ` One or more: ${L.pts1.pred.toFixed(0)} predicted, ${L.pts1.act} actual. Three or more: ${L.pts3.pred.toFixed(0)} predicted, ${L.pts3.act} actual.` : ""} Game totals missed by ${L.totals.mae} goals on average (projected ${L.totals.mean_pred}, actual ${L.totals.mean_act}).</p>
    ${L.market && L.market.games ? `<p class="note"><b>Against DraftKings</b> (${L.market.games} games, lines the NHL publishes): totals missed by ${L.market.total_mae_model} goals for the model vs ${L.market.total_mae_market} for the market; over/under log loss ${L.market.over_ll_model.toFixed(3)} vs ${L.market.over_ll_market.toFixed(3)}; winner Brier score ${L.market.win_brier_model.toFixed(3)} vs ${L.market.win_brier_market.toFixed(3)}. Lower is better on all three; the market is the bar to clear.</p>` : ""}
  </section>`;
}
function renderModel(view) {
  const M = D.model, ts = M.this_season;
  view.innerHTML = `
    <section class="zone">
      <h1>Can you trust these odds?</h1>
      <p class="lede">The model was replayed across all of ${esc(M.season)} the honest way: every night predicted using only games played before it. Here is what that showed.</p>
      <div class="grid-3">
        <div><div class="bignum">${M.goal.pred.toLocaleString()}</div><p>goal scorers predicted across ${M.player_games.toLocaleString()} player-games. ${M.goal.act.toLocaleString()} actually scored.</p></div>
        <div><div class="bignum">${M.pts.pred.toLocaleString()}</div><p>two-point games predicted. ${M.pts.act.toLocaleString()} actually happened.</p></div>
        <div><div class="bignum">${M.totals.corr.toFixed(2)}</div><p>correlation between projected and actual game totals over ${M.games.toLocaleString()} games. That is essentially no signal, so totals here are context only.</p></div>
      </div>
    </section>
    ${liveRecord(M.live)}
    <section class="zone grid-2">
      <div class="figure narrow"><h3>Goal chances</h3><p class="note">Each dot groups player-games by what the model said. On the line means the model was right on average. Bigger dots hold more games.</p>${calibrationChart(M.goal.cal, "Goal probability calibration")}</div>
      <div class="figure narrow"><h3>Two or more points</h3><p class="note">Same check for multi-point games.</p>${calibrationChart(M.pts.cal, "Two point probability calibration")}</div>
    </section>
    <section class="zone">
      <h2>What this does and doesn't prove</h2>
      <p class="lede">It beats a naive guess (league scoring rates times ice time) in every month of last season. It has not been tested against sportsbook prices, which are much sharper than a naive guess. The only real test is logging the model's price next to the closing line for a few weeks.</p>
      ${ts ? `<p class="lede">This season so far: ${ts.goal_pred} scorers predicted and ${ts.goal_actual} actual across ${ts.player_games.toLocaleString()} player-games.</p>` : ""}
    </section>`;
}

// ------------------------------------------------------------------ router
const ROUTES = { tonight: renderTonight, games: renderGames, game: renderGame, preview: renderPreview, goals: renderGoals, live: renderLive, news: renderNews, league: renderLeague,
  teams: renderTeams, players: renderPlayers, fantasy: renderFantasy, model: renderModel };
const TAB_OF = { game: "games", goals: "games", preview: "tonight", live: "tonight" };
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
  if (p && p.catch) p.catch((e) => (view.innerHTML = `<p class="empty">Something failed to load (${esc(e.message)}). Reload to try again.</p>`));
  tip.hidden = true;
  if (rerender) {
    // Same page at a new width: put the reader back where they were once the async render settles.
    Promise.resolve(p).then(() => requestAnimationFrame(() => scrollTo(0, keepY)));
  } else if (param || tab === "game" || tab === "preview" || tab === "goals" || tab === "live" || tab === "news") scrollTo(0, 0);
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
    $("#view").innerHTML = `<p class="empty">The data files didn't load (${esc(e.message)}). The nightly build may still be running; reload in a few minutes.</p>`;
    return;
  }
  try { S.goalies = JSON.parse(store.get("goalies:" + D.tonight.date) || "{}"); } catch (e) { S.goalies = {}; }
  $("#freshness").textContent = `Updated ${D.meta.updated} MT with games through ${dateLabel(D.meta.last_game)}`;
  showFantasyTab(!!store.get(FKEY));
  addEventListener("hashchange", route);
  route();
  liveStart();      // ESPN scoreboard: live scores and probable goalies
  liveInjuries();   // ESPN injury report: flags on the odds
}
boot();
