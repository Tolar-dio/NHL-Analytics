/* Goal replay theater. Rebuilds each goal from the NHL's recorded events and
   shift charts: the puck travels between real event locations in game time,
   jersey chips appear where players made recorded plays, and the on-ice
   lineups update at every moment. Passes are not recorded, so movement between
   events is interpolated, and the page says so. */
"use strict";

const NET = { x: 89.6, y: 0 };
const PERIOD_NAME = ["", "1st", "2nd", "3rd", "OT"];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

// keep chips inside the boards, including the rounded corners (radius 28 ft)
function onIce(x, y) {
  x = Math.max(-96.5, Math.min(96.5, x));
  const ax = Math.abs(x);
  const maxY = ax > 72 ? 14.5 + Math.sqrt(Math.max(0, 28 * 28 - (ax - 72) ** 2)) - 3 : 39.5;
  return { x, y: Math.max(-maxY, Math.min(maxY, y)) };
}
function clockOf(t) {
  const p = Math.min(Math.floor(t / 1200) + 1, 4), within = t - (p - 1) * 1200;
  return `${PERIOD_NAME[p]} ${Math.floor(within / 60)}:${String(Math.floor(within % 60)).padStart(2, "0")}`;
}
function strengthOf(sc, scorerIsHome) {
  if (!sc || sc.length !== 4) return "";
  const [ag, as, hs, hg] = sc.split("").map(Number);
  const own = scorerIsHome ? hs : as, opp = scorerIsHome ? as : hs;
  const oppG = scorerIsHome ? ag : hg;
  if (!oppG) return "into an empty net";
  return own === opp ? `${own} on ${opp}` : own > opp ? `${own} on ${opp}, power play` : `${own} on ${opp}, shorthanded`;
}

