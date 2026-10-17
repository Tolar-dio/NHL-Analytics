/* Player page extras.
   "How he plays": All Three Zones hand tracking (Corey Sznajder), shown as an interactive style map of every forward or
   defenseman, percentile bars, where his shots and setups come from next to a typical player at his position, and a
   few plain sentences on what to watch for. Derived numbers only, credited.
   "Highlights": his goals and assists this season, each with our replay of the build-up and the NHL's official clip,
   plus the latest official game highlights through YouTube's player. */
"use strict";

const PLAY_MAPS = {
  F: [
    { k: "create", label: "Shooter or playmaker", x: "chances60", y: "sa1_60", xl: "His scoring chances per 60", yl: "Primary shot assists per 60",
      q: ["Does both", "Playmaker", "Finisher", "Support role"] },
    { k: "quality", label: "Getting the good looks", x: "shots60", y: "hd_shots60", xl: "Shot attempts per 60", yl: "Shots off high-danger passes per 60",
      q: ["Volume and quality", "Waits for the good look", "Shoots from anywhere", "Low volume"] },
    { k: "carry", label: "Carrying the puck in", x: "entries60", y: "carry_pct", xl: "Zone entries per 60", yl: "Share of entries carried in",
      q: ["Drives the play in", "Picks his spots", "Dumps it in a lot", "Rarely leads the entry"] },
  ],
  D: [
    { k: "move", label: "Moving the puck", x: "exit_poss_pct", y: "carry_pct", xl: "Exits with possession", yl: "Share of entries carried in",
      q: ["Puck mover", "Carries, but exits are messy", "Clean exits, dumps it in", "Chip and chase"] },
    { k: "defend", label: "Defending the blue line", x: "denial_pct", y: "exit_poss_pct", xl: "Entries denied against him", yl: "Exits with possession",
      q: ["Two-way", "Moves it, gives up the line", "Holds the line", "Under pressure both ways"] },
    { k: "offense", label: "Offense from the back", x: "chances60", y: "sa1_60", xl: "His scoring chances per 60", yl: "Primary shot assists per 60",
      q: ["Drives offense", "Distributor", "Shooter", "Stay-at-home"] },
  ],
};
const PLAY_SHARE = new Set(["carry_pct", "exit_poss_pct", "denial_pct", "rush_share"]);
const playVal = (k, v) => (v == null ? "–" : PLAY_SHARE.has(k) ? pct(v, 0) : num(v, 2));
const GLOSSARY = [
  ["Scoring chances", "Shot attempts from the home-plate area in front of the net, between the faceoff dots and up to the top of the circles. Most goals come from there, so chances say more about a player than total shots."],
  ["Primary shot assists", "The last pass before a shot attempt. Assists only count passes before goals, which makes them noisy; shot assists count every pass that creates a shot, so they settle much faster and are the best early sign of future assists."],
  ["Chance assists", "Primary shot assists on scoring chances: the passes that set up the dangerous looks."],
  ["High-danger passes", "Passes across the royal road (the line from the net out to the middle of the ice, which forces the goalie to move side to side) and passes from behind the goal line. Shots off those passes go in far more often."],
  ["Zone entries and carry-ins", "How the puck gets over the offensive blue line. Carrying it in keeps possession; dumping it in gives it up and asks the forecheck to win it back. Carry-ins lead to far more scoring chances."],
  ["Exits with possession", "Getting the puck out of his own end by carrying it or passing it out with control, rather than clearing it off the glass or turning it over. Clean exits are how teams spend less time defending."],
  ["Entries denied", "When an opponent tries to get into the zone on his side, how often the entry fails. The best defensemen take away the blue line before a play can start."],
  ["Off the rush, forecheck or cycle", "What happened before the shot: the rush is offense in transition, the forecheck is winning the puck back in the offensive zone, and the cycle is sustained possession down low."],
];

