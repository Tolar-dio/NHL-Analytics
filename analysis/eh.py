"""Evolving-Hockey season tables (paid, private) as priors for the prop model.

The tables live only in the private repo (Tolar-dio/nhl-private, eh/tables/, built from Tolar's CSV exports by its
scripts/eh_tables.py) and are checked out to private/eh/tables by the nightly job. Evolving-Hockey's terms: data for
personal use; models built on it may be shown publicly with a link back to evolving-hockey.com. So nothing from these
tables is published as-is; only what our own model does with them, credited.

  python analysis/eh.py props            # does last season's EH profile improve goal/point prices?
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EH_DIR = os.environ.get("EH_DIR", os.path.join(ROOT, "private", "eh", "tables"))
CREDIT = "Player impact and value models (RAPM, GAR): Evolving-Hockey (evolving-hockey.com)."
MIN_TOI, SHRINK = 200, 600     # minutes: who sets the league mean and spread; how fast a player's z earns full weight


def available():
    return os.path.exists(os.path.join(EH_DIR, "skaters.csv.gz"))


def load(kind="skaters"):
    return pd.read_csv(os.path.join(EH_DIR, f"{kind}.csv.gz"))


def profile(season):
    """One season's EH skater profile as per-60 rates, z-scored within forwards and within defensemen and shrunk
    toward 0 by ice time. Features:
      rapm_off   RAPM xGF/60 at even strength (his isolated effect on his team's chances)
      rapm_def   minus RAPM xGA/60 (higher = suppresses more)
      evo60      even-strength offence GAR per 60 (all situations TOI)
      ppo60      power-play offence GAR per 60
      finish     shooting goals above average per 100 unblocked shots (EH's finishing talent)
      qot        quality of teammates (their RAPM xG+/-60): context, not talent"""
    sk = load()
    d = sk[sk.season == int(season)].copy()
    d["pg"] = np.where(d.pos.astype(str).str.upper().str.startswith("D"), "D", "F")
    toi = d.toi_all.fillna(d.all_toi).fillna(d.toi_ev)
    d["toi"] = toi
    d["rapm_off"] = d.rapm_xgf60
    d["rapm_def"] = -d.rapm_xga60
    d["evo60"] = d.evo_gar / toi * 60
    d["ppo60"] = d.ppo_gar / toi * 60
    d["finish"] = 100 * d.shot_all_sh_goals / (d.shot_ev_iff + d.shot_pp_iff).replace(0, np.nan)
    d["qot"] = d.qot_rapm_xg_pm60
    feats = ["rapm_off", "rapm_def", "evo60", "ppo60", "finish", "qot"]
    for f in feats:
        z = pd.Series(0.0, index=d.index)
        for pg, grp in d.groupby("pg"):
            ref = grp[grp.toi >= MIN_TOI][f].dropna()
            if len(ref) > 20 and ref.std() > 0:
                z.loc[grp.index] = ((grp[f] - ref.mean()) / ref.std()).fillna(0.0)
        d[f + "_z"] = (z * d.toi / (d.toi + SHRINK)).clip(-3, 3)
    return d[["player_id", "pg", "toi"] + [f + "_z" for f in feats]]


def goalie_profile(seasons):
    """Goals saved above expected per 60 over the given seasons (EH's own xG), z-scored and shrunk hard toward 0:
    goalie seasons barely repeat. One row per goalie."""
    g = load("goalies")
    g = g[g.season.isin([int(s) for s in seasons])]
    a = g.groupby("player_id").agg(toi=("toi", "sum"), gsax=("gsax", "sum")).reset_index()
    a["gsax60"] = a.gsax / a.toi * 60
    ref = a[a.toi >= 1500].gsax60
    a["opp_gsax_z"] = ((a.gsax60 - ref.mean()) / ref.std() * a.toi / (a.toi + 3000)).clip(-3, 3)
    return a[["player_id", "opp_gsax_z"]].rename(columns={"player_id": "opp_goalie"})


def _lg(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def props_test(bt, prev, fold="month", label="", start=2, extra=None):
    """Walk-forward check: recalibrate the model's own probability (logit) on every earlier fold, with and without
    last season's EH profile, and score the next fold. `extra` adds features that are already in use (A3Z) so the
    gain over them can be read too."""
    from sklearn.linear_model import LogisticRegression
    pr = profile(prev)
    d = bt.merge(pr, on="player_id", how="left")
    if "opp_goalie" in d.columns:
        d = d.merge(goalie_profile([prev, str(int(prev[:4]) - 1) + prev[:4]]), on="opp_goalie", how="left")
    zc = [c for c in d.columns if c.endswith("_z")]
    d[zc] = d[zc].fillna(0.0)
    d["y_1"] = (d.y_pts >= 1).astype(int)
    d["fold"] = pd.to_datetime(d.date).dt.strftime("%Y-%m") if fold == "month" else d.date.astype(str)
    print(f"{label}: {len(d)} player-games, {d.toi.notna().mean():.0%} with an EH profile from {prev}")
    out = {}
    gz = ["opp_gsax_z"] if "opp_gsax_z" in d.columns else []
    for target, pcol, ycol, feats in (("goal", "p_goal", "y_goal", ["finish_z", "rapm_off_z", "evo60_z", "ppo60_z"] + gz),
                                      ("1+ points", "p_1pt", "y_1", ["rapm_off_z", "evo60_z", "ppo60_z", "qot_z"]),
                                      ("2+ points", "p_2pts", "y_2", ["rapm_off_z", "evo60_z", "ppo60_z", "qot_z"])):
        y = d[ycol].values.astype(int)
        X0 = pd.DataFrame(dict(lp=_lg(d[pcol].values)))
        sets = {"recal": X0, "eh": X0.join(d[feats].reset_index(drop=True))}
        if extra is not None:
            sets["extra"] = X0.join(d[extra].reset_index(drop=True))
            sets["extra+eh"] = sets["extra"].join(d[feats].reset_index(drop=True))
        folds = sorted(d.fold.unique())
        ll = {k: [] for k in ["model"] + list(sets)}
        n = 0
        for f in folds[start:]:
            tr, te = (d.fold < f).values, (d.fold == f).values
            if te.sum() == 0 or tr.sum() < 500:
                continue
            for name, X in sets.items():
                m = LogisticRegression(C=1.0, max_iter=2000).fit(X[tr], y[tr])
                p = m.predict_proba(X[te])[:, 1]
                ll[name].append(-np.sum(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)))
            p = np.clip(d[pcol].values[te], 1e-4, 1 - 1e-4)
            ll["model"].append(-np.sum(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)))
            n += te.sum()
        res = {k: round(sum(v) / n, 5) for k, v in ll.items() if v}
        full = LogisticRegression(C=1.0, max_iter=2000).fit(sets["eh"], y)
        res["coef"] = {c: round(float(b), 3) for c, b in zip(sets["eh"].columns, full.coef_[0])}
        res["n"] = int(n)
        out[target] = res
        gain = res["recal"] - res["eh"]
        more = f"  A3Z {res['extra']:.5f} -> +EH {res['extra+eh']:.5f} ({res['extra'] - res['extra+eh']:+.5f})" if "extra" in res else ""
        print(f"  {target:10s} n={n}: model {res['model']:.5f} recal {res['recal']:.5f} +EH {res['eh']:.5f} gain {gain:+.5f}{more}"
              f"\n             {res['coef']}")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "props"
    if mode == "props":
        bt = pd.read_csv(os.path.join(ROOT, "analysis", "output", "20252026", "bt_players.csv"))
        props_test(bt, "20242025", label="2025-26 backtest (no in-model priors)")
        late = bt[bt.date >= "2026-01-01"]
        props_test(late, "20242025", label="2025-26 from January (current season dominates)", start=1)
        if len(sys.argv) > 2:      # a 2026-27 backtest priced WITH 2025-26 priors (the live setup), e.g. from prior-backtest
            props_test(pd.read_csv(sys.argv[2]), "20252026", fold="date", start=3, label="2026-27 with priors")
