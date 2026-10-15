/* Game catalogue, game pages and same-day previews. Loaded after app.js and
   reuses its helpers ($, esc, pct, signed, num, fair, table, sortRows, ...). */
"use strict";

const cache = {};
async function getJSON(path) {
  if (!cache[path]) cache[path] = fetch(path, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(path); return r.json(); });
  return cache[path];
}
const endTag = (e) => (e && e !== "REG" ? ` <span class="end">${e}</span>` : "");
const shortDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const headshot = (url, alt) => url ? `<img class="mug" src="${esc(url)}" alt="${esc(alt)}" loading="lazy" width="40" height="40">` : `<span class="mug mug-empty" aria-hidden="true"></span>`;
const strengthLabel = { ev: "Even strength", pp: "Power play", sh: "Shorthanded", en: "Empty net" };

// ------------------------------------------------------------------ charts
function fullRinkSVG(shots, away, home) {
  const marks = shots.map(([x, y, xg, g, isHome, sec, pid, st]) => {
    const rr = 0.6 + Math.sqrt(xg / 1000) * 3;
    const who = (D._names && D._names[pid]) || "";
    const tipTxt = `${g ? "<b>Goal</b>" : "Shot"} by ${esc(who) || (isHome ? home : away)}<br>${(xg / 10).toFixed(1)}% chance, ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")} elapsed${st && st !== "EV" ? `, ${st}` : ""}`;
    return { g, svg: `<circle class="${g ? "goal" : "shot"}" cx="${x}" cy="${-y}" r="${g ? Math.max(rr, 1.3) : rr}" data-tip="${esc(tipTxt)}"></circle>` };
  }).sort((a, b) => a.g - b.g).map((m) => m.svg);
  const half = (s) => `<circle class="circle" cx="${s * 69}" cy="-22" r="15"/><circle class="circle" cx="${s * 69}" cy="22" r="15"/>
    <circle class="dot" cx="${s * 69}" cy="-22" r="0.6"/><circle class="dot" cx="${s * 69}" cy="22" r="0.6"/>
    <circle class="dot" cx="${s * 20}" cy="-22" r="0.6"/><circle class="dot" cx="${s * 20}" cy="22" r="0.6"/>
    <line class="goalline" x1="${s * 89}" y1="-36.7" x2="${s * 89}" y2="36.7"/>
    <path class="crease" d="M${s * 89},-4 L${s * 85.5},-4 A6,6 0 0 ${s > 0 ? 0 : 1} ${s * 85.5},4 L${s * 89},4 Z"/>
    <rect class="net" x="${s > 0 ? 89 : -92.3}" y="-3" width="3.3" height="6" rx="0.8"/>
    <rect class="blueline" x="${s > 0 ? 25 : -26}" y="-42.5" width="1" height="85"/>`;
  return `<svg class="chart rink" viewBox="-101 -46 202 92" role="img" aria-label="Both teams' shots: ${away} shooting left, ${home} shooting right">
    <path class="boards" d="M-72,-42.5 L72,-42.5 A28,28 0 0 1 100,-14.5 L100,14.5 A28,28 0 0 1 72,42.5 L-72,42.5 A28,28 0 0 1 -100,14.5 L-100,-14.5 A28,28 0 0 1 -72,-42.5 Z"/>
    <rect class="redline" x="-0.5" y="-42.5" width="1" height="85"/><circle class="circle" cx="0" cy="0" r="15"/>
    ${half(1)}${half(-1)}
    <text class="zone-label" x="-50" y="-44" text-anchor="middle" style="font-size:3.4px;font-weight:700">${away} shooting this way</text>
    <text class="zone-label" x="50" y="-44" text-anchor="middle" style="font-size:3.4px;font-weight:700">${home} shooting this way</text>
    ${marks.join("")}</svg>`;
}

