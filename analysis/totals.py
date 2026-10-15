"""Game total (over/under) model.

Each team's expected regulation goals:
    lam_A = offA * defB / league * goalieB_factor * calib
  offA   = A's xGF/60 (all situations, MoneyPuck xG) shrunk toward league, K minutes
  defB   = B's xGA/60 shrunk toward league
  goalie = B's starter GA/xGA shrunk (Kg xG of prior)
  calib  = league goals / league xG (to date)

Distribution: regulation goals ~ independent Poisson(lam_A), Poisson(lam_B).
A tie after regulation adds exactly one goal to the graded total (OT winner or
shootout winner counted as one goal, which is how sportsbooks grade NHL totals).

Usage:
  python analysis/totals.py backtest
  python analysis/totals.py tonight      (reads analysis/slate.csv)
"""
import os, sys
import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "output")
TG = pd.read_csv(os.path.join(OUT, "team_games.csv"))
GG = pd.read_csv(os.path.join(OUT, "goalie_games.csv"))
GAMES = pd.read_csv(os.path.join(ROOT, "data", "tables", "20262027", "games.csv.gz"))
NAMES = pd.read_csv(os.path.join(ROOT, "data", "tables", "20262027", "players.csv.gz")) \
          .drop_duplicates("player_id").set_index("player_id").player
DEFAULT = dict(Kt=600, Kg=60)
MAXG = 15


def fit(cut, K=DEFAULT):
    tg = TG[TG.date < cut]
    gg = GG[GG.date < cut]
    t = tg.groupby("team").agg(xgf=("xgf", "sum"), xga=("xga", "sum"), gf=("gf", "sum"), toi=("toi", "sum"))
    lg60 = t.xgf.sum() / t.toi.sum() * 60
    t["off60"] = (t.xgf + K["Kt"] * lg60 / 60) / (t.toi + K["Kt"]) * 60
    t["def60"] = (t.xga + K["Kt"] * lg60 / 60) / (t.toi + K["Kt"]) * 60
    calib = t.gf.sum() / t.xgf.sum()
    g = gg.groupby("player_id").agg(team=("team", "last"), xga=("xga", "sum"), ga=("ga", "sum"),
                                   starts=("starter", "sum"))
    g["ratio"] = (g.ga + K["Kg"]) / (g.xga + K["Kg"])
    team_g = g.assign(w=g.starts.clip(lower=0.5)).groupby("team").apply(
        lambda x: np.average(x.ratio, weights=x.w), include_groups=False)
    return t, lg60, calib, g, team_g


def lam(t, lg60, calib, g, team_g, off, dfn, goalie):
    o = t.off60.get(off, lg60)
    d = t.def60.get(dfn, lg60)
    gf = g.ratio.get(goalie, np.nan) if goalie is not None else np.nan
    if np.isnan(gf):
        gf = 1.0 if goalie == -1 else team_g.get(dfn, 1.0)
    return o * d / lg60 * gf * calib


def total_dist(la, lb):
    """P(graded total = k) for k = 0..2*MAXG+1."""
    pa, pb = poisson.pmf(np.arange(MAXG + 1), la), poisson.pmf(np.arange(MAXG + 1), lb)
    joint = np.outer(pa, pb)
    out = np.zeros(2 * MAXG + 2)
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            out[i + j + (i == j)] += joint[i, j]
    return out


def summarize(la, lb):
    d = total_dist(la, lb)
    k = np.arange(len(d))
    p_tie = sum(poisson.pmf(i, la) * poisson.pmf(i, lb) for i in range(MAXG + 1))
    return dict(exp_total=(d * k).sum(), p_ot=p_tie,
                over55=d[k >= 6].sum(), over65=d[k >= 7].sum(), dist=d)


def backtest(dates, K=DEFAULT, verbose=True):
    rows = []
    for cut in dates:
        t, lg60, calib, g, team_g = fit(cut, K)
        base = lg60 * calib  # league-average team
        st = GG[(GG.date == cut) & GG.starter].set_index(["game_id", "team"]).player_id
        for _, gm in GAMES[GAMES.date == cut].iterrows():
            la = lam(t, lg60, calib, g, team_g, gm.home, gm.away, st.get((gm.game_id, gm.away)))
            lb = lam(t, lg60, calib, g, team_g, gm.away, gm.home, st.get((gm.game_id, gm.home)))
            m, b = summarize(la, lb), summarize(base, base)
            y = int(gm.home_score + gm.away_score)
            rows.append(dict(date=cut, game=f"{gm.away}@{gm.home}", pred=m["exp_total"], base=b["exp_total"],
                             actual=y, ll_model=np.log(m["dist"][y]), ll_base=np.log(b["dist"][y]),
                             p_over55=m["over55"], over55=int(y >= 6)))
    r = pd.DataFrame(rows)
    if verbose:
        rm = lambda c: np.sqrt(((r[c] - r.actual) ** 2).mean())
        print(f"backtest {len(r)} games: actual mean total {r.actual.mean():.2f}, sd {r.actual.std():.2f}")
        print(f"  RMSE model {rm('pred'):.3f} vs league-average baseline {rm('base'):.3f}")
        print(f"  log-likelihood per game: model {r.ll_model.mean():.4f}  baseline {r.ll_base.mean():.4f}")
        print(f"  corr(pred, actual) {np.corrcoef(r.pred, r.actual)[0, 1]:.3f}")
        print(f"  over 5.5: predicted {r.p_over55.mean():.3f}, actual rate {r.over55.mean():.3f}")
    return r


def american(p):
    return f"+{100 * (1 - p) / p:.0f}" if p < 0.5 else f"{-100 * p / (1 - p):.0f}"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    dates = sorted(TG.date.unique())
    if mode == "backtest":
        backtest([d for d in dates if d >= "2026-10-06"])
    else:
        slate = pd.read_csv(os.path.join(ROOT, "analysis", "slate.csv"))
        cut = slate.date.iloc[0]
        t, lg60, calib, g, team_g = fit(cut)
        gid = {n.lower(): pid for pid, n in NAMES.items()}
        rows = []
        for _, s in slate.iterrows():
            ag, hg = gid.get(s.away_goalie.lower(), -1), gid.get(s.home_goalie.lower(), -1)
            la = lam(t, lg60, calib, g, team_g, s.away, s.home, hg)   # away scores on home goalie
            lh = lam(t, lg60, calib, g, team_g, s.home, s.away, ag)
            m = summarize(la, lh)
            rows.append(dict(game=f"{s.away} @ {s.home}", goalies=f"{s.away_goalie} / {s.home_goalie}",
                             away_xg=round(la, 2), home_xg=round(lh, 2), exp_total=round(m["exp_total"], 2),
                             p_ot=round(m["p_ot"], 3), p_over55=round(m["over55"], 3),
                             fair_over55=american(m["over55"]), fair_under55=american(1 - m["over55"]),
                             p_over65=round(m["over65"], 3), fair_over65=american(m["over65"]),
                             fair_under65=american(1 - m["over65"])))
        r = pd.DataFrame(rows).sort_values("exp_total", ascending=False)
        r.to_csv(os.path.join(OUT, f"totals_{cut}.csv"), index=False)
        pd.set_option("display.width", 250)
        print(f"league xG/60 per team {lg60:.2f}, goals/xG calibration {calib:.3f}")
        print(r.to_string(index=False))
