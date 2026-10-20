"""Lineup context per game, from the NHL's shift charts and events: who played with whom, and in what role.

For every skater-game (regular season and playoffs, no shootouts):
  toi5, toipp, toipk     minutes at 5v5, on the power play and on the penalty kill (both goalies in net)
  toi_sh                 all minutes from the shift chart
  ixg_pp, ixg_np         his own expected goals on the power play and in all other states
  xgf_pp, xgf_np         expected goals for while he was on the ice, power play vs everything else
  rank5                  his rank by 5v5 minutes among his team's forwards (or defensemen) that night
  mate1, mate2, dmate    the two forwards (forwards) or the defenseman (D) he shared the most 5v5 time with
  pp_rank                his rank by power-play minutes on his team that night (1-5 is the first unit, roughly)
And for every team-game, the 5v5 minutes and expected goals it ALLOWED against top-six forward groups and against
depth groups (the three attacking forwards' average 5v5-minutes rank: 6.5 or better is top six).

xG per shot: MoneyPuck's where the shot matches (credit MoneyPuck.com), else ours (as in defense.py).
Writes analysis/output/<season>/context_games.csv and tier_games.csv.

  python analysis/context.py 20252026
"""
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from defense import _xg  # noqa: E402

ATT = ["shot-on-goal", "missed-shot", "goal", "blocked-shot"]


def _state(code, home):
    """'5v5', 'pp', 'pk' or '' for one side of a situation code (away goalie, away sk, home sk, home goalie)."""
    if code == "1551":
        return "5v5"
    if code[0] != "1" or code[3] != "1":
        return ""
    own, opp = (int(code[2]), int(code[1])) if home else (int(code[1]), int(code[2]))
    return "pp" if own > opp else ("pk" if own < opp else "")


