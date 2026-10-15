"""Per-game analysis pages for the catalogue.

Writes site/data/games/index.json (one row per game, with sort keys) and
site/data/games/<game_id>.json (everything a game page draws). Called from
site/build.py; reads the per-game tables from analysis/props_data.py and the
raw NHL landing / right-rail files (goal clips, stars, linescore, series).
"""
import glob, gzip, json, os
import numpy as np
import pandas as pd

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


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def build_games(season, ev, xg_shots, pg, gg, games, names, out_dir, stories_dir):
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
        shots = []
        for row in s.itertuples():
            side = 1 if row.team == home else -1
            shots.append([int(round(row.nx * side)), int(round(row.ny * side)), int(round(row.xgv * 1000)),
                          int(row.event == "goal"), 1 if row.team == home else 0,
                          int(row.game_seconds), int(row.player1_id) if not pd.isna(row.player1_id) else 0,
                          row.state])
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
                    period=pd_.get("number"), ptype=pd_.get("periodType"), t=g.get("timeInPeriod"),
                    team=_nm(g.get("teamAbbrev")), pid=g.get("playerId"),
                    name=f"{_nm(g.get('firstName'))} {_nm(g.get('lastName'))}".strip(),
                    num=g.get("goalsToDate"), headshot=g.get("headshot"),
                    assists=[dict(pid=a.get("playerId"), name=f"{_nm(a.get('firstName'))} {_nm(a.get('lastName'))}".strip(),
                                  num=a.get("assistsToDate")) for a in g.get("assists", [])],
                    strength=g.get("strength"), shot=g.get("shotType"), mod=g.get("goalModifier"),
                    score=f"{g.get('awayScore')}-{g.get('homeScore')}",
                    xg=r(xg_by_event.get(g.get("eventId"))), clip=g.get("highlightClipSharingUrl")))
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

        story = None
        sp = os.path.join(stories_dir, f"{gid}.json")
        if os.path.exists(sp):
            story = json.load(open(sp)).get("text")

        winner = home if gm.home_score > gm.away_score else away
        w_deserve = dtw if winner == home else 1 - dtw
        detail = dict(id=gid, date=gm.date, away=away, home=home, a=int(gm.away_score), h=int(gm.home_score),
                      end=gm.decided_in, venue=gm.venue, gamecenter=gc_link,
                      xg_a=r(xg_a, 2), xg_h=r(xg_h, 2), xg5_a=r(xg5_a, 2), xg5_h=r(xg5_h, 2), cf_a=cf_a, cf_h=cf_h,
                      dtw_home=r(dtw), periods=per, lines=lines, sog_periods=sog_p, team_stats=tstats,
                      goals=goals, shootout=shootout, stars=stars, penalties=penalties, series=series,
                      shots=shots, players=sorted(players, key=lambda p: -(p["gs"] or 0)), goalies=goalies, story=story)
        with open(os.path.join(out_dir, f"{gid}.json"), "w") as f:
            json.dump(detail, f, separators=(",", ":"), allow_nan=False)

        top = max(players, key=lambda p: p["gs"] or 0) if players else None
        index.append(dict(id=gid, date=gm.date, away=away, home=home, a=int(gm.away_score), h=int(gm.home_score),
                          end=gm.decided_in, xg_a=r(xg_a, 2), xg_h=r(xg_h, 2), dtw_home=r(dtw),
                          winner=winner, w_deserve=r(w_deserve), chaos=r(xg_a + xg_h, 2),
                          goals=int(gm.away_score + gm.home_score), star=top["name"] if top else None,
                          has_story=bool(story),
                          blurb=(story.split(". ")[0] + ".") if story else None))
    index.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"), allow_nan=False)
    print(f"  games/: {len(index)} game pages")
    return index
