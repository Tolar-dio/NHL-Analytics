"""Sleepers: Top Shelf's own under-the-radar picks for each game, chosen on process, role and matchup.

Never "he's due" (goals lagging his chances). Two kinds, at most one of each per game:

  depth  A third- or fourth-line forward (by tonight's projected minutes) whose recent shots have been dangerous:
         individual expected goals per 60 over his last ten games in the top 30% of depth forwards, with real
         high-danger looks, against a defense or goalie that gives chances up. Ranked on recent shot quality,
         the matchup and our goal probability.
  point  A player who isn't a star by his scoring line, whose chance of a point tonight is high (38%+) and clearly
         above what his season scoring rate alone says, because something changed or lines up tonight: more ice
         time lately, a new power-play role, a promotion into the top six, a line that drives chances, or a
         defense that gives them up. Season scoring is roughly what a casual read (and much of the market) leans on.

Every pick carries its reasons as data plus a plain sentence, and our probabilities. The archive keeps them and
analysis/track.py grades them on the Track record page.
"""
import numpy as np
import pandas as pd

HD = 0.15          # high-danger: an unblocked shot worth 15% or more
WINDOW = 10        # recent games


def _mmss(x):
    m = int(x)
    return f"{m}:{int(round((x - m) * 60)):02d}"


def _ord(n):
    n = int(n)
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def american(p):
    return f"+{round(100 * (1 - p) / p)}" if p < 0.5 else f"{round(-100 * p / (1 - p))}"


def recent(pg, shots, cut):
    """Last ten games per skater: minutes, own xG, shots, high-danger shots, points."""
    pg = pg[(pg.date < cut) & (pg.game_type == "regular")].sort_values("date")
    last = pg.groupby("player_id").tail(WINDOW)
    r = last.groupby("player_id").agg(n=("game_id", "nunique"), toi=("toi", "sum"), ixg=("ixg", "sum"), sog=("sog", "sum"),
                                      pts=("pts", "sum"), g=("g", "sum"))
    hd = shots[(shots.xgv >= HD)][["game_id", "player1_id"]].copy()
    hd = hd.merge(last[["game_id", "player_id"]], left_on=["game_id", "player1_id"], right_on=["game_id", "player_id"])
    r["hd"] = hd.groupby("player_id").size().reindex(r.index).fillna(0)
    r["ixg60"] = r.ixg / r.toi.clip(lower=1) * 60
    r["hd60"] = r.hd / r.toi.clip(lower=1) * 60
    return r