def build(season):
    T = os.path.join(ROOT, "data", "tables", season)
    ev = pd.read_csv(os.path.join(T, "events.csv.gz"))
    ev = ev[(ev.period_type != "SO") & ev.situation_code.notna()].copy()
    ev["sc"] = ev.situation_code.astype(int).astype(str).str.zfill(4)
    ev["psec"] = ev.game_seconds - (ev.period.clip(upper=4) - 1) * 1200
    sh = pd.read_csv(os.path.join(T, "shifts.csv.gz")).dropna(subset=["player_id"])
    pos = pd.read_csv(os.path.join(T, "players.csv.gz")).drop_duplicates("player_id").set_index("player_id").position
    pos = pos.map(lambda p: "G" if p == "G" else ("D" if p == "D" else "F"))
    sh["player_id"] = sh.player_id.astype(int)
    sh["pos"] = sh.player_id.map(pos).fillna("F")
    sh = sh[(sh.pos != "G") & (sh.end_sec > sh.start_sec)]
    att = _xg(season, ev[ev.event.isin(ATT)].copy())
    att["goal"] = (att.event == "goal").astype(int)
    home_of = ev.drop_duplicates("game_id").set_index("game_id").home_team

    rows, tier = [], []
    shg = dict(tuple(sh.groupby("game_id")))
    evg = dict(tuple(ev.groupby("game_id")))
    atg = dict(tuple(att.groupby("game_id")))
    for gid, gsh in shg.items():
        e_all, a_all = evg.get(gid), atg.get(gid)
        if e_all is None:
            continue
        home = home_of[gid]
        stat = defaultdict(lambda: defaultdict(float))      # player -> stat -> value
        team_of = dict(zip(gsh.player_id, gsh.team))
        pos_of = dict(zip(gsh.player_id, gsh.pos))
        pair5 = defaultdict(float)                         # (p, q) -> shared 5v5 seconds
        groups = defaultdict(lambda: [0.0, 0.0, 0])        # (attacking team, forward set) -> [sec, xgf, gf]
        for per, s in gsh.groupby("period"):
            e = e_all[e_all.period == per].sort_values(["psec", "sort_order"])
            if e.empty:
                continue
            et, ec = e.psec.values.astype(float), e.sc.values
            b = np.unique(np.concatenate([s.start_sec.values, s.end_sec.values, et]).astype(float))
            if len(b) < 2:
                continue
            a0, a1 = b[:-1], b[1:]
            dur = a1 - a0
            nxt = np.minimum(np.searchsorted(et, (a0 + a1) / 2), len(ec) - 1)
            codes = ec[nxt]
            players, pidx = np.unique(s.player_id.values, return_inverse=True)
            cover = (s.start_sec.values[:, None] <= a0[None, :]) & (s.end_sec.values[:, None] >= a1[None, :])
            P = np.zeros((len(players), len(a0)))
            np.add.at(P, pidx, cover.astype(float))
            P = (P > 0).astype(float)
            teams = np.array([team_of[p] for p in players])
            ishome = teams == home
            st_h = np.array([_state(c, True) for c in codes])
            st_a = np.array([_state(c, False) for c in codes])
            for side_home, st in ((True, st_h), (False, st_a)):
                m = ishome == side_home
                if not m.any():
                    continue
                Pm = P[m]
                for key in ("5v5", "pp", "pk"):
                    w = dur * (st == key) / 60
                    for p, v in zip(players[m], Pm @ w):
                        stat[p]["toi" + ("5" if key == "5v5" else key)] += v
                for p, v in zip(players[m], Pm @ (dur / 60)):
                    stat[p]["toi_sh"] += v
                # shared 5v5 time between teammates
                w5 = dur * (st == "5v5")
                S = (Pm * w5) @ Pm.T
                ids = players[m]
                iu, ju = np.triu_indices(len(ids), 1)
                for i, j in zip(iu, ju):
                    if S[i, j] > 0:
                        pair5[(ids[i], ids[j])] += S[i, j]
                # forward groups at 5v5, for the depth-vs-top-six split
                fm = np.array([pos_of[p] == "F" for p in ids])
                team = teams[m][0]
                for k in np.nonzero(st == "5v5")[0]:
                    on = tuple(sorted(ids[fm & (Pm[:, k] > 0)]))
                    if len(on) == 3:
                        groups[(team, on)][0] += dur[k]
            # shots: individual xG by state, on-ice xGF split power play / other, and xG for each 5v5 forward group
            if a_all is not None:
                sv = a_all[a_all.period == per]
                for x in sv.itertuples():
                    k = np.searchsorted(a1, x.psec, side="left")           # interval with a0 < t <= a1
                    if k >= len(a0) or not (a0[k] < x.psec <= a1[k]):
                        continue
                    shooter_home = x.team == home
                    stt = (st_h if shooter_home else st_a)[k]
                    xg = float(x.xg) if x.event != "blocked-shot" else 0.0
                    if x.player1_id == x.player1_id:
                        stat[int(x.player1_id)]["ixg_pp" if stt == "pp" else "ixg_np"] += xg
                    on_team = (P[:, k] > 0) & (ishome == shooter_home)
                    for p in players[on_team]:
                        stat[p]["xgf_pp" if stt == "pp" else "xgf_np"] += xg
                    if stt == "5v5":
                        fwd = tuple(sorted(p for p in players[on_team] if pos_of.get(p) == "F"))
                        if len(fwd) == 3:
                            g = groups[(x.team, fwd)]
                            g[1] += xg
                            g[2] += int(x.goal) if x.event != "blocked-shot" else 0
        # ranks and linemates
        df = pd.DataFrame([dict(player_id=p, **v) for p, v in stat.items() if p in team_of])
        if df.empty:
            continue
        df["team"], df["pos"] = df.player_id.map(team_of), df.player_id.map(pos_of)
        for c in ("toi5", "toipp", "toipk", "toi_sh", "ixg_pp", "ixg_np", "xgf_pp", "xgf_np"):
            if c not in df:
                df[c] = 0.0
        df = df.fillna(0.0)
        df["rank5"] = df.groupby(["team", "pos"]).toi5.rank(ascending=False, method="first").astype(int)
        df["pp_rank"] = df.groupby("team").toipp.rank(ascending=False, method="first").astype(int)
        mates = defaultdict(list)
        for (p, q), v in pair5.items():
            mates[p].append((v, q))
            mates[q].append((v, p))
        m1, m2, dm, s1, s2 = [], [], [], [], []
        for p, ps in zip(df.player_id, df.pos):
            fw = sorted(((v, q) for v, q in mates[p] if pos_of.get(q) == "F"), reverse=True)
            dd = sorted(((v, q) for v, q in mates[p] if pos_of.get(q) == "D"), reverse=True)
            if ps == "F":
                m1.append(fw[0][1] if len(fw) > 0 else None); s1.append(fw[0][0] / 60 if fw else 0)
                m2.append(fw[1][1] if len(fw) > 1 else None); s2.append(fw[1][0] / 60 if len(fw) > 1 else 0)
                dm.append(None)
            else:
                m1.append(None); m2.append(None); s1.append(dd[0][0] / 60 if dd else 0); s2.append(0)
                dm.append(dd[0][1] if dd else None)
        df["mate1"], df["mate2"], df["dmate"], df["shared1"], df["shared2"] = m1, m2, dm, s1, s2
        df["game_id"] = gid
        rows.append(df)
        rk = dict(zip(zip(df.team, df.player_id), df.rank5))
        for (team, on), (sec, xg, gl) in groups.items():
            r = np.mean([rk.get((team, p), 12) for p in on])
            opp = [t for t in set(team_of.values()) if t != team]
            tier.append(dict(game_id=gid, team=opp[0] if opp else None, att=team, tier="top" if r <= 6.5 else "depth",
                             toi=sec / 60, xga=xg, ga=gl))
    C = pd.concat(rows, ignore_index=True)
    for c in ("mate1", "mate2", "dmate"):
        C[c] = C[c].astype("Int64")
    Tt = pd.DataFrame(tier).groupby(["game_id", "team", "att", "tier"], as_index=False)[["toi", "xga", "ga"]].sum()
    games = pd.read_csv(os.path.join(T, "games.csv.gz")).set_index("game_id")
    for df in (C, Tt):
        df["date"] = df.game_id.map(games.date)
        df["game_type"] = df.game_id.map(games.game_type)
    out = os.path.join(ROOT, "analysis", "output", season)
    os.makedirs(out, exist_ok=True)
    C.to_csv(os.path.join(out, "context_games.csv"), index=False)
    Tt.to_csv(os.path.join(out, "tier_games.csv"), index=False)
    return C, Tt


if __name__ == "__main__":
    import time
    t0 = time.time()
    C, Tt = build(sys.argv[1] if len(sys.argv) > 1 else "20262027")
    print(f"context: {len(C)} player-games, {C.game_id.nunique()} games; tiers {len(Tt)} rows; {time.time() - t0:.0f}s")
    print(C[["toi5", "toipp", "toipk", "toi_sh"]].describe().round(2))
