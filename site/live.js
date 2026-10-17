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
  return game[side + "_goalie_src"] === "espn" ? "ESPN probable starter" : "Projected from recent starts";
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
// players priced tonight who weren't in their team's last lineup (prices assume they play, like a sportsbook prop)
function lineupTag(r) {
  if (!r || !r.lineup || r.lineup === "last") return "";
  const back = r.lineup === "returning";
  const tip = `<b>${back ? "Coming back" : "Not in the last lineup"}</b><br>${esc(r.lineup_note || "")}<br><span class="dim">Price assumes he plays; most books void the bet if he doesn't.</span>`;
  return `<span class="tag tag-lu${back ? " tag-back" : ""}" data-tip="${esc(tip)}">${back ? "Back" : "Scratch?"}</span>`;
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
const LIVE_CODE = { wrist: "w", snap: "s", slap: "l", backhand: "b", "tip-in": "t", deflected: "d", "wrap-around": "r" };
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
          const st = shotType(p.text), dist = Math.round(Math.hypot(89 - p.coordinate.x * dir, p.coordinate.y));
          shots.push([Math.round(p.coordinate.x * dir * side), Math.round(p.coordinate.y * dir * side), Math.round(xg * 1000),
            k === "goal" ? 1 : 0, team === home ? 1 : 0, t, shooter?.athlete?.id || 0, state,
            LIVE_CODE[st] || "", dist, 0, 0, (rebound ? 1 : 0) | (rush ? 2 : 0) | (k === "missed-shot" ? 0 : 4), -1]);
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
    const keep = smKeep(view);
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
        <div class="figure">${gameShotMap({ away: G.away, home: G.home, live: true }, G.shots, G.names)}
          <div class="legend"><span><i style="background:var(--blue);opacity:.5"></i>Shot or miss, sized by chance</span><span><i style="background:var(--red)"></i>Goal</span></div></div>
      </section>`;
    smRestore(view, keep);
    requestAnimationFrame(() => scrollTo(0, y));
    if (!done) LIVE.gameTimer = setTimeout(draw, 60000);
  };
  draw();
}

// ------------------------------------------------------------------ news, reads, listening, watching
// data/news/index.json is written hourly by scripts/write_news.py (stories grouped across outlets,
// worth-reading pieces, podcast episodes, videos, NHL highlight ids per game). ESPN headlines newer
// than that file are merged in live.
const ago = (iso) => {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 60 ? `${Math.max(1, m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
const mins = (s) => (s ? `${Math.round(s / 60)} min` : "");
let NEWS = null;
async function newsIndex() {
  if (NEWS && Date.now() - NEWS.at < 5 * 60000) return NEWS.d;
  try { const r = await fetch(NEWS_INDEX, { cache: "no-cache" }); NEWS = { at: Date.now(), d: r.ok ? await r.json() : {} }; }
  catch (e) { NEWS = { at: Date.now(), d: {} }; }
  const d = NEWS.d;
  if (d.items && !d.stories)   // older single-source format
    d.stories = d.items.map((x) => ({ id: String(x.id), ids: [String(x.id)], title: x.headline, desc: x.description, published: x.published,
      latest: x.published, teams: x.teams || [], players: x.players || [], take: x.take, items: [{ source: "ESPN", title: x.headline, link: x.link, published: x.published }] }));
  for (const k of ["stories", "reads", "listen", "watch", "moves"]) d[k] ||= [];
  d.highlights ||= {};
  return d;
}
const tagged = (x, team, pid) => (!team || (x.teams || []).includes(team)) && (!pid || (x.players || []).some((p) => p.id === pid));
const teamChips = (teams) => (teams || []).length ? ` · ${teams.slice(0, 3).join(", ")}` : "";

function storyCard(st) {
  // one link per outlet (an outlet often files a news brief and a follow-up on the same story); its latest piece
  const byOutlet = new Map();
  for (const i of st.items) byOutlet.set(i.source, i);
  const outlets = [...byOutlet.values()].map((i) => `<a href="${esc(i.link || "#")}" target="_blank" rel="noopener">${esc(i.source)}${i.paywalled ? `<span class="sub" title="Subscription">sub</span>` : ""}</a>`);
  const first = st.take ? st.take.split(/\n\s*\n/)[0] : "";
  return `<article class="news-item">
    <div class="ni-meta">${ago(st.latest || st.published)}${teamChips(st.teams)}</div>
    <h3>${st.take ? `<a href="#news/${esc(st.id)}">${esc(st.title)}</a>` : esc(st.title)}</h3>
    ${st.desc ? `<p class="ni-desc">${esc(st.desc)}</p>` : ""}
    ${st.take ? `<div class="ni-take"><b>Our take.</b> ${esc(first)} <a href="#news/${esc(st.id)}">Read it</a></div>` : ""}
    <div class="ni-src">${outlets.length > 1 ? `Covered by ${outlets.length} outlets:` : st.items.length > 1 ? `${st.items.length} reports:` : "Report:"} ${outlets.join(" · ")}</div>
  </article>`;
}
function readCard(r) {
  return `<article class="read-item">
    <div class="ni-meta">${esc(r.source)}${r.kind === "newsletter" ? " newsletter" : ""}${r.author && r.author !== r.source ? ` · ${esc(r.author)}` : ""} · ${ago(r.published)}${teamChips(r.teams)}${r.paywalled ? " · subscription" : ""}</div>
    <h3><a href="${esc(r.link || "#")}" target="_blank" rel="noopener">${esc(r.title)}</a></h3>
    ${r.desc ? `<p class="ni-desc">${esc(r.desc)}</p>` : ""}
  </article>`;
}
function listenCard(e, i) {
  return `<article class="listen-item">
    ${e.image ? `<img class="pod-art" src="${esc(e.image)}" alt="" loading="lazy" width="56" height="56">` : `<span class="pod-art"></span>`}
    <div>
      <div class="ni-meta">${esc(e.show)} · ${ago(e.published)}${e.duration ? ` · ${mins(e.duration)}` : ""}${teamChips(e.teams)}</div>
      <h3>${esc(e.title)}</h3>
      ${e.desc ? `<p class="ni-desc">${esc(e.desc)}</p>` : ""}
      <div class="pod-actions"><button type="button" class="chip chip-solid" data-play="${i}">Play</button>
        ${e.apple ? `<a href="${esc(e.apple)}" target="_blank" rel="noopener">Apple Podcasts</a>` : ""}${e.link && e.link !== e.apple ? ` <a href="${esc(e.link)}" target="_blank" rel="noopener">Episode</a>` : ""}</div>
      <div class="pod-player" id="pod${i}"></div>
    </div>
  </article>`;
}
// YouTube's own player, loaded only when tapped (thumbnail until then)
function videoCard(v) {
  return `<article class="watch-item">
    <button type="button" class="yt" data-yt="${esc(v.id)}" aria-label="Play ${esc(v.title)}">
      <img src="https://i.ytimg.com/vi/${esc(v.id)}/mqdefault.jpg" alt="" loading="lazy" width="320" height="180"><span class="yt-play" aria-hidden="true"></span></button>
    <div class="ni-meta">${esc(v.channel)} · ${ago(v.published)}${teamChips(v.teams)}</div>
    <h3>${esc(v.title)}</h3>
  </article>`;
}
function bindMedia(root, listen) {
  // safe to call again after more cards are added: each button is wired once
  root.querySelectorAll("[data-play]:not([data-on])").forEach((b) => {
    b.dataset.on = "";
    b.addEventListener("click", () => {
      const e = listen[+b.dataset.play], box = root.querySelector(`#pod${b.dataset.play}`);
      if (!box.innerHTML) box.innerHTML = `<audio controls autoplay preload="none" src="${esc(e.audio)}"></audio>`;
      b.remove();
    });
  });
  root.querySelectorAll("[data-yt]:not([data-on])").forEach((b) => {
    b.dataset.on = "";
    b.addEventListener("click", () => {
      b.outerHTML = `<div class="yt-frame"><iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(b.dataset.yt)}?autoplay=1&rel=0" title="YouTube video"
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen loading="lazy"></iframe></div>`;
    });
  });
}
async function liveEspnStories(d) {
  // ESPN headlines that arrived after the hourly index was written
  const known = new Set(d.stories.flatMap((s) => s.ids || [s.id]));
  const since = d.updated ? new Date(d.updated) : 0;
  try {
    const a = await espn("news?limit=15");
    return (a.articles || []).filter((x) => x.type === "HeadlineNews" && !known.has(String(x.id)) && new Date(x.published) > since)
      .map((x) => ({ id: String(x.id), ids: [String(x.id)], title: x.headline, desc: x.description, published: x.published, latest: x.published,
        teams: (x.categories || []).filter((c) => c.type === "team" && /~l:90~/.test(c.uid || "")).map((c) => ESPN_TEAM[c.teamId]).filter(Boolean),
        players: [], items: [{ source: "ESPN", title: x.headline, link: x.links?.web?.href, published: x.published }] }));
  } catch (e) { return []; }
}

// roster and staff moves: ESPN's transactions feed, gathered hourly by scripts/moves.py
const MOVE_KIND = { trade: "Trade", signing: "Signing", up: "Call-up", down: "Sent down", injury: "Injury list", waivers: "Waivers",
  staff: "Front office", suspension: "Suspension", other: "Roster" };
const MOVE_FILTERS = [["all", "All"], ["trade", "Trades"], ["signing", "Signings"], ["updown", "Up and down"], ["injury", "Injuries"],
  ["waivers", "Waivers"], ["staff", "Front office"]];
const moveMatch = (m, k) => k === "all" || m.kind === k || (k === "updown" && (m.kind === "up" || m.kind === "down"));
let SK_BY = null;
function moveCard(m) {
  SK_BY ||= Object.fromEntries((D.skaters || []).map((x) => [x.id, x]));
  const chips = (m.players || []).map((p) => {
    const s = SK_BY[p.id];
    return s ? `<a class="wchip mv-who" href="#players/${p.id}">${esc(p.name)} <span class="dim">${s.pts} pt${s.pts === 1 ? "" : "s"} in ${s.gp}</span></a>` : `<span class="wchip">${esc(p.name)}</span>`;
  }).join("");
  return `<article class="move-item">
    <div class="ni-meta">${shortDate(m.date)} · <b>${(m.teams || []).join(" / ")}</b> · <span class="mv-kind mv-${m.kind}">${MOVE_KIND[m.kind] || "Roster"}</span></div>
    ${m.items.map((i) => `<p class="mv-text">${m.items.length > 1 ? `<b>${esc(i.team)}:</b> ` : ""}${esc(i.text)}</p>`).join("")}
    ${chips ? `<div class="wc-chips">${chips}</div>` : ""}
    ${m.take ? `<p class="mv-take"><b>What it means.</b> ${esc(m.take)}</p>` : ""}
  </article>`;
}

// News is five tabs over one team filter; all panels stay in the page and only their visibility changes, so a
// podcast keeps playing while you look at another tab. Features are Ice Sheet's own pieces plus worth-reading links.
const NEWS_TABS = [["stories", "Top stories", "Stories"], ["moves", "Moves", "Moves"], ["features", "Features", "Features"], ["listen", "Listen", "Listen"], ["watch", "Watch", "Watch"]];
const NEWS_PAGE = { stories: 12, moves: 20, features: 12, listen: 8, watch: 9 };
async function renderNews(view, id) {
  if (id === "reads") id = "features";   // old links
  const asTab = NEWS_TABS.some(([k]) => k === id);
  view.innerHTML = `<p class="empty">Loading the latest…</p>`;
  if (id && !asTab) return renderTake(view, id);
  const [d, feats] = await Promise.all([newsIndex(), getJSON("data/features.json").catch(() => [])]);
  const fresh = await liveEspnStories(d);
  S.nTeam ||= "all";
  S.mKind ||= "all";
  S.nTab = asTab ? id : S.nTab || "stories";
  const teams = Object.values(ESPN_TEAM).sort();
  const cards = { stories: storyCard, moves: moveCard, features: (x) => (x.slug ? featureCard(x) : readCard(x)), listen: listenCard, watch: videoCard };
  const empty = { stories: "No stories", moves: "No moves", features: "Nothing new to read", listen: "No new episodes", watch: "No new videos" };
  const blurb = {
    stories: "ESPN, The Athletic, The Hockey News and Daily Faceoff, grouped when they cover the same story. Stories about players or teams we track get a short take from Claude using this site's numbers.",
    moves: `Every call-up, assignment, signing, trade, waiver move and front-office change from the last 30 days, as the teams announced them (via ESPN's transactions feed). Trades and staff changes get a short note from Claude using this site's numbers.
      <span class="chips mv-filter" role="group" aria-label="Kind of move">${MOVE_FILTERS.map(([k, l]) => `<button type="button" class="chip" data-mkind="${k}" aria-pressed="${S.mKind === k}">${l}</button>`).join("")}</span>`,
    features: "Our own writing first: a weekly column and deep dives on players and teams, written by Claude from this site's numbers. Then analysis, features and newsletters from elsewhere; links go to the writer's site, and some need a subscription.",
    listen: "32 Thoughts, The Sheet, The Athletic Hockey Show, the PDOcast and more. Play here or in your podcast app.",
    watch: "The Hockey Guy, Hockey Psychology, the PDOcast, Daily Faceoff and more, played through YouTube.",
  };
  const listClass = { stories: "news-list", moves: "move-list", features: "read-list", listen: "listen-list", watch: "watch-grid" };
  let sets = {}, shown = {};
  const draw = () => {
    const team = S.nTeam === "all" ? null : S.nTeam;
    sets = { stories: [...fresh, ...d.stories].filter((x) => tagged(x, team)), moves: d.moves.filter((x) => tagged(x, team) && moveMatch(x, S.mKind)),
      features: [...feats.filter((x) => tagged(x, team)), ...d.reads.filter((x) => tagged(x, team))],
      listen: d.listen.filter((x) => tagged(x, team)), watch: d.watch.filter((x) => tagged(x, team)) };
    shown = Object.fromEntries(NEWS_TABS.map(([k]) => [k, Math.min(NEWS_PAGE[k], sets[k].length)]));
    view.innerHTML = `<section class="zone news-head">
        <div class="news-title"><h1>News</h1>
          <label class="news-team"><span class="sr-only">Team</span><select id="nTeam"><option value="all">All teams</option>${teams.map((t) => `<option ${S.nTeam === t ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
        <p class="lede">Updated hourly${d.updated ? `, last ${ago(d.updated)}` : ""}.</p>
      </section>
      <div class="news-bar" id="newsBar">
        <div class="news-tabs" role="tablist" aria-label="News sections">${NEWS_TABS.map(([k, l, sh]) => `<button type="button" role="tab" id="nt-${k}" aria-controls="np-${k}"
          aria-selected="${S.nTab === k}" tabindex="${S.nTab === k ? 0 : -1}" data-ntab="${k}"><span class="nt-long">${l}</span><span class="nt-short">${sh}</span><span class="nt-n">${sets[k].length}</span></button>`).join("")}</div>
      </div>
      ${NEWS_TABS.map(([k]) => `<section class="zone news-panel" role="tabpanel" id="np-${k}" aria-labelledby="nt-${k}" ${S.nTab === k ? "" : "hidden"}>
        <div class="note np-blurb">${blurb[k]}</div>
        <div class="${listClass[k]}" id="nl-${k}">${sets[k].slice(0, shown[k]).map((x, i) => cards[k](x, i)).join("") || `<p class="empty">${empty[k]}${team ? ` on ${team}` : ""} in the last few days.</p>`}</div>
        ${more(k)}
      </section>`).join("")}`;
    bindMedia(view, sets.listen);
    stick();
  };
  const more = (k) => sets[k].length > shown[k] ? `<div class="controls np-more"><button type="button" class="chip" data-nmore="${k}">Show ${Math.min(NEWS_PAGE[k], sets[k].length - shown[k])} more</button><span class="dim">${shown[k]} of ${sets[k].length}</span></div>` : "";
  // on phones the masthead scrolls away, so the tab bar sticks to the top; on wider screens it sits under the masthead
  const stick = () => {
    const m = $(".masthead"), bar = $("#newsBar");
    if (bar) bar.style.top = m && getComputedStyle(m).position === "sticky" ? `${m.offsetHeight}px` : "0px";
  };
  const pick = (k, focus) => {
    S.nTab = k;
    view.querySelectorAll("[data-ntab]").forEach((b) => { const on = b.dataset.ntab === k; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    view.querySelectorAll(".news-panel").forEach((p) => (p.hidden = p.id !== `np-${k}`));
    history.replaceState(null, "", `#news/${k}`);
    // if the bar is stuck, bring the top of the new tab into view under it
    const bar = $("#newsBar"), top = bar.getBoundingClientRect().top;
    if (top <= parseFloat(bar.style.top || 0) + 1) scrollTo(0, scrollY + $(`#np-${k}`).getBoundingClientRect().top - bar.offsetHeight - parseFloat(bar.style.top || 0));
  };
  view.onclick = (e) => {
    const t = e.target.closest("[data-ntab]");
    if (t) return pick(t.dataset.ntab);
    const mk = e.target.closest("[data-mkind]");
    if (mk) {   // redraw only the moves list, so audio in the Listen tab keeps playing
      S.mKind = mk.dataset.mkind;
      view.querySelectorAll("[data-mkind]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mkind === S.mKind));
      const team = S.nTeam === "all" ? null : S.nTeam;
      sets.moves = d.moves.filter((x) => tagged(x, team) && moveMatch(x, S.mKind));
      shown.moves = Math.min(NEWS_PAGE.moves, sets.moves.length);
      $("#nl-moves").innerHTML = sets.moves.slice(0, shown.moves).map(moveCard).join("") || `<p class="empty">No moves of that kind${team ? ` for ${team}` : ""} in the last 30 days.</p>`;
      const old = $("#np-moves .np-more");
      if (old) old.remove();
      $("#nl-moves").insertAdjacentHTML("afterend", more("moves"));
      $("#nt-moves .nt-n").textContent = sets.moves.length;
      return;
    }
    const m = e.target.closest("[data-nmore]");
    if (m) {
      const k = m.dataset.nmore, from = shown[k];
      shown[k] = Math.min(sets[k].length, from + NEWS_PAGE[k]);
      $(`#nl-${k}`).insertAdjacentHTML("beforeend", sets[k].slice(from, shown[k]).map((x, i) => cards[k](x, from + i)).join(""));
      m.closest(".np-more").outerHTML = more(k);
      bindMedia($(`#np-${k}`), sets.listen);
    }
  };
  view.onkeydown = (e) => {   // arrow keys move between tabs
    if (!e.target.matches("[data-ntab]") || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const i = NEWS_TABS.findIndex(([k]) => k === S.nTab), n = NEWS_TABS.length;
    const j = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n;
    pick(NEWS_TABS[j][0], true);
  };
  view.onchange = (e) => { if (e.target.id === "nTeam") { S.nTeam = e.target.value; draw(); } };
  draw();
}
async function renderTake(view, id) {
  const d = await newsIndex(), st = d.stories.find((x) => x.id === String(id) || (x.ids || []).includes(String(id)));
  if (!st || !st.take) { view.innerHTML = `<section class="zone"><p class="crumbs"><a href="#news">News</a></p><h1>Not written yet</h1><p class="lede">There's no take on that story yet. They're written every hour or two.</p></section>`; return; }
  view.innerHTML = `<section class="zone take">
      <p class="crumbs"><a href="#news">News</a></p>
      <h1>${esc(st.title)}</h1>
      <p class="ni-meta">${ago(st.latest || st.published)}${teamChips(st.teams)}</p>
      <div class="story">${st.take.split(/\n\s*\n/).map((p) => `<p>${esc(p)}</p>`).join("")}</div>
      ${st.players?.length ? `<p class="note">Players in this story: ${st.players.map((p) => playerLink(p.id, p.name)).join(", ")}</p>` : ""}
      <h3 class="kicker">The reports</h3>
      <ul class="plist">${st.items.map((i) => `<li><a href="${esc(i.link || "#")}" target="_blank" rel="noopener">${esc(i.title)}</a> <span class="dim">${esc(i.source)}${i.paywalled ? ", subscription" : ""}, ${ago(i.published)}</span></li>`).join("")}</ul>
      <p class="note">The facts come from the reports above. The analysis is written by Claude from those headlines and this site's own numbers.</p>
    </section>`;
}
// compact "around the league" block for team and player pages
async function relatedMedia(team, pid, label) {
  const d = await newsIndex();
  const stories = d.stories.filter((x) => tagged(x, team, pid)).slice(0, 5);
  const reads = d.reads.filter((x) => tagged(x, team, pid)).slice(0, 4);
  const listen = d.listen.filter((x) => tagged(x, team, pid)).slice(0, 3);
  const watch = d.watch.filter((x) => tagged(x, team, pid)).slice(0, 3);
  if (!stories.length && !reads.length && !listen.length && !watch.length) return "";
  const html = `<section class="zone media-block"><h2>${esc(label)}</h2>
      ${stories.length ? `<div class="news-list">${stories.map(storyCard).join("")}</div>` : ""}
      ${reads.length ? `<h3 class="kicker">Worth reading</h3><div class="read-list">${reads.map(readCard).join("")}</div>` : ""}
      ${listen.length ? `<h3 class="kicker">Listen</h3><div class="listen-list">${listen.map(listenCard).join("")}</div>` : ""}
      ${watch.length ? `<h3 class="kicker">Watch</h3><div class="watch-grid">${watch.map(videoCard).join("")}</div>` : ""}
    </section>`;
  return { html, listen };
}
async function teamNews(team) {
  const r = await relatedMedia(team, null, `Latest on ${team}`);
  return r ? r : "";
}
// official NHL highlight video for a finished game, through YouTube's player
async function gameHighlights(gid) {
  const d = await newsIndex(), vid = d.highlights[String(gid)];
  return vid ? `<section class="zone"><h2>Highlights</h2><div class="hl-video">${videoCard({ id: vid, channel: "NHL on YouTube", title: "Official game highlights", published: null, teams: [] }).replace(/<div class="ni-meta">.*?<\/div>\s*<h3>.*?<\/h3>/s, "")}</div></section>` : "";
}
