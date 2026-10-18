/* The coaching and goaltending layer.
   Player pages: "Defense" (analysis/defense.py via build): chances against on and off the ice at 5v5, high-danger
   chances, blocks, takeaways and giveaways, penalty-kill minutes, own-end starts; this season next to last season,
   percentiles, plain notes and a league map of hard minutes against results.
   Goalie pages (#goalie/<id>, site/goalies.py): saves above expected, save rate by shot danger against the league,
   rebound control, shots-against map, start log, last season, EDGE areas, Evolving-Hockey history.
   Team pages: "Lines and deployment" (site/tactics.py): forward lines and defense pairs at 5v5, power-play and
   penalty-kill units, who plays when, shift lengths, own-end starts, team style from All Three Zones. */
"use strict";

const DEF_MAPS = [
  { k: "minutes", label: "Hard minutes vs results", x: "dz_share", y: "supp", xl: "Share of 5v5 faceoffs in his own end", yl: "Chances prevented vs without him (xGA/60)",
    q: ["Hard minutes, holds up", "Easy minutes, holds up", "Hard minutes, leaks", "Easy minutes, leaks"] },
  { k: "work", label: "Penalty kill and blocks", x: "pk_pg", y: "blk60", xl: "Penalty-kill minutes a game", yl: "Blocks per 60",
    q: ["PK workhorse who blocks", "Blocks, little PK", "PK minutes, few blocks", "Neither"] },
];
const DEF_FMT = { rate: (v) => `${signed(v, 2)}`, rate1: (v) => num(v, 1), min: (v) => num(v, 1), share: (v) => pct(v, 0) };
const DEF_SHARE = new Set(["dz_share"]);

function defCell(r, v) {
  if (v == null) return "–";
  return (DEF_FMT[r.unit] || ((x) => num(x, 2)))(v);
}

