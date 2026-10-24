/* The narrative layer on the page: the Pulse tab (who's hot, who's not, and whether it's real), storylines and
   players to watch on previews and Tonight, the story block on player pages and storylines on team pages.
   Everything it shows is written by site/narrative.py from the site's own numbers. */
"use strict";

const VERDICT = {
  earned: ["Earned", "The chances are up too, so this has legs."],
  partly: ["Partly real", "Chances are up a little; finishing is doing most of the work."],
  bounces: ["Bounces", "The chances are normal. Expect it to cool."],
  due: ["Due", "The chances are still there; the goals usually follow."],
  real: ["Real dip", "The chances have dried up too."],
  mixed: ["Mixed", "A few fewer chances, and the ones he gets aren't going in."],
};
const SL_KIND = { streak: "Streak", luck: "Luck", b2b: "Schedule", rest: "Schedule", sched: "Schedule", trip: "Road trip", home: "Home", stand: "Home stand",
  rematch: "Rematch", series: "Series", playoff: "Playoff rematch", division: "Division", injury: "Injury", back: "Returning", new: "New face",
  goalie: "In net", special: "Special teams", market: "Market", milestone: "Milestone", former: "Old team", hometown: "Homecoming",
  vs: "History", hot: "Hot", cold: "Cold" };

// a Hot or Cold tag for tables (props, skaters); the tooltip says whether the chances back it
function formTag(r) {
  if (!r || !r.form) return "";
  const v = VERDICT[r.fv] || ["", ""];
  return `<span class="tag tag-form tag-${r.form}" data-tip="${esc(`<b>${r.form === "hot" ? "Hot" : "Cold"}: ${v[0]}</b><br>${v[1]}<br><span class='dim'>His last ten games compared with what we'd expect at his ice time.</span>`)}">${r.form === "hot" ? "Hot" : "Cold"}</span>`;
}

// storylines: what's going on, and whether the model already accounts for it
function storyList(lines, opts = {}) {
  if (!lines || !lines.length) return "";
  return `<ul class="slines${opts.compact ? " compact" : ""}">${lines.map((x) => {
    const eff = opts.compact || x.priced == null ? "" : `<p class="sl-eff"><span class="sl-priced ${x.priced ? "in" : "out"}">${x.priced ? "Factored in" : "Story only"}</span> ${x.effect ? esc(x.effect) : ""}</p>`;
    const where = opts.game ? `<a class="sl-game" href="#preview/${x.game}">${x.away} at ${x.home}</a>` : "";
    return `<li class="sl"${opts.compact && x.effect ? ` data-tip="${esc(`<b>${x.priced ? "Factored into our numbers" : "Story only, not in our numbers"}</b><br>${x.effect}`)}"` : ""}>
      <span class="sl-team">${x.team || "Both"}</span>
      <div><span class="sl-kind">${SL_KIND[x.k] || ""}</span>${where}<p class="sl-text">${esc(x.text)}</p>${x.ripple ? `<p class="sl-ripple"><b>Who gets his minutes:</b> ${esc(x.ripple)}</p>` : ""}${eff}</div></li>`;
  }).join("")}</ul>`;
}

// players to watch: three a team, with the stories around them and the model's numbers
function watchCards(list) {
  return (list || []).map((w) => `<article class="wcard">
      <div class="wc-head">${playerLink(w.id, w.name)}${w.team ? `<span class="dim">${w.team}</span>` : ""}${typeof injuryTag === "function" ? injuryTag(w.name) : ""}</div>
      <div class="wc-chips">${w.chips.map((c) => `<span class="wchip wchip-${c.k}">${esc(c.t)}</span>`).join("")}</div>
      ${w.why ? `<p class="wc-why">${esc(w.why)}</p>` : ""}
      <p class="wc-line">${esc(w.line)} <span class="dim">Fair: ${fair(w.p_goal)}</span></p>
    </article>`).join("");
}
function watchBlock(watch, teams) {
  if (!watch) return "";
  return `<div class="grid-2">${teams.map((t) => `<div><h3>${t}</h3><div class="wlist">${watchCards(watch[t])}</div></div>`).join("")}</div>`;
}

