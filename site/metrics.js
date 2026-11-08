// Win probability, wins added, the playoff race, talent ranges, possession value and "plays like".
// Data: games/<id>.json .wp, clutch.json, race.json, players/<id>.json .range .wins .like, a3z card .value, a3z_value.json.

const wpPeriod = (t) => (t >= 3600 ? "OT" : ["1st", "2nd", "3rd"][Math.floor(t / 1200)]);
const wpClock = (t) => { const s = t >= 3600 ? t - 3600 : t % 1200; return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`; };

// ------------------------------------------------------------------ game page: win probability through the game
function wpChart(g, wp) {
  const W = mainW(1000), H = Math.max(220, Math.round(W * 0.28)), m = { l: 44, r: 56, t: 14, b: 32 };
  const s = wp.series;
  const end = Math.max(3600, s[s.length - 1][0]);
  const X = (t) => m.l + (t / end) * (W - m.l - m.r), Y = (p) => m.t + (1 - p) * (H - m.t - m.b);
  const line = "M" + s.map(([t, p]) => `${X(t).toFixed(1)},${Y(p).toFixed(1)}`).join(" L");
  const area = (above) => `M${X(s[0][0])},${Y(0.5)} ` + s.map(([t, p]) => `L${X(t).toFixed(1)},${Y(above ? Math.max(p, 0.5) : Math.min(p, 0.5)).toFixed(1)}`).join(" ") + ` L${X(s[s.length - 1][0])},${Y(0.5)} Z`;
  const periods = [1200, 2400, 3600].filter((t) => t < end).map((t) => `<line class="grid" x1="${X(t)}" x2="${X(t)}" y1="${m.t}" y2="${H - m.b}"/>`).join("");
  const plabels = ["1st", "2nd", "3rd", "OT"].map((l, i) => (i * 1200 < end ? `<text x="${X(Math.min(i * 1200 + 600, (i * 1200 + end) / 2))}" y="${H - 10}" text-anchor="middle">${l}</text>` : "")).join("");
  const yl = [[1, `${g.home} 100%`], [0.75, "75%"], [0.5, "50%"], [0.25, "75%"], [0, `${g.away} 100%`]]
    .map(([p, l]) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(p)}" y2="${Y(p)}"/><text x="${W - m.r + 6}" y="${Y(p) + 4}">${esc(l)}</text>`).join("");
  // hover bands: one per stretch between recorded points, so any spot on the chart names the moment
  const bands = s.slice(0, -1).map(([t, p], i) => {
    const t2 = s[i + 1][0], hp = p;
    const lead = hp >= 0.5 ? `${g.home} ${pct(hp)}` : `${g.away} ${pct(1 - hp)}`;
    return `<rect x="${X(t)}" y="${m.t}" width="${Math.max(1, X(t2) - X(t))}" height="${H - m.t - m.b}" fill="transparent" data-tip="${esc(`${wpPeriod(t)} ${wpClock(t)}<br>${lead} to win`)}"/>`;
  }).join("");
  const hy = (q) => (q.team === g.home ? q.after : 1 - q.after);   // goals carry the scorer's side; the chart is the home side
  const dots = wp.goals.map((q) => {
    const team = q.team, gain = Math.abs(q.swing);
    return `<g data-tip="${esc(`<b>${esc(q.name || "Goal")}</b> ${team}, ${q.period >= 4 ? "OT" : wpPeriod(q.t)} ${wpClock(q.t)}<br>${team} win chance ${pct(q.before)} to ${pct(q.after)} (+${Math.round(100 * gain)} points)`)}">
      <circle cx="${X(q.t)}" cy="${Y(hy(q))}" r="10" fill="transparent"/><circle cx="${X(q.t)}" cy="${Y(hy(q))}" r="5" fill="var(--red)" stroke="var(--sheet)" stroke-width="2"/></g>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${g.home} win probability through the game`)}">
    ${yl}${periods}
    <path d="${area(true)}" fill="var(--th, var(--blue))" opacity=".22"/><path d="${area(false)}" fill="var(--ta, var(--ink))" opacity=".18"/>
    <line x1="${m.l}" x2="${W - m.r}" y1="${Y(0.5)}" y2="${Y(0.5)}" stroke="var(--muted)" stroke-width="1"/>
    <path d="${line}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
    ${bands}${dots}${plabels}</svg>`;
}

function renderWP(el, g) {
  const wp = g.wp;
  if (!el || !wp || !wp.series || wp.series.length < 3) return;
  const swing = [...wp.goals].sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing)).slice(0, 3);
  const goalLine = (q) => {
    const fav = q.before, aft = q.after;
    return `<li><b>${q.id ? playerLink(q.id, q.name) : esc(q.name || "Goal")}</b> <span class="dim">${q.team}, ${q.period >= 4 ? "OT" : wpPeriod(q.t)} ${wpClock(q.t)}</span><br>
      ${q.team} went from ${pct(fav)} to ${pct(aft)} to win.</li>`;
  };
  const sv = wp.save;
  el.innerHTML = `<h2>Who was going to win, moment by moment</h2>
    <p class="lede">Our win probability through the game, from the score, the clock, power plays and pulled goalies, using how often teams in each spot went on to win over the last two seasons. Above the middle line, ${esc(g.home)} were favored; below it, ${esc(g.away)}. Red dots are goals.</p>
    <div class="figure">${wpChart(g, wp)}</div>
    <div class="grid-2 wp-notes">
      <div><h3>The goals that swung it</h3><ol class="notes">${swing.map(goalLine).join("") || `<li class="dim">No goals.</li>`}</ol></div>
      <div>${sv ? `<h3>The save that mattered most</h3><p><b><a class="who" href="#goalie/${sv.goalie}">${esc(sv.name)}</a></b> stopped ${esc(sv.shooter || "a shot")} in the ${sv.period >= 4 ? "overtime" : wpPeriod(sv.t)} (${wpClock(sv.t)} in). The chance went in ${pct(sv.xg)} of the time, and a goal there would have moved the win chance ${Math.round(100 * Math.abs(sv.swing))} points.</p>` : ""}
        ${wp.top && wp.top.length ? `<h3>Who added the most</h3><ul class="notes">${wp.top.map((x) => `<li>${playerLink(x.id, x.name)}: ${num(x.added, 2)} of a win</li>`).join("")}</ul>
        <p class="note">Wins added: each goal earns its scorer the jump in win chance it caused; each save earns its goalie the shot's chance of going in times the jump a goal would have caused.</p>` : ""}</div>
    </div>`;
  el.hidden = false;
}

// ------------------------------------------------------------------ League: the playoff race and wins added
async function renderRace(el) {
  let R;
  try { R = await getJSON("data/race.json"); } catch (e) { return; }
  if (!el || !R || !R.rows) return;
  const fav = myTeam();
  S.raceConf ||= fav && R.rows.find((r) => r.team === fav)?.conf || "East";
  const draw = () => {
    const rows = R.rows.filter((r) => r.conf === S.raceConf).sort((a, b) => b.playoffs - a.playoffs || b.pts - a.pts).map((r) => ({ ...r, id: r.team }));
    el.querySelector("#raceT").innerHTML = table(rows, [
      { key: "team", label: "Team", nosort: true, fmt: (r) => `<a class="who" href="#teams/${r.team}">${r.team}</a><span class="sub">${esc(r.div)}</span>` },
      { key: "gp", label: "GP", nosort: true },
      { key: "pts", label: "Pts", nosort: true },
      { key: "xpts", label: "Deserved", nosort: true, fmt: (r) => `${num(r.xpts, 1)} <span class="sub">${signed(r.luck, 1)}</span>` },
      { key: "proj", label: "Projected", nosort: true, fmt: (r) => `${Math.round(r.proj)} <span class="sub">${r.lo} to ${r.hi}</span>` },
      { key: "playoffs", label: "Playoffs", nosort: true, fmt: (r) => cellBar(r.playoffs, 1) },
      { key: "division", label: "Wins division", nosort: true, fmt: (r) => pct(r.division), cls: "hide-sm" },
    ], null, "race-t");
    if (fav) el.querySelector(`tr[data-id="${fav}"]`)?.classList.add("is-mine");
    el.querySelectorAll("[data-rconf]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.rconf === S.raceConf));
  };
  el.innerHTML = `<h2>The playoff race</h2>
    <p class="lede">The rest of the season played ${R.sims.toLocaleString()} times. Each team's strength blends the chances it creates and allows with its goals, pulled toward last season and the league average because ${Math.round(R.rows.reduce((a, r) => a + r.gp, 0) / R.rows.length)} games is still a small sample, and every simulated season redraws how good each team really is. Deserved points replay every game from its shots: what the team's chances usually earn. The number beside it is points banked above or below that. Projected is the middle of the simulations with an 80% range.</p>
    <div class="chips" role="group" aria-label="Conference">${["East", "West"].map((c) => `<button type="button" class="chip" data-rconf="${c}">${c === "East" ? "Eastern" : "Western"} Conference</button>`).join("")}</div>
    <div id="raceT"></div>
    <p class="note">Top three in each division plus two wild cards per conference make it; ties go to regulation wins. ${R.games_left} regular-season games left. Odds assume today's rosters stay healthy.</p>`;
  el.querySelectorAll("[data-rconf]").forEach((b) => b.addEventListener("click", () => { S.raceConf = b.dataset.rconf; draw(); }));
  draw();
  el.hidden = false;
}