function styleMapSVG(lg, card, pid, map, W) {
  const pos = card.pos, ki = (k) => lg.keys.indexOf(k);
  const ix = ki(map.x), iy = ki(map.y);
  const pool = lg.rows.filter((r) => r[3] === pos && r[ix] != null && r[iy] != null);
  const mine = card.rows.reduce((o, r) => ((o[r.k] = r.v), o), {});
  const meRow = pool.find((r) => r[0] === pid);
  const mx = meRow ? meRow[ix] : mine[map.x], my = meRow ? meRow[iy] : mine[map.y];
  const H = Math.round(Math.min(460, Math.max(300, W * 0.72))), m = { l: 48, r: 14, t: 14, b: 42 };
  const xs = pool.map((r) => r[ix]).concat(mx ?? []), ys = pool.map((r) => r[iy]).concat(my ?? []);
  const q = (a, p) => { const s = [...a].sort((u, v) => u - v); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
  // trim the extremes a little so a handful of tiny samples don't flatten everyone else; they sit on the edge
  const x0 = Math.min(q(xs, 0.005), mx ?? Infinity), x1 = Math.max(q(xs, 0.995), mx ?? -Infinity);
  const y0 = Math.min(q(ys, 0.005), my ?? Infinity), y1 = Math.max(q(ys, 0.995), my ?? -Infinity);
  const px = (x1 - x0) * 0.06 || 0.1, py = (y1 - y0) * 0.06 || 0.1;
  const X = (v) => m.l + ((Math.min(Math.max(v, x0 - px), x1 + px) - (x0 - px)) / (x1 - x0 + 2 * px)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((Math.min(Math.max(v, y0 - py), y1 + py) - (y0 - py)) / (y1 - y0 + 2 * py)) * (H - m.t - m.b);
  const med = (a) => q(a, 0.5);
  const mxd = med(pool.map((r) => r[ix])), myd = med(pool.map((r) => r[iy]));
  const fmt = (k, v) => (PLAY_SHARE.has(k) ? `${Math.round(100 * v)}%` : (+v).toFixed(1));
  const tx = ticks(x0 - px, x1 + px, 5), ty = ticks(y0 - py, y1 + py, 5);
  const grid = tx.map((v) => `<line class="grid" x1="${X(v)}" x2="${X(v)}" y1="${m.t}" y2="${H - m.b}"/><text x="${X(v)}" y="${H - m.b + 15}" text-anchor="middle">${fmt(map.x, v)}</text>`).join("") +
    ty.map((v) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${fmt(map.y, v)}</text>`).join("");
  const tipOf = (r) => `<b>${esc(r[1])}</b> ${r[2]}<br>${esc(map.xl)}: ${playVal(map.x, r[ix])}<br>${esc(map.yl)}: ${playVal(map.y, r[iy])}`;
  const dots = pool.filter((r) => r[0] !== pid).map((r) => `<a href="#players/${r[0]}" data-tip="${esc(tipOf(r))}"><circle cx="${X(r[ix])}" cy="${Y(r[iy])}" r="8" fill="transparent"/>
      <circle class="sm-dot" cx="${X(r[ix])}" cy="${Y(r[iy])}" r="3.5"/></a>`).join("");
  // a few names for orientation: the league leaders on each axis, where they fit
  const lead = [...pool].sort((a, b) => b[ix] - a[ix]).slice(0, 2).concat([...pool].sort((a, b) => b[iy] - a[iy]).slice(0, 2))
    .filter((r, i, a) => r[0] !== pid && a.findIndex((z) => z[0] === r[0]) === i);
  const hit = (b, list) => list.some((p) => b.x < p.x + p.w && b.x + b.w > p.x && b.y < p.y + p.h && b.y + b.h > p.y);
  const meName = lg.rows.find((r) => r[0] === pid)?.[1]?.split(" ").slice(-1)[0] || "Him";
  const halfW = meName.length * 4.2, lx = mx == null ? 0 : Math.min(Math.max(X(mx), m.l + halfW), W - m.r - halfW);
  const meBox = mx != null ? [{ x: Math.min(lx - halfW, X(mx) - 9) - 4, y: Y(my) - 27, w: Math.max(2 * halfW, 18) + 12, h: 37 }] : [];
  // quadrant names sit in the outer corner of each quadrant; if he is standing there, they move to the inner corner by the median line
  const qPos = [[W - m.r - 4, "end", m.t + 12, Y(myd) - 6], [m.l + 6, "start", m.t + 12, Y(myd) - 6],
    [W - m.r - 4, "end", H - m.b - 8, Y(myd) + 16], [m.l + 6, "start", H - m.b - 8, Y(myd) + 16]];
  const qBoxes = [];
  const quads = map.q.map((txt, i) => {
    const [x, anchor, yOut, yIn] = qPos[i], w = txt.length * 6.2 + 4, bx = anchor === "end" ? x - w : x;
    for (const y of [yOut, yIn]) {
      const b = { x: bx, y: y - 11, w, h: 14 };
      if (!hit(b, meBox)) { qBoxes.push(b); return `<text class="lbl sm-q" x="${x}" y="${y}" text-anchor="${anchor}">${esc(txt)}</text>`; }
    }
    return "";
  }).join("");
  const placed = meBox.concat(qBoxes);
  const labels = lead.map((r) => {
    const nm = String(r[1]).split(" ").slice(-1)[0], w = nm.length * 6.4 + 4, cx = X(r[ix]), cy = Y(r[iy]);
    for (const [dx, anchor] of [[7, "start"], [-7, "end"]]) {
      const b = { x: anchor === "start" ? cx + dx : cx + dx - w, y: cy - 7, w, h: 14 };
      if (b.x > m.l && b.x + w < W - m.r && !hit(b, placed)) {
        placed.push(b);
        return `<text class="lbl sm-lead" x="${cx + dx}" y="${cy + 4}" text-anchor="${anchor}">${esc(nm)}</text>`;
      }
    }
    return "";
  }).join("");
  const me = mx == null ? "" : `<g data-tip="${esc(`<b>${esc(lg.rows.find((r) => r[0] === pid)?.[1] || "Him")}</b><br>${esc(map.xl)}: ${playVal(map.x, mx)}<br>${esc(map.yl)}: ${playVal(map.y, my)}`)}">
      <circle cx="${X(mx)}" cy="${Y(my)}" r="8" class="sm-me"/>
      <text class="lbl sm-me-lbl" x="${lx}" y="${Y(my) - 13}" text-anchor="middle">${esc(meName)}</text></g>`;
  return `<svg class="chart style-map" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${map.label}: every ${pos === "D" ? "defenseman" : "forward"} with 150+ tracked minutes`)}">
    ${grid}
    <line class="axis" x1="${X(mxd)}" x2="${X(mxd)}" y1="${m.t}" y2="${H - m.b}"/><line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${Y(myd)}" y2="${Y(myd)}"/>
    ${quads}
    ${dots}${labels}${me}
    <text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle">${esc(map.xl)}</text>
    <text transform="translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">${esc(map.yl)}</text>
  </svg>`;
}

// his share of each kind against a typical player at his position: one bar each, the average as a tick
function mixBars(title, mine, avg, cats, noun) {
  if (!mine || mine.n < 8) return "";
  const rows = cats.filter(([k]) => (mine.shares[k] || 0) > 0 || (avg && avg[k] > 0.03)).map(([k, label]) => {
    const v = mine.shares[k] || 0, a = avg ? avg[k] || 0 : null;
    const tipTxt = `<b>${esc(label)}</b><br>Him: ${pct(v, 0)} of his ${noun}${a != null ? `<br>Typical: ${pct(a, 0)}` : ""}`;
    return `<div class="mix-row" data-tip="${esc(tipTxt)}"><span class="mix-l">${esc(label)}</span>
      <span class="mix-track"><span class="mix-fill" style="width:${Math.min(100, 100 * v / 0.6)}%"></span>${a != null ? `<span class="mix-avg" style="left:${Math.min(100, 100 * a / 0.6)}%"></span>` : ""}</span>
      <span class="mix-v">${pct(v, 0)}</span></div>`;
  }).join("");
  return `<h3 class="mix-h">${esc(title)} <span class="dim">(${mine.n} ${noun})</span></h3><div class="mix">${rows}</div>`;
}

async function renderPlays(el, card, pid, name) {
  let lg = null;
  try { lg = (await getJSON("data/a3z_league.json"))[card.season]; } catch (e) { lg = null; }
  const maps = PLAY_MAPS[card.pos === "D" ? "D" : "F"];
  S.playMap = maps.some((m) => m.k === S.playMap) ? S.playMap : maps[0].k;
  const posName = card.pos === "D" ? "defensemen" : "forwards", posOne = card.pos === "D" ? "defenseman" : "forward";
  const bars = card.rows.map((r) => `<div class="meter"><span>${esc(r.label)}</span>
      <span class="bar-track" data-tip="${esc(`${r.pctile == null ? "Too few tracked players to rank" : `${ordinal(Math.min(99, Math.max(1, Math.round(100 * r.pctile))))} percentile among ${posName}`}${r.lg != null ? `<br>Typical: ${r.share ? pct(r.lg, 0) : num(r.lg, 2) + " per 60"}` : ""}`)}"><span class="bar-fill" style="width:${r.pctile == null ? 0 : 100 * r.pctile}%"></span></span>
      <span class="val">${r.share ? pct(r.v, 0) : `${num(r.v, 1)}/60`}</span></div>`).join("");
  const cats = lg ? lg.pass_cats : [], plays = lg ? lg.play_cats : [];
  const draw = () => {
    const box = el.querySelector("#playMap");
    if (!box || !lg) return;
    const map = maps.find((m) => m.k === S.playMap);
    box.innerHTML = styleMapSVG(lg, card, pid, map, Math.max(300, box.clientWidth || 520));
  };
  el.innerHTML = `<h2>How he plays</h2>
    <p class="lede">Hand-tracked from ${card.games} of his games (${Math.round(card.toi5)} minutes at five on five) in ${esc(card.season)}: every shot, the passes before it, and every time he carried the puck in or out.</p>
    <div class="plays-notes">${card.notes.map((n) => `<p>${esc(n)}</p>`).join("")}</div>
    <div class="grid-2 plays-grid">
      <div class="figure">
        <div class="chips" role="group" aria-label="Map">${maps.map((m) => `<button type="button" class="chip" data-pmap="${m.k}" aria-pressed="${S.playMap === m.k}">${esc(m.label)}</button>`).join("")}</div>
        <div id="playMap" class="play-map">${lg ? "" : `<p class="note">The league map isn't available.</p>`}</div>
        <p class="note">Every ${posOne} with at least 150 tracked minutes; the lines are the middle of the pack. Hover or tap a dot for the player, tap again to open his page.</p>
      </div>
      <div>
        <h3>Percentiles among ${posName}</h3>${bars}
      </div>
    </div>
    <div class="mix-grid">
      <div>${mixBars("The pass before his shots", card.mix?.shot, card.avg?.shot, cats, "shots")}</div>
      <div>${mixBars("Where his setups come from", card.mix?.ast, card.avg?.ast, cats.filter(([k]) => k !== "none"), "setups")}</div>
      <div>${mixBars("How his shots happen", card.mix?.play, card.avg?.play, plays, "shots")}</div>
    </div>
    ${card.mix?.shot ? `<p class="note"><span class="mix-key"></span> marks a typical ${posOne}. Bars run to 60%.</p>` : ""}
    <details class="fold glossary"><summary>What these stats mean</summary>
      <dl>${GLOSSARY.map(([t, d]) => `<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join("")}</dl></details>
    <p class="note">Five-on-five tracking by All Three Zones (Corey Sznajder, allthreezones.com), which covers about a third of each season's games. A few games of tracking is noise; the numbers settle over a couple of months.</p>`;
  el.hidden = false;
  draw();
  // touch: the first tap on a dot names the player, a second tap on the same dot opens his page
  let armed = null, ptype = "mouse";
  const box = el.querySelector("#playMap");
  box?.addEventListener("pointerdown", (e) => (ptype = e.pointerType));
  box?.addEventListener("click", (e) => {
    const link = e.target.closest("a");
    if (!link || ptype === "mouse" || armed === link) return;
    e.preventDefault();
    e.stopPropagation();
    armed = link;
    const r = link.getBoundingClientRect();
    showTip(link, r.left + r.width / 2, r.top);
  });
  el.querySelectorAll("[data-pmap]").forEach((b) => b.addEventListener("click", () => {
    S.playMap = b.dataset.pmap;
    el.querySelectorAll("[data-pmap]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.pmap === S.playMap));
    draw();
  }));
}

// ------------------------------------------------------------------ highlights
const ROLE = { G: "Goal", A1: "Primary assist", A2: "Secondary assist" };
async function renderReel(el, reel, log, name) {
  const items = reel || [];
  let video = "";
  try {   // the latest game of his with official NHL highlights on YouTube (loaded on tap, through YouTube's player)
    const d = await newsIndex();
    const g = [...(log || [])].reverse().find((x) => d.highlights && d.highlights[String(x.id)]);
    if (g) video = `<div class="reel-video">${videoCard({ id: d.highlights[String(g.id)], channel: "NHL on YouTube", published: null, teams: [],
      title: `Highlights: ${shortDate(g.date)} ${g.home ? "vs" : "at"} ${g.opp}` }).replace(/<div class="ni-meta">.*?<\/div>/s, "")}</div>`;
  } catch (e) { video = ""; }
  if (!items.length && !video) { el.hidden = true; return; }
  const per = (x) => (x.ptype === "OT" ? "OT" : ["", "1st", "2nd", "3rd"][x.period] || "");
  const item = (x) => `<li class="goal-item reel-item">
      <span class="reel-role reel-${x.role}">${x.role === "G" ? "G" : x.role}</span>
      <div><div class="gi-top"><span class="gi-when">${shortDate(x.date)} ${x.home ? "vs" : "at"} ${x.opp}</span> <b>${ROLE[x.role] || "Assist"}</b>
          <span class="dim">${per(x)} ${esc(x.t)}</span></div>
        <div class="gi-sub">${x.role === "G" ? "" : `On ${esc(x.scorer)}'s goal. `}${esc(strengthLabel[x.strength] || x.strength || "")}${x.shot ? `, ${esc(x.shot)}` : ""}${x.xg != null ? `, a ${pct(x.xg)} chance` : ""}.</div></div>
      <span class="gi-acts">${x.seq ? `<button type="button" class="watch replay" data-rg="${x.game}" data-re="${x.eid}">Replay</button>` : ""}
        ${x.clip ? `<a class="watch" href="${esc(x.clip)}" target="_blank" rel="noopener">Watch</a>` : ""}</span></li>`;
  const goals = items.filter((x) => x.role === "G").length, ast = items.length - goals;
  S.reelN = 8;
  const list = () => `<ol class="goal-list">${items.slice(0, S.reelN).map(item).join("")}</ol>
    ${items.length > S.reelN ? `<div class="controls" style="margin-top:10px"><button type="button" class="chip" data-reelmore>Show all ${items.length}</button></div>` : ""}`;
  el.innerHTML = `<h2>Highlights</h2>
    <p class="lede">${items.length ? `His ${goals} goal${goals === 1 ? "" : "s"} and ${ast} assist${ast === 1 ? "" : "s"} this season, newest first. Replay rebuilds the play from the NHL's recorded events and shift charts; Watch opens the official clip on NHL.com.` : "No goals or assists yet this season."}</p>
    ${video}<div id="reelList">${list()}</div>`;
  el.hidden = false;
  bindMedia(el, []);
  el.addEventListener("click", async (e) => {
    const more = e.target.closest("[data-reelmore]");
    if (more) { S.reelN = items.length; el.querySelector("#reelList").innerHTML = list(); return; }
    const b = e.target.closest("[data-rg]");
    if (!b) return;
    const g = await getJSON(`data/games/${b.dataset.rg}.json`);
    D._names = Object.fromEntries((g.players || []).map((p) => [p.id, p.name]));
    openTheater(g, b.dataset.re);
  });
}