function flowChart(g) {
  const W = mainW(1000), H = Math.max(240, Math.round(W * 0.3)), m = { l: 40, r: 56, t: 14, b: 32 };
  const shots = [...g.shots].sort((a, b) => a[5] - b[5]);
  const end = Math.max(3600, ...shots.map((s) => s[5] + 30), g.end === "REG" ? 3600 : 3900);
  const series = { 0: [[0, 0]], 1: [[0, 0]] }, tot = { 0: 0, 1: 0 }, goals = [];
  shots.forEach((s) => {
    const k = s[4];
    series[k].push([s[5], tot[k]]);
    tot[k] += s[2] / 1000;
    series[k].push([s[5], tot[k]]);
    if (s[3]) goals.push({ k, t: s[5], v: tot[k], pid: s[6] });
  });
  series[0].push([end, tot[0]]); series[1].push([end, tot[1]]);
  const ymax = Math.max(1, tot[0], tot[1]) * 1.08;
  const X = (t) => m.l + (t / end) * (W - m.l - m.r), Y = (v) => H - m.b - (v / ymax) * (H - m.t - m.b);
  const path = (pts) => "M" + pts.map(([t, v]) => `${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join(" L");
  const periods = [1200, 2400, 3600].filter((t) => t < end).map((t, i) => `<line class="grid" x1="${X(t)}" x2="${X(t)}" y1="${m.t}" y2="${H - m.b}"/>`);
  const plabels = ["1st", "2nd", "3rd", "OT"].map((l, i) => i * 1200 < end ? `<text x="${X(Math.min(i * 1200 + 600, (i * 1200 + end) / 2))}" y="${H - 10}" text-anchor="middle">${l}</text>` : "");
  const yt = ticks(0, ymax, 4).map((v) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(1)}</text>`);
  const col = { 1: "var(--blue)", 0: "var(--ink)" };
  const dots = goals.map((q) => `<g data-tip="${esc(`<b>Goal</b> ${esc((D._names && D._names[q.pid]) || "")}, ${Math.floor(q.t / 60)}:${String(q.t % 60).padStart(2, "0")} elapsed`)}">
    <circle cx="${X(q.t)}" cy="${Y(q.v)}" r="10" fill="transparent"/><circle cx="${X(q.t)}" cy="${Y(q.v)}" r="5" fill="var(--red)" stroke="var(--sheet)" stroke-width="2"/></g>`);
  const endLbl = (k, abbr) => `<text class="lbl" x="${W - m.r + 6}" y="${Y(tot[k]) + 4}">${abbr} ${tot[k].toFixed(2)}</text>`;
  const lblGap = Math.abs(Y(tot[0]) - Y(tot[1])) < 14;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Expected goals building through the game">
    ${yt.join("")}${periods.join("")}
    <path d="${path(series[0])}" fill="none" stroke="${col[0]}" stroke-width="2" stroke-linejoin="round"/>
    <path d="${path(series[1])}" fill="none" stroke="${col[1]}" stroke-width="2" stroke-linejoin="round"/>
    ${dots.join("")}${lblGap ? "" : endLbl(0, g.away) + endLbl(1, g.home)}${plabels.join("")}</svg>`;
}

// ------------------------------------------------------------------ catalogue
const SORTS = {
  newest: { label: "Newest", fn: (a, b) => b.date.localeCompare(a.date) || b.id - a.id },
  robbed: { label: "Won while outplayed", fn: (a, b) => a.w_deserve - b.w_deserve },
  chaos: { label: "Most chances", fn: (a, b) => b.chaos - a.chaos },
  close: { label: "Coin flips", fn: (a, b) => Math.abs(a.dtw_home - 0.5) - Math.abs(b.dtw_home - 0.5) },
};
function gameRow(x, team) {
  const w = x.winner, lab = (t, sc) => `<span class="${t === w ? "won" : ""}">${t} ${sc}</span>`;
  // from a team's point of view, show that team's share; otherwise the winner's
  const who = team || w;
  const share = who === x.home ? x.dtw_home : 1 - x.dtw_home;
  const won = who === w;
  const flag = won && share < 0.35 ? `<span class="tag">${team ? "Stole one" : "Outplayed and won"}</span>`
    : team && !won && share > 0.65 ? `<span class="tag">Deserved better</span>` : "";
  const persp = team ? (won ? "W" : x.end !== "REG" ? "OTL" : "L") : "";
  return `<li><a class="game-row" href="#game/${x.id}">
    <span class="gr-date">${shortDate(x.date)}${persp ? ` <b class="res res-${persp}">${persp}</b>` : ""}</span>
    <span class="gr-score">${lab(x.away, x.a)} <span class="dim">at</span> ${lab(x.home, x.h)}${endTag(x.end)}</span>
    <span class="gr-deserve" data-tip="${esc(`Replaying every shot, ${who} wins ${pct(share)} of the time.`)}">
      <span class="bar-track"><span class="bar-fill" style="width:${100 * share}%"></span></span><span>${who} deserved ${pct(share)}</span></span>
    <span class="gr-blurb">${flag}${x.blurb ? esc(x.blurb) : x.star ? `Top performer: ${esc(x.star)}` : ""}</span></a></li>`;
}
async function renderGames(view) {
  view.innerHTML = `<p class="empty">Loading the season's games…</p>`;
  const idx = await getJSON("data/games/index.json");
  S.gTeam ||= "all"; S.gSort ||= "newest"; S.gLimit ||= 40;
  const draw = () => {
    let rows = idx.filter((x) => S.gTeam === "all" || x.away === S.gTeam || x.home === S.gTeam);
    rows = [...rows].sort(SORTS[S.gSort].fn);
    $("#gameList").innerHTML = rows.slice(0, S.gLimit).map((x) => gameRow(x, S.gTeam === "all" ? null : S.gTeam)).join("") ||
      `<li class="empty">No games yet for that team.</li>`;
    $("#gMore").hidden = rows.length <= S.gLimit;
  };
  const teams = [...new Set(idx.flatMap((x) => [x.away, x.home]))].sort();
  view.innerHTML = `<section class="zone">
      <h1>Every game, replayed</h1>
      <p class="lede">${idx.length} games so far. "Deserved" replays every shot from the game thousands of times using its expected-goal chance and counts how often the winner still wins. Under 35% means they got away with one.</p>
      <div class="controls">
        <select id="gTeam" aria-label="Team"><option value="all">All teams</option>${teams.map((t) => `<option ${S.gTeam === t ? "selected" : ""}>${t}</option>`).join("")}</select>
        <div class="chips" role="group" aria-label="Sort games">${Object.entries(SORTS).map(([k, v]) => `<button type="button" class="chip" data-gsort="${k}" aria-pressed="${S.gSort === k}">${v.label}</button>`).join("")}</div>
      </div>
      <ul class="game-list" id="gameList"></ul>
      <div class="controls" style="margin-top:10px"><button type="button" class="chip" id="gMore">Show more games</button></div>
    </section>`;
  draw();
  $("#gTeam").addEventListener("change", (e) => { S.gTeam = e.target.value; draw(); });
  $("#gMore").addEventListener("click", () => { S.gLimit += 40; draw(); });
  $$("[data-gsort]", view).forEach((b) => b.addEventListener("click", () => { S.gSort = b.dataset.gsort; $$("[data-gsort]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); }));
}

// ------------------------------------------------------------------ game page
async function renderGame(view, id) {
  view.innerHTML = `<p class="empty">Loading the game…</p>`;
  let g;
  try { g = await getJSON(`data/games/${id}.json`); } catch (e) { view.innerHTML = `<p class="empty">That game isn't in the catalogue yet. Games appear the morning after they're played.</p>`; return; }
  D._names = Object.fromEntries(g.players.map((p) => [p.id, p.name]));
  const winner = g.h > g.a ? g.home : g.away, dtwW = winner === g.home ? g.dtw_home : 1 - g.dtw_home;
  const ts = g.team_stats || {};
  const stat = (label, a, h, tipTxt) => `<div class="vs"${tipTxt ? ` data-tip="${esc(tipTxt)}"` : ""}><span>${a ?? "–"}</span><b>${label}</b><span>${h ?? "–"}</span></div>`;
  const goalItem = (x) => `<li class="goal-item">
      ${headshot(x.headshot, x.name)}
      <div><div class="gi-top"><span class="gi-when">${x.ptype === "OT" ? "OT" : ["", "1st", "2nd", "3rd"][x.period] || `P${x.period}`} ${esc(x.t)}</span> <b>${esc(x.name)}</b> <span class="dim">(${x.num})</span> <span class="gi-team">${x.team}</span></div>
        <div class="gi-sub">${x.assists.length ? `from ${x.assists.map((a) => esc(a.name)).join(" and ")}` : "unassisted"}. ${esc(strengthLabel[x.strength] || x.strength)}, ${esc(x.shot || "shot")}${x.xg != null ? `, a ${pct(x.xg)} chance` : ""}. <span class="dim">${g.away} ${x.score.split("-")[0]}, ${g.home} ${x.score.split("-")[1]}</span></div></div>
      ${x.clip ? `<a class="watch" href="${esc(x.clip)}" target="_blank" rel="noopener">Watch</a>` : ""}</li>`;
  const pcols = [
    { key: "name", label: "Player", fmt: (r) => `${playerLink(r.id, r.name)}<span class="sub">${r.pos}</span>` },
    { key: "gs", label: "Game score", fmt: (r) => num(r.gs, 2) },
    { key: "toi", label: "TOI", fmt: (r) => num(r.toi, 1) },
    { key: "g", label: "G" }, { key: "a", label: "A" }, { key: "sog", label: "Shots" },
    { key: "ixg", label: "xG", fmt: (r) => num(r.ixg, 2) },
    { key: "xgdiff", label: "On-ice xG ±", fmt: (r) => divCell(r.xgdiff, 1.5, 2), cls: "hide-sm" },
    { key: "hits", label: "Hits", cls: "hide-sm" }, { key: "blk", label: "Blocks", cls: "hide-sm" },
  ];
  S.gpSort ||= { key: "gs", dir: -1 };
  const so = g.shootout && g.shootout.length;
  view.innerHTML = `
    <section class="zone">
      <p class="crumbs"><a href="#games">All games</a></p>
      <h1>${g.away} ${g.a}, ${g.home} ${g.h}${g.end !== "REG" ? ` (${g.end})` : ""}</h1>
      <p class="lede">${esc(new Date(g.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }))} at ${esc(g.venue)}. <a href="${esc(g.gamecenter)}" target="_blank" rel="noopener">Watch the recap and condensed game on NHL.com</a></p>
      <div class="game-open">
        <div>${g.story ? `<div class="story">${g.story.split(/\n\s*\n/).map((p) => `<p>${esc(p)}</p>`).join("")}</div>` : `<p class="note">The written recap arrives with the next nightly build.</p>`}</div>
        <div>
          <div class="deserve" data-tip="${esc("Every shot replayed thousands of times using its chance of going in; ties split evenly")}">
            <div class="bignum">${pct(dtwW)}</div>
            <p>of replays go ${winner}'s way. ${dtwW < 0.35 ? `${winner} won a game it usually loses.` : dtwW > 0.65 ? `${winner} earned this one.` : "This one could have gone either way."}</p>
          </div>
          <div class="vs-grid">
            <div class="vs vs-head"><span>${g.away}</span><b></b><span>${g.home}</span></div>
            ${stat("Expected goals", num(g.xg_a, 2), num(g.xg_h, 2), "Sum of every unblocked shot's chance of going in")}
            ${stat("At even strength", num(g.xg5_a, 2), num(g.xg5_h, 2))}
            ${stat("Shot attempts", g.cf_a, g.cf_h, "Shots, misses and blocked shots")}
            ${stat("Shots on goal", ts.sog?.[0], ts.sog?.[1])}
            ${stat("Power play", ts.powerPlay?.[0], ts.powerPlay?.[1])}
            ${stat("Faceoffs", ts.faceoffWins?.[0], ts.faceoffWins?.[1])}
            ${stat("Hits", ts.hits?.[0], ts.hits?.[1])}
          </div>
        </div>
      </div>
    </section>
    <section class="zone">
      <h2>How the chances piled up</h2>
      <p class="lede">Each line climbs by a shot's chance of going in. Red dots are goals. Steep stretches are when a team was taking over.</p>
      <div class="figure">${flowChart(g)}
        <div class="legend"><span><i style="background:var(--ink)"></i>${g.away}</span><span><i style="background:var(--blue)"></i>${g.home}</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
    </section>
    <section class="zone grid-2">
      <div><h2>Goals</h2><ol class="goal-list">${g.goals.map(goalItem).join("") || `<li class="empty">No goals.</li>`}</ol>
        ${so ? `<h3 style="margin-top:16px">Shootout</h3><ol class="so-list">${g.shootout.map((x) => `<li><b>${esc(x.name)}</b> ${x.team}: ${x.result === "goal" ? `<span class="goal-word">scored</span>` : esc(x.result)}</li>`).join("")}</ol>` : ""}
      </div>
      <div><h2>Three stars</h2><ol class="stars">${g.stars.map((s) => `<li>${headshot(s.headshot, s.name)}<div><b>${esc(s.name)}</b> ${s.team}<div class="dim">${s.pos === "G" ? (s.sv != null ? `${pct(s.sv, 1)} saves` : "goalie") : `${s.g} G, ${s.a} A`}</div></div></li>`).join("")}</ol>
        <h3 style="margin-top:18px">Goalies</h3>
        ${table(g.goalies.filter((x) => x.toi > 0), [
          { key: "name", label: "Goalie", nosort: true, fmt: (x) => `${esc(x.name)}<span class="sub">${x.team}</span>` },
          { key: "sa", label: "Shots", nosort: true }, { key: "ga", label: "GA", nosort: true },
          { key: "gsax", label: "Saves above expected", nosort: true, fmt: (x) => divCell(x.gsax, 3, 2) },
        ], null, "gg")}</div>
    </section>
    <section class="zone">
      <h2>Every shot</h2>
      <div class="figure">${fullRinkSVG(g.shots, g.away, g.home)}
        <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss, sized by chance</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
    </section>
    <section class="zone">
      <h2>Player by player</h2>
      <p class="lede">Game score credits goals, assists, shots, blocks and what happened on the ice while each player was out there. On-ice xG ± is chances for minus chances against during his shifts.</p>
      <div class="grid-2"><div><h3>${g.away}</h3><div id="pAway"></div></div><div><h3>${g.home}</h3><div id="pHome"></div></div></div>
    </section>
    ${g.series && g.series.length > 1 ? `<section class="zone"><h2>Season series</h2><ul class="game-list">${g.series.map((x) => x.a == null
      ? `<li><span class="game-row is-future"><span class="gr-date">${shortDate(x.date)}</span><span class="gr-score">${x.away} at ${x.home}</span><span class="dim">Upcoming</span></span></li>`
      : `<li><a class="game-row" href="#game/${x.id}"><span class="gr-date">${shortDate(x.date)}</span><span class="gr-score">${x.away} ${x.a} <span class="dim">at</span> ${x.home} ${x.h}${endTag(x.end)}</span>${x.id === g.id ? `<span class="dim">This game</span>` : ""}</a></li>`).join("")}</ul></section>` : ""}`;
  const drawP = () => {
    for (const [team, el] of [[g.away, "#pAway"], [g.home, "#pHome"]]) {
      const rows = sortRows(g.players.filter((p) => p.team === team).map((p) => ({ ...p, xgdiff: (p.xgf ?? 0) - (p.xga ?? 0) })), S.gpSort);
      $(el).innerHTML = table(rows, pcols, S.gpSort, "p" + team);
      bindSort($(el), S.gpSort, drawP);
    }
  };
  drawP();
}

// ------------------------------------------------------------------ preview page
async function renderPreview(view, id) {
  view.innerHTML = `<p class="empty">Loading the preview…</p>`;
  let p;
  try { p = await getJSON(`data/previews/${id}.json`); } catch (e) { view.innerHTML = `<p class="empty">Previews exist for today's games only. <a href="#tonight">Back to tonight</a>.</p>`; return; }
  const A = p.teams[p.away], H = p.teams[p.home];
  const better = (a, h, higherIsBetter = true) => {
    if (a == null || h == null || a === h) return ["", ""];
    const aBetter = higherIsBetter ? a > h : a < h;
    return aBetter ? ["better", ""] : ["", "better"];
  };
  const row = (label, a, h, fmt, hib = true, tipTxt) => {
    const [ca, ch] = better(a, h, hib);
    return `<div class="vs"${tipTxt ? ` data-tip="${esc(tipTxt)}"` : ""}><span class="${ca}">${fmt(a)}</span><b>${label}</b><span class="${ch}">${fmt(h)}</span></div>`;
  };
  const f2 = (x) => num(x, 2), fp = (x) => (x == null ? "–" : pct(x));
  const form = (t) => `<ol class="form">${t.last5.map((x) => {
    const res = x.gf > x.ga ? "W" : x.end !== "REG" ? "OTL" : "L";
    return `<li><a href="#game/${x.id}" data-tip="${esc(`${x.home ? "vs" : "at"} ${x.opp}, ${x.gf}-${x.ga}${x.end !== "REG" ? " " + x.end : ""}<br>Got ${pct(x.xg_share)} of the expected goals`)}">
      <b class="res res-${res}">${res}</b><span class="bar-track"><span class="bar-fill" style="width:${100 * x.xg_share}%"></span></span><span class="dim">${x.home ? "vs" : "@"} ${x.opp}</span></a></li>`;
  }).join("")}</ol>`;
  const goalieCard = (gc, team) => !gc ? `<p class="note">No projected goalie for ${team}.</p>` :
    `<div class="gcard"><b>${esc(gc.name)}</b> <span class="dim">${team}, projected</span>
      <div>This season: ${gc.gp} games, ${pct(gc.sv_pct, 1)} save rate, ${signed(gc.gsax)} saves above expected</div>
      <div class="dim">Last season: ${gc.prev_gp ? `${gc.prev_gp} games, ${signed(gc.prev_gsax)} saves above expected` : "no NHL games"}</div></div>`;
  const lines = (t) => {
    const L = p.lines[t];
    return `<div><h3>${t}</h3><ol class="lines">${(L.F || []).map((u) => `<li>${u.map((x) => playerLink(x.id, x.name)).join(", ")}</li>`).join("")}</ol>
      <ol class="lines">${(L.D || []).map((u) => `<li>${u.map((x) => playerLink(x.id, x.name)).join(", ")}</li>`).join("")}</ol></div>`;
  };
  const props = (t) => `<div><h3>${t}</h3><ul class="plist">${p.props[t].goal.map((x) => `<li>${playerLink(x.id, x.name)} <span class="dim">to score</span> <b>${pct(x.p_goal)}</b> <span class="dim">fair ${fair(x.p_goal)}</span></li>`).join("")}
      ${p.props[t].pts.map((x) => `<li>${playerLink(x.id, x.name)} <span class="dim">2+ points</span> <b>${pct(x.p_2pts)}</b> <span class="dim">fair ${fair(x.p_2pts)}</span></li>`).join("")}</ul></div>`;
  const rest = (t) => t.rest_days == null ? "–" : t.rest_days <= 0 ? "Back-to-back" : `${t.rest_days} day${t.rest_days === 1 ? "" : "s"}`;
  const series = p.series.filter((x) => x.a != null);
  view.innerHTML = `
    <section class="zone">
      <p class="crumbs"><a href="#tonight">Tonight</a></p>
      <h1>${p.away} at ${p.home}</h1>
      <p class="lede">${timeMT(p.start)}. The model expects ${p.away} ${num(p.away_xg, 2)} and ${p.home} ${num(p.home_xg, 2)} goals with the projected goalies.</p>
      ${p.story ? `<div class="story">${p.story.split(/\n\s*\n/).map((x) => `<p>${esc(x)}</p>`).join("")}</div>` : `<p class="note">The written preview arrives with the next build.</p>`}
    </section>
    <section class="zone">
      <h2>Tale of the tape</h2>
      <p class="lede">This season, all situations unless noted. The better side of each row is marked.</p>
      <div class="vs-grid">
        <div class="vs vs-head"><span>${p.away}</span><b></b><span>${p.home}</span></div>
        ${row("Chances created per 60", A.xgf60, H.xgf60, f2, true, "Expected goals per 60 minutes")}
        ${row("Chances allowed per 60", A.xga60, H.xga60, f2, false)}
        ${row("Even-strength chance share", A.xg5_share, H.xg5_share, fp)}
        ${row("Power play chances per game", A.pp_xg_pg, H.pp_xg_pg, f2)}
        ${row("Penalty kill chances allowed per game", A.pk_xga_pg, H.pk_xga_pg, f2, false)}
        ${row("Penalties taken per game", A.pen_taken_pg, H.pen_taken_pg, f2, false)}
        ${row("Goals per game", A.gf_pg, H.gf_pg, f2)}
        ${row("Goals allowed per game", A.ga_pg, H.ga_pg, f2, false)}
        <div class="vs"><span>${rest(A)}</span><b>Rest</b><span>${rest(H)}</span></div>
      </div>
    </section>
    <section class="zone grid-2">
      <div><h2>Last five</h2><p class="note">Bars show each game's share of expected goals. Tap one to open that game.</p>
        <h3 style="margin-top:12px">${p.away}</h3>${form(A)}<h3 style="margin-top:12px">${p.home}</h3>${form(H)}</div>
      <div><h2>In net</h2>${goalieCard(p.goalies[p.away], p.away)}${goalieCard(p.goalies[p.home], p.home)}
        <p class="note">Projected from recent starts. Switch goalies on the Tonight page to reprice everything.</p></div>
    </section>
    <section class="zone"><h2>Lines from their last game</h2><p class="lede">Grouped by who shared the most ice time. Coaches shuffle, so treat these as likely, not certain.</p>
      <div class="grid-2">${lines(p.away)}${lines(p.home)}</div></section>
    <section class="zone"><h2>Who the model likes</h2><div class="grid-2">${props(p.away)}${props(p.home)}</div></section>
    ${series.length ? `<section class="zone"><h2>Earlier this season</h2><ul class="game-list">${series.map((x) => `<li><a class="game-row" href="#game/${x.id}"><span class="gr-date">${shortDate(x.date)}</span><span class="gr-score">${x.away} ${x.a} <span class="dim">at</span> ${x.home} ${x.h}${endTag(x.end)}</span><span class="dim">${x.h > x.a ? x.home : x.away} deserved ${pct(x.h > x.a ? x.dtw_home : 1 - x.dtw_home)}</span></a></li>`).join("")}</ul></section>` : ""}`;
}

// team season log (appended to the Teams page)
async function teamLog(team) {
  const idx = await getJSON("data/games/index.json");
  const rows = idx.filter((x) => x.away === team || x.home === team);
  return `<section class="zone"><h2>Season log</h2><p class="lede">Every ${team} game, newest first. The bar is how often ${team} wins when the game is replayed from its shots.</p>
    <ul class="game-list">${rows.map((x) => gameRow(x, team)).join("")}</ul></section>`;
}
