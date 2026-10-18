"""The coaching view of each team, from the NHL's shift charts and events (our own data).

Play is cut into stretches where the same skaters are on the ice. Each stretch is tagged with the game state from
the events (5v5, power play, penalty kill), then:
  forward lines (three forwards together) and defense pairs at 5v5: minutes, shot attempts, expected goals and goals
    for and against while that group was out (xG: MoneyPuck where the shot matches, our model otherwise)
  power-play and penalty-kill units: the most-used groups of skaters, their minutes and xG for/against per 60
  deployment per skater: 5v5, power-play and penalty-kill minutes a game, average shift length, share of 5v5
    faceoffs in the offensive and defensive zones
  team style from All Three Zones tracking when it's available (carry-in share, controlled exits, entry defence)
Writes the dict that build.py stores as data/tactics/<team>.json.
"""
import numpy as np
import pandas as pd

FWD_MIN, PAIR_MIN, UNIT_MIN = 15.0, 15.0, 4.0     # minutes together before a group is listed


def _segments(gsh, ev_gp, home, away):
    """Constant-lineup stretches in one game-period: (start, end, home skaters, away skaters, situation code)."""
    pts = sorted(set(gsh.start_sec.tolist()) | set(gsh.end_sec.tolist()))
    e = ev_gp.sort_values(["psec", "sort_order"])
    et, ec = e.psec.values.astype(float), e.sc.values
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        if b <= a:
            continue
        on = gsh[(gsh.start_sec <= a) & (gsh.end_sec >= b)]
        hs = frozenset(on[on.team == home].player_id)
        as_ = frozenset(on[on.team == away].player_id)
        i = np.searchsorted(et, (a + b) / 2)          # the next event's code describes this stretch
        code = ec[i] if i < len(ec) else (ec[-1] if len(ec) else "1551")
        out.append((a, b, hs, as_, code))
    return out


def build(season_ev, shifts, positions, shots, a3z_team=None):
    """season_ev: events (regular season, no shootouts) with sc and psec; shifts: skater shifts; positions: id -> F/D;
    shots: unblocked + blocked attempts with xgv (blocked = 0), team, game_id, period, psec, event."""
    ev = season_ev
    sh = shifts[shifts.player_id.map(positions).isin(["F", "D"])]
    groups = {}          # (team, kind, key) -> stats
    player = {}          # player_id -> deployment stats
    def acc(team, kind, key, **kw):
        g = groups.setdefault((team, kind, key), dict(toi=0.0, cf=0, ca=0, xgf=0.0, xga=0.0, gf=0, ga=0))
        for k, v in kw.items():
            g[k] += v
    def pacc(pid, **kw):
        p = player.setdefault(pid, dict(toi5=0.0, toipp=0.0, toipk=0.0))
        for k, v in kw.items():
            p[k] = p.get(k, 0) + v

    for (gid, per), gsh in sh.groupby(["game_id", "period"]):
        e = ev[(ev.game_id == gid) & (ev.period == per)]
        if e.empty:
            continue
        home, away = e.home_team.iloc[0], e.away_team.iloc[0]
        segs = _segments(gsh, e, home, away)
        if not segs:
            continue
        sv = shots[(shots.game_id == gid) & (shots.period == per)]
        st = np.array([s[0] for s in segs]), np.array([s[1] for s in segs])
        # shots into the stretch they happened in (start < t <= end, the house rule for on-ice credit)
        idx = {}
        for x in sv.itertuples():
            j = np.searchsorted(st[1], x.psec, side="left")
            if j < len(segs) and segs[j][0] < x.psec <= segs[j][1]:
                idx.setdefault(j, []).append(x)
        for j, (a, b, hs, as_, code) in enumerate(segs):
            dur = (b - a) / 60
            nh, na = int(code[2]), int(code[1])
            both_goalies = code[0] == "1" and code[3] == "1"
            for team, mine, theirs, n_own, n_opp in ((home, hs, as_, nh, na), (away, as_, hs, na, nh)):
                f = sorted(p for p in mine if positions.get(p) == "F")
                d = sorted(p for p in mine if positions.get(p) == "D")
                state = "5v5" if code == "1551" else ("pp" if both_goalies and n_own > n_opp else ("pk" if both_goalies and n_own < n_opp else None))
                evs = idx.get(j, [])
                kw = dict(toi=dur, cf=sum(1 for x in evs if x.team == team), ca=sum(1 for x in evs if x.team != team),
                          xgf=sum(x.xgv for x in evs if x.team == team), xga=sum(x.xgv for x in evs if x.team != team),
                          gf=sum(1 for x in evs if x.team == team and x.event == "goal"),
                          ga=sum(1 for x in evs if x.team != team and x.event == "goal"))
                if state == "5v5":
                    if len(f) == 3:
                        acc(team, "line", tuple(f), **kw)
                    if len(d) == 2:
                        acc(team, "pair", tuple(d), **kw)
                    for p in mine:
                        pacc(p, toi5=dur)
                elif state in ("pp", "pk") and len(mine) >= 3:
                    acc(team, state, tuple(sorted(mine)), **kw)
                    for p in mine:
                        pacc(p, **{("toipp" if state == "pp" else "toipk"): dur})
    rows = [dict(team=t, kind=k, ids=list(key), **v) for (t, k, key), v in groups.items()]
    G = pd.DataFrame(rows)
    # shift lengths and games
    sl = sh.assign(dur=sh.end_sec - sh.start_sec)
    sl = sl[sl.dur > 0].groupby("player_id").agg(shift=("dur", "mean"), gp=("game_id", "nunique"), team=("team", "last"))
    P = pd.DataFrame.from_dict(player, orient="index").join(sl, how="outer").fillna({"toi5": 0, "toipp": 0, "toipk": 0})
    return G, P


