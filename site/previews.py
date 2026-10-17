"""Same-day game previews: one JSON per game on the slate.

Writes site/data/previews/<game_id>.json with team comparison, special teams,
last-five form, goalie matchup, season series, rest, projected lines (from
shared ice time in each team's last game) and the key props.
"""
import datetime as dt, json, os
from itertools import combinations
import numpy as np
import pandas as pd


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def team_profile(team, s, tg, ev, index):
    t = tg[(tg.team == team) & (tg.game_type == "regular")]
    gp = len(t)
    mine, theirs = s[s.team == team], s[(s.game_id.isin(t.game_id)) & (s.team != team)]
    pp_for = mine[mine.state == "PP"].xgv.sum()
    pp_against = theirs[theirs.state == "PP"].xgv.sum()
    ev5_for, ev5_against = mine[mine.state == "EV"].xgv.sum(), theirs[theirs.state == "EV"].xgv.sum()
    pens = ev[(ev.event == "penalty") & ev.game_id.isin(t.game_id)]
    taken = int((pens.team == team).sum())
    drawn = int((pens.team != team).sum())
    games = sorted([g for g in index if team in (g["home"], g["away"])], key=lambda g: g["date"])
    last5 = []
    for g in games[-5:]:
        home = g["home"] == team
        xf, xa = (g["xg_h"], g["xg_a"]) if home else (g["xg_a"], g["xg_h"])
        gf, ga = (g["h"], g["a"]) if home else (g["a"], g["h"])
        last5.append(dict(id=g["id"], date=g["date"], opp=g["away"] if home else g["home"], home=home,
                          gf=gf, ga=ga, end=g["end"], xg_share=r(xf / (xf + xa) if xf + xa else 0.5)))
    return dict(team=team, gp=gp,
                xgf60=r(t.xgf.sum() / t.toi.sum() * 60), xga60=r(t.xga.sum() / t.toi.sum() * 60),
                gf_pg=r(t.gf.sum() / max(gp, 1), 2), ga_pg=r(t.ga.sum() / max(gp, 1), 2),
                xg5_share=r(ev5_for / (ev5_for + ev5_against)) if ev5_for + ev5_against else None,
                pp_xg_pg=r(pp_for / max(gp, 1)), pk_xga_pg=r(pp_against / max(gp, 1)),
                pen_taken_pg=r(taken / max(gp, 1), 2), pen_drawn_pg=r(drawn / max(gp, 1), 2),
                last5=last5, last_date=games[-1]["date"] if games else None)


def projected_lines(team, pg, shifts, pos, names):
    """Most common forward trios and defence pairs by shared ice time in the team's last game."""
    last = pg[pg.team == team].game_id.max()
    sh = shifts[(shifts.game_id == last) & (shifts.team == team)].dropna(subset=["player_id"])
    sh = sh.assign(pos=sh.player_id.map(pos))
    out = {}
    for grp, size, n in (("F", 3, 4), ("D", 2, 3)):
        g = sh[sh.pos == grp]
        ids = g.player_id.unique().tolist()
        toi = g.assign(d=g.end_sec - g.start_sec).groupby("player_id").d.sum()
        def overlap(a, b):
            A, B = g[g.player_id == a], g[g.player_id == b]
            tot = 0
            for p in A.period.unique():
                for s1, e1 in A[A.period == p][["start_sec", "end_sec"]].values:
                    for s2, e2 in B[B.period == p][["start_sec", "end_sec"]].values:
                        tot += max(0, min(e1, e2) - max(s1, s2))
            return tot
        ov = {frozenset(c): overlap(*c) for c in combinations(ids, 2)}
        left, units = set(ids), []
        for _ in range(n):
            if len(left) < size:
                break
            lead = max(left, key=lambda i: toi.get(i, 0))
            unit = [lead]
            while len(unit) < size:
                cand = max((i for i in left if i not in unit), key=lambda i: sum(ov.get(frozenset((i, u)), 0) for u in unit))
                unit.append(cand)
            left -= set(unit)
            units.append([dict(id=int(i), name=names.get(i, "")) for i in unit])
        out[grp] = units
        # 11F/7D nights and the like: whoever didn't fit a full unit still dressed
        out[grp + "_extra"] = [dict(id=int(i), name=names.get(i, "")) for i in sorted(left, key=lambda i: -toi.get(i, 0))]
    return out