async function renderDefense(el, card, pid, extras) {
  const tag = card.main, M = card[tag];
  if (!M) { el.hidden = true; return; }
  let lg = null;
  try { lg = (await getJSON("data/defense_league.json"))[M.season]; } catch (e) { lg = null; }
  const posName = M.pos === "D" ? "defensemen" : "forwards", posOne = M.pos === "D" ? "defenseman" : "forward";
  S.defMap = DEF_MAPS.some((m) => m.k === S.defMap) ? S.defMap : DEF_MAPS[0].k;
  const cur = card.cur, prev = card.prev;
  const rows = (M.rows || []).map((r) => {
    const other = tag === "cur" ? prev : cur;
    const ov = other ? (other.v || {})[r.k] : null;
    return `<tr><td>${esc(r.label)}</td><td class="tnum">${defCell(r, r.v)}</td><td class="tnum dim">${ov == null ? "–" : defCell(r, ov)}</td>
      <td class="tnum dim">${r.lg == null ? "–" : defCell(r, r.lg)}</td>
      <td><span class="bar-track" data-tip="${esc(`${r.pctile == null ? "Too few players to rank" : `${ordinal(Math.min(99, Math.max(1, Math.round(100 * r.pctile))))} percentile among ${posName}`}${r.k === "dz_share" ? "<br>Context, not quality: a longer bar means harder starts" : r.lower_better ? "<br>Fewer is better, so a long bar is good" : ""}`)}"><span class="bar-fill" style="width:${r.pctile == null ? 0 : 100 * r.pctile}%"></span></span></td></tr>`;
  }).join("");
  const other = tag === "cur" ? (prev && prev.season) : (cur && cur.season);
  const shim = { pos: M.pos, name: card.name, rows: Object.entries(M.map || {}).map(([k, v]) => ({ k, v })) };
  const poolN = (m) => (lg ? lg.rows.filter((r) => r[3] === M.pos && r[lg.keys.indexOf(m.x)] != null && r[lg.keys.indexOf(m.y)] != null).length : 0);
  const mapOK = poolN(DEF_MAPS[0]) >= 25;
  const draw = () => {
    const box = el.querySelector("#defMap"), m = DEF_MAPS.find((x) => x.k === S.defMap);
    if (box && lg && poolN(m) >= 25) box.innerHTML = styleMapSVG(lg, shim, pid, m, Math.max(300, box.clientWidth || 520));
  };
  const cross = [];
  if (extras.eh && extras.eh.rapm_xga60 != null) {
    const r = (extras.eh.rows || []).find((x) => x.k === "rapm_def");
    cross.push(`Evolving-Hockey's RAPM, which also adjusts for teammates, opponents and zone starts: ${signed(extras.eh.rapm_xga60, 2)} expected goals against per 60 in ${esc(extras.eh.season)}${r && r.pctile != null ? ` (${ordinal(Math.min(99, Math.max(1, Math.round(100 * r.pctile))))} percentile)` : ""}.`);
  }
  if (extras.a3z) {
    const d = (extras.a3z.rows || []).find((x) => x.k === "denial_pct");
    const x = (extras.a3z.rows || []).find((x) => x.k === "exit_poss_pct");
    if (d && d.v != null) cross.push(`All Three Zones tracking: he stops ${pct(d.v, 0)} of the zone entries aimed at him${d.pctile != null ? ` (${ordinal(Math.min(99, Math.max(1, Math.round(100 * d.pctile))))} percentile)` : ""}${x && x.v != null ? ` and gets ${pct(x.v, 0)} of his exits out with possession` : ""} (${esc(extras.a3z.season)}).`);
  }
  const v = M.v || {};
  el.innerHTML = `<h2>Defense</h2>
    <p class="lede">How he defends and how he's used, from the NHL's play-by-play and shift charts. Chances against are at five on five and compared with his own team while he sits, which takes out most of the team's quality. Ranks use ${esc(M.season)}${tag === "prev" ? ", the bigger sample" : ""}.</p>
    <div class="plays-notes">${(card.notes || []).map((n) => `<p>${esc(n)}</p>`).join("")}${cross.map((n) => `<p class="cross">${esc(n)}</p>`).join("")}</div>
    <div class="grid-2 plays-grid">
      ${mapOK ? `<div class="figure">
        <div class="chips" role="group" aria-label="Map">${DEF_MAPS.map((m) => `<button type="button" class="chip" data-dmap="${m.k}" aria-pressed="${S.defMap === m.k}">${esc(m.label)}</button>`).join("")}</div>
        <div id="defMap" class="play-map"></div>
        <p class="note">Every ${posOne} with enough 5v5 minutes in ${esc(M.season)}; the lines are the middle of the pack. Hover or tap a dot for the player, tap again to open his page.</p>
      </div>` : ""}
      <div>
        <div class="table-wrap"><table class="mini def-table"><thead><tr><th>${esc(M.season)}</th><th class="tnum">Him</th><th class="tnum">${other ? esc(other) : "Other season"}</th><th class="tnum">Typical</th><th>Rank</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="note">${num(M.toi5, 0)} minutes at 5v5 in ${M.gp} games. Counting stats: ${v.blk ?? 0} blocks, ${v.hits ?? 0} hits, ${v.take ?? 0} takeaways, ${v.give ?? 0} giveaways, ${v.pen_taken ?? 0} penalties taken and ${v.pen_drawn ?? 0} drawn. Hits, takeaways and giveaways are counted by each rink's scorer, so they run high in some buildings.</p>
      </div>
    </div>`;
  el.hidden = false;
  draw();
  bindMapTaps(el.querySelector("#defMap"));
  el.querySelectorAll("[data-dmap]").forEach((b) => b.addEventListener("click", () => {
    S.defMap = b.dataset.dmap;
    el.querySelectorAll("[data-dmap]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.dmap === S.defMap));
    draw();
  }));
}

// touch: the first tap on a dot names the player, a second tap opens his page
function bindMapTaps(box) {
  if (!box) return;
  let armed = null, ptype = "mouse";
  box.addEventListener("pointerdown", (e) => (ptype = e.pointerType));
  box.addEventListener("click", (e) => {
    const link = e.target.closest("a");
    if (!link || ptype === "mouse" || armed === link) return;
    e.preventDefault();
    e.stopPropagation();
    armed = link;
    const r = link.getBoundingClientRect();
    showTip(link, r.left + r.width / 2, r.top);
  });
}

// ------------------------------------------------------------------ goalie pages
const svStr = (x) => (x == null ? "–" : x.toFixed(3).replace(/^0/, ""));
const goalieLink = (id, name) => `<a class="who" href="#goalie/${id}">${esc(name)}</a>`;

async function renderGoalie(view, param) {
  const id = +param;
  const row = (D.goalies || []).find((g) => g.id === id);
  const G = await getJSON(`data/goalies/${id}.json`).catch(() => null);
  if (!G) { view.innerHTML = `<section class="zone"><p class="empty">No goalie page for that id yet.</p><p><a href="#players">Back to players</a></p></section>`; return; }
  const tile = (v, label, sub) => `<div class="stat"><b>${v}</b><span>${label}</span>${sub ? `<small>${sub}</small>` : ""}</div>`;
  const pctTxt = (p) => (p == null ? "" : `${ordinal(Math.min(99, Math.max(1, Math.round(100 * p))))} percentile`);
  const hd = G.bands[2];
  const maxBand = Math.max(...G.bands.map((b) => Math.abs(b.gsax)), 2);
  const bands = G.bands.map((b) => `<div class="mix-row vb-row" data-tip="${esc(`<b>${esc(b.label)}</b><br>${b.sog} shots on goal, ${b.goals} goals<br>Save rate ${svStr(b.sv)} (league ${svStr(b.lg_sv)})<br>${signed(b.gsax, 1)} goals saved above expected`)}">
      <span class="mix-l">${esc(b.label)} <span class="dim">${b.sog} shots</span></span>
      <span class="sv-dots">${svDots(b.sv, b.lg_sv, b.key)}</span>
      <span class="mix-v">${svStr(b.sv)}</span></div>`).join("");
  const log = (G.log || []).map((g) => `<tr><td><a href="#game/${g.game}">${shortDate(g.date)} ${g.home ? "vs" : "at"} ${g.opp || ""}</a>${g.start ? "" : ' <span class="tag">relief</span>'}</td>
      <td class="tnum">${g.dec || "–"}</td><td class="tnum">${g.sa ?? "–"}</td><td class="tnum">${g.ga}</td><td class="tnum">${num(g.xga, 2)}</td><td>${divCell(g.gsax, 3, 1)}</td></tr>`).join("");
  const areas = (G.areas || []).filter((a) => a.sa >= 5).slice(0, 8).map((a) => `<tr><td>${esc(a.area)}</td><td class="tnum">${a.sa}</td><td class="tnum">${svStr(a.sv)}</td><td class="tnum dim">${svStr(a.lg)}</td></tr>`).join("");
  const eh = (G.eh || []).filter((x) => x.gsax != null || x.gar != null).map((x) => `<tr><td>${esc(x.season)}</td><td class="tnum">${x.gp ?? "–"}</td><td class="tnum">${x.gsax == null ? "–" : signed(x.gsax, 1)}</td><td class="tnum">${x.gar == null ? "–" : signed(x.gar, 1)}</td></tr>`).join("");
  view.innerHTML = `
    <section class="zone">
      <div class="phead">
        <div class="ph-photo"><img src="https://assets.nhle.com/mugs/nhl/${esc(D.meta.season)}/${esc(G.team)}/${G.id}.png" alt="" width="128" height="128"
          onerror="this.parentNode.classList.add('ph-none'); this.remove()"></div>
        <div class="ph-text"><h1>${esc(G.name || "Goalie")}</h1>
          <div class="meta">${esc(G.team)}, goalie, ${G.gp} games (${G.starts} starts), ${esc(G.rec)}</div></div>
        <div class="meta ph-bio"><a href="#teams/${esc(G.team)}">${esc(G.team)} team page</a> · <a href="#league">all goalies</a></div>
      </div>
      <div class="stat-row">
        ${tile(signed(G.gsax, 1), "Saves above expected", pctTxt(G.pct.gsax60) ? `${pctTxt(G.pct.gsax60)} per 60` : `${G.ga} allowed on ${num(G.xga, 1)} expected`)}
        ${tile(svStr(G.sv), "Save rate", `${G.sa} shots on goal`)}
        ${tile(svStr(hd.sv), "High-danger save rate", `league ${svStr(hd.lg_sv)}`)}
        ${tile(G.reb == null ? "–" : pct(G.reb, 1), "Saves that become rebounds", `league ${pct(G.lg_reb, 1)}`)}
        ${tile(G.last5 == null ? "–" : signed(G.last5, 1), "Last five starts", "saves above expected")}
        ${tile(G.prev ? signed(G.prev.gsax, 1) : "–", "Last season", G.prev ? `${G.prev.gp} games` : "")}
      </div>
      <div class="plays-notes">${(G.notes || []).map((n) => `<p>${esc(n)}</p>`).join("")}</div>
    </section>
    <section class="zone grid-2 grid-top">
      <div class="figure"><h3>Every unblocked shot he has faced</h3><p class="note">Shots against him this season, all attacking the same net. Bigger dots were better chances; red went in. Tap one for the details.</p>
        ${shotMap(rinkSVG(G.map || [], { label: `${G.name} shots against` }), G.map || [], { kind: "goalie", name: null, id: null })}
        <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Saved or missed</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      <div>
        <h3>Save rate by shot danger</h3>
        <div class="mix">${bands}</div>
        <p class="note"><span class="sv-key me"></span> him <span class="sv-key lg"></span> league. Danger is the shot's expected-goal value: low under 6%, high 15% and up. High-danger saves are where goalies separate, and they take a full season to trust.</p>
        ${areas ? `<h3 class="mix-h">By area (NHL EDGE)</h3><div class="table-wrap"><table class="mini"><thead><tr><th>Area</th><th class="tnum">Shots</th><th class="tnum">Save rate</th><th class="tnum">League</th></tr></thead><tbody>${areas}</tbody></table></div>` : ""}
      </div>
    </section>
    <section class="zone">
      <h2>Start by start</h2>
      <p class="lede">Every appearance this season, newest first. Saves above expected per game swing hard; streaks of five or more starts say more.</p>
      <div class="table-wrap"><table class="mini"><thead><tr><th>Game</th><th class="tnum">Dec</th><th class="tnum">Shots</th><th class="tnum">GA</th><th class="tnum">xGA</th><th>Saves above expected</th></tr></thead><tbody>${log}</tbody></table></div>
      ${eh ? `<h3 class="mix-h">By season (Evolving-Hockey)</h3>
        <div class="table-wrap"><table class="mini"><thead><tr><th>Season</th><th class="tnum">GP</th><th class="tnum">GSAx</th><th class="tnum">GAR</th></tr></thead><tbody>${eh}</tbody></table></div>
        <p class="note">Goals saved above expected and goals above replacement from <a href="https://evolving-hockey.com" target="_blank" rel="noopener">Evolving-Hockey</a>'s models, used with permission. Their expected goals differ a little from ours.</p>` : ""}
      <p class="note">Shot data and expected goals courtesy of MoneyPuck.com. A goalie's season barely predicts his next one, so the model shrinks goalie numbers hard toward average before pricing anything.</p>
    </section>`;
}

function svDots(sv, lg, key) {
  // a save-rate strip for this band: range set so the league sits mid-way
  const span = key === "high" ? [0.55, 0.85] : key === "mid" ? [0.78, 0.95] : [0.92, 1.0];
  const at = (v) => Math.min(100, Math.max(0, (100 * (v - span[0])) / (span[1] - span[0])));
  return `<span class="mix-track">${lg != null ? `<span class="sv-dot lg" style="left:${at(lg)}%"></span>` : ""}${sv != null ? `<span class="sv-dot me" style="left:${at(sv)}%"></span>` : ""}</span>`;
}

// ------------------------------------------------------------------ team tactics
async function renderTactics(el, team) {
  const T = await getJSON(`data/tactics/${team}.json`).catch(() => null);
  if (!T) { el.hidden = true; return; }
  const names = (ps) => ps.map((p) => playerLink(p.id, p.name.split(" ").slice(-1)[0])).join(" – ");
  const share = (v) => (v == null ? "–" : `<span class="share-cell"><span class="share-bar"><span style="width:${100 * v}%"></span></span>${pct(v, 0)}</span>`);
  const grp = (rows, label) => rows.length ? `<div class="table-wrap"><table class="mini"><thead><tr><th>${label}</th><th class="tnum">5v5 min</th><th>xG share</th><th class="tnum hide-sm">Shot share</th><th class="tnum">Goals</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td>${names(r.players)}</td><td class="tnum">${num(r.toi, 0)}</td><td>${share(r.xg_pct)}</td><td class="tnum hide-sm">${pct(r.cf_pct, 0)}</td><td class="tnum">${r.gf}-${r.ga}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">Not enough minutes together yet.</p>`;
  const units = (rows, pp) => rows.length ? `<div class="table-wrap"><table class="mini"><thead><tr><th>${pp ? "Power-play unit" : "Penalty-kill unit"}</th><th class="tnum">Min</th><th class="tnum">${pp ? "xG for" : "xG against"} /60</th><th class="tnum">Goals</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td>${names(r.players)}</td><td class="tnum">${num(r.toi, 0)}</td><td class="tnum">${num(pp ? r.xgf60 : r.xga60, 2)}</td><td class="tnum">${pp ? r.gf : r.ga}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No unit has played enough yet.</p>`;
  const dep = (T.deployment || []).filter((d) => d.gp >= 2).map((d) => `<tr><td>${playerLink(d.id, d.name)}</td><td class="tnum">${num(d.toi5, 1)}</td><td class="tnum">${num(d.pp, 1)}</td><td class="tnum">${num(d.pk, 1)}</td><td class="tnum">${d.shift == null ? "–" : d.shift + " s"}</td>
      <td>${d.oz == null ? "–" : `<span class="zs-bar" data-tip="${esc(`${pct(d.oz, 0)} of his 5v5 faceoffs in the offensive zone, ${pct(d.dz, 0)} in his own end`)}"><span class="zs-oz" style="width:${100 * d.oz}%"></span><span class="zs-dz" style="width:${100 * d.dz}%"></span></span>`}</td></tr>`).join("");
  const st = T.style, sl = T.style_lg || {};
  const styleRow = (k, label, hib, note) => st && st[k] != null ? `<div class="mix-row" data-tip="${esc(`${label}<br>${team}: ${pct(st[k], 0)}<br>League middle: ${pct(sl[k], 0)}${note ? `<br>${note}` : ""}`)}"><span class="mix-l">${esc(label)}</span>
      <span class="mix-track"><span class="mix-fill" style="width:${Math.min(100, 100 * st[k] / 0.7)}%"></span>${sl[k] != null ? `<span class="mix-avg" style="left:${Math.min(100, 100 * sl[k] / 0.7)}%"></span>` : ""}</span><span class="mix-v">${pct(st[k], 0)}</span></div>` : "";
  const top = (T.lines || [])[0], pair = (T.pairs || [])[0];
  const notes = [];
  if (top) notes.push(`The most-used line, ${top.players.map((p) => p.name.split(" ").slice(-1)[0]).join("-")}, has played ${num(top.toi, 0)} minutes together at 5v5 and won ${pct(top.xg_pct, 0)} of the expected goals.`);
  if (pair) notes.push(`The top pair, ${pair.players.map((p) => p.name.split(" ").slice(-1)[0]).join("-")}, has ${num(pair.toi, 0)} minutes together and ${pct(pair.xg_pct, 0)} of the expected goals.`);
  const sp = T.special || {};
  if (sp.pp && sp.pp.toi) notes.push(`Power play: ${num(sp.pp.toi, 0)} minutes, ${num(sp.pp.xgf60, 2)} expected goals per 60, ${sp.pp.gf} goals. Penalty kill: ${num(sp.pk.toi, 0)} minutes, ${num(sp.pk.xga60, 2)} expected against per 60, ${sp.pk.ga} allowed.`);
  el.innerHTML = `<h2>Lines and deployment</h2>
    <p class="lede">Who the coach puts together and when, from the NHL's shift charts. Groups are listed once they have enough minutes; a few games together is noise, so read the minutes column first.</p>
    <div class="plays-notes">${notes.map((n) => `<p>${esc(n)}</p>`).join("")}</div>
    <div class="grid-2 grid-top">
      <div><h3>Forward lines at 5v5</h3>${grp(T.lines || [], "Line")}</div>
      <div><h3>Defense pairs at 5v5</h3>${grp(T.pairs || [], "Pair")}</div>
    </div>
    <div class="grid-2 grid-top">
      <div><h3>Power play</h3>${units(T.pp_units || [], true)}</div>
      <div><h3>Penalty kill</h3>${units(T.pk_units || [], false)}</div>
    </div>
    <h3 class="mix-h">Who plays when</h3>
    <div class="table-wrap"><table class="mini dep-table"><thead><tr><th>Player</th><th class="tnum">5v5 a game</th><th class="tnum">PP</th><th class="tnum">PK</th><th class="tnum">Shift</th><th>Faceoff starts <span class="zs-key oz"></span>offense <span class="zs-key dz"></span>own end</th></tr></thead><tbody>${dep}</tbody></table></div>
    <p class="note">Minutes per game. Faceoff starts count the 5v5 draws a player was on the ice for; the rest happen in the neutral zone. Coaches use own-end starts for players they trust defensively.</p>
    ${st ? `<h3 class="mix-h">How they move the puck (All Three Zones, ${esc(T.style_season)})</h3>
      <div class="mix">${styleRow("carry_in", "Entries carried in", true, "Carrying the puck in leads to far more chances than dumping it")}
        ${styleRow("carry_in_against", "Opponents' entries carried in", false, "Lower is better: the blue line held")}
        ${styleRow("controlled_exits", "Exits with possession", true)}
        ${styleRow("rush_share", "Shots off the rush", null)}</div>
      <p class="note"><span class="mix-key"></span> marks the league middle. Hand-tracked 5v5 play from ${st.games} of their games by Corey Sznajder (allthreezones.com).</p>` : ""}`;
  el.hidden = false;
}
