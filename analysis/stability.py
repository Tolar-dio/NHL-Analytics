"""How much of each stat is skill and how much is noise (Nov 18, 2026).

For every stat we estimate K, the amount of evidence (minutes, shots or shots faced) at which a player's own
number and the average deserve equal weight. A player's best estimate is then

    (his total + K x average rate) / (his exposure + K)

which is the empirical-Bayes posterior mean, and his reliability after n units is n / (n + K). Two independent
ways to get K, both on 2025-26 season totals:

  1. Marginal likelihood. Counts per minute: gamma-Poisson (the season total is negative binomial given his
     minutes); K is the gamma prior's rate, in minutes. Rates per attempt (shooting %, save %): beta-binomial;
     K = a + b, in shots. Fitted by maximum likelihood over every player above a small minimum.
  2. Split-half reliability. Odd and even games, correlation r between halves, then K = n (1 - r) / r, where n
     is the typical exposure in one half (Spearman-Brown in K form).

When the two agree, the stat's signal is well measured. Output: data/derived/stability.json (stat, position, K,
games until half signal, reliability after 20/41/82 games). The site shows it as "signal and noise".
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import betaln, gammaln

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else "20252026"


def nb_K(x, t):
    """Gamma-Poisson marginal likelihood: x_i ~ NB with mean m t_i, shape a; returns (K minutes, m per minute)."""
    x, t = np.asarray(x, float), np.asarray(t, float)
    def nll(p):
        a, m = np.exp(p)
        b = a / m
        return -np.sum(gammaln(x + a) - gammaln(a) - gammaln(x + 1) + a * np.log(b / (b + t)) + x * np.log(t / (b + t)))
    m0 = x.sum() / t.sum()
    r = minimize(nll, [np.log(5.0), np.log(m0)], method="Nelder-Mead", options=dict(maxiter=4000, xatol=1e-6, fatol=1e-8))
    a, m = np.exp(r.x)
    return a / m, m


def bb_K(s, n):
    """Beta-binomial marginal likelihood: s_i successes of n_i; returns (K attempts, mean)."""
    s, n = np.asarray(s, float), np.asarray(n, float)
    def nll(p):
        mu, k = 1 / (1 + np.exp(-p[0])), np.exp(p[1])
        a, b = mu * k, (1 - mu) * k
        return -np.sum(betaln(s + a, n - s + b) - betaln(a, b))
    mu0 = s.sum() / n.sum()
    r = minimize(nll, [np.log(mu0 / (1 - mu0)), np.log(500.0)], method="Nelder-Mead", options=dict(maxiter=4000))
    return float(np.exp(r.x[1])), float(1 / (1 + np.exp(-r.x[0])))


def split_K(df, num, den, min_den):
    """Odd/even game split: K = n (1 - r) / r with n the median half exposure."""
    d = df.assign(half=df.game_id % 2)
    h = d.groupby(["player_id", "half"])[[num, den]].sum().unstack()
    h = h[(h[(den, 0)] >= min_den) & (h[(den, 1)] >= min_den)]
    if len(h) < 30:
        return None, None
    r0, r1 = h[(num, 0)] / h[(den, 0)], h[(num, 1)] / h[(den, 1)]
    r = np.corrcoef(r0, r1)[0, 1]
    n = float(np.median(np.r_[h[(den, 0)], h[(den, 1)]]))
    return (n * (1 - r) / r if r > 0.02 else float("inf")), r


def main():
    out = os.path.join(ROOT, "analysis", "output", SEASON)
    pg = pd.read_csv(os.path.join(out, "player_games.csv"))
    pg = pg[pg.game_id.astype(str).str[4:6] == "02"].copy()
    gg = pd.read_csv(os.path.join(out, "goalie_games.csv"))
    gg = gg[(gg.game_id.astype(str).str[4:6] == "02") & gg.sa.notna()].copy()
    pg["shots"] = pg.box_sog if "box_sog" in pg else pg.sog
    rows = []
    toi_pg = pg.groupby("pos").toi.mean().to_dict()
    COUNTS = [("goals", "g", "Goals"), ("points", "pts", "Points"), ("shots", "shots", "Shots on goal"),
              ("ixg", "ixg", "Expected goals from his own shots"), ("blocks", "blk", "Blocked shots"),
              ("onice_xgf", "xgf", "Expected goals for, on the ice"), ("onice_xga", "xga", "Expected goals against, on the ice")]
    CONT = ("ixg", "onice_xgf", "onice_xga")   # continuous: the count likelihood doesn't apply, split-half K is used
    for key, col, label in COUNTS:
        if col not in pg:
            continue
        for pos in ("F", "D"):
            q = pg[pg.pos == pos]
            tot = q.groupby("player_id")[[col, "toi"]].sum()
            tot = tot[tot.toi >= 100]
            K_sp, r = split_K(q, col, "toi", 150)
            if key in CONT:
                K_ml, m = K_sp, tot[col].sum() / tot.toi.sum()
            else:
                K_ml, m = nb_K(tot[col].values, tot.toi.values)
            rows.append(dict(stat=key, label=label, pos=pos, unit="minutes", K=round(K_ml), K_split=None if K_sp is None else round(K_sp),
                             r_half=None if r is None else round(r, 3), mean_per60=round(m * 60, 3), per_game=round(toi_pg[pos], 1)))
    # shooting percentage: goals per shot on goal
    for pos in ("F", "D"):
        q = pg[pg.pos == pos]
        tot = q.groupby("player_id")[["g", "shots"]].sum()
        tot = tot[tot.shots >= 20]
        K_ml, mu = bb_K(tot.g, tot.shots)
        K_sp, r = split_K(q, "g", "shots", 30)
        rows.append(dict(stat="sh_pct", label="Shooting percentage", pos=pos, unit="shots", K=round(K_ml), K_split=None if K_sp is None else round(K_sp),
                         r_half=None if r is None else round(r, 3), mean=round(mu, 4), per_game=round(q.groupby("game_id").shots.sum().sum() / len(q), 2)))
    # goalies: save percentage, and goals saved relative to expected (GA per xGA as a rate on shots)
    tot = gg.groupby("player_id")[["saves", "sa"]].sum()
    tot = tot[tot.sa >= 200]
    K_ml, mu = bb_K(tot.saves, tot.sa)
    K_sp, r = split_K(gg, "saves", "sa", 300)
    rows.append(dict(stat="sv_pct", label="Save percentage", pos="G", unit="shots faced", K=round(K_ml), K_split=None if K_sp is None else round(K_sp),
                     r_half=None if r is None else round(r, 3), mean=round(mu, 4), per_game=round(gg[gg.starter].sa.mean(), 1)))
    for r_ in rows:
        n = r_["per_game"]
        k = r_["K"]
        r_["games_half_signal"] = round(k / n, 1) if n else None
        r_["rel_20"], r_["rel_41"], r_["rel_82"] = (round(g * n / (g * n + k), 2) for g in (20, 41, 82))
    os.makedirs(os.path.join(ROOT, "data", "derived"), exist_ok=True)
    path = os.path.join(ROOT, "data", "derived", "stability.json")
    json.dump(dict(season=SEASON, rows=rows), open(path, "w"), indent=1)
    for r_ in rows:
        print(f"{r_['label'][:34]:34s} {r_['pos']}  K {r_['K']:>6} {r_['unit']:11s} (split-half {r_['K_split']}, r {r_['r_half']})  "
              f"half signal after {r_['games_half_signal']} games; reliability 20/41/82 games {r_['rel_20']}/{r_['rel_41']}/{r_['rel_82']}")


if __name__ == "__main__":
    main()