def team_view(team, G, P, names, defense=None, a3z_team=None, lg_style=None):
    """Everything the team page's tactical section needs, as plain JSON."""
    nm = lambda ids: [dict(id=int(i), name=names.get(int(i), "")) for i in ids]
    def grp(kind, min_toi, n):
        g = G[(G.team == team) & (G.kind == kind) & (G.toi >= min_toi)].sort_values("toi", ascending=False).head(n)
        out = []
        for r in g.itertuples():
            out.append(dict(players=nm(r.ids), toi=round(r.toi, 1), xgf60=round(r.xgf / r.toi * 60, 2),
                            xga60=round(r.xga / r.toi * 60, 2), xg_pct=round(r.xgf / (r.xgf + r.xga), 3) if (r.xgf + r.xga) else None,
                            cf_pct=round(r.cf / (r.cf + r.ca), 3) if (r.cf + r.ca) else None, gf=int(r.gf), ga=int(r.ga)))
        return out
    lines, pairs = grp("line", FWD_MIN, 4), grp("pair", PAIR_MIN, 3)
    pp, pk = grp("pp", UNIT_MIN, 2), grp("pk", UNIT_MIN, 3)
    q = P[P.team == team].copy()
    q = q[q.gp > 0]
    dep = []
    q["per"] = q.toi5 / q.gp
    for pid, r in q.sort_values("per", ascending=False).iterrows():
        dz = oz = None
        if defense is not None and pid in defense.index:
            dd = defense.loc[pid]
            tot = dd.fo_oz + dd.fo_dz
            oz = round(float(dd.fo_oz / tot), 3) if tot else None
            dz = round(float(dd.fo_dz / tot), 3) if tot else None
        dep.append(dict(id=int(pid), name=names.get(int(pid), ""), gp=int(r.gp), toi5=round(r.toi5 / r.gp, 1), pp=round(r.toipp / r.gp, 1),
                        pk=round(r.toipk / r.gp, 1), shift=round(float(r["shift"]), 0) if not pd.isna(r["shift"]) else None, oz=oz, dz=dz))
    team_rows = G[G.team == team]
    tot = {k: team_rows[team_rows.kind == k][["toi", "xgf", "xga", "gf", "ga"]].sum().to_dict() for k in ("pp", "pk")}
    style = a3z_team.get(team) if a3z_team else None
    return dict(team=team, lines=lines, pairs=pairs, pp_units=pp, pk_units=pk, deployment=dep,
                special=dict(pp=dict(toi=round(tot["pp"]["toi"], 1), xgf60=round(tot["pp"]["xgf"] / tot["pp"]["toi"] * 60, 2) if tot["pp"]["toi"] else None,
                                     gf=int(tot["pp"]["gf"])),
                             pk=dict(toi=round(tot["pk"]["toi"], 1), xga60=round(tot["pk"]["xga"] / tot["pk"]["toi"] * 60, 2) if tot["pk"]["toi"] else None,
                                     ga=int(tot["pk"]["ga"]))),
                style=style, style_lg=lg_style)


def a3z_style(season):
    """Team style from All Three Zones (5v5, tracked games): carry-in share, entry defence, controlled exits, rush share."""
    import a3z as A3
    if not A3.available(season):
        return None, None
    en, ex = A3.load(season, "entries"), A3.load(season, "exits")
    sh = A3.load(season, "shots")
    out = {}
    for team in sorted(set(en.team.dropna())):
        e = en[en.team == team]
        carry = (e.type.astype(str).str.lower() == "c").mean() if len(e) else None
        # entries against: rows where the defending team is this team are entries by its opponents in its games
        games = set(e.game_id)
        ea = en[(en.game_id.isin(games)) & (en.team != team)]
        x = ex[ex.team == team]
        ctl = x.exit_result.astype(str).str.lower().isin(["cex", "pex"]).mean() if len(x) else None
        s = sh[sh.team == team] if "team" in sh.columns else pd.DataFrame()
        rush = (s["play"].astype(str).str.lower() == "r").mean() if len(s) and "play" in s.columns else None
        out[team] = dict(games=len(games), carry_in=None if carry is None else round(float(carry), 3),
                         carry_in_against=round(float((ea.type.astype(str).str.lower() == "c").mean()), 3) if len(ea) else None,
                         controlled_exits=None if ctl is None else round(float(ctl), 3), rush_share=None if rush is None else round(float(rush), 3))
    vals = lambda k: [v[k] for v in out.values() if v.get(k) is not None]
    lg = {k: round(float(np.median(vals(k))), 3) for k in ("carry_in", "carry_in_against", "controlled_exits", "rush_share") if vals(k)}
    return out, lg