async function renderClutch(el) {
  let C;
  try { C = await getJSON("data/clutch.json"); } catch (e) { return; }
  if (!el || !C) return;
  const team = Object.fromEntries([...D.skaters, ...(D.goalies || [])].map((p) => [p.id, p.team]));
  const sk = C.skaters.slice(0, 12), gk = C.goalies.slice(0, 8), gb = [...C.goalies].reverse().slice(0, 3);
  const li = (r, v, sub, href) => `<li><a class="who" href="${href}">${esc(r.name)}</a> <span class="dim">${team[r.id] || ""}</span> <b>${num(v, 2)}</b>${sub ? ` <span class="sub">${sub}</span>` : ""}</li>`;
  el.innerHTML = `<h2>Wins added</h2>
    <p class="lede">Not every goal is worth the same. A tying goal with three minutes left moves a team's chance of winning far more than a sixth goal in a blowout. We credit every goal with the jump in win probability it caused, and every save with what the shot was likely to cost. Totals are in wins.</p>
    <div class="grid-2">
      <div><h3>Skaters: wins added by their goals</h3><ol class="rank-list">${sk.map((r) => li(r, r.goals, `${signed(r.clutch, 2)} vs his chances`, `#players/${r.id}`)).join("")}</ol>
        <p class="note">"Vs his chances" compares his total with what his shots would add on average from the same moments: above zero means his goals came in bigger spots or went in more often than the chances suggest.</p></div>
      <div><h3>Goalies: wins added by their saves</h3><ol class="rank-list">${gk.map((r) => li(r, r.saves_added, `${r.shots} shots`, `#goalie/${r.id}`)).join("")}</ol>
        ${gb.length ? `<p class="note">Furthest below zero: ${gb.map((r) => `<a class="who" href="#goalie/${r.id}">${esc(r.name)}</a> ${signed(r.saves_added, 2)}`).join(", ")}.</p>` : ""}</div>
    </div>`;
  el.hidden = false;
}

// ------------------------------------------------------------------ player and goalie pages: skill, luck, projection
function rangeBar(label, r, now, lg, fmt, max) {
  const at = (v) => Math.max(0, Math.min(100, (100 * v) / max));
  return `<div class="rbar" data-tip="${esc(`<b>${esc(label)}</b><br>Our estimate of his true level: ${fmt(r[1])} (80% range ${fmt(r[0])} to ${fmt(r[2])})${now != null ? `<br>This season so far: ${fmt(now)}` : ""}${lg != null ? `<br>Typical at his position: ${fmt(lg)}` : ""}`)}">
    <span class="rb-l">${esc(label)}</span>
    <span class="rb-track">
      <span class="rb-band" style="left:${at(r[0])}%;width:${at(r[2]) - at(r[0])}%"></span>
      <span class="rb-mid" style="left:${at(r[1])}%"></span>
      ${lg != null ? `<span class="mix-avg" style="left:${at(lg)}%"></span>` : ""}
      ${now != null ? `<span class="rb-now" style="left:${at(now)}%"></span>` : ""}
    </span>
    <span class="rb-v">${fmt(r[1])}</span></div>`;
}

function rangeSentence(label, r, now, fmt, small) {
  if (now == null) return "";
  if (now > r[2]) return `His ${fmt(now)} ${label} so far is above the range we think is real (${fmt(r[0])} to ${fmt(r[2])}): expect it to cool${small ? ", and the sample is still small" : ""}.`;
  if (now < r[0]) return `His ${fmt(now)} ${label} so far is below the range we think is real (${fmt(r[0])} to ${fmt(r[2])}): there's better to come.`;
  return `His ${fmt(now)} ${label} so far sits inside the range we think is real (${fmt(r[0])} to ${fmt(r[2])}).`;
}