def preview_notes(away, home, prof, goalies, series):
    """Plain sentences on where this matchup tilts, from the data only (shown above or without a written preview)."""
    A, H = prof[away], prof[home]
    notes = []
    if A.get("xg5_share") is not None and H.get("xg5_share") is not None:
        a, h = A["xg5_share"], H["xg5_share"]
        lead = away if a > h else home
        verdict = (f"{lead} has controlled more of the play." if abs(a - h) >= 0.05 else
                   "Both have been outchanced more often than not." if max(a, h) < 0.5 else
                   "There isn't much between them.")
        notes.append(f"At five on five, {away} has taken {round(100 * a)}% of the expected goals in its games and "
                     f"{home} {round(100 * h)}%. {verdict}")
    # special teams mismatch: each power play against the other side's kill
    for pp_team, pk_team in ((away, home), (home, away)):
        pp, pk = prof[pp_team].get("pp_xg_pg"), prof[pk_team].get("pk_xga_pg")
        if pp is not None and pk is not None and pp >= 0.75 and pk >= 0.75:
            notes.append(f"{pp_team}'s power play creates {pp:.2f} expected goals a game and {pk_team}'s penalty kill "
                         f"allows {pk:.2f}. That's the special-teams matchup to watch.")
    taken = max((away, home), key=lambda t: prof[t].get("pen_taken_pg") or 0)
    if (prof[taken].get("pen_taken_pg") or 0) >= 4:
        notes.append(f"{taken} has taken {prof[taken]['pen_taken_pg']:.1f} penalties a game, which keeps handing the other side power plays.")
    # goalie edge
    ga, gh = goalies.get(away), goalies.get(home)
    if ga and gh and ga.get("gsax") is not None and gh.get("gsax") is not None:
        notes.append(f"In net: {ga['name']} ({away}) is at {ga['gsax']:+.1f} saves above expected this season, "
                     f"{gh['name']} ({home}) at {gh['gsax']:+.1f}.")
    # rest
    for t in (away, home):
        if prof[t].get("rest_days") is not None and prof[t]["rest_days"] <= 0:
            notes.append(f"{t} is on the second night of a back-to-back.")
    # form: last five by chance share, not just results
    for t in (away, home):
        l5 = prof[t]["last5"]
        if len(l5) >= 3:
            w = sum(1 for x in l5 if x["gf"] > x["ga"])
            otl = sum(1 for x in l5 if x["gf"] < x["ga"] and x["end"] != "REG")
            share = sum(x["xg_share"] for x in l5) / len(l5)
            notes.append(f"{t} is {w}-{len(l5) - w - otl}-{otl} in its last {len(l5)}, "
                         f"with {round(100 * share)}% of the expected goals in those games.")
    played = [x for x in series if x.get("a") is not None]
    if played:
        x = played[-1]
        win = x["home"] if x["h"] > x["a"] else x["away"]
        notes.append(f"They met on {dt.date.fromisoformat(x['date']).strftime('%b %-d')}: {x['away']} {x['a']}, {x['home']} {x['h']}"
                     f"{'' if x['end'] == 'REG' else ' (' + x['end'] + ')'}, a game {win} deserved "
                     f"{round(100 * (x['dtw_home'] if win == x['home'] else 1 - x['dtw_home']))}% of the time.")
    return notes[:7]


def build_previews(slate, props, tonight_games, s, tg, ev, index, goalies, pg, shifts, pos, names, out_dir, stories_dir, today,
                   stories=None):
    os.makedirs(out_dir, exist_ok=True)
    gl = {g["id"]: g for g in goalies}
    written = 0
    for g in tonight_games:
        away, home = g["away"], g["home"]
        prof = {t: team_profile(t, s, tg, ev, index) for t in (away, home)}
        for t in (away, home):
            last = prof[t]["last_date"]
            prof[t]["rest_days"] = (dt.date.fromisoformat(today) - dt.date.fromisoformat(last)).days - 1 if last else None
        series = [dict(id=x["id"], date=x["date"], away=x["away"], home=x["home"], a=x["a"], h=x["h"], end=x["end"],
                       dtw_home=x["dtw_home"])
                  for x in index if {x["away"], x["home"]} == {away, home}]
        def goalie_card(gid):
            x = gl.get(gid)
            return None if not x else {k: x.get(k) for k in ("id", "name", "team", "gp", "sv_pct", "gsax", "gsax60",
                                                          "prev_gp", "prev_gsax", "hd_sv", "hd_sv_pctile", "hd_sv_lg")}
        game_props = [p for p in props if p["game"] == g["id"]]
        key = {}
        for t in (away, home):
            tp = [p for p in game_props if p["team"] == t]
            key[t] = dict(goal=sorted(tp, key=lambda p: -p["p_goal"])[:4],
                          pts=sorted(tp, key=lambda p: -p["p_2pts"])[:3])
        story = None
        sp = os.path.join(stories_dir, f"{g['id']}.json")
        if os.path.exists(sp):
            d = json.load(open(sp))
            story = d.get("text") if d.get("v", 1) >= 2 else None   # v1 stories had swapped team stats; see write_stories.STORY_VERSION
            if d.get("goalies") and d["goalies"] != [(goalie_card(g[f"{s}_goalie"]) or {}).get("id") for s in ("away", "home")]:
                story = None   # written for other starters; write_stories rewrites it this run
        gcards = {away: goalie_card(g["away_goalie"]), home: goalie_card(g["home_goalie"])}
        detail = dict(id=g["id"], date=today, start=g["start"], away=away, home=home,
                      away_xg=g["away_xg"], home_xg=g["home_xg"], total=g["total"], market=g.get("market"),
                      away_b2b=g.get("away_b2b"), home_b2b=g.get("home_b2b"),
                      teams=prof, series=series, notes=preview_notes(away, home, prof, gcards, series),
                      goalies=gcards,
                      lines={t: projected_lines(t, pg, shifts, pos, names) for t in (away, home)},
                      props=key, story=story,
                      storylines=(stories or {}).get(g["id"], {}).get("storylines", []),
                      watch=(stories or {}).get(g["id"], {}).get("watch", {}))
        with open(os.path.join(out_dir, f"{g['id']}.json"), "w") as f:
            json.dump(detail, f, separators=(",", ":"), allow_nan=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
        written += 1
    print(f"  previews/: {written} previews")