// one player card for the Pulse lists
function pulseCard(x, kind) {
  const v = VERDICT[x.verdict];
  const head = `<div class="pc-head">${playerLink(x.id, x.name)}<span class="dim">${x.team}${x.pos ? ", " + x.pos : ""}</span>${v ? `<span class="tag tag-v tag-v-${x.verdict}" data-tip="${esc(v[1])}">${v[0]}</span>` : ""}</div>`;
  if (kind === "form") {
    return `<article class="pcard">${head}
      <div class="pc-stat"><b>${x.pts}</b> points in his last ${x.n} <span class="dim">(${x.g} G); about ${num(x.xpts, 1)} expected</span></div>
      <p class="pc-text">${esc(x.why || x.text)}</p></article>`;
  }
  if (kind === "rookie") {
    return `<article class="pcard">${head}<div class="pc-stat"><b>${x.pts}</b> points in ${x.gp} <span class="dim">${x.age ? `age ${x.age}` : ""}</span></div>
      <p class="pc-text">${esc(x.text)}</p></article>`;
  }
  return `<article class="pcard">${head}<p class="pc-text">${esc(x.text)}</p></article>`;
}
const pulseGrid = (items, kind, empty) => items && items.length ? `<div class="pgrid">${items.map((x) => pulseCard(x, kind)).join("")}</div>` : `<p class="empty">${empty}</p>`;
const pulseRows = (items, empty) => items && items.length ? `<ul class="plist prow">${items.map((x) => `<li>${playerLink(x.id, x.name)} <span class="dim">${x.team}</span><span class="pr-text">${esc(x.text)}</span></li>`).join("")}</ul>` : `<p class="empty">${empty}</p>`;

const PULSE_TABS = [["tonight", "Tonight", "Tonight"], ["form", "Hot and cold", "Form"], ["rising", "Breakouts", "Rising"], ["luck", "Luck", "Luck"], ["league", "Goalies, teams, milestones", "League"]];

