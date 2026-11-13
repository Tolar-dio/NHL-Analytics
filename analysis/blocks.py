"""Blocked-shot prices for tonight's props.

Rate per 60 = this season's blocks blended with last season's rate (worth K minutes; players with no usable last
season get their position's rate), times projected ice time, times how many shot attempts tonight's opponent takes
per game relative to league (this season, shrunk with KO league-average games): a team that shoots a lot gives a
defender more to block. Counts follow a negative binomial with shape SIZE. Blocks are the official boxscore
counts (what props settle on), which depend a little on each rink's scorer.

`python analysis/blocks.py check` fits on 2025-26 (walk-forward, position rates as the prior, since we have no
2024-25 tables) and checks on 2026-27 with our 2025-26 rates as the prior, using the projected ice time the points
backtest used (bt_players.csv; pass a 2026-27 backtest file as the third argument).

Fit Nov 12, 2026 on 2025-26 (44k player-games): mean 0.79 predicted vs 0.79 actual, NB log likelihood per game
-1.113 vs -1.138 for a flat position average; 1+ 48.9% vs 48.8%, 2+ 19.3% vs 19.1%, 3+ 7.1% vs 7.1%. Checked on
2026-27 with priors (9.4k): -1.106 vs -1.131; 1+ 47.7% vs 48.5%, 2+ 18.6% vs 18.7%, 3+ 6.8% vs 6.8%. KO 3 and
SIZE 10 scored the same within noise.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import nbinom

K, KO, SCALE, SIZE = 300, 5, 0.98, 12
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _regular(df):
    return df[df.game_id.astype(str).str[4:6] == "02"]


def parts(rows, cur_pg, prev_pg, cur_tg, cut):
    """The pieces of the mean that don't depend on the tuning constants (so a fit can vary them cheaply)."""
    cur = _regular(cur_pg)
    cur = cur[cur.date < cut]
    prev = _regular(prev_pg) if prev_pg is not None else cur.iloc[0:0]
    a = cur.groupby("player_id").agg(blk=("blk", "sum"), toi=("toi", "sum"))
    pv = prev.groupby("player_id").agg(blk=("blk", "sum"), toi=("toi", "sum"))
    pv = pv[pv.toi >= 200]
    base = prev if len(prev) else cur
    posr = (base.groupby("pos").blk.sum() / base.groupby("pos").toi.sum() * 60).to_dict()
    tg = _regular(cur_tg)
    tg = tg[tg.date < cut]
    lg = tg.attf.mean() if len(tg) else 57.5
    o = tg.groupby("team").attf.agg(["sum", "count"])
    d = rows.copy()
    d["rp"] = d.player_id.map((pv.blk / pv.toi * 60).to_dict()).fillna(d.pos.map(posr)).fillna(3.0)
    d["sc"] = d.player_id.map(a.blk).fillna(0)
    d["tc"] = d.player_id.map(a.toi).fillna(0)
    d["o_sum"] = d.opp.map(o["sum"]).fillna(0)
    d["o_n"] = d.opp.map(o["count"]).fillna(0)
    d["lg_att"] = lg
    return d


def mean(d, k=K, ko=KO, scale=SCALE):
    r60 = (d.sc + d.rp * k / 60) / (d.tc + k) * 60
    of = ((d.o_sum + d.lg_att * ko) / (d.o_n + ko)) / d.lg_att
    return r60 * d.proj_toi / 60 * of * scale


def tail(mu, k, size=SIZE):
    return 1 - nbinom.cdf(k - 1, size, size / (size + mu))


def prices(rows, cur_pg, prev_pg, cur_tg, cut):
    """rows: DataFrame with player_id, opp, pos, proj_toi. Returns rows with exp_blk and p_blk1/2/3."""
    d = parts(rows, cur_pg, prev_pg, cur_tg, cut)
    mu = mean(d)
    out = rows.copy()
    out["exp_blk"] = mu.round(2)
    for k in (1, 2, 3):
        out[f"p_blk{k}"] = tail(mu, k)
    return out


def _walk(bt, cur_pg, prev_pg, cur_tg):
    y = cur_pg.set_index(["game_id", "player_id"]).blk
    out = []
    for cut, rows in bt.groupby("date"):
        d = parts(rows[["player_id", "game_id", "opp", "pos", "proj_toi"]], cur_pg, prev_pg, cur_tg, cut)
        out.append(d)
    d = pd.concat(out)
    d["y"] = [y.get((g, p), np.nan) for g, p in zip(d.game_id, d.player_id)]
    return d.dropna(subset=["y"])


def _score(d, k, ko, scale, size):
    mu = mean(d, k, ko, scale)
    return -nbinom.logpmf(d.y.astype(int), size, size / (size + mu)).mean()


def _report(d, label, k=K, ko=KO, scale=SCALE, size=SIZE):
    mu = mean(d, k, ko, scale)
    print(f"{label}: {len(d)} player-games, mean {mu.mean():.3f} predicted vs {d.y.mean():.3f} actual, "
          f"loglik/game {-_score(d, k, ko, scale, size):.4f}")
    flat = d.groupby("pos").y.transform("mean")
    print(f"  position-average baseline loglik/game {nbinom.logpmf(d.y.astype(int), size, size / (size + flat)).mean():.4f}")
    for t in (1, 2, 3):
        p = tail(mu, t, size)
        yy = (d.y >= t).astype(int)
        ll = -(yy * np.log(p) + (1 - yy) * np.log(1 - p)).mean()
        print(f"  {t}+ blocks: {100 * p.mean():.1f}% predicted vs {100 * yy.mean():.1f}% actual, log loss {ll:.4f}")
    q = d.assign(p=tail(mu, 2, size), yy=(d.y >= 2).astype(int), b=pd.qcut(tail(mu, 2, size), 5))
    print(q.groupby("b", observed=True).agg(n=("yy", "size"), pred=("p", "mean"), act=("yy", "mean")).round(3).to_string())


if __name__ == "__main__" and sys.argv[1:2] == ["check"]:
    out = os.path.join(ROOT, "analysis", "output")
    ld = lambda s, f: pd.read_csv(os.path.join(out, s, f))
    pg25, tg25, pg26, tg26 = ld("20252026", "player_games.csv"), ld("20252026", "team_games.csv"), \
        ld("20262027", "player_games.csv"), ld("20262027", "team_games.csv")
    bt25 = ld("20252026", "bt_players.csv")
    d25 = _walk(bt25, pg25, None, tg25)
    best = min(((k, ko, sc, sz) for k in (150, 300, 500, 800) for ko in (2, 3, 5, 10, 20)
                for sc in (0.96, 0.98, 1.0, 1.02, 1.04) for sz in (8, 10, 12, 16, 25)),
               key=lambda p: _score(d25, *p))
    print("best on 2025-26 (K, KO, SCALE, SIZE):", best)
    _report(d25, "2025-26 fit", *best)
    if len(sys.argv) > 2:
        bt26 = pd.read_csv(sys.argv[2])
        d26 = _walk(bt26, pg26, pg25, tg26)
        _report(d26, "2026-27 check (with 2025-26 priors)", *best)
