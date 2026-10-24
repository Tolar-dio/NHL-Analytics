/* Player dossiers and coverage: "Path to the NHL" and "Background" (from the nightly build, site/dossier.py),
   "The buzz" on player pages and "From the room" on team pages (live from data/coverage/, written hourly by
   scripts/buzz.py and read straight from GitHub so it doesn't wait for the nightly deploy).
   Loaded before app.js; reuses $, esc, table, playerLink, teamName, ago, bindMedia. */
"use strict";

const COVERAGE = "https://raw.githubusercontent.com/Tolar-dio/NHL-Analytics/main/data/coverage/";
const covCache = {};
async function coverage(path) {
  if (!covCache[path]) covCache[path] = fetch(COVERAGE + path, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return covCache[path];
}
const ppg = (p, gp) => (gp ? (p / gp).toFixed(2) : "–");
const statLine = (r) => `${r.gp} GP, ${r.g} G, ${r.a} A, ${r.p} P`;

// ---------------------------------------------------------------- Path to the NHL
function renderPath(el, d, name) {
  if (!el || !d || (!d.notes?.length && !d.pre?.length && !d.wiki)) return;
  const last = (name || "").split(" ").slice(1).join(" ") || name;
  const dr = d.draft;
  const near = (x) => (x ? (x.id && (D.skaters.some((s) => s.id === x.id) || (D.goalies || []).some((g) => g.id === x.id))
    ? playerLink(x.id, x.name) : esc(x.name)) + ` <span class="dim">(${esc(x.team)})</span>` : "");
  const draftCard = dr && dr.overall ? `<div class="dcard">
      <div class="dc-pick"><b>${dr.overall}</b><span>overall</span></div>
      <div><div class="dc-line"><b>${dr.year} draft</b>, round ${dr.round}, by ${esc(teamName(dr.team))}</div>
        ${dr.club ? `<div class="dim">From ${esc(dr.club)}${dr.league ? ` (${esc(dr.league)})` : ""}</div>` : ""}
        ${dr.cs && dr.cs.final ? `<div class="dc-cs">Central Scouting: <b>No. ${dr.cs.final}</b> among ${esc(dr.cs.cat)}${dr.cs.mid && dr.cs.mid !== dr.cs.final ? ` <span class="dim">(No. ${dr.cs.mid} at midterm)</span>` : ""}</div>` : ""}
        ${dr.before || dr.after ? `<div class="dim dc-near">${dr.before ? `Pick before: ${near(dr.before)}` : ""}${dr.before && dr.after ? " · " : ""}${dr.after ? `Pick after: ${near(dr.after)}` : ""}</div>` : ""}
      </div></div>`
    : `<div class="dcard"><div class="dc-pick dc-und"><b>–</b><span>undrafted</span></div><div class="dc-line">Signed as a free agent</div></div>`;
  const pre = (d.pre || []).slice().reverse();
  const svs = (x) => (x == null ? `<span class="dim">–</span>` : x.toFixed(3).replace(/^0/, ""));
  const preTable = !pre.length ? "" : d.pos === "G" ? table(pre.map((r, i) => ({ ...r, id: i })), [
    { key: "season", label: "Season", nosort: true },
    { key: "league", label: "League", nosort: true, fmt: (r) => `${esc(r.league)}<div class="sub">${esc((r.teams || []).join(", "))}</div>` },
    { key: "gp", label: "GP", nosort: true }, { key: "w", label: "W", nosort: true, fmt: (r) => r.w ?? "–" },
    { key: "sv", label: "Save %", nosort: true, fmt: (r) => svs(r.sv) },
    { key: "gaa", label: "GAA", nosort: true, cls: "hide-sm", fmt: (r) => (r.gaa == null ? `<span class="dim">–</span>` : r.gaa.toFixed(2)) },
    { key: "po", label: "Playoffs", nosort: true, cls: "hide-sm", fmt: (r) => (r.po ? `${r.po.gp} GP` : `<span class="dim">–</span>`) },
  ], null, "dpath") : table(pre.map((r, i) => ({ ...r, id: i })), [
    { key: "season", label: "Season", nosort: true },
    { key: "league", label: "League", nosort: true, fmt: (r) => `${esc(r.league)}<div class="sub">${esc((r.teams || []).join(", "))}</div>` },
    { key: "gp", label: "GP", nosort: true }, { key: "g", label: "G", nosort: true, cls: "hide-sm" }, { key: "a", label: "A", nosort: true, cls: "hide-sm" },
    { key: "p", label: "P", nosort: true },
    { key: "ppg", label: "P/GP", nosort: true, cls: "hide-sm", fmt: (r) => ppg(r.p, r.gp) },
    { key: "nhle82", label: "NHL pace", nosort: true, fmt: (r) => (r.nhle82 != null ? `<span data-tip="Roughly what this scoring rate is worth over 82 NHL games, by our league translation">${r.nhle82}</span>` : `<span class="dim">–</span>`) },
    { key: "po", label: "Playoffs", nosort: true, cls: "hide-sm", fmt: (r) => (r.po ? `${r.po.p} P in ${r.po.gp}` : `<span class="dim">–</span>`) },
  ], null, "dpath");
  const intl = (d.intl || []).slice().reverse();
  const intlList = intl.length ? `<ul class="plist intl">${intl.map((r) => `<li><b>${esc(r.season)} ${esc(r.event)}</b> <span class="dim">${esc(r.team || "")}</span><span class="il-stat">${r.sv != null ? `${r.gp} GP` : statLine(r)}</span></li>`).join("")}</ul>` : "";
  const c = d.comps;
  const compTable = c && c.list?.length ? `
    <h3 class="kicker">Taken around the same spot</h3>
    <p class="note">${esc(c.group[0].toUpperCase() + c.group.slice(1))}: ${c.n} players. ${c.established_n ? `Of the ${c.established_n} drafted early enough to have had four-plus seasons, ${c.reached_200} reached 200 NHL games.` : ""}
      ${c.first_full_ppg_median != null ? `In their first season of 20+ games they scored a median <b>${c.first_full_ppg_median.toFixed(2)}</b> points a game${c.his ? `; ${esc(last)} is at <b>${c.his.ppg.toFixed(2)}</b> through ${c.his.gp}` : ""}.` : ""}
      The closest picks:</p>
    ${table(c.list.map((r) => ({ ...r })), [
      { key: "name", label: "Player", nosort: true, fmt: (r) => (D.skaters.some((s) => s.id === r.id) ? playerLink(r.id, r.name) : esc(r.name)) },
      { key: "overall", label: "Pick", nosort: true, fmt: (r) => `${r.year} #${r.overall}` },
      { key: "first_full", label: "First full season", nosort: true, cls: "hide-sm", fmt: (r) => (r.first_full ? `${esc(r.first_full.season)}: ${r.first_full.p} P in ${r.first_full.gp}` : `<span class="dim">none yet</span>`) },
      { key: "ff", label: "P/GP", nosort: true, fmt: (r) => (r.first_full ? r.first_full.ppg.toFixed(2) : "–"), tip: "In his first season of 20+ games" },
      { key: "nhl_gp", label: "NHL GP", nosort: true },
    ], null, "dcomp")}` : "";
  const awards = (d.awards || []).length ? `<h3 class="kicker">Hardware</h3><ul class="plist">${d.awards.map((a) => `<li><b>${esc(a.name)}</b> <span class="dim">${esc(a.seasons.join(", "))}</span></li>`).join("")}</ul>` : "";
  const w = d.wiki;
  const paras = w ? w.extract.split(/\n+/).filter(Boolean) : [];
  const wiki = w ? `<div class="wiki">
      <h3 class="kicker">Background</h3>
      <div class="wiki-body">${paras.slice(0, 2).map((p) => `<p>${esc(p)}</p>`).join("")}</div>
      ${paras.length > 2 ? `<details class="wiki-more"><summary>Read the rest of the introduction</summary>${paras.slice(2).map((p) => `<p>${esc(p)}</p>`).join("")}</details>` : ""}
      <p class="note credit">From <a href="${esc(w.url)}" target="_blank" rel="noopener">Wikipedia's article on ${esc(w.title)}</a>, by its contributors, under <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener">CC BY-SA 4.0</a>. Shown as written.</p>
    </div>` : "";
  el.innerHTML = `<h2>Path to the NHL</h2>
    <p class="lede">Where ${esc(name)} came from: the draft, the leagues before the NHL, and how players taken around the same spot have done.</p>
    <div class="path-top">${draftCard}${d.notes?.length ? `<ul class="notes">${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}</div>
    ${preTable ? `<h3 class="kicker">Before the NHL</h3>${preTable}` : ""}
    ${intlList ? `<h3 class="kicker">For his country</h3>${intlList}` : ""}
    ${awards}${compTable}${wiki}
    <p class="note">Career numbers from <a href="${esc(d.nhl_url)}" target="_blank" rel="noopener">his NHL.com page</a> (which lists every league he's played in); Central Scouting rankings and draft picks from the NHL. "NHL pace" is our own translation of a scoring rate into NHL terms, learned from players who moved between leagues; it's rough, especially for junior leagues. <a href="#about/glossary">More in the glossary</a>.</p>`;
  el.hidden = false;
}