function openTheater(g, eid) {
  const seq = g.seqs && g.seqs[String(eid)];
  const goal = g.goals.find((x) => String(x.eid) === String(eid));
  if (!seq || !goal || !seq.events.length) return;
  const R = g.roster, scorer = seq.team, other = scorer === g.home ? g.away : g.home;
  const scorerIsHome = scorer === g.home;
  const evs = seq.events.map((e, i) => ({ ...e, i }));
  const pts = evs.filter((e) => e.x != null);

  // playback timeline: real game seconds, but simultaneous events get a beat so you can see both
  // Long stretches with nothing recorded become a short fast-forward: we don't
  // know where the puck went, so it dims instead of gliding. The clock keeps real time.
  const GAP = 6;
  let pt = 0.6, gaps = 0;
  evs.forEach((e, i) => {
    if (i > 0) {
      const dt = e.t - evs[i - 1].t;
      e.gapBefore = dt > GAP ? dt : 0;
      if (e.gapBefore) gaps++;
      pt += e.gapBefore ? 2.2 : Math.max(dt, 0.55);
    }
    e.p = pt;
  });
  const compressed = gaps > 0;
  const goalP = evs[evs.length - 1].p, END = goalP + 2.2;

  // frame the play: zoom to the attacking end when every located moment happens there
  const minX = pts.length ? Math.min(...pts.map((e) => e.x)) : -101;
  const frame = minX > -12 ? "-26 -46 127 92" : "-101 -46 202 92";
  const lastGoal = evs[evs.length - 1];
  const sub = `${strengthOf(lastGoal.sc, scorerIsHome)}${goal.xg != null ? `, a ${pct(goal.xg)} chance` : ""}`;
  const chip = (ri, own) => { const p = R[ri]; return p ? `<li class="${own ? "own" : ""}" data-ri="${ri}"><span class="num">${p.num ?? ""}</span>${esc(p.name)}<span class="dim">${p.pos === "G" ? " G" : ""}</span></li>` : ""; };

  const box = document.createElement("div");
  box.className = "theater";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", `Replay of ${goal.name}'s goal`);
  box.innerHTML = `
    <div class="th-inner">
      <header class="th-head">
        <div><h2>${esc(goal.name)} <span class="dim">(${goal.num})</span></h2>
          <p>${scorer} goal, ${goal.ptype === "OT" ? "OT" : PERIOD_NAME[goal.period]} ${esc(goal.t)}. ${esc(sub)}.</p></div>
        <button type="button" class="th-close" aria-label="Close replay">Close</button>
      </header>
      <div class="th-main">
        <div class="th-stage">
          <svg class="chart rink th-rink" viewBox="${frame}" role="img" aria-label="Animated reconstruction of the play">
            ${rinkChrome(`${other} defending`, `${scorer} attacking`)}
            <g class="th-trail"></g><g class="th-shotline"></g><g class="th-marks"></g>
            <g class="th-pulse"></g>
            <circle class="th-puck" r="1.25" cx="${pts[0] ? pts[0].x : 0}" cy="${pts[0] ? -pts[0].y : 0}"/>
            <g class="th-label"></g>
          </svg>
          <div class="th-caption" aria-live="polite"></div>
          <div class="th-gap" hidden></div>
          <div class="th-controls">
            <button type="button" class="th-btn" data-act="back" aria-label="Previous moment">Back</button>
            <button type="button" class="th-btn th-play" data-act="play" aria-label="Play">Play</button>
            <button type="button" class="th-btn" data-act="fwd" aria-label="Next moment">Next</button>
            <span class="th-clock" aria-label="Game clock">${clockOf(evs[0].t)}</span>
            <span class="spacer"></span>
            <div class="chips" role="group" aria-label="Playback speed">
              ${[0.25, 0.5, 1, 2].map((v) => `<button type="button" class="chip" data-speed="${v}" aria-pressed="${v === 1}">${v}x</button>`).join("")}
            </div>
          </div>
          <div class="th-scrub">
            <div class="th-ticks">${evs.map((e) => `<span class="th-tick ${e.k === "goal" ? "is-goal" : ""} ${e.s ? "own" : ""}" style="left:${(100 * e.p) / END}%" data-jump="${e.i}" title="${esc(clockOf(e.t))}: ${esc(e.c)}"></span>`).join("")}</div>
            <input type="range" min="0" max="${END}" step="0.01" value="0" aria-label="Scrub through the play">
          </div>
          <p class="note">${seq.note ? esc(seq.note) + " " : ""}Rebuilt from the NHL's recorded events and shift charts: ${seq.duration} seconds of play, ${seq.shots} ${scorer} shot attempt${seq.shots === 1 ? "" : "s"}. The puck moves between recorded moments; passes in between aren't in the public data.${compressed ? " Long stretches with nothing recorded are fast-forwarded." : ""}
          ${goal.clip ? `<a class="watch" href="${esc(goal.clip)}" target="_blank" rel="noopener">Watch the real goal</a>` : ""}</p>
        </div>
        <aside class="th-side">
          <h3>Every recorded moment</h3>
          <ol class="th-feed">${evs.map((e) => `<li data-jump="${e.i}" class="${e.s ? "own" : ""} ${e.k === "goal" ? "is-goal" : ""}"><button type="button"><span class="dim">${clockOf(e.t)}</span> ${esc(e.c)}</button></li>`).join("")}</ol>
          <h3>On the ice</h3>
          <div class="th-onice"><div><b>${scorer}</b><ul class="th-ice-own"></ul></div><div><b>${other}</b><ul class="th-ice-opp"></ul></div></div>
        </aside>
      </div>
    </div>`;
  document.body.appendChild(box);
  document.body.classList.add("theater-open");
  const $t = (sel) => box.querySelector(sel);
  const svgNS = "http://www.w3.org/2000/svg";
  const puck = $t(".th-puck"), trail = $t(".th-trail"), marks = $t(".th-marks"), label = $t(".th-label"),
    shotline = $t(".th-shotline"), pulse = $t(".th-pulse"), range = $t("input[type=range]"), clock = $t(".th-clock"),
    cap = $t(".th-caption"), gapNote = $t(".th-gap"), playBtn = $t(".th-play"), feed = [...box.querySelectorAll(".th-feed li")];
  const prevFocus = document.activeElement;

  let playT = 0, playing = false, speed = 1, last = 0, raf = 0, shownIdx = -1, goalShown = false;
  const smooth = (u) => u * u * (3 - 2 * u);

  function posAt(T) {
    // puck position: interpolate between consecutive located events
    if (!pts.length) return { x: 0, y: 0 };
    if (T <= pts[0].p) return pts[0];
    for (let j = 0; j < pts.length - 1; j++) {
      const a = pts[j], b = pts[j + 1];
      if (T <= b.p) {
        if (b.gapBefore) return { x: a.x, y: a.y, gap: b.gapBefore };
        const u = smooth((T - a.p) / (b.p - a.p)); return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
      }
    }
    const lastPt = pts[pts.length - 1];
    if (T <= goalP) return lastPt;
    const u = Math.min(1, (T - goalP) / 0.35);  // the finishing shot into the net
    return { x: lastPt.x + (NET.x - lastPt.x) * u, y: lastPt.y + (NET.y - lastPt.y) * u };
  }
  function idxAt(T) { let k = 0; evs.forEach((e, i) => { if (e.p <= T + 1e-6) k = i; }); return k; }
  function gameTimeAt(T) {
    const k = idxAt(T), a = evs[k], b = evs[k + 1];
    if (!b || T <= a.p) return a.t;
    return a.t + (b.t - a.t) * Math.min(1, (T - a.p) / (b.p - a.p));
  }

  function drawMarks(k) {
    marks.innerHTML = ""; label.innerHTML = ""; shotline.innerHTML = "";
    const seen = new Map();   // latest location per actor
    for (let i = 0; i <= k; i++) {
      const e = evs[i]; if (e.x == null) continue;
      e.a.forEach((ri, n) => {
        // second actor (hit target, blocker, faceoff loser) belongs to the other side of e.s
        const own = n === 0 ? e.s === 1 : e.s !== 1;
        const c = onIce(e.x + (n ? (e.x > 80 ? -4.2 : 4.2) : 0), e.y + (n ? -3.2 : 0));
        seen.set(ri, { x: c.x, y: c.y, own, i });
      });
    }
    seen.forEach((m, ri) => {
      const p = R[ri]; if (!p || p.pos === "G") return;
      const g = document.createElementNS(svgNS, "g");
      g.setAttribute("class", `th-chip ${m.own ? "own" : "opp"} ${m.i === k ? "now" : "past"}`);
      g.innerHTML = `<circle cx="${m.x}" cy="${-m.y}" r="2.6"/><text x="${m.x}" y="${-m.y + 1.05}" text-anchor="middle">${p.num ?? ""}</text>`;
      marks.appendChild(g);
    });
    const e = evs[k];
    if (e && e.x != null) {
      const who = e.a.length ? R[e.a[0]] : null;
      if (who) {
        const t = document.createElementNS(svgNS, "text");
        t.setAttribute("x", Math.min(84, Math.max(-84, e.x)));
        t.setAttribute("y", -e.y - 4.2);
        t.setAttribute("text-anchor", "middle");
        t.setAttribute("class", "th-name");
        t.textContent = who.name.split(" ").slice(-1)[0];
        label.appendChild(t);
      }
      if (["shot-on-goal", "missed-shot", "goal"].includes(e.k) && e.s === 1) {
        shotline.innerHTML = `<line x1="${e.x}" y1="${-e.y}" x2="${NET.x}" y2="${NET.y}" class="${e.k === "goal" ? "is-goal" : ""}"/>`;
      } else if (["shot-on-goal", "missed-shot", "goal"].includes(e.k)) {
        shotline.innerHTML = `<line x1="${e.x}" y1="${-e.y}" x2="${-NET.x}" y2="${NET.y}"/>`;
      }
    }
  }
  function drawIce(k) {
    const [own, opp] = seq.onice[k] || [[], []];
    const act = new Set(evs[k].a);
    const li = (ri, side) => { const p = R[ri]; return p ? `<li class="${act.has(ri) ? "is-actor" : ""}"><span class="num ${side}">${p.num ?? ""}</span>${esc(p.name)}${p.pos === "G" ? ` <span class="dim">G</span>` : ""}</li>` : ""; };
    const sortG = (a) => [...a].sort((x, y) => (R[x]?.pos === "G") - (R[y]?.pos === "G"));
    $t(".th-ice-own").innerHTML = sortG(own).map((ri) => li(ri, "own")).join("");
    $t(".th-ice-opp").innerHTML = sortG(opp).map((ri) => li(ri, "opp")).join("");
  }

  function render(T, forceMarks) {
    const p = posAt(T), k = idxAt(T);
    puck.setAttribute("cx", p.x); puck.setAttribute("cy", -p.y);
    puck.classList.toggle("is-gap", !!p.gap);
    gapNote.textContent = p.gap ? `${Math.round(p.gap)} seconds of play with nothing recorded` : "";
    gapNote.hidden = !p.gap;
    // trail through visited event points plus the live puck
    const visited = pts.filter((e) => e.p <= T).map((e) => `${e.x},${-e.y}`);
    trail.innerHTML = `<polyline points="${[...visited, `${p.x},${-p.y}`].join(" ")}"/>`;
    if (k !== shownIdx || forceMarks) {
      shownIdx = k;
      drawMarks(k); drawIce(k);
      cap.innerHTML = `<b>${clockOf(evs[k].t)}</b> ${esc(evs[k].c)}`;
      cap.classList.toggle("is-goal", evs[k].k === "goal" && T >= goalP);
      feed.forEach((li, i) => li.classList.toggle("is-now", i === k));
      const cur = feed[k]; if (cur && cur.scrollIntoView && playing) cur.scrollIntoView({ block: "nearest" });
    }
    const atGoal = T >= goalP;
    if (atGoal && !goalShown) {
      goalShown = true;
      pulse.innerHTML = `<circle cx="${NET.x}" cy="0" r="3" class="${reduceMotion ? "static" : "ring"}"/><circle cx="${NET.x}" cy="0" r="3" class="${reduceMotion ? "static" : "ring ring-2"}"/>`;
    } else if (!atGoal && goalShown) { goalShown = false; pulse.innerHTML = ""; }
    clock.textContent = clockOf(gameTimeAt(T));
    range.value = T;
  }

  function tick(now) {
    if (!playing) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (reduceMotion) {
      // no tweening: hop from moment to moment
      const k = idxAt(playT);
      if (now - (tick.lastHop || 0) > 1100 / speed) { tick.lastHop = now; playT = k + 1 < evs.length ? evs[k + 1].p : END; }
    } else playT += dt * speed;
    if (playT >= END) { playT = END; setPlaying(false); }
    render(playT);
    if (playing) raf = requestAnimationFrame(tick);
  }
  function setPlaying(on) {
    playing = on;
    playBtn.textContent = on ? "Pause" : playT >= END ? "Replay" : "Play";
    playBtn.setAttribute("aria-label", playBtn.textContent);
    if (on) { if (playT >= END) playT = 0; last = performance.now(); raf = requestAnimationFrame(tick); }
    else cancelAnimationFrame(raf);
  }
  function jump(i) { setPlaying(false); playT = evs[i].p + (evs[i].k === "goal" ? 0.4 : 0); render(playT, true); }
  function step(dir) {
    const k = idxAt(playT);
    const exact = Math.abs(evs[k].p - playT) < 0.02;
    const target = dir > 0 ? Math.min(evs.length - 1, k + 1) : Math.max(0, exact ? k - 1 : k);
    jump(target);
  }
  function close() {
    setPlaying(false); box.remove(); document.body.classList.remove("theater-open");
    document.removeEventListener("keydown", onKey); prevFocus && prevFocus.focus && prevFocus.focus();
  }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === " " && !e.target.matches("input,button")) { e.preventDefault(); setPlaying(!playing); }
    else if (e.key === "ArrowRight" && !e.target.matches("input")) { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft" && !e.target.matches("input")) { e.preventDefault(); step(-1); }
  }

  box.addEventListener("click", (e) => {
    const b = e.target.closest("button, [data-jump]");
    if (e.target === box) return close();
    if (!b) return;
    if (b.matches(".th-close")) close();
    else if (b.dataset.act === "play") setPlaying(!playing);
    else if (b.dataset.act === "fwd") step(1);
    else if (b.dataset.act === "back") step(-1);
    else if (b.dataset.speed) { speed = +b.dataset.speed; box.querySelectorAll("[data-speed]").forEach((x) => x.setAttribute("aria-pressed", x === b)); }
    else { const j = b.closest("[data-jump]"); if (j) jump(+j.dataset.jump); }
  });
  range.addEventListener("input", () => { setPlaying(false); playT = +range.value; render(playT); });
  document.addEventListener("keydown", onKey);
  render(0, true);
  playBtn.focus();
  if (!reduceMotion) setTimeout(() => setPlaying(true), 450);
}
