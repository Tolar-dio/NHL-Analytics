"""Shots-on-goal prices for tonight's props.

Rate per 60 = this season's shots on goal blended with last season's rate (worth K minutes; players with no usable
last season get their position's rate), times projected ice time, times how many shots tonight's opponent allows
per game relative to league (this season, shrunk with 10 league-average games). Counts follow a negative binomial
with shape SIZE (shots are a little burstier than Poisson).

Fit Oct 2026: K, SCALE and SIZE chosen on 2025-26 (46k player-games, walk-forward, NST 2024-25 rates as the prior),
then checked on 2026-27 with our 2025-26 rates as the prior (3.5k): mean 1.54 predicted vs 1.52 actual, 2+ shots
41.8% vs 42.1%, 3+ 21.4% vs 21.2%, 4+ 10.2% vs 9.6%.
"""
import numpy as np
import pandas as pd
from scipy.stats import nbinom

K, SCALE, SIZE = 600, 0.98, 12


def _regular(pg):
    return pg[pg.game_id.astype(str).str[4:6] == "02"]


def prices(rows, cur_pg, prev_pg, cut):
    """rows: DataFrame with player_id, opp, pos, proj_toi. Returns rows with exp_sog and p_sog2/3/4."""
    cur = _regular(cur_pg)
    cur = cur[cur.date < cut]
    prev = _regular(prev_pg)
    a = cur.groupby("player_id").agg(sog=("sog", "sum"), toi=("toi", "sum"))
    pv = prev.groupby("player_id").agg(sog=("sog", "sum"), toi=("toi", "sum"))
    pv = pv[pv.toi >= 200]
    prior = (pv.sog / pv.toi * 60).to_dict()
    posr = (prev.groupby("pos").sog.sum() / prev.groupby("pos").toi.sum() * 60).to_dict()
    per_game = cur.groupby(["game_id", "opp"]).sog.sum().reset_index()
    lgpg = per_game.sog.mean() if len(per_game) else _regular(prev_pg).groupby(["game_id", "opp"]).sog.sum().mean()
    o = per_game.groupby("opp").sog.agg(["sum", "count"])
    d = rows.copy()
    rp = d.player_id.map(prior).fillna(d.pos.map(posr)).fillna(np.nanmean(list(posr.values())))
    sc = d.player_id.map(a.sog).fillna(0)
    tc = d.player_id.map(a.toi).fillna(0)
    r60 = (sc + rp * K / 60) / (tc + K) * 60
    of = ((d.opp.map(o["sum"]).fillna(0) + lgpg * 10) / (d.opp.map(o["count"]).fillna(0) + 10)) / lgpg
    mu = r60 * d.proj_toi / 60 * of * SCALE
    q = SIZE / (SIZE + mu)
    d["exp_sog"] = mu.round(2)
    for k in (2, 3, 4):
        d[f"p_sog{k}"] = 1 - nbinom.cdf(k - 1, SIZE, q)
    return d