// ---------------------------------------------------------------- The buzz
const KIND_LABEL = { presser: "Press conference", recap: "Recap", video: "Video" };
function teamVideoCard(v) {
  return `<article class="watch-item">
    <button type="button" class="yt" data-yt="${esc(v.id)}" aria-label="Play ${esc(v.t)}">
      <img src="https://i.ytimg.com/vi/${esc(v.id)}/mqdefault.jpg" alt="" loading="lazy" width="320" height="180"><span class="yt-play" aria-hidden="true"></span></button>
    <div class="ni-meta">${esc(teamName(v.team))} on YouTube · ${KIND_LABEL[v.k] || "Video"}${v.d ? ` · ${ago(v.d)}` : ""}</div>
    <h3>${esc(v.t)}</h3>
  </article>`;
}
function postCard(p) {
  return `<article class="bpost">
    <p class="bp-text">${esc(p.t)}</p>
    <div class="ni-meta"><b>${esc(p.a)}</b>${p.o ? `, ${esc(p.o)}` : ""} · <a href="${esc(p.u)}" target="_blank" rel="noopener">on Bluesky</a> · ${ago(p.d)}</div>
  </article>`;
}
const headlineItem = (n) => `<li><a href="${esc(n.u)}" target="_blank" rel="noopener">${esc(n.t)}</a> <span class="dim">${esc(n.o || "")}${n.d ? `, ${ago(n.d)}` : ""}</span></li>`;
const threadItem = (t) => `<li><a href="${esc(t.u)}" target="_blank" rel="noopener">${esc(t.t)}</a> <span class="dim">r/${esc(t.sub)}${t.d ? `, ${ago(t.d)}` : ""}</span></li>`;