def pick(d, pg, prev_pg, shots, C, teams_rows, goalie_rows, names, strength, games, cut):
    """d: tonight's priced props (player_id, name, team, opp, game, pos, lineup, proj_toi, p_goal, p_1pt, def_f, g_f,
    oxgf60, gp, g, pts). Returns ({game_id: [sleeper, ...]}, {player_id: kind})."""
    R = recent(pg, shots, cut)
    season = pg[(pg.date < cut) & (pg.game_type == "regular")].groupby("player_id").agg(
        gp=("game_id", "nunique"), toi=("toi", "sum"), pts=("pts", "sum"), pos=("pos", "last"))
    season["toi_pg"] = season.toi / season.gp
    prevs = prev_pg[prev_pg.game_type == "regular"].groupby("player_id").agg(gp=("game_id", "nunique"), pts=("pts", "sum"))
    prev_ppg = (prevs.pts / prevs.gp).where(prevs.gp >= 20)
    # depth-forward reference: forwards under 15.5 minutes a night with an hour of recent ice
    ref = R.join(season[["toi_pg", "pos"]])
    ref = ref[(ref.pos == "F") & (ref.toi_pg < 15.5) & (ref.toi >= 60)]
    pct_of = lambda col, v: float((ref[col] <= v).mean()) if len(ref) else 0.5
    # team defence ranks (more expected goals allowed per 60 = worse)
    xga = {t["team"]: t["xga60"] for t in teams_rows}
    dfr = {t: i + 1 for i, (t, _) in enumerate(sorted(xga.items(), key=lambda kv: -kv[1]))}   # 1 = gives up the most
    gl = {g["id"]: g for g in goalie_rows}
    opp_goalie = {}
    for g in games:
        opp_goalie[(g["id"], g["away"])] = g.get("home_goalie")
        opp_goalie[(g["id"], g["home"])] = g.get("away_goalie")
    pts_rank = season.pts.rank(ascending=False, method="min")
    # context: power-play minutes and lines, last three games
    ctx = None
    if C is not None and len(C):
        Cc = C[(C.date < cut)].sort_values("date")
        l3 = Cc.groupby("player_id").tail(3).groupby("player_id").agg(pp3=("toipp", "mean"), toi3=("toi_sh", "mean"))
        allg = Cc.groupby("player_id").agg(pp_all=("toipp", "mean"), rank_med=("rank5", "median"))
        lastc = Cc.groupby("player_id").tail(1).set_index("player_id")[["rank5", "mate1", "mate2"]]
        ctx = l3.join(allg).join(lastc)
    of_ref = d[d.pos == "F"].oxgf60
    out, kinds = {}, {}
    for gid, G in d.groupby("game"):
        picks = []
        g = next((x for x in games if x["id"] == gid), None)
        if g is None:
            continue
        # ---- depth scorer
        cands = []
        for team, T in G.groupby("team"):
            lineup = set(strength.get(team, []))
            F = T[(T.pos == "F") & T.player_id.isin(lineup)].sort_values("proj_toi", ascending=False)
            F = F.assign(rank=np.arange(1, len(F) + 1))
            for x in F[F["rank"] >= 7].itertuples():
                if x.lineup != "last" or x.player_id not in R.index:
                    continue
                r = R.loc[x.player_id]
                if r.n < 4 or r.toi < 40 or r.hd < 3 or x.p_goal < 0.12:
                    continue
                q, qh = pct_of("ixg60", r.ixg60), pct_of("hd60", r.hd60)
                mu = float(x.def_f * x.g_f)
                if q < 0.70 or mu < 1.0:          # dangerous lately, and tonight's defense and goalie are no better than average
                    continue
                score = q + 0.5 * qh + 2.0 * (mu - 1) + 2.0 * (x.p_goal - 0.15)
                cands.append((score, x, r, q, mu, int(x.rank)))
        if cands:
            score, x, r, q, mu, rk = max(cands, key=lambda c: c[0])
            line = "third" if rk <= 9 else "fourth"
            og = opp_goalie.get((gid, x.team))
            G_ = gl.get(og) if og else None
            bits = [f"{x.name} plays on the {line} line, about {_mmss(x.proj_toi)} a night, but his shots have been dangerous: "
                    f"{r.ixg:.1f} expected goals in his last {int(r.n)} games ({r.ixg60:.2f} per 60, better than {round(100 * q)}% of "
                    f"depth forwards), with {int(r.hd)} shots from high-danger spots."]
            rk_ = dfr.get(x.opp)
            opp_bit = (f"{x.opp} give up the {_ord(rk_)}-most expected goals per 60" if rk_ and rk_ <= 12 else
                       f"{x.opp} are about average at keeping chances down ({_ord(rk_)} in expected goals allowed per 60)" if rk_ and rk_ <= 20 else None)
            gk_bit = (f"{G_['name']} has allowed {abs(G_['gsax']):.1f} more goals than his shots deserved"
                      if G_ and G_.get("gsax") is not None and G_["gsax"] <= -1.5 else None)
            if opp_bit or gk_bit:
                bits.append("Tonight " + (opp_bit + (", and " + gk_bit if gk_bit else "") if opp_bit else gk_bit) + ".")
            bits.append(f"We have him at {round(100 * x.p_goal)}% to score and {round(100 * x.p_1pt)}% for a point.")
            picks.append(dict(id=int(x.player_id), name=x.name, team=x.team, opp=x.opp, kind="depth", line=line,
                              p_goal=round(float(x.p_goal), 4), p_1pt=round(float(x.p_1pt), 4), fair_goal=american(x.p_goal),
                              fair_point=american(x.p_1pt),
                              facts=dict(games=int(r.n), expected_goals=round(float(r.ixg), 2), expected_goals_per_60=round(float(r.ixg60), 2),
                                         better_than_pct_of_depth_forwards=round(100 * q), high_danger_shots=int(r.hd),
                                         shots_on_goal=int(r.sog), goals=int(r.g), opponent_defense_rank=dfr.get(x.opp),
                                         opponent_goalie=G_["name"] if G_ else None,
                                         opponent_goalie_saved_above_expected=G_.get("gsax") if G_ else None),
                              why=" ".join(bits)))
        # ---- underrated for a point
        pc = []
        for x in G[(G.lineup == "last") & (G.p_1pt >= 0.38)].itertuples():
            if any(p["id"] == int(x.player_id) for p in picks):
                continue
            s = season.loc[x.player_id] if x.player_id in season.index else None
            gp = int(s.gp) if s is not None else 0
            pp = float(s.pts) if s is not None else 0.0
            if pts_rank.get(x.player_id, 999) <= 60 or (prev_ppg.get(x.player_id, 0) or 0) >= 0.75:
                continue
            pv = prev_ppg.get(x.player_id)
            pos_avg = 0.55 if x.pos == "F" else 0.35
            naive = (pp + 20 * pv) / (gp + 20) if pv == pv and pv is not None else (pp + 8 * pos_avg) / (gp + 8)
            naive_p1 = 1 - np.exp(-naive)
            gap = float(x.p_1pt - naive_p1)
            if gap < 0.06:
                continue
            reasons, facts = [], dict(season_points=int(pp), season_games=gp, season_pace_point_pct=round(100 * naive_p1),
                                      our_point_pct=round(100 * float(x.p_1pt)))
            c = ctx.loc[x.player_id] if ctx is not None and x.player_id in ctx.index else None
            if s is not None and x.proj_toi - s.toi_pg >= 1.2:
                reasons.append(f"his ice time is up ({_mmss(x.proj_toi)} a night projected, {_mmss(s.toi_pg)} on the season)")
                facts["projected_minutes"], facts["season_minutes"] = round(float(x.proj_toi), 1), round(float(s.toi_pg), 1)
            if c is not None and c.pp3 >= 1.8 and c.pp_all < 1.2:
                reasons.append(f"he's on the power play now ({c.pp3:.1f} power-play minutes a game over his last three)")
                facts["power_play_minutes_last_three"] = round(float(c.pp3), 1)
            if c is not None and x.pos == "F" and c.rank5 <= 6 and c.rank_med >= 7:
                mates = [names.get(int(m), "") for m in (c.mate1, c.mate2) if m == m and m is not None]
                mates = [m for m in mates if m]
                reasons.append("he moved into the top six last game" + (f", with {' and '.join(mates)}" if mates else ""))
                facts["moved_up_with"] = mates
            if x.pos == "F" and len(of_ref) and float((of_ref <= x.oxgf60).mean()) >= 0.75:
                reasons.append(f"his line creates chances ({x.oxgf60:.2f} expected goals per 60 with him on the ice)")
                facts["on_ice_expected_goals_per_60"] = round(float(x.oxgf60), 2)
            if x.def_f * x.g_f >= 1.05 and dfr.get(x.opp, 99) <= 10:
                reasons.append(f"{x.opp} give up the {_ord(dfr[x.opp])}-most expected goals per 60")
                facts["opponent_defense_rank"] = dfr.get(x.opp)
            if not reasons:
                continue
            pc.append((gap, x, reasons, facts, naive_p1))
        if pc:
            gap, x, reasons, facts, naive_p1 = max(pc, key=lambda c: c[0])
            why = (f"{x.name} is {round(100 * x.p_1pt)}% for a point tonight, {'well ' if gap >= 0.10 else ''}above what his season pace says "
                   f"({round(100 * naive_p1)}%): " + (", ".join(reasons[:-1]) + ", and " + reasons[-1] if len(reasons) > 1 else reasons[0]) + ".")
            picks.append(dict(id=int(x.player_id), name=x.name, team=x.team, opp=x.opp, kind="point",
                              p_goal=round(float(x.p_goal), 4), p_1pt=round(float(x.p_1pt), 4), fair_goal=american(x.p_goal),
                              fair_point=american(x.p_1pt), facts=facts, why=why))
        if picks:
            out[gid] = picks
            for p in picks:
                kinds[p["id"]] = p["kind"]
    return out, kinds
