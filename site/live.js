/* Live layer, all from ESPN's public site API (it allows browser requests; the NHL's own API doesn't).
   1. Scoreboard every 30 s while tonight's games are on: score, clock, shots, probable goalies.
   2. Per-game feed every 60 s on an open live game page: shot map, chance flow and deserved-to-win,
      each shot rated by our in-game xG model (analysis/xg_live.py; MoneyPuck's xG only exists next morning).
   3. The nightly build's full game page takes over the next morning.
   Also: ESPN injuries (flags on the odds) and headlines (News tab, with Claude's takes from data/news).
   ESPN's rink coordinates are the NHL's; ESPN credits a blocked shot to the blocking team. */
"use strict";

const ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl";
const ESPN_TEAM = { 1: "BOS", 2: "BUF", 3: "CGY", 4: "CHI", 5: "DET", 6: "EDM", 7: "CAR", 8: "LAK", 9: "DAL", 10: "MTL",
  11: "NJD", 12: "NYI", 13: "NYR", 14: "OTT", 15: "PHI", 16: "PIT", 17: "COL", 18: "SJS", 19: "STL", 20: "TBL", 21: "TOR",
  22: "VAN", 23: "WSH", 25: "ANA", 26: "FLA", 27: "NSH", 28: "WPG", 29: "CBJ", 30: "MIN", 37: "VGK", 124292: "SEA", 129764: "UTA" };
const ESPN_ID = Object.fromEntries(Object.entries(ESPN_TEAM).map(([k, v]) => [v, k]));
const NEWS_INDEX = "https://raw.githubusercontent.com/Tolar-dio/NHL-Analytics/main/data/news/index.json";
const normName = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim();

const LIVE = { games: {}, byNhl: {}, at: 0, timer: null, ready: null, injuries: null, gameTimer: null, probSig: "" };