async function renderBuzz(el, pid, name) {
  if (!el) return;
  const [c, buzz] = await Promise.all([coverage(`players/${pid}.json`), coverage("buzz.json")]);
  if (!c) return;
  const news = c.news || [], posts = c.posts || [], threads = c.threads || [], vids = c.videos || [];
  if (!news.length && !posts.length && !threads.length && !vids.length) return;
  const mine = buzz?.players?.[pid];
  let meter = "";
  if (mine && mine[0] >= 2) {
    const all = Object.values(buzz.players).map((x) => x[0]);
    const below = all.filter((x) => x < mine[0]).length, share = Math.round(100 * below / Math.max(1, all.length));
    meter = `<p class="buzz-meter"><b>${mine[0]}</b> headlines in the last week, from ${mine[2]} outlet${mine[2] === 1 ? "" : "s"} over the last month${share >= 50 ? `: more than ${share}% of NHL players` : ""}.</p>`;
  }
  const more = (arr, n, item, cls) => `<ul class="plist ${cls}">${arr.slice(0, n).map(item).join("")}</ul>` +
    (arr.length > n ? `<details class="more-list"><summary>${arr.length - n} more</summary><ul class="plist ${cls}">${arr.slice(n).map(item).join("")}</ul></details>` : "");
  el.innerHTML = `<h2>The buzz</h2>
    <p class="lede">What the hockey world is saying about ${esc(name)}: the latest headlines, reporters who cover him, his team's videos and what fans are talking about. Updated every hour.</p>
    ${meter}
    <div class="buzz-grid">
      ${news.length ? `<div><h3 class="kicker">In the headlines</h3>${more(news, 6, headlineItem, "heads")}</div>` : ""}
      ${posts.length ? `<div><h3 class="kicker">From the reporters</h3><div class="bposts">${posts.slice(0, 4).map(postCard).join("")}</div></div>` : ""}
    </div>
    ${vids.length ? `<h3 class="kicker">From the team</h3><div class="watch-grid">${vids.slice(0, 3).map(teamVideoCard).join("")}</div>` : ""}
    ${threads.length ? `<h3 class="kicker">Fans are talking</h3>${more(threads, 4, threadItem, "threads")}` : ""}
    <p class="note">Headlines via Google News, linked to each outlet; we show headlines only. Reporters' posts are public Bluesky posts from writers who cover the league; fan threads are Reddit post titles. Videos are the team's own, played through YouTube.</p>`;
  el.hidden = false;
  bindMedia(el, []);
}