function winsLine(w, name) {
  if (!w) return "";
  if (w.kind === "goalie")
    return `<p>${esc(name)}'s saves have added <b>${num(w.saves_added, 2)}</b> wins this season, ${ordinal(w.rank)} of ${w.of} goalies, counting each save by what the shot was likely to cost at that moment of the game.</p>`;
  if (!w.goals) return "";
  return `<p>His goals have added <b>${num(w.goals, 2)}</b> wins this season, ${ordinal(w.rank)} among ${w.of} skaters who have scored. ${Math.abs(w.clutch) >= 0.15 ? (w.clutch > 0
    ? `That's ${num(w.clutch, 2)} more than his chances usually add from the same moments: big-spot goals and finishing.`
    : `That's ${num(-w.clutch, 2)} less than his chances usually add from the same moments.`) : "About what his chances usually add from the same moments."}</p>`;
}

function renderRange(el, file, p) {
  const r = file.range, w = file.wins;
  if (!el || (!r && !w)) return;
  const small = (p.gp || 0) < 25;
  const p60 = (v) => num(v, 2), shp = (v) => `${num(v, 1)}%`;
  el.innerHTML = `<h2>Skill, luck and where he's headed</h2>
    <p class="lede">What his numbers say about his real level once the bounces are taken out, and where his season is likely to end up. Each estimate starts from his position's average, adds last season at a discount, then this season; the more he plays, the more his own numbers count.</p>
    <div class="grid-2">
      <div>
        ${r ? `${rangeBar("Points per 60", r.pts60, r.pts60_now, r.pts60_lg, p60, Math.max(5, r.pts60[2] * 1.15, (r.pts60_now || 0) * 1.05))}
        ${rangeBar("Shooting %", r.sh, r.sh_now, r.sh_lg, shp, Math.max(25, r.sh[2] * 1.3, (r.sh_now || 0) * 1.05))}
        <p class="note rb-key"><span class="rb-band-k"></span> 80% range for his true level <span class="rb-now-k"></span> this season <span class="mix-key"></span> typical at his position</p>
        <p>${esc(rangeSentence("points per 60", r.pts60, r.pts60_now, p60, small))} ${esc(r.sog >= 20 ? rangeSentence("shooting", r.sh, r.sh_now, shp, small) : "")}</p>` : ""}
      </div>
      <div>
        ${r && r.games_left && r.toi_recent ? `<h3>How his season ends</h3>
          <div class="stat-row stat-row-2"><div class="stat"><b>${r.proj_pts[1]}</b><span>Points</span><small>${r.proj_pts[0]} to ${r.proj_pts[2]}</small></div>
          <div class="stat"><b>${r.proj_g[1]}</b><span>Goals</span><small>${r.proj_g[0]} to ${r.proj_g[2]}</small></div></div>
          <p class="note">If he plays all ${r.games_left} of his team's remaining games at his recent ${num(r.toi_recent, 1)} minutes a night. Injuries, scratches and role changes all pull these down; the range covers luck and our uncertainty about his level, not missed games.</p>` : ""}
        ${w ? `<h3>Wins added</h3>${winsLine(w, p.name)}` : ""}
      </div>
    </div>`;
  el.hidden = false;
}

function renderGoalieRange(el, G) {
  const r = G.range, w = G.wins;
  if (!el || (!r && !w)) return;
  const sv = (v) => (v == null ? "–" : v.toFixed(3).replace(/^0/, ""));
  const lo = Math.min(r ? r.sv[0] : 0.9, r && r.sv_now != null ? r.sv_now : 1, 0.9) - 0.005, hi = Math.max(r ? r.sv[2] : 0.93, r && r.sv_now != null ? r.sv_now : 0, 0.935) + 0.005;
  const shifted = (x) => [x[0] - lo, x[1] - lo, x[2] - lo];
  el.innerHTML = `<h2>Skill or a hot run</h2>
    <p class="lede">Goalie seasons swing more than almost anything in hockey: a goalie's save rate this year says little about next year's. So we lean hard on the league average and last season, and let this season move the estimate slowly. Save rates here are against league-average shots, so a goalie who faces harder shots isn't punished for it.</p>
    <div class="grid-2"><div>
      ${r ? `${rangeBar("Save %", shifted(r.sv), r.sv_now == null ? null : r.sv_now - lo, r.sv_lg - lo, (v) => sv(v + lo), hi - lo)}
      <p class="note rb-key"><span class="rb-band-k"></span> 80% range for his true level <span class="rb-now-k"></span> this season <span class="mix-key"></span> league average</p>
      <p>${esc(r.sv_now == null ? "" : rangeSentence("save rate against average shots", r.sv, r.sv_now, sv, true))}</p>` : ""}
    </div><div>${w ? `<h3>Wins added</h3>${winsLine(w, G.name)}` : ""}</div></div>`;
  el.hidden = false;
}

// ------------------------------------------------------------------ plays like
function renderLike(el, like, name) {
  if (!el || !like || !like.comps || !like.comps.length) return;
  el.innerHTML = `<h2>Plays like</h2>
    <p class="lede">The ${like.pos === "D" ? "defensemen" : "forwards"} whose game looks most like ${esc(name)}'s over this season and last: how they're used, how much and from where they shoot, how they set others up, what happens on the ice with them, and, where we have them, skating, shot speed and hand-tracked zone play. 100 would be identical.</p>
    <ul class="like-list">${like.comps.map((c) => `<li><div class="like-top"><a class="who" href="#players/${c.id}">${esc(c.name)}</a> <span class="dim">${c.team}</span><b class="like-score">${c.match}</b></div>
      ${c.shared.length ? `<div class="sub">Both: ${esc(c.shared.join(", "))}</div>` : ""}</li>`).join("")}</ul>`;
  el.hidden = false;
}

// ------------------------------------------------------------------ possession value (All Three Zones), inside "How he plays"
function possessionBlock(v, pos, tbl) {
  if (!v || !v.rows) return "";
  const posName = pos === "D" ? "defensemen" : "forwards";
  const lab = { total_v: "Total", entry_v: "Zone entries", exit_v: "Zone exits", deny_v: "Entries denied" };
  const lim = Math.max(0.12, ...v.rows.map((r) => Math.abs(r.v)));
  const at = (x) => 50 + (50 * x) / lim;
  const bars = v.rows.map((r) => `<div class="mix-row vb-row" data-tip="${esc(`<b>${lab[r.k]}</b><br>${signed(r.v, 3)} expected goals per 60 vs a typical ${pos === "D" ? "defenseman" : "forward"}${r.pctile != null ? `<br>${ordinal(Math.min(99, Math.max(1, Math.round(100 * r.pctile))))} percentile among ${posName}` : ""}`)}">
      <span class="mix-l">${lab[r.k]}</span>
      <span class="mix-track vb-track"><span class="vb-zero"></span><span class="vb-fill ${r.v < 0 ? "vb-neg" : ""}" style="left:${Math.min(at(r.v), 50)}%;width:${Math.abs(at(r.v) - 50)}%"></span></span>
      <span class="mix-v">${signed(r.v, 3)}</span></div>`).join("");
  const worth = tbl ? `<table class="worth"><thead><tr><th>Play</th><th>Net chances after</th></tr></thead><tbody>
      ${[...tbl.entry, ...tbl.exit].map((x) => `<tr><td>${esc(x.label)}${tbl.exit.includes(x) ? " <span class=\"dim\">(exit)</span>" : " <span class=\"dim\">(entry)</span>"}</td><td>${signed(x.net, 3)}</td></tr>`).join("")}</tbody></table>
      <p class="note">Expected goals for minus against in the ${Math.round(tbl.window)} seconds after each kind of play, from ${tbl.n.entries.toLocaleString()} tracked entries and ${tbl.n.exits.toLocaleString()} exits.</p>` : "";
  return `<h3 class="mix-h">What his puck moving is worth <span class="dim">(${esc(v.season)})</span></h3>
    <div class="grid-2 plays-grid"><div><div class="vbars">${bars}</div>
      <p class="note">Each carry-in, dump-in, failed entry, exit and denial is valued by the chances that usually follow it; these are his plays' value above a typical ${pos === "D" ? "defenseman" : "forward"}, in expected goals per 60 minutes at five on five.</p></div>
      <div>${worth}</div></div>`;
}

// ------------------------------------------------------------------ live win probability (mirrors analysis/winprob.py)
function wpModel(P) {
  if (!P || !P.rate) return null;
  const r = (k, home) => P.rate[`${k}|${home ? "h" : "a"}`];
  const cal = (p) => { p = Math.min(1 - 1e-6, Math.max(1e-6, p)); const [a, b] = P.cal || [0, 1]; return 1 / (1 + Math.exp(-(a + b * Math.log(p / (1 - p))))); };
  const pois = (lam, n = 24) => { const o = [Math.exp(-lam)]; for (let i = 1; i <= n; i++) o.push((o[i - 1] * lam) / i); return o; };
  const side = (sc, home) => {
    const c = String(sc || "1551").padStart(4, "0"), ag = +c[0], as = +c[1], hs = +c[2], hg = +c[3];
    const [og, xg, own, opp] = home ? [hg, ag, hs, as] : [ag, hg, as, hs];
    return og === 0 ? "en_att" : xg === 0 ? "en_def" : own > opp ? "pp" : own < opp ? "pk" : "ev";
  };
  const lam = (home, left, st, ppl) => {
    if (st !== "pp" && st !== "pk") return r("ev", home) * left;
    const d = Math.min(ppl, left);
    return r("ev", home) * (left - d) + r(st, home) * d;
  };
  return {
    at(diff, t, period, sc, penEnd) {
      if (period >= 4) {
        if (diff) return diff > 0 ? 1 : 0;
        const left = Math.max(0, 3900 - t), rh = r("ot", true) * left, ra = r("ot", false) * left;
        const any = 1 - Math.exp(-(rh + ra));
        return cal(any * (rh / Math.max(rh + ra, 1e-9)) + (1 - any) * 0.5);
      }
      let hs = side(sc, true), as = side(sc, false);
      if (hs.startsWith("en") || as.startsWith("en")) hs = as = "ev";
      const left = Math.max(0, 3600 - t);
      let ppl = 60;
      if (hs === "pp" || hs === "pk") { const ends = Object.values(penEnd || {}).filter((v) => v > t); ppl = ends.length ? Math.min(...ends) - t : 60; }
      let lh = lam(true, left, hs, ppl), la = lam(false, left, as, ppl);
      for (const [k, secs] of Object.entries(P.pull || {})) {
        const n = +k, s = left <= 180 ? Math.min(left, secs) : 0, th = diff === -n ? s : 0, ta = diff === n ? s : 0;
        lh += th * (r("en_att", true) - r("ev", true)) + ta * (r("en_def", true) - r("ev", true));
        la += ta * (r("en_att", false) - r("ev", false)) + th * (r("en_def", false) - r("ev", false));
      }
      const H = pois(Math.max(lh, 1e-9)), A = pois(Math.max(la, 1e-9));
      let win = 0, tie = 0;
      H.forEach((ph, i) => A.forEach((pa, j) => { const m = i - j + diff; if (m > 0) win += ph * pa; else if (m === 0) tie += ph * pa; }));
      return cal(win + tie * P.ot_home);
    },
  };
}

// ------------------------------------------------------------------ Claude's writing, read live
// A scheduled Claude session writes recaps, previews, takes and player/team writeups (WRITING.md) and commits them
// to data/stories/; the site reads them live through our data relay (proxy/api/data.js) so they show without a rebuild. Until one exists,
// the page keeps whatever the build put there (the API writer's version, or nothing).
const STORIES_RAW = "https://readtheice-api.vercel.app/api/data?path=stories/";
const WRITER_LABEL = `<p class="ai-label">Written by Claude, an AI, from our data and the season's story. Opinions and hunches are labeled as ours. <a href="#about/ai">How we use AI</a></p>`;
async function writerInto(el, path, opts = {}) {
  if (!el) return;
  const here = location.hash;
  let d;
  try {
    const r = await fetch(`${STORIES_RAW}${esc(D.meta.season)}/${path}`, { cache: "no-cache" });
    if (!r.ok) return;
    d = await r.json();
  } catch (e) { return; }
  if (!d || d.by !== "session" || !d.text || location.hash !== here || !el.isConnected) return;
  const paras = d.text.trim().split(/\n\s*\n/).map((p) => `<p>${esc(p)}</p>`).join("");
  const h = d.hunch && d.hunch.text && opts.hunch ? `<aside class="hunch"><b>Our hunch</b> ${esc(d.hunch.text)}</aside>` : "";
  el.innerHTML = `${opts.kicker ? `<h3 class="kicker">${esc(opts.kicker)}</h3>` : ""}${d.headline ? `<h2 class="story-head">${esc(d.headline)}</h2>` : ""}
    <div class="story">${paras}</div>${h}${WRITER_LABEL}`;
  el.classList.add("writer");
}
