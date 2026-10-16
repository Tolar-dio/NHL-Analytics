"""Per-game analysis pages for the catalogue.

Writes site/data/games/index.json (one row per game, with sort keys) and
site/data/games/<game_id>.json (everything a game page draws). Called from
site/build.py; reads the per-game tables from analysis/props_data.py and the
raw NHL landing / right-rail files (goal clips, stars, linescore, series).
"""
import glob, gzip, json, os, re
import numpy as np
import pandas as pd

# one-letter shot types for the compact shot arrays (decoded by SHOT_TYPE in site/app.js)
SHOT_CODE = {"wrist": "w", "snap": "s", "slap": "l", "backhand": "b", "tip-in": "t", "deflected": "d", "wrap-around": "r",
             "poke": "p", "bat": "a", "between-legs": "x", "cradle": "c"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gz(path):
    return json.load(gzip.open(path, "rt")) if os.path.exists(path) else None


def _nm(x):
    return (x or {}).get("default", "") if isinstance(x, dict) else (x or "")


def _shootout_events(land):
    so = ((land or {}).get("summary") or {}).get("shootout")
    if isinstance(so, dict):
        so = so.get("events")
    return [x for x in (so or []) if isinstance(x, dict)]


def poisson_binomial(ps):
    """Exact distribution of goals from independent shots with chances ps."""
    dist = np.array([1.0])
    for p in ps:
        dist = np.convolve(dist, [1 - p, p])
    return dist


def deserve_to_win(home_ps, away_ps):
    h, a = poisson_binomial(home_ps), poisson_binomial(away_ps)
    joint = np.outer(h, a)
    win = np.tril(joint, -1).sum()   # home goals > away goals
    tie = np.trace(joint)
    return float(win + 0.5 * tie)


SEQ_EVENTS = {"faceoff", "hit", "giveaway", "takeaway", "blocked-shot", "missed-shot", "shot-on-goal", "goal",
              "penalty", "delayed-penalty"}


def _last(n):
    return str(n).split(" ")[-1] if n and str(n) != "nan" else ""


def caption(ev, assists, xg):
    p1, p2, gl = ev.player1, ev.player2, ev.goalie
    p1 = p1 if isinstance(p1, str) else ""
    p2 = p2 if isinstance(p2, str) else ""
    k = ev.event
    if k == "faceoff":
        return f"{p1} wins the faceoff against {_last(p2)}" if p2 else f"{p1} wins the faceoff"
    if k == "hit":
        return f"{p1} hits {p2}" if p2 else f"{p1} lands a hit"
    if k == "giveaway":
        return f"{p1} gives the puck away"
    if k == "takeaway":
        return f"{p1} strips the puck"
    if k == "blocked-shot":
        return f"{p1} shoots, blocked by {p2}" if p2 else f"{p1}'s shot is blocked"
    if k == "missed-shot":
        why = str(ev.reason).replace("-", " ") if isinstance(ev.reason, str) else "misses"
        return f"{p1} shoots{f', {why}' if why != 'misses' else ' and misses'}" + (f" ({round(100 * xg)}% chance)" if xg else "")
    if k == "shot-on-goal":
        return f"{p1} shoots, saved by {_last(gl)}" + (f" ({round(100 * xg)}% chance)" if xg else "")
    if k == "goal":
        a = f", from {' and '.join(assists)}" if assists else ", unassisted"
        return f"{p1} scores{a}" + (f" ({round(100 * xg)}% chance)" if xg else "")
    if k == "penalty":
        what = str(ev.penalty_type).replace("-", " ") if isinstance(ev.penalty_type, str) else "a penalty"
        return f"{p1} takes a penalty: {what}"
    if k == "delayed-penalty":
        return "Delayed penalty signalled, goalie heads for the bench"
    return k


def goal_sequences(gid, e, shifts, goals, home, away, xg_by_event, roster_info):
    """For each goal (by NHL event id): the recorded events since the faceoff that
    started the play (capped at the last 60s of a long shift), with coordinates
    flipped so the scoring team attacks the right-hand net, captions, xG, and
    the skaters on the ice at every event."""
    e = e.sort_values("sort_order").reset_index(drop=True)
    sh = shifts[shifts.game_id == gid].dropna(subset=["player_id"])
    roster, ridx = [], {}
    def ri(pid):
        pid = int(pid)
        if pid not in ridx:
            info = roster_info.get(pid, {})
            ridx[pid] = len(roster)
            roster.append(dict(id=pid, name=info.get("name", ""), num=info.get("num"), pos=info.get("pos", ""),
                               team=info.get("team", "")))
        return ridx[pid]
    by_eid = {g["eid"]: g for g in goals if g.get("eid") is not None}
    seqs = {}
    for i in e.index[e.event == "goal"]:
        gr = e.loc[i]
        meta = by_eid.get(int(gr.event_id))
        if meta is None:
            continue
        scorer_team = gr.team
        per = gr.period
        same = e[(e.period == per) & (e.index <= i)]
        fo = same[same.event == "faceoff"]
        start_i = fo.index.max() if len(fo) else same.index.min()
        pool = e.loc[start_i:i]
        pool = pool[pool.event.isin(SEQ_EVENTS)]
        note = None
        since = int(gr.game_seconds - e.loc[start_i, "game_seconds"])
        if since > 75:
            # long shift: show the last minute, but never fewer than the last 4 recorded moments,
            # so a goal after a quiet stretch still shows how play got there
            win = pool[pool.game_seconds >= gr.game_seconds - 60]
            if len(win) < 4:
                win = pool.iloc[-4:]
            span = int(gr.game_seconds - win.game_seconds.min())
            shown = "the last minute" if span <= 60 else f"the last {span // 60}:{span % 60:02d}"
            note = f"Play continued from a faceoff {since // 60}:{since % 60:02d} earlier; showing {shown}."
        else:
            win = pool
        hds = gr.home_defending_side
        if hds in ("left", "right"):
            flip = 1 if (scorer_team == home) == (hds == "left") else -1
        else:
            flip = 1 if (gr.x or 0) >= 0 else -1
        psh = sh[sh.period == per]
        evs, onice = [], []
        for _, ev in win.iterrows():
            t = ev.game_seconds - (min(per, 4) - 1) * 1200
            if ev.event == "faceoff":
                cur = psh[(psh.start_sec <= t) & (psh.end_sec > t)]
            else:
                cur = psh[(psh.start_sec < t) & (psh.end_sec >= t)]
            mine = [ri(p) for p in cur[cur.team == scorer_team].player_id]
            theirs = [ri(p) for p in cur[cur.team != scorer_team].player_id]
            onice.append([mine, theirs])
            xg = xg_by_event.get(ev.event_id)
            # second player is on the OTHER side for faceoffs (loser), hits (hittee), blocks (blocker)
            # and penalties (drawn by); on goals it's the first assist, who has no recorded location
            second = ev.player2_id if ev.event in ("faceoff", "hit", "blocked-shot", "penalty") else None
            actors = [ri(p) for p in (ev.player1_id, second) if p is not None and not pd.isna(p)]
            evs.append(dict(t=int(ev.game_seconds), k=ev.event, s=1 if ev.team == scorer_team else 0,
                            x=None if pd.isna(ev.x) else int(ev.x * flip), y=None if pd.isna(ev.y) else int(ev.y * flip),
                            a=actors, xg=r(xg, 3) if xg is not None else None,
                            c=caption(ev, [a["name"] for a in meta["assists"]] if ev.event == "goal" else None,
                                      xg if xg is not None and not (isinstance(xg, float) and np.isnan(xg)) else None),
                            sc=str(ev.situation_code)))
        shots = [x for x in evs if x["k"] in ("shot-on-goal", "missed-shot", "goal", "blocked-shot") and x["s"] == 1]
        seqs[str(int(gr.event_id))] = dict(
            team=scorer_team, period=int(per), note=note, events=evs, onice=onice,
            duration=int(gr.game_seconds - evs[0]["t"]) if evs else 0,
            shots=len(shots), xg=r(sum(x["xg"] or 0 for x in shots), 3))
    return roster, seqs


PERIOD_WORD = {1: "first", 2: "second", 3: "third", 4: "overtime"}


def _in_period(p):
    p = int(p)
    return "in overtime" if p >= 4 else f"in the {PERIOD_WORD[p]} period"


def _pct(x):
    return f"{round(100 * x)}%" if x >= 0.01 else "under 1%"


def game_notes(s, goals, goalies, tstats, home, away, names, final_h, final_a):
    """Up to six plain sentences on what decided the game, built only from the data.
    They sit at the top of every game page, so it reads well even before (or without) a written recap."""
    notes = []
    s = s[s.state != "EN"] if len(s) else s
    # 1. the period one team owned
    if len(s):
        per = s.groupby(["period", "team"]).xgv.sum().unstack(fill_value=0.0)
        if home in per and away in per:
            gap = (per[home] - per[away])
            p = gap.abs().idxmax()
            if abs(gap[p]) >= 0.5:
                t, o = (home, away) if gap[p] > 0 else (away, home)
                notes.append(f"{t} owned {'overtime' if int(p) >= 4 else 'the ' + PERIOD_WORD[int(p)] + ' period'}, out-chancing {o} "
                             f"{per.loc[p, t]:.2f} to {per.loc[p, o]:.2f} in expected goals.")
    # 2. the best chance that didn't go in
    if len(s):
        miss = s[s.event != "goal"].sort_values("xgv", ascending=False).head(1)
        for row in miss.itertuples():
            if row.xgv >= 0.15:
                who = names.get(row.player1_id, "") or row.team
                how = f"stopped by {names.get(row.goalie_id, 'the goalie')}" if row.event == "shot-on-goal" and not pd.isna(row.goalie_id) \
                    else "off target" if row.event == "missed-shot" else "kept out"
                notes.append(f"Best chance that didn't go in: {who} ({row.team}), a {_pct(row.xgv)} look "
                             f"{_in_period(row.period)}, {how}.")
    # 3. the least likely goal
    real = [g for g in goals if g.get("xg") is not None and g.get("strength") != "en"]
    if real:
        lo = min(real, key=lambda g: g["xg"])
        if lo["xg"] < 0.06:
            notes.append(f"Least likely goal: {lo['name']} ({lo['team']}) scored on a {_pct(lo['xg'])} chance "
                         f"{_in_period(lo['period'])}.")
    # 4. comeback
    if goals:
        lead_h = 0
        worst = {home: 0, away: 0}
        for g in goals:
            a_, h_ = (int(v) for v in g["score"].split("-"))
            worst[home] = min(worst[home], h_ - a_)
            worst[away] = min(worst[away], a_ - h_)
        winner = home if final_h > final_a else away
        if worst[winner] <= -2:
            notes.append(f"{winner} came back from {-worst[winner]} goals down.")
    # 5. goaltending swing
    gk = [x for x in goalies if (x.get("toi") or 0) >= 20 and x.get("gsax") is not None]
    if gk:
        x = max(gk, key=lambda x: abs(x["gsax"]))
        if abs(x["gsax"]) >= 0.9:
            notes.append(f"{x['name']} ({x['team']}) " + (f"saved {x['gsax']:.1f} goals more than his {x['sa']} shots against deserved."
                         if x["gsax"] > 0 else f"allowed {-x['gsax']:.1f} goals more than his {x['sa']} shots against deserved."))
    # 6. special teams
    pp = tstats.get("powerPlay") if tstats else None
    if pp and len(s):
        parts = []
        for t, val in ((away, pp[0]), (home, pp[1])):
            try:
                got, opp = (int(v) for v in str(val).split("/"))
            except ValueError:
                continue
            if opp:
                xg = s[(s.team == t) & (s.state == "PP")].xgv.sum()
                parts.append(f"{t} {got} for {opp} ({xg:.2f} expected goals)")
        if parts:
            notes.append("Power plays: " + "; ".join(parts) + ".")
    return notes[:6]


CLIP_RE = re.compile(r"^https://(www\.)?nhl\.com/video/[a-z0-9-]+-\d{6,}$")


def _clip(url):
    """NHL sometimes publishes a bare 'https://nhl.com/video/' before the clip is ready; treat that as no clip."""
    return url if url and CLIP_RE.match(url) else None


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def build_games(season, ev, xg_shots, pg, gg, games, names, out_dir, stories_dir, shifts=None, plist=None, speeds=None):
    """ev: events (no shootout); xg_shots: unblocked shots with nx/ny normalised to
    'attacking right' and column xgv; pg/gg: player/goalie per-game tables."""
    os.makedirs(out_dir, exist_ok=True)
    raw = os.path.join(ROOT, "data", "raw", season)
    index = []
    pg_by = dict(tuple(pg.groupby("game_id")))
    gg_by = dict(tuple(gg.groupby("game_id")))
    sh_by = dict(tuple(xg_shots.groupby("game_id")))
    ev_by = dict(tuple(ev.groupby("game_id")))

    for _, gm in games.iterrows():
        gid = int(gm.game_id)
        d = os.path.join(raw, str(gid))
        land, rail, box = _gz(os.path.join(d, "landing.json.gz")), _gz(os.path.join(d, "rightrail.json.gz")), \
            _gz(os.path.join(d, "boxscore.json.gz"))
        home, away = gm.home, gm.away
        s = sh_by.get(gid, pd.DataFrame(columns=xg_shots.columns))
        e = ev_by.get(gid, pd.DataFrame(columns=ev.columns))

        # ---- shots: home attacks right (+x), away attacks left (-x)
        # [0 x, 1 y, 2 xg_milli, 3 goal, 4 home, 5 game second, 6 shooter, 7 strength, 8 shot type code,
        #  9 distance ft, 10 goalie, 11 event id, 12 flags (1 rebound, 2 rush, 4 on net), 13 seconds into shift or -1,
        #  14 shot speed mph when NHL EDGE lists it among the shooter's 10 hardest this season, else 0]
        shots = []
        num = lambda v, d=0: d if v is None or pd.isna(v) else int(v)
        for row in s.sort_values("sort_order").itertuples() if len(s) else []:
            side = 1 if row.team == home else -1
            flags = (1 if getattr(row, "shotRebound", 0) == 1 else 0) | (2 if getattr(row, "shotRush", 0) == 1 else 0) | \
                    (4 if row.event in ("shot-on-goal", "goal") else 0)
            shots.append([int(round(row.nx * side)), int(round(row.ny * side)), int(round(row.xgv * 1000)),
                          int(row.event == "goal"), 1 if row.team == home else 0,
                          int(row.game_seconds), num(row.player1_id), row.state,
                          SHOT_CODE.get(row.shot_type, "") if isinstance(row.shot_type, str) else "",
                          int(round(np.hypot(89 - row.nx, row.ny))), num(row.goalie_id), num(row.event_id), flags,
                          num(getattr(row, "shooterTimeOnIce", None), -1),
                          (speeds or {}).get((gid, num(row.player1_id), int(row.period), str(row.time_in_period)), 0)])
        not_en = s[s.state != "EN"]
        xg_h = float(s[s.team == home].xgv.sum())
        xg_a = float(s[s.team == away].xgv.sum())
        dtw = deserve_to_win(not_en[not_en.team == home].xgv.values, not_en[not_en.team == away].xgv.values)
        ev5 = s[s.state == "EV"]
        xg5_h, xg5_a = float(ev5[ev5.team == home].xgv.sum()), float(ev5[ev5.team == away].xgv.sum())
        att = e[e.event.isin(["shot-on-goal", "missed-shot", "goal", "blocked-shot"])]
        cf_h, cf_a = int((att.team == home).sum()), int((att.team == away).sum())

        # ---- xG by period
        per = []
        for pnum, grp in s.groupby("period"):
            per.append(dict(p=int(pnum), xg_h=r(grp[grp.team == home].xgv.sum()), xg_a=r(grp[grp.team == away].xgv.sum())))

        # ---- goals with clips (landing), matched to our xG by event id
        goals = []
        xg_by_event = dict(zip(s.event_id, s.xgv)) if len(s) else {}
        for p in ((land or {}).get("summary") or {}).get("scoring", []):
            pd_ = p.get("periodDescriptor", {})
            if pd_.get("periodType") == "SO":
                continue  # the shootout winner is listed with the shootout, not as a goal
            for g in p.get("goals", []):
                goals.append(dict(
                    eid=g.get("eventId"),
                    period=pd_.get("number"), ptype=pd_.get("periodType"), t=g.get("timeInPeriod"),
                    team=_nm(g.get("teamAbbrev")), pid=g.get("playerId"),
                    name=f"{_nm(g.get('firstName'))} {_nm(g.get('lastName'))}".strip(),
                    num=g.get("goalsToDate"), headshot=g.get("headshot"),
                    assists=[dict(pid=a.get("playerId"), name=f"{_nm(a.get('firstName'))} {_nm(a.get('lastName'))}".strip(),
                                  num=a.get("assistsToDate")) for a in g.get("assists", [])],
                    strength=g.get("strength"), shot=g.get("shotType"), mod=g.get("goalModifier"),
                    score=f"{g.get('awayScore')}-{g.get('homeScore')}",
                    xg=r(xg_by_event.get(g.get("eventId"))), clip=_clip(g.get("highlightClipSharingUrl"))))
        shootout = [dict(team=_nm(x.get("teamAbbrev")), pid=x.get("playerId"),
                         name=f"{_nm(x.get('firstName'))} {_nm(x.get('lastName'))}".strip(), result=x.get("result"),
                         shot=x.get("shotType"))
                    for x in _shootout_events(land)]
        stars = [dict(star=x.get("star"), pid=x.get("playerId"), team=x.get("teamAbbrev"), name=_nm(x.get("name")),
                      headshot=x.get("headshot"), pos=x.get("position"), g=x.get("goals"), a=x.get("assists"),
                      sv=x.get("savePctg"))
                 for x in ((land or {}).get("summary") or {}).get("threeStars", [])]
        penalties = []
        for p in ((land or {}).get("summary") or {}).get("penalties", []):
            for x in p.get("penalties", []):
                who = x.get("committedByPlayer") or {}
                penalties.append(dict(period=p.get("periodDescriptor", {}).get("number"), t=x.get("timeInPeriod"),
                                      team=_nm(x.get("teamAbbrev")), dur=x.get("duration"), what=x.get("descKey"),
                                      who=f"{_nm(who.get('firstName'))} {_nm(who.get('lastName'))}".strip() if who else ""))

        # ---- linescore, team stats, season series (right-rail)
        lines = [dict(p=x["periodDescriptor"]["number"], type=x["periodDescriptor"].get("periodType"),
                      a=x.get("away"), h=x.get("home")) for x in (rail or {}).get("linescore", {}).get("byPeriod", [])]
        sog_p = [dict(p=x["periodDescriptor"]["number"], a=x.get("away"), h=x.get("home"))
                 for x in (rail or {}).get("shotsByPeriod", [])]
        tstats = {x["category"]: [x.get("awayValue"), x.get("homeValue")] for x in (rail or {}).get("teamGameStats", [])}
        series = [dict(id=x["id"], date=x.get("gameDate"), away=x["awayTeam"]["abbrev"], home=x["homeTeam"]["abbrev"],
                       a=x["awayTeam"].get("score"), h=x["homeTeam"].get("score"),
                       end=(x.get("gameOutcome") or {}).get("lastPeriodType"))
                  for x in (rail or {}).get("seasonSeries", [])]
        gc_link = None
        for x in (rail or {}).get("seasonSeries", []):
            if x["id"] == gid and x.get("gameCenterLink"):
                gc_link = "https://www.nhl.com" + x["gameCenterLink"]
        if not gc_link:
            y, mth, dd = gm.date.split("-")
            gc_link = f"https://www.nhl.com/gamecenter/{away.lower()}-vs-{home.lower()}/{y}/{mth}/{dd}/{gid}"

        # ---- players (our on-ice numbers + boxscore extras)
        extra = {}
        for side in ("homeTeam", "awayTeam"):
            for grp in ("forwards", "defense"):
                for p in ((box or {}).get("playerByGameStats", {}).get(side, {}).get(grp, [])):
                    extra[p["playerId"]] = dict(pm=p.get("plusMinus"), hits=p.get("hits"), blk=p.get("blockedShots"),
                                               pim=p.get("pim"), fo=p.get("faceoffWinningPctg"), num=p.get("sweaterNumber"))
        players = []
        for row in pg_by.get(gid, pd.DataFrame()).itertuples():
            x = extra.get(row.player_id, {})
            # simplified Game Score (Luszczyszyn): scoring, shots, blocks, on-ice goals for/against
            gs = 0.75 * row.g + 0.7 * row.a1 + 0.55 * row.a2 + 0.075 * row.sog + 0.05 * (x.get("blk") or 0) \
                + 0.15 * row.gf - 0.15 * row.ga + 0.5 * (row.xgf - row.xga) / 3
            players.append(dict(id=int(row.player_id), name=names.get(row.player_id, ""), team=row.team, pos=row.pos,
                                num=x.get("num"), toi=r(row.toi, 1), g=int(row.g), a=int(row.a), sog=int(row.sog),
                                ixg=r(row.ixg, 2), xgf=r(row.xgf, 2), xga=r(row.xga, 2), gf=int(row.gf), ga=int(row.ga),
                                pm=x.get("pm"), hits=x.get("hits"), blk=x.get("blk"), pim=x.get("pim"),
                                fo=r(x.get("fo"), 3), gs=r(gs, 2)))
        goalies = []
        for row in gg_by.get(gid, pd.DataFrame()).itertuples():
            sa = int(((e.event.isin(["shot-on-goal", "goal"])) & (e.goalie_id == row.player_id)).sum()) if len(e) else 0
            goalies.append(dict(id=int(row.player_id), name=names.get(row.player_id, ""), team=row.team,
                                toi=r(row.toi, 1), sa=sa, ga=int(row.ga), xga=r(row.xga, 2),
                                gsax=r(row.xga - row.ga, 2), starter=bool(row.starter)))

        roster, seqs = [], {}
        if shifts is not None and plist is not None and goals:
            info = {int(pid): dict(name=names.get(pid, ""), num=None if pd.isna(row.number) else int(row.number),
                                   pos=row.position, team=row.team) for pid, row in plist.iterrows()}
            for pid, x in extra.items():           # sweater numbers / teams as dressed in this game
                if pid in info:
                    info[pid]["num"] = x.get("num")
            for row in pg_by.get(gid, pd.DataFrame()).itertuples():
                if int(row.player_id) in info:
                    info[int(row.player_id)]["team"] = row.team
            roster, seqs = goal_sequences(gid, e, shifts, goals, home, away, xg_by_event, info)

        story = None
        sp = os.path.join(stories_dir, f"{gid}.json")
        if os.path.exists(sp):
            d = json.load(open(sp))
            story = d.get("text") if d.get("v", 1) >= 2 else None   # v1 stories had swapped team stats; see write_stories.STORY_VERSION

        winner = home if gm.home_score > gm.away_score else away
        w_deserve = dtw if winner == home else 1 - dtw
        notes = game_notes(s, goals, goalies, tstats, home, away, names, int(gm.home_score), int(gm.away_score))
        detail = dict(id=gid, date=gm.date, away=away, home=home, a=int(gm.away_score), h=int(gm.home_score),
                      end=gm.decided_in, venue=gm.venue, gamecenter=gc_link,
                      xg_a=r(xg_a, 2), xg_h=r(xg_h, 2), xg5_a=r(xg5_a, 2), xg5_h=r(xg5_h, 2), cf_a=cf_a, cf_h=cf_h,
                      dtw_home=r(dtw), periods=per, lines=lines, sog_periods=sog_p, team_stats=tstats,
                      goals=goals, shootout=shootout, stars=stars, penalties=penalties, series=series,
                      shots=shots, players=sorted(players, key=lambda p: -(p["gs"] or 0)), goalies=goalies, story=story,
                      notes=notes, roster=roster, seqs=seqs)
        with open(os.path.join(out_dir, f"{gid}.json"), "w") as f:
            json.dump(detail, f, separators=(",", ":"), allow_nan=False)

        top = max(players, key=lambda p: p["gs"] or 0) if players else None
        index.append(dict(id=gid, date=gm.date, away=away, home=home, a=int(gm.away_score), h=int(gm.home_score),
                          end=gm.decided_in, xg_a=r(xg_a, 2), xg_h=r(xg_h, 2), dtw_home=r(dtw),
                          winner=winner, w_deserve=r(w_deserve), chaos=r(xg_a + xg_h, 2),
                          goals=int(gm.away_score + gm.home_score), star=top["name"] if top else None,
                          has_story=bool(story),
                          blurb=(story.split(". ")[0].rstrip(".") + ".") if story else (notes[0] if notes else None)))
    index.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"), allow_nan=False)
    print(f"  games/: {len(index)} game pages")
    return index