async function espn(path) {
  const r = await fetch(`${ESPN}/${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`ESPN ${r.status}`);
  return r.json();
}

// ------------------------------------------------------------------ layer 1: scoreboard
function parseBoard(d) {
  const out = {};
  for (const e of d.events || []) {
    const c = e.competitions[0], st = c.status, ty = st.type;
    const A = c.competitors.find((x) => x.homeAway === "away"), H = c.competitors.find((x) => x.homeAway === "home");
    if (!A || !H) continue;
    const ab = (x) => ESPN_TEAM[x.team.id] || x.team.abbreviation;
    const stat = (x, n) => +((x.statistics || []).find((s) => s.name === n)?.displayValue || 0);
    const prob = (x) => (x.probables || []).find((p) => p.name === "probableStartingGoalie")?.athlete?.displayName || null;
    const a = +A.score || 0, h = +H.score || 0;
    out[`${ab(A)}@${ab(H)}`] = {
      eid: e.id, away: ab(A), home: ab(H), a, h, state: ty.state, detail: ty.shortDetail, period: st.period,
      clock: st.displayClock, start: e.date, final: !!ty.completed,
      sog_a: stat(H, "saves") + a, sog_h: stat(A, "saves") + h,   // a team's shots = the other goalie's saves + its goals
      prob: { [ab(A)]: prob(A), [ab(H)]: prob(H) },
    };
  }
  return out;
}

function liveStart() {
  if (LIVE.ready || !D.tonight || !D.tonight.games.length) return LIVE.ready;
  const day = D.tonight.date.replace(/-/g, "");
  const tick = async () => {
    try {
      LIVE.games = parseBoard(await espn(`scoreboard?dates=${day}`));
      for (const g of D.tonight.games) { const L = LIVE.games[`${g.away}@${g.home}`]; if (L) LIVE.byNhl[g.id] = L; }
      LIVE.at = Date.now();
      liveApply();
    } catch (e) { /* keep the last good board */ }
    const all = Object.values(LIVE.byNhl);
    clearTimeout(LIVE.timer);
    if (!(all.length && all.every((g) => g.state === "post")) && !document.hidden)
      LIVE.timer = setTimeout(tick, all.some((g) => g.state === "in") ? 30000 : 120000);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { clearTimeout(LIVE.timer); tick(); } });
  LIVE.ready = tick();
  liveInjuries();
  return LIVE.ready;
}

// ESPN writes "7:07 - 1st" (time left) and "20:00 - 2nd" (period about to start)
function liveStatus(L) {
  if (!L) return "";
  if (L.state === "pre") return timeMT(L.start);
  if (L.state === "post") return L.detail || "Final";
  const m = /^(\d+:\d+) - (.+)$/.exec(L.detail || "");
  if (!m) return L.detail || "Live";
  return m[1] === "20:00" || (m[1] === "5:00" && /OT/.test(m[2])) ? `${m[2]} starting` : `${m[1]} left, ${m[2]}`;
}

function liveApply() {
  // probable goalies change the odds: redraw Tonight when they first arrive or change (before filling the cards)
  const sig = JSON.stringify(Object.values(LIVE.byNhl).map((L) => L.prob));
  if (sig !== LIVE.probSig) {
    LIVE.probSig = sig;
    if ((location.hash || "#tonight").startsWith("#tonight") && !document.activeElement?.matches("input,select")) {
      const y = scrollY; renderTonight($("#view")); requestAnimationFrame(() => scrollTo(0, y));
    }
  }
  // site-wide strip
  const strip = $("#liveStrip");
  const games = D.tonight.games.map((g) => ({ g, L: LIVE.byNhl[g.id] })).filter((x) => x.L);
  if (strip) {
    strip.hidden = !games.length;
    strip.innerHTML = games.map(({ g, L }) => `<a class="ls-game ls-${L.state}" href="#${L.state === "pre" ? "preview" : "live"}/${g.id}">
      <span class="ls-sc"><span class="ls-t">${g.away}</span> <b>${L.state === "pre" ? "" : L.a}</b><span class="ls-sep">${L.state === "pre" ? "at" : ""}</span><span class="ls-t">${g.home}</span> <b>${L.state === "pre" ? "" : L.h}</b></span>
      <span class="ls-st">${L.state === "in" ? `<i class="live-dot" aria-hidden="true"></i>` : ""}${esc(liveStatus(L))}</span></a>`).join("");
  }
  fillLiveLines();
}
function fillLiveLines() {
  $$(".live-line[data-live]").forEach((el) => {
    const L = LIVE.byNhl[el.dataset.live];
    el.innerHTML = !L || L.state === "pre" ? "" : `<a href="#live/${el.dataset.live}">${L.state === "in" ? `<i class="live-dot" aria-hidden="true"></i>` : ""}<b>${L.away} ${L.a}, ${L.home} ${L.h}</b> <span class="dim">${esc(liveStatus(L))}. Shots ${L.sog_a}-${L.sog_h}.</span> <span class="ll-go">Live page</span></a>`;
  });
}

// The goalie ESPN lists as probable, if he's one of the model's options for that team
function probableId(game, side) {
  const L = LIVE.byNhl[game.id], name = L?.prob?.[game[side]];
  if (!name) return null;
  const o = (game[side + "_goalies"] || []).find((x) => normName(x.name) === normName(name));
  return o ? o.id : null;
}
function goalieSource(game, side) {
  if (S.goalies[game.id]?.[side] != null) return "Your pick";
  const L = LIVE.byNhl[game.id], name = L?.prob?.[game[side]];
  if (probableId(game, side) != null) return "ESPN probable starter";
  if (name) return `ESPN lists ${name}, who isn't in the model's options`;
  return "Projected from recent starts";
}

// ------------------------------------------------------------------ injuries
async function liveInjuries() {
  if (LIVE.injuries && Date.now() - LIVE.injuries.at < 15 * 60000) return LIVE.injuries;
  try {
    const d = await espn("injuries");
    const map = {};
    for (const t of d.injuries || []) for (const x of t.injuries || []) {
      const st = x.status || "", abbr = /reserve/i.test(st) ? "IR" : /day/i.test(st) ? "DTD" : /out/i.test(st) ? "Out" : st;
      map[normName(x.athlete?.displayName)] = { status: st, abbr, team: ESPN_TEAM[t.id], what: x.details?.type || "",
        back: x.details?.returnDate || "", note: x.shortComment || "" };
    }
    LIVE.injuries = { at: Date.now(), map };
    const h = location.hash || "#tonight";
    if ((h.startsWith("#tonight") || h.startsWith("#preview") || h.startsWith("#fantasy")) && !document.activeElement?.matches("input,select")) {
      const y = scrollY; route(); requestAnimationFrame(() => scrollTo(0, y));
    }
  } catch (e) { /* injuries are a nice-to-have */ }
  return LIVE.injuries;
}
function injuryOf(name) { return LIVE.injuries?.map[normName(name)] || null; }
function injuryTag(name) {
  const x = injuryOf(name);
  if (!x) return "";
  const cls = x.abbr === "DTD" ? "dtd" : "out";
  const tipTxt = `<b>${esc(x.status)}</b>${x.what ? `, ${esc(x.what)}` : ""}${x.back ? `<br>Expected back ${esc(x.back)}` : ""}${x.note ? `<br>${esc(x.note)}` : ""}<br><span class="dim">ESPN injury report</span>`;
  return `<span class="tag tag-inj tag-${cls}" data-tip="${esc(tipTxt)}">${esc(x.abbr)}</span>`;
}

// ------------------------------------------------------------------ layer 2: live game page
const KIND = { Shot: "shot-on-goal", Missed: "missed-shot", Goal: "goal", Blocked: "blocked-shot" };
const SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around"];
const shotType = (text) => {
  const m = /(wrist shot|snap shot|slap shot|backhand|tip-in|deflected|wrap-around|wrap around)/i.exec(text || "");
  return !m ? "other" : ({ "wrist shot": "wrist", "snap shot": "snap", "slap shot": "slap", "wrap around": "wrap-around" })[m[1].toLowerCase()] || m[1].toLowerCase();
};
// mirrors features() in analysis/xg_live.py
function featurise(x, y, dir, type, state, rebound, rush) {
  const nx = 89 * dir, dist = Math.hypot(nx - x, y), angle = (Math.atan2(Math.abs(y), Math.abs(nx - x)) * 180) / Math.PI;
  const f = { dist, log_dist: Math.log1p(dist), angle, dist_x_angle: dist * angle, rebound, rush, pp: +(state === "PP"), sh: +(state === "SH") };
  for (const t of [...SHOT_TYPES, "other"]) f["st_" + t] = +(type === t);
  return f;
}
function xgOf(m, f) {
  let z = m.intercept;
  m.features.forEach((n, i) => { z += m.coef[i] * (((f[n] ?? 0) - m.mean[i]) / m.std[i]); });
  return 1 / (1 + Math.exp(-z));
}
function pbDist(ps) {
  let d = [1];
  for (const p of ps) { const n = new Array(d.length + 1).fill(0); d.forEach((v, i) => { n[i] += v * (1 - p); n[i + 1] += v * p; }); d = n; }
  return d;
}
function deserveHome(home, away) {
  const H = pbDist(home), A = pbDist(away);
  let w = 0, t = 0;
  H.forEach((ph, i) => A.forEach((pa, j) => { if (i > j) w += ph * pa; else if (i === j) t += ph * pa; }));
  return w + t / 2;
}

function buildLive(sum, g0, model) {
  const home = g0.home, away = g0.away, other = (t) => (t === home ? away : home);
  const plays = (sum.plays || []).filter((p) => p.period && p.period.number < 5);
  const secs = (p) => { const [m, s] = (p.clock?.displayValue || "0:00").split(":").map(Number); return (p.period.number - 1) * 1200 + m * 60 + (s || 0); };
  const teamOf = (p) => ESPN_TEAM[p.team?.id];
  const shooterTeam = (p) => (p.type.text === "Blocked" ? other(teamOf(p)) : teamOf(p));
  // which net each team attacks in each period, from where its attempts came from
  const votes = {};
  for (const p of plays) if (KIND[p.type.text] && p.coordinate) { const k = shooterTeam(p) + p.period.number; votes[k] = (votes[k] || 0) + Math.sign(p.coordinate.x); }
  const dirOf = (team, per) => {
    if (votes[team + per]) return Math.sign(votes[team + per]);
    if (votes[other(team) + per]) return -Math.sign(votes[other(team) + per]);
    return per > 1 ? -dirOf(team, per - 1) : team === home ? 1 : -1;
  };
  const names = {}, shots = [], goals = [], pens = [], attempts = { [away]: 0, [home]: 0 }, sogP = {};
  let prev = null;
  for (const p of plays) {
    (p.participants || []).forEach((x) => { if (x.athlete) names[x.athlete.id] = x.athlete.displayName; });
    const k = KIND[p.type.text], t = secs(p);
    if (p.type.penaltyMinutes) pens.push({ per: p.period.number, clock: p.clock?.displayValue, team: teamOf(p), text: p.text, min: p.type.penaltyMinutes });
    if (k) {
      const team = shooterTeam(p);
      attempts[team] = (attempts[team] || 0) + 1;
      if (k !== "blocked-shot") {
        if (k !== "missed-shot") { const key = p.period.number + team; sogP[key] = (sogP[key] || 0) + 1; }
        const state = { "power-play": "PP", "short-handed": "SH" }[p.strength?.abbreviation] || "EV";
        let xg = null;
        if (p.coordinate && model) {
          const dir = dirOf(team, p.period.number), dt = prev ? t - secs(prev) : 99;
          const rebound = prev && KIND[prev.type.text] && dt <= 3 ? 1 : 0;
          const rush = prev && prev.coordinate && dt <= 4 && !["Face Off", "Stoppage"].includes(prev.type.text) && prev.coordinate.x * dir <= 25 ? 1 : 0;
          xg = xgOf(model, featurise(p.coordinate.x, p.coordinate.y, dir, shotType(p.text), state, rebound, rush));
          const side = team === home ? 1 : -1;
          const shooter = (p.participants || []).find((x) => x.type === "shooter" || x.type === "scorer");
          shots.push([Math.round(p.coordinate.x * dir * side), Math.round(p.coordinate.y * dir * side), Math.round(xg * 1000),
            k === "goal" ? 1 : 0, team === home ? 1 : 0, t, shooter?.athlete?.id || 0, state]);
        }
        if (k === "goal") goals.push({ per: p.period.number, clock: p.clock?.displayValue, team, text: p.text, xg, state,
          score: `${p.awayScore}-${p.homeScore}`, head: (p.participants || []).find((x) => x.type === "scorer")?.athlete?.headshot?.href });
      }
    }
    prev = p;
  }
  const xh = shots.filter((s) => s[4] === 1).map((s) => s[2] / 1000), xa = shots.filter((s) => s[4] === 0).map((s) => s[2] / 1000);
  const box = {};
  for (const t of sum.boxscore?.teams || []) {
    const ab = ESPN_TEAM[t.team?.id];
    box[ab] = Object.fromEntries((t.statistics || []).map((s) => [s.name, s.displayValue]));
  }
  const lastPer = Math.max(1, ...plays.map((p) => p.period.number));
  return { home, away, shots, goals, pens, names, attempts, sogP, box, lastPer,
    xg_h: xh.reduce((a, b) => a + b, 0), xg_a: xa.reduce((a, b) => a + b, 0), dtw_home: deserveHome(xh, xa) };
}

async function renderLive(view, id) {
  const g0 = (D.tonight.games || []).find((x) => String(x.id) === String(id));
  if (!g0) { view.innerHTML = `<section class="zone"><h1>Not tonight</h1><p class="lede">Live pages exist for tonight's games. <a href="#games">Every finished game is here</a>.</p></section>`; return; }
  view.innerHTML = `<p class="empty">Connecting to the game…</p>`;
  const here = location.hash;
  const model = await getJSON("data/xg_live.json").catch(() => null);
  await liveStart();
  clearTimeout(LIVE.gameTimer);
  const gen = (LIVE.gen = (LIVE.gen || 0) + 1);   // a redraw of this page (resize) retires the old loop
  const draw = async () => {
    if (location.hash !== here || gen !== LIVE.gen) return;          // left the page: stop polling
    const L = LIVE.byNhl[g0.id];
    if (!L || L.state === "pre") {
      view.innerHTML = `<section class="zone"><p class="crumbs"><a href="#tonight">Tonight</a></p><h1>${g0.away} at ${g0.home}</h1>
        <p class="lede">Puck drop ${timeMT(g0.start)}. This page goes live when the game starts. <a href="#preview/${g0.id}">Read the preview</a>.</p></section>`;
      LIVE.gameTimer = setTimeout(draw, 60000);
      return;
    }
    let sum;
    try { sum = await espn(`summary?event=${L.eid}`); } catch (e) { LIVE.gameTimer = setTimeout(draw, 60000); return; }
    if (location.hash !== here || gen !== LIVE.gen) return;
    const G = buildLive(sum, g0, model);
    const [cm, cs] = String(L.clock || "0:00").split(":").map(Number), rem = (cm || 0) * 60 + (cs || 0);
    const now = L.state === "post" ? null : L.period >= 4 ? 3600 + Math.max(0, 300 - rem) : (L.period - 1) * 1200 + (1200 - rem);
    D._names = G.names;
    const winner = L.h > L.a ? G.home : L.a > L.h ? G.away : null;
    const lead = G.dtw_home >= 0.5 ? G.home : G.away, share = Math.max(G.dtw_home, 1 - G.dtw_home);
    const bx = (t, k) => G.box[t]?.[k] ?? "–";
    const stat = (label, a, h) => `<div class="vs"><span>${a ?? "–"}</span><b>${label}</b><span>${h ?? "–"}</span></div>`;
    const pers = Array.from({ length: G.lastPer }, (_, i) => i + 1);
    const perLabel = (p) => (p > 3 ? "OT" : ["", "1st", "2nd", "3rd"][p]);
    const updated = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
    const done = L.state === "post";
    const y = scrollY;
    view.innerHTML = `
      <section class="zone">
        <p class="crumbs"><a href="#tonight">Tonight</a></p>
        <h1>${G.away} ${L.a}, ${G.home} ${L.h}</h1>
        <p class="lede">${done ? `<b>${esc(L.detail || "Final")}.</b> The full breakdown with shifts, goal replays and MoneyPuck's chance ratings arrives with tomorrow morning's build.`
          : `<i class="live-dot" aria-hidden="true"></i><b>${esc(liveStatus(L))}.</b> Updates every minute (last ${updated}).`} Chances below are rated by our in-game model.</p>
        <div class="game-open">
          <div>
            <h3 class="kicker">Goals</h3>
            ${G.goals.length ? `<ol class="goal-list">${G.goals.map((x) => `<li class="goal-item">${headshot(x.head, "")}
              <div><div class="gi-top"><span class="gi-when">${perLabel(x.per)} ${esc(x.clock || "")}</span> <span class="gi-team">${x.team}</span></div>
              <div class="gi-sub">${esc(x.text)}${x.xg != null ? `. A ${pct(x.xg)} chance` : ""}${x.state !== "EV" ? `, ${x.state === "PP" ? "power play" : "shorthanded"}` : ""}. <span class="dim">${G.away} ${x.score.split("-")[0]}, ${G.home} ${x.score.split("-")[1]}</span></div></div></li>`).join("")}</ol>`
              : `<p class="note">No goals yet.</p>`}
            <h3 class="kicker">By period</h3>
            <div class="table-wrap ls-wrap"><table class="linescore"><thead><tr><th></th><th></th>${pers.map((p) => `<th>${perLabel(p)}</th>`).join("")}<th class="tot">Total</th></tr></thead><tbody>
              <tr><th rowspan="2" class="grp">Shots</th><th scope="row">${G.away}</th>${pers.map((p) => `<td>${G.sogP[p + G.away] || 0}</td>`).join("")}<td class="tot">${L.sog_a}</td></tr>
              <tr><th scope="row">${G.home}</th>${pers.map((p) => `<td>${G.sogP[p + G.home] || 0}</td>`).join("")}<td class="tot">${L.sog_h}</td></tr>
              <tr class="brk"><th rowspan="2" class="grp">xG</th><th scope="row">${G.away}</th>${pers.map((p) => `<td>${num(G.shots.filter((s) => s[4] === 0 && Math.min(4, Math.floor(s[5] / 1200) + 1) === p).reduce((a, s) => a + s[2] / 1000, 0), 2)}</td>`).join("")}<td class="tot">${num(G.xg_a, 2)}</td></tr>
              <tr><th scope="row">${G.home}</th>${pers.map((p) => `<td>${num(G.shots.filter((s) => s[4] === 1 && Math.min(4, Math.floor(s[5] / 1200) + 1) === p).reduce((a, s) => a + s[2] / 1000, 0), 2)}</td>`).join("")}<td class="tot">${num(G.xg_h, 2)}</td></tr>
            </tbody></table></div>
            <h3 class="kicker">Penalties</h3>
            ${G.pens.length ? `<ol class="pen-list">${G.pens.map((x) => `<li><span class="gi-when">${perLabel(x.per)} ${esc(x.clock || "")}</span> <span class="gi-team">${x.team || ""}</span> ${esc(x.text)} <span class="dim">${x.min} min</span></li>`).join("")}</ol>` : `<p class="note">None yet.</p>`}
          </div>
          <div>
            <div class="deserve" data-tip="${esc("Every shot so far replayed thousands of times using its chance of going in; ties split evenly")}">
              <div class="bignum">${pct(share)}</div>
              <p>of replays of the shots so far go ${lead}'s way.${winner && winner !== lead ? (done ? ` ${winner} won it anyway.` : ` ${winner} leads on the scoreboard anyway.`) : ""}</p>
            </div>
            <div class="vs-grid">
              <div class="vs vs-head"><span>${G.away}</span><b></b><span>${G.home}</span></div>
              ${stat("Expected goals", num(G.xg_a, 2), num(G.xg_h, 2))}
              ${stat("Shot attempts", G.attempts[G.away], G.attempts[G.home])}
              ${stat("Shots on goal", L.sog_a, L.sog_h)}
              ${stat("Power play", `${bx(G.away, "powerPlayGoals")}/${bx(G.away, "powerPlayOpportunities")}`, `${bx(G.home, "powerPlayGoals")}/${bx(G.home, "powerPlayOpportunities")}`)}
              ${stat("Faceoffs won", bx(G.away, "faceoffsWon"), bx(G.home, "faceoffsWon"))}
              ${stat("Hits", bx(G.away, "hits"), bx(G.home, "hits"))}
              ${stat("Blocked shots", bx(G.away, "blockedShots"), bx(G.home, "blockedShots"))}
            </div>
            <p class="note">Score, shots and game stats from ESPN. ${model ? `In-game chance model: trained on ${model.shots.toLocaleString()} shots from the last two seasons. It ranks shots a little less sharply than MoneyPuck's model, which the morning page uses (AUC ${model.auc} vs about 0.78).` : ""}</p>
          </div>
        </div>
      </section>
      <section class="zone">
        <h2>How the chances are piling up</h2>
        <div class="figure">${flowChart({ shots: G.shots, end: G.lastPer > 3 || L.period > 3 ? "OT" : "REG", away: G.away, home: G.home, now })}
          <div class="legend"><span><i style="background:var(--ink)"></i>${G.away}</span><span><i style="background:var(--blue)"></i>${G.home}</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      </section>
      <section class="zone">
        <h2>Every shot so far</h2>
        <div class="figure">${fullRinkSVG(G.shots, G.away, G.home)}
          <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss, sized by chance</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      </section>`;
    requestAnimationFrame(() => scrollTo(0, y));
    if (!done) LIVE.gameTimer = setTimeout(draw, 60000);
  };
  draw();
}

// ------------------------------------------------------------------ news
const ago = (iso) => {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 60 ? `${Math.max(1, m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
async function takes() {
  try { const r = await fetch(NEWS_INDEX, { cache: "no-cache" }); if (!r.ok) return {}; const d = await r.json(); return Object.fromEntries((d.items || []).map((x) => [String(x.id), x])); }
  catch (e) { return {}; }
}
function newsItem(a, take) {
  const teams = (a.categories || []).filter((c) => c.type === "team").map((c) => ESPN_TEAM[c.teamId]).filter(Boolean);
  const link = a.links?.web?.href;
  return `<article class="news-item">
    <div class="ni-meta">${ago(a.published)}${teams.length ? ` · ${[...new Set(teams)].join(", ")}` : ""}</div>
    <h3>${take ? `<a href="#news/${a.id}">${esc(a.headline)}</a>` : esc(a.headline)}</h3>
    ${a.description ? `<p class="ni-desc">${esc(a.description)}</p>` : ""}
    ${take ? `<p class="ni-take"><b>Our take:</b> ${esc(take.take.split(/(?<=\.)\s/)[0])} <a href="#news/${a.id}">Read it</a></p>` : ""}
    ${link ? `<a class="ni-src" href="${esc(link)}" target="_blank" rel="noopener">Full story on ESPN</a>` : ""}
  </article>`;
}
async function renderNews(view, id) {
  view.innerHTML = `<p class="empty">Loading the latest…</p>`;
  if (id) return renderTake(view, id);
  const [d, T] = await Promise.all([espn("news?limit=40").catch(() => ({ articles: [] })), takes()]);
  const arts = (d.articles || []).filter((a) => a.type === "HeadlineNews" || a.type === "Story");
  view.innerHTML = `<section class="zone">
      <h1>News</h1>
      <p class="lede">The latest NHL headlines from ESPN. When a story involves players or teams we track, Claude writes a short take on what our numbers say about it, usually within a couple of hours.</p>
      <div class="news-list">${arts.map((a) => newsItem(a, T[String(a.id)])).join("") || `<p class="empty">No headlines right now.</p>`}</div>
    </section>`;
}
async function renderTake(view, id) {
  const T = await takes(), x = T[String(id)];
  if (!x) { view.innerHTML = `<section class="zone"><p class="crumbs"><a href="#news">News</a></p><h1>Not written yet</h1><p class="lede">There's no take on that story yet. They're written every hour or two.</p></section>`; return; }
  view.innerHTML = `<section class="zone take">
      <p class="crumbs"><a href="#news">News</a></p>
      <h1>${esc(x.headline)}</h1>
      <p class="ni-meta">Reported by ESPN ${ago(x.published)}${x.teams?.length ? ` · ${x.teams.join(", ")}` : ""}</p>
      <div class="story">${x.take.split(/\n\s*\n/).map((p) => `<p>${esc(p)}</p>`).join("")}</div>
      ${x.players?.length ? `<p class="note">Players in this story: ${x.players.map((p) => playerLink(p.id, p.name)).join(", ")}</p>` : ""}
      <p class="note">The facts of the story come from ESPN's report${x.link ? ` (<a href="${esc(x.link)}" target="_blank" rel="noopener">read it here</a>)` : ""}. The analysis is written by Claude from this site's own numbers.</p>
    </section>`;
}
async function teamNews(team) {
  const id = ESPN_ID[team];
  if (!id) return "";
  const [d, T] = await Promise.all([espn(`news?team=${id}&limit=12`).catch(() => ({ articles: [] })), takes()]);
  const recent = (a) => Date.now() - new Date(a.published) < 14 * 864e5;
  const arts = (d.articles || []).filter((a) => (a.type === "HeadlineNews" || a.type === "Story") && recent(a)).slice(0, 5);
  return arts.length ? `<section class="zone"><h2>Latest on ${team}</h2><div class="news-list">${arts.map((a) => newsItem(a, T[String(a.id)])).join("")}</div></section>` : "";
}