// ---------------------------------------------------------------- From the room (team pages)
async function renderRoom(el, team) {
  if (!el) return;
  const c = await coverage(`teams/${team}.json`);
  if (!c) return;
  const vids = (c.videos || []).slice().sort((a, b) => (b.k === "presser") - (a.k === "presser") || (b.d || "").localeCompare(a.d || ""));
  const posts = c.posts || [], threads = c.threads || [];
  if (!vids.length && !posts.length && !threads.length) return;
  el.innerHTML = `<h2>From the room</h2>
    <p class="lede">Press conferences and interviews from the team's own channel, what the reporters on the ${esc(teamName(team))} beat are posting, and what fans are talking about. Updated every hour.</p>
    ${vids.length ? `<h3 class="kicker">Team videos</h3><div class="watch-grid">${vids.slice(0, 6).map(teamVideoCard).join("")}</div>` : ""}
    <div class="buzz-grid">
      ${posts.length ? `<div><h3 class="kicker">On the beat</h3><div class="bposts">${posts.slice(0, 5).map(postCard).join("")}</div></div>` : ""}
      ${threads.length ? `<div><h3 class="kicker">Fans are talking</h3><ul class="plist threads">${threads.slice(0, 8).map(threadItem).join("")}</ul></div>` : ""}
    </div>
    <p class="note">Videos from the team's YouTube channel, played through YouTube. Reporters' posts are public Bluesky posts; fan threads are Reddit post titles, linked.</p>`;
  el.hidden = false;
  bindMedia(el, []);
}

// ---------------------------------------------------------------- Pulse: most talked about
async function talkedAbout() {
  const b = await coverage("buzz.json");
  const top = (b?.top || []).slice(0, 10);
  if (!top.length) return "";
  return `<h2 class="mt">Most talked about</h2><p class="lede">The players with the most headlines across outlets this week, plus reporters' posts and fan threads. Updated every hour.</p>
    <ol class="talked">${top.map((x) => `<li>${D.skaters.some((s) => s.id === x.id) ? playerLink(x.id, x.name) : (D.goalies || []).some((g) => g.id === x.id) ? goalieLink(x.id, x.name) : esc(x.name)}
      <span class="dim">${esc(x.team)} · ${x.news7} headline${x.news7 === 1 ? "" : "s"} from ${x.outlets} outlet${x.outlets === 1 ? "" : "s"}${x.posts7 ? `, ${x.posts7} reporter post${x.posts7 === 1 ? "" : "s"}` : ""}${x.threads7 ? `, ${x.threads7} fan thread${x.threads7 === 1 ? "" : "s"}` : ""}</span></li>`).join("")}</ol>`;
}