async function renderPulse(view, tab) {
  view.innerHTML = `<p class="empty">Loading the pulse…</p>`;
  const P = await getJSON("data/pulse.json");
  S.pTab = PULSE_TABS.some(([k]) => k === tab) ? tab : S.pTab || (P.headlines && P.headlines.length ? "tonight" : "form");
  const count = { tonight: (P.headlines || []).length, form: P.hot.length + P.cold.length, rising: P.breakouts.length + P.rookies.length,
    luck: P.cooling.length + P.due.length, league: P.goalies_hot.length + P.goalies_cold.length + P.milestones.length };
  const teamCard = (t) => `<article class="pcard"><div class="pc-head"><a class="who" href="#teams/${t.team}">${t.team}</a><span class="dim">${t.rec}${t.last10 && t.last10 !== t.rec ? `, last ten ${t.last10}` : ""}</span></div>
      ${t.streak ? `<p class="pc-text">${esc(t.streak)}</p>` : ""}${t.luck_text ? `<p class="pc-text">${esc(t.luck_text)}</p>` : ""}</article>`;
  const goalieCard = (g) => `<article class="pcard"><div class="pc-head"><b>${esc(g.name)}</b><span class="dim">${g.team}, ${g.rec} this season</span></div>
      <div class="pc-stat"><b>${signed(g.gsax5, 1)}</b> goals saved above expected <span class="dim">in his last ${g.n5} starts (${g.rec5}), ${svPct(g.sv5)}</span></div></article>`;
  const panels = {
    tonight: () => (P.headlines || []).length ? `
      <h2>Tonight's storylines</h2><p class="lede">The biggest storylines across tonight's games. "Factored in" means it moves our numbers (rest, injuries, goalies, special teams); "Story only" means it's worth knowing but doesn't.</p>
      ${storyList(P.headlines, { game: true })}
      <h2 class="mt">One to watch from each team</h2><p class="lede">One player per team: the likeliest producer, with the story around him (a streak, his old team, a milestone, chances that haven't gone in yet).</p>
      <div class="wlist wgrid">${watchCards(P.watch)}</div>`
      : `<p class="empty">No games tonight. Who's hot, who's rising and who's due are in the other tabs.</p>`,
    form: () => `
      <h2>Who's hot</h2><p class="lede">Points over the last ten games compared with what we'd expect at each player's ice time, and whether his chances back it up. "Earned" means they do; "Bounces" means the puck is going in more than the chances say it should.</p>
      ${pulseGrid(P.hot, "form", "Nobody is far enough above expectation to call hot yet.")}
      <h2 class="mt">Who's cold</h2><p class="lede">"Due" means the chances are still coming and the goals usually follow. "Real dip" means the chances have dried up too.</p>
      ${pulseGrid(P.cold, "form", "Nobody is far enough below expectation to call cold yet.")}
      <div class="grid-2 mt"><div><h3>Streaks</h3>${pulseRows(P.streaks, "No streaks of note.")}</div>
        <div><h3>Droughts</h3>${pulseRows(P.droughts, "No droughts of note.")}</div></div>`,
    rising: () => `
      <h2>Breakouts to watch</h2><p class="lede">Young players whose role (ice time, power play) and chances have both stepped up from last season. Ice time settles within a couple of weeks; scoring takes months.</p>
      ${pulseGrid(P.breakouts, "", "No breakouts that meet the bar yet.")}
      <h2 class="mt">Rookie watch</h2><p class="lede">This season's rookies (the NHL's definition), by production and role.</p>
      ${pulseGrid(P.rookies, "rookie", "No rookies with three games yet.")}`,
    luck: () => `
      <h2>Due to cool off</h2><p class="lede">Scoring well ahead of the chances, or riding unusual luck with them on the ice. The finishing rarely lasts; the chances might.</p>
      ${pulseGrid(P.cooling, "", "Nobody far enough ahead of the chances yet.")}
      <h2 class="mt">Due for more</h2><p class="lede">Getting the chances without the goals. Of everything on this page, this is the likeliest to turn.</p>
      ${pulseGrid(P.due, "", "Nobody far enough behind the chances yet.")}`,
    league: () => `
      <div class="grid-2"><div><h2>Goalies on a heater</h2><p class="lede">Last five starts, goals saved above expected.</p>${P.goalies_hot.length ? `<div class="wlist">${P.goalies_hot.map(goalieCard).join("")}</div>` : `<p class="empty">None yet.</p>`}</div>
        <div><h2>Goalies struggling</h2><p class="lede">Last five starts. Goalie form swings hard and barely carries over from one season to the next, so our projections lean on it only a little.</p>${P.goalies_cold.length ? `<div class="wlist">${P.goalies_cold.map(goalieCard).join("")}</div>` : `<p class="empty">None yet.</p>`}</div></div>
      <h2 class="mt">Teams</h2><p class="lede">Streaks, and records that run ahead of or behind the chances.</p>
      <div class="pgrid">${P.teams.filter((t) => t.streak || t.luck_text).map(teamCard).join("")}</div>
      <h2 class="mt">Milestones in reach</h2><p class="lede">Career numbers before each player's next game.</p>
      ${pulseRows(P.milestones, "Nothing within reach this week.")}`,
  };
  view.innerHTML = `<section class="zone news-head"><h1>The pulse</h1>
      <p class="lede">Who's hot, who's not, and whether it's real. We judge every streak against the chances behind it, so you can tell a player who's earning it from one riding the bounces. ${esc(P.note)}</p></section>
    <div class="news-bar" id="pulseBar"><div class="news-tabs pulse-tabs" role="tablist" aria-label="Pulse sections">${PULSE_TABS.map(([k, l, sh]) => `<button type="button" role="tab" id="pt-${k}" aria-controls="pp-${k}"
      aria-selected="${S.pTab === k}" tabindex="${S.pTab === k ? 0 : -1}" data-ptab="${k}"><span class="nt-long">${l}</span><span class="nt-short">${sh}</span><span class="nt-n">${count[k]}</span></button>`).join("")}</div></div>
    ${PULSE_TABS.map(([k]) => `<section class="zone news-panel pulse-panel" role="tabpanel" id="pp-${k}" aria-labelledby="pt-${k}" ${S.pTab === k ? "" : "hidden"}>${panels[k]()}</section>`).join("")}
    <p class="note">Updated every morning, through ${esc(dateLabel(P.through))}'s games.</p>`;
  const bar = $("#pulseBar"), m = $(".masthead");
  bar.style.top = m && getComputedStyle(m).position === "sticky" ? `${m.offsetHeight}px` : "0px";
  const pick = (k, focus) => {
    S.pTab = k;
    view.querySelectorAll("[data-ptab]").forEach((b) => { const on = b.dataset.ptab === k; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    view.querySelectorAll(".pulse-panel").forEach((p) => (p.hidden = p.id !== `pp-${k}`));
    history.replaceState(null, "", `#pulse/${k}`);
    const top = bar.getBoundingClientRect().top;
    if (top <= parseFloat(bar.style.top || 0) + 1) scrollTo(0, scrollY + $(`#pp-${k}`).getBoundingClientRect().top - bar.offsetHeight - parseFloat(bar.style.top || 0));
  };
  view.onclick = (e) => { const t = e.target.closest("[data-ptab]"); if (t) pick(t.dataset.ptab); };
  view.onkeydown = (e) => {
    if (!e.target.matches("[data-ptab]") || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const i = PULSE_TABS.findIndex(([k]) => k === S.pTab), n = PULSE_TABS.length;
    const j = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n;
    pick(PULSE_TABS[j][0], true);
  };
}
const svPct = (x) => (x == null ? "–" : x.toFixed(3).replace(/^0/, ""));

// the story block on a player page: who he is, his form, and what's around him
// the bio line in the player page header: age, birthplace, size, draft, and his NHL teams when there are several
function playerBio(st) {
  const b = st.bio || {}, bits = [];
  if (b.age) bits.push(`Age ${b.age}`);
  if (b.born) bits.push(`born in ${esc(b.born)}`);
  if (b.height) bits.push(`${b.height}${b.weight ? `, ${b.weight} lb` : ""}`);
  if (b.shoots) bits.push(`shoots ${b.shoots === "L" ? "left" : "right"}`);
  const draft = b.draft ? (b.draft === "Undrafted" ? "Undrafted" : `Drafted ${esc(b.draft)}`) : "";
  const teams = (b.teams || []).length > 1 ? `NHL teams: ${b.teams.map(([t, n]) => `${t} (${n})`).join(", ")}` : "";
  const career = st.career ? `Career: ${st.career.gp.toLocaleString()} games, ${st.career.g} goals, ${st.career.pts.toLocaleString()} points` : "";
  return [bits.join(", "), draft].filter(Boolean).join(". ") + (st.rookie ? ` <span class="tag">Rookie</span>` : "") +
    ((teams || career) ? `<br><span class="dim">${[teams, career].filter(Boolean).join(". ")}</span>` : "");
}
// the story block under the stat tiles: his form, streaks, flags, milestones and tonight's storylines
function playerStory(st) {
  if (!st) return "";
  const f = st.form || {};
  let form = "";
  if (f.state) {
    const v = VERDICT[f.verdict] || ["", ""];
    form = `<p class="ps-form"><span class="tag tag-form tag-${f.state}">${f.state === "hot" ? "Hot" : "Cold"}</span><span class="tag tag-v tag-v-${f.verdict}">${v[0]}</span> ${esc(f.text)}</p>`;
  } else if (f.n >= 3) {
    const near = Math.abs(f.pts - f.xpts) < 1.5;
    form = `<p class="ps-form">${f.pts} points (${f.g} G) in his last ${f.n} games, ${near ? "right about what" : f.pts > f.xpts ? "a little above what" : "a little below what"} we'd expect at his ice time (${num(f.xpts, 1)}).${f.ixg != null ? ` ${num(f.ixg, 1)} expected goals on his own shots.` : ""}</p>`;
  }
  const streaks = (f.streaks || []).map((s) => `<span class="wchip wchip-${s.k === "points" || s.k === "goals" ? "streak" : "due"}">${esc(s.text)}</span>`).join("");
  const flags = (st.flags || []).map((x) => `<li><b>${esc(x.label)}.</b> ${esc(x.text)}</li>`).join("");
  const ms = (st.milestones || []).map((m) => `<li><b>Milestone.</b> ${esc(m.text)}${m.stat === "gp" || m.stat.startsWith("first") ? "" : "."}</li>`).join("");
  const tonight = (st.tonight || []).map((t) => `<li><b>Tonight.</b> ${esc(t)}</li>`).join("");
  return `<div class="pstory">${form}${streaks ? `<div class="wc-chips">${streaks}</div>` : ""}
      ${flags || ms || tonight ? `<ul class="notes">${tonight}${flags}${ms}</ul>` : ""}</div>`;
}

// ------------------------------------------------------------------ our own writing (scripts/write_features.py)
const FEATURE_KIND = { column: "Around the league", player: "Player deep dive", team: "Team deep dive" };
const readMins = (w) => `${Math.max(1, Math.round((w || 0) / 230))} min read`;
function featureCard(f) {
  return `<article class="news-item feat-item">
    <div class="ni-meta"><span class="feat-kind">${FEATURE_KIND[f.kind] || "Feature"}</span> · ${shortDate(f.date)} · ${readMins(f.words)}</div>
    <h3><a href="#feature/${esc(f.slug)}">${esc(f.title)}</a></h3>
    ${f.dek ? `<p class="ni-desc">${esc(f.dek)}</p>` : ""}
  </article>`;
}
const featureLink = (f) => `<a class="feat-link" href="#feature/${esc(f.slug)}"><span class="feat-kind">${FEATURE_KIND[f.kind]}</span> ${esc(f.title)} <span class="dim">${shortDate(f.date)}</span></a>`;
async function renderFeature(view, slug) {
  view.innerHTML = `<p class="empty">Loading…</p>`;
  let f;
  try { f = await getJSON(`data/features/${slug}.json`); } catch (e) {
    view.innerHTML = `<section class="zone"><p class="crumbs"><a href="#news/features">Features</a></p><h1>Not found</h1><p class="lede">We couldn't find that piece. Everything we've published is on the <a href="#news/features">Features</a> tab.</p></section>`;
    return;
  }
  const body = f.text.split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean)
    .map((x) => (x.startsWith("## ") ? `<h3>${esc(x.slice(3))}</h3>` : `<p>${esc(x)}</p>`)).join("");
  const subj = f.kind === "player" && f.subject?.id ? `<a href="#players/${f.subject.id}">${esc(f.subject.name)}'s page</a>` :
    f.kind === "team" ? `<a href="#teams/${esc(f.subject.team)}">the ${esc(f.subject.team)} page</a>` : `<a href="#pulse">the Pulse</a>`;
  view.innerHTML = `<article class="zone feature">
      <p class="crumbs"><a href="#news/features">Features</a></p>
      <p class="kicker">${FEATURE_KIND[f.kind] || "Feature"}</p>
      <h1>${esc(f.title)}</h1>
      ${f.dek ? `<p class="lede feat-dek">${esc(f.dek)}</p>` : ""}
      <p class="byline">Read the Ice · Written with AI from our data · ${new Date(f.date + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })} · ${readMins(f.words)}</p>
      <div class="story feature-body">${body}</div>
      <p class="note ai-note">How this was made: an AI model (Claude, by Anthropic) wrote this piece from our data only. Shot data and expected goals courtesy of MoneyPuck.com; game, shift and tracking data from the NHL. There's no outside reporting: no interviews, quotes or inside information. More on ${subj}, and on <a href="#about/ai">how we use AI</a>.</p>
    </article>`;
}
