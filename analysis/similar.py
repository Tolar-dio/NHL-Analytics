"""Plays like: the skaters whose game looks most like his.

Each skater with 300+ minutes over this season and last is described by how he is used and what he does, all as
rates so ice time doesn't decide it: minutes a game, power-play and penalty-kill shares, shot attempts and shot
quality, primary assists and the assist share of his points, on-ice chances for and against, hits and blocks, and
when we have them NHL EDGE top speed and hardest shot and All Three Zones (credited) chances, shot assists, entries,
carry-ins, possession exits and entry denials. Every measure is turned into a z-score within his position (forwards
and defensemen separately), groups are weighted so no one kind of measure dominates, and the closest players by
distance are his comps. The match score is 100 at identical and falls with distance; "what they share" names the
measures where both sit well away from average on the same side.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "output")
MIN_TOI = 300.0

# (column, group, label when high, label when low)
FEATS = [
    ("toi_pg", "role", "big minutes", "limited minutes"),
    ("pp_share", "role", "a power-play regular", "little power-play time"),
    ("pk_share", "role", "kills penalties", None),
    ("ush60", "shoot", "shoots a lot", "shoots rarely"),
    ("xg_per", "shoot", "shoots from dangerous spots", "shoots from distance"),
    ("a1_60", "pass", "sets up teammates", None),
    ("ast_share", "pass", "more passer than finisher", "more finisher than passer"),
    ("xgf60", "onice", "his team creates a lot with him on", "his team creates little with him on"),
    ("xga60", "onice", "chances against pile up with him on", "keeps chances against down"),
    ("hits60", "phys", "hits a lot", None),
    ("blk60", "phys", "blocks shots", None),
    ("speed", "edge", "top-end speed", None),
    ("shot_mph", "edge", "a heavy shot", None),
    ("chances60", "a3z", "gets to scoring chances", None),
    ("sa1_60", "a3z", "creates shots for others", None),
    ("entries60", "a3z", "drives zone entries", None),
    ("carry_pct", "a3z", "carries the puck in", "dumps the puck in"),
    ("exit_poss_pct", "a3z", "exits with possession", "clears the puck"),
    ("denial_pct", "a3z", "denies entries at his line", None),
]
GROUP_W = {"role": 1.0, "shoot": 1.0, "pass": 1.0, "onice": 0.8, "phys": 0.6, "edge": 0.5, "a3z": 1.0}


def profile(seasons, sk=None, edge=None, a3z_rows=None):
    """One row per skater: totals over the given seasons as rates, plus optional extras keyed by player id."""
    pg = pd.concat([pd.read_csv(os.path.join(OUT, s, "player_games.csv")) for s in seasons])
    pg = pg[pg.game_type == "regular"]
    t = pg.groupby("player_id").agg(pos=("pos", "last"), team=("team", "last"), gp=("game_id", "nunique"), toi=("toi", "sum"),
                                    ush=("ush", "sum"), ixg=("ixg", "sum"), a1=("a1", "sum"), a=("a", "sum"), pts=("pts", "sum"),
                                    xgf=("xgf", "sum"), xga=("xga", "sum"))
    ctx = pd.concat([pd.read_csv(os.path.join(OUT, s, "context_games.csv")) for s in seasons
                     if os.path.exists(os.path.join(OUT, s, "context_games.csv"))])
    ctx = ctx[ctx.game_type == "regular"].groupby("player_id")[["toipp", "toipk"]].sum()
    t = t.join(ctx)
    t = t[(t.toi >= MIN_TOI) & (t.pos != "G")].copy()
    t["pos"] = np.where(t.pos == "D", "D", "F")
    per60 = lambda c: t[c] / t.toi * 60
    t["toi_pg"] = t.toi / t.gp
    t["pp_share"], t["pk_share"] = t.toipp / t.toi, t.toipk / t.toi
    t["ush60"], t["xg_per"], t["a1_60"] = per60("ush"), t.ixg / t.ush.where(t.ush > 0), per60("a1")
    t["ast_share"] = t.a / t.pts.where(t.pts >= 5)
    t["xgf60"], t["xga60"] = per60("xgf"), per60("xga")
    if sk is not None:   # this season's hits and blocks (counts depend on each rink's scorer; a light weight)
        s = sk.set_index("id") if "id" in sk else sk
        cur_toi = s.toi_pg * s.gp
        t["hits60"] = (s.hits / cur_toi * 60).reindex(t.index)
        t["blk60"] = (s.blk / cur_toi * 60).reindex(t.index)
        if "max_speed_mph" in s:
            t["speed"], t["shot_mph"] = s.max_speed_mph.reindex(t.index), s.top_shot_mph.reindex(t.index)
    if a3z_rows is not None and len(a3z_rows):
        t = t.join(a3z_rows[[c for c, g, *_ in FEATS if g == "a3z" and c in a3z_rows]], how="left")
    return t


def comps(t, names, k=3):
    feats = [f for f in FEATS if f[0] in t]
    out = {}
    for pos, q in t.groupby("pos"):
        Z = pd.DataFrame(index=q.index)
        w = []
        for c, g, *_ in feats:
            x = q[c].astype(float)
            sd = x.std()
            Z[c] = ((x - x.mean()) / sd).clip(-3, 3) if sd and sd == sd else 0.0
            w.append(GROUP_W[g] / sum(1 for f in feats if f[1] == g))
        w = np.array(w)
        have = Z.notna().values
        z = Z.fillna(0).values
        for i, pid in enumerate(q.index):
            both = have[i] & have          # compare only measures both players have
            diff = (z - z[i]) ** 2 * w * both
            wsum = (w * both).sum(axis=1)
            d = np.sqrt(diff.sum(axis=1) / np.maximum(wsum, 1e-9))
            d[i] = np.inf
            d[wsum < 0.6 * w.sum()] = np.inf
            best = np.argsort(d)[:k]
            rows = []
            for j in best:
                if not np.isfinite(d[j]):
                    continue
                shared = []
                for fi, (c, g, hi, lo) in enumerate(feats):
                    a, b = z[i, fi], z[j, fi]
                    if have[i, fi] and have[j, fi] and min(a, b) >= 0.8 and hi:
                        shared.append((min(a, b), hi))
                    elif have[i, fi] and have[j, fi] and max(a, b) <= -0.8 and lo:
                        shared.append((-max(a, b), lo))
                shared = [s for _, s in sorted(shared, reverse=True)[:3]]
                rows.append(dict(id=int(q.index[j]), name=names.get(int(q.index[j])), team=q.team.iloc[j],
                                 match=int(round(100 * np.exp(-d[j] ** 2 / 2))), shared=shared))
            out[int(pid)] = dict(pos=pos, comps=rows)
    return out
