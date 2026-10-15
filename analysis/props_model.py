"""Anytime-goal and 2+ point model.

For each skater in a game:
  goal_lambda = shrunk ixG/60 * projected TOI * finishing * opp defense * opp goalie
  pts_lambda  = shrunk on-ice xGF/60 * projected TOI * opp defense * opp goalie * shrunk IPP
  P(goal)  = 1 - exp(-goal_lambda)
  P(2+pts) = 1 - exp(-L)(1 + L)          (Poisson thinning of on-ice goals)

Shrinkage: each rate is pulled toward a prior predicted from the player's TOI
per game and power-play role (fit across the league at each cutoff), with
strength set by K (minutes). Small samples => mostly prior.

Usage:
  python analysis/props_model.py backtest
  python analysis/props_model.py tonight
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "output")
PG = pd.read_csv(os.path.join(OUT, "player_games.csv"))
TG = pd.read_csv(os.path.join(OUT, "team_games.csv"))
GG = pd.read_csv(os.path.join(OUT, "goalie_games.csv"))
NAMES = pd.read_csv(os.path.join(ROOT, "data", "tables", "20262027", "players.csv.gz")) \
          .drop_duplicates("player_id").set_index("player_id").player

DEFAULT = dict(Kx=300, Ko=600, Ki=20, Kf=30, Kt=600, Kg=60)


def wls_prior(df, y, cols, w):
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols])
    W = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * W[:, None], y * W, rcond=None)
    return beta


def fit(cut, K=DEFAULT):
    """Aggregate everything before date `cut` and return per-player, team, goalie params."""
    pg = PG[PG.date < cut]
    tg = TG[TG.date < cut]
    gg = GG[GG.date < cut]

    p = pg.groupby("player_id").agg(team=("team", "last"), pos=("pos", "last"), gp=("game_id", "nunique"),
                                   toi=("toi", "sum"), ixg=("ixg", "sum"), g=("g", "sum"), pts=("pts", "sum"),
                                   xgf=("xgf", "sum"), gf=("gf", "sum"), pp_xgf=("pp_xgf", "sum"),
                                   team_pp=("team_pp_xgf", "sum"))
    last3 = pg.sort_values("date").groupby("player_id").tail(3).groupby("player_id").toi.mean()
    p["toi_pg"] = p.toi / p.gp
    p["proj_toi"] = 0.6 * last3.reindex(p.index) + 0.4 * p.toi_pg
    p["pp_share"] = (p.pp_xgf / p.team_pp.replace(0, np.nan)).fillna(0).clip(0, 1)

    for pos in ("F", "D"):
        m = p.pos == pos
        q = p[m & (p.toi >= 40)]
        # prior for individual xG rate
        bx = wls_prior(q, (q.ixg / q.toi * 60).values, ["toi_pg", "pp_share"], q.toi.values)
        prior_x = (bx[0] + bx[1] * p.loc[m, "toi_pg"] + bx[2] * p.loc[m, "pp_share"]).clip(lower=0.03)
        p.loc[m, "ixg60"] = (p.loc[m, "ixg"] + K["Kx"] * prior_x / 60) / (p.loc[m, "toi"] + K["Kx"]) * 60
        # prior for on-ice xGF rate
        bo = wls_prior(q, (q.xgf / q.toi * 60).values, ["toi_pg", "pp_share"], q.toi.values)
        prior_o = (bo[0] + bo[1] * p.loc[m, "toi_pg"] + bo[2] * p.loc[m, "pp_share"]).clip(lower=0.5)
        p.loc[m, "oxgf60"] = (p.loc[m, "xgf"] + K["Ko"] * prior_o / 60) / (p.loc[m, "toi"] + K["Ko"]) * 60
        # IPP prior: league share of on-ice goals a player at this position gets a point on
        ipp0 = q.pts.sum() / q.gf.sum()
        p.loc[m, "ipp"] = (p.loc[m, "pts"] + K["Ki"] * ipp0) / (p.loc[m, "gf"] + K["Ki"])
    lg_fin = pg.g.sum() / pg.ixg.sum()
    p["fin"] = ((p.g + K["Kf"] * lg_fin) / (p.ixg + K["Kf"])).clip(0.8, 1.25)

    # team defense: shrunk xGA/60 relative to league
    t = tg.groupby("team").agg(xga=("xga", "sum"), toi=("toi", "sum"))
    lg_xga60 = t.xga.sum() / t.toi.sum() * 60
    t["def_factor"] = ((t.xga + K["Kt"] * lg_xga60 / 60) / (t.toi + K["Kt"]) * 60) / lg_xga60

    # goalies: shrunk GA/xGA ratio
    g = gg.groupby("player_id").agg(team=("team", "last"), xga=("xga", "sum"), ga=("ga", "sum"),
                                   starts=("starter", "sum"))
    g["ratio"] = (g.ga + K["Kg"]) / (g.xga + K["Kg"])
    return p, t, g


def predict(rows, p, t, g, K=DEFAULT):
    """rows: DataFrame with player_id, team, opp, opp_goalie (player_id or NaN)."""
    d = rows.join(p[["pos", "gp", "proj_toi", "ixg60", "oxgf60", "ipp", "fin", "pp_share", "g", "pts", "ixg"]],
                  on="player_id", how="inner")
    d["def_f"] = d.opp.map(t.def_factor).fillna(1.0)
    # unknown goalie: weight the opponent's goalies by their starts
    gw = g.assign(w=g.starts.clip(lower=0.5)).groupby("team").apply(
        lambda x: np.average(x.ratio, weights=x.w), include_groups=False)
    d["g_f"] = d.opp_goalie.map(g.ratio)
    d["g_f"] = d.g_f.fillna(d.opp.map(gw)).fillna(1.0)
    d["lam_g"] = d.ixg60 / 60 * d.proj_toi * d.fin * d.def_f * d.g_f
    d["lam_p"] = d.oxgf60 / 60 * d.proj_toi * d.def_f * d.g_f * d.ipp
    d["p_goal"] = 1 - np.exp(-d.lam_g)
    d["p_2pts"] = 1 - np.exp(-d.lam_p) * (1 + d.lam_p)
    d["p_1pt"] = 1 - np.exp(-d.lam_p)
    return d


def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def backtest(dates, K=DEFAULT, verbose=True):
    out = []
    for cut in dates:
        p, t, g = fit(cut, K)
        day = PG[PG.date == cut]
        starters = GG[(GG.date == cut) & GG.starter].set_index(["game_id", "team"]).player_id
        rows = day[["game_id", "player_id", "team", "opp", "g", "pts", "pos", "toi"]].rename(
            columns={"g": "y_g", "pts": "y_pts", "pos": "pos_true", "toi": "toi_true"})
        rows["opp_goalie"] = [starters.get((gid, o), np.nan) for gid, o in zip(rows.game_id, rows.opp)]
        rows = rows.set_index("player_id")
        d = predict(rows.reset_index().set_index("player_id"), p, t, g, K).reset_index()
        # naive baseline: league per-position rates x projected TOI
        pg = PG[PG.date < cut]
        for pos in ("F", "D"):
            q = pg[pg.pos == pos]
            m = d.pos == pos
            d.loc[m, "base_g"] = 1 - np.exp(-q.g.sum() / q.toi.sum() * d.loc[m, "proj_toi"])
            lp = q.pts.sum() / q.toi.sum() * d.loc[m, "proj_toi"]
            d.loc[m, "base_2"] = 1 - np.exp(-lp) * (1 + lp)
        out.append(d)
    r = pd.concat(out)
    r["y_goal"] = (r.y_g >= 1).astype(int)
    r["y_2pts"] = (r.y_pts >= 2).astype(int)
    if verbose:
        print(f"backtest: {len(r)} player-games over {len(dates)} dates")
        print(f"  goal:  model logloss {logloss(r.y_goal, r.p_goal):.4f}  baseline {logloss(r.y_goal, r.base_g):.4f}"
              f"   predicted {r.p_goal.sum():.0f} vs actual {r.y_goal.sum()} scorers")
        print(f"  2+pts: model logloss {logloss(r.y_2pts, r.p_2pts):.4f}  baseline {logloss(r.y_2pts, r.base_2):.4f}"
              f"   predicted {r.p_2pts.sum():.0f} vs actual {r.y_2pts.sum()}")
    return r


def calib(r, col, ycol, bins):
    r = r.copy()
    r["b"] = pd.cut(r[col], bins)
    return r.groupby("b", observed=True).agg(n=(ycol, "size"), pred=(col, "mean"), actual=(ycol, "mean")).round(3)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    dates = sorted(PG.date.unique())
    if mode == "backtest":
        test = [d for d in dates if d >= "2026-10-08"]
        r = backtest(test)
        print(calib(r, "p_goal", "y_goal", [0, .1, .15, .2, .25, .3, .4, 1]))
        print(calib(r, "p_2pts", "y_2pts", [0, .05, .1, .15, .2, .3, 1]))
    elif mode == "tonight":
        # slate file: analysis/slate.csv with columns date, away, home, away_goalie, home_goalie
        slate = pd.read_csv(os.path.join(ROOT, "analysis", "slate.csv"))
        cut = slate.date.iloc[0]
        p, t, g = fit(cut)
        gid = {n.lower(): pid for pid, n in NAMES.items()}
        rows = []
        for _, s in slate.iterrows():
            for team, opp, og in ((s.away, s.home, s.home_goalie), (s.home, s.away, s.away_goalie)):
                last_game = PG[(PG.team == team) & (PG.date < cut)].game_id.max()
                for pid in PG[(PG.game_id == last_game) & (PG.team == team)].player_id:
                    rows.append({"player_id": pid, "team": team, "opp": opp, "home": team == s.home,
                                 "opp_goalie": gid.get(str(og).lower(), -1)})
        rows = pd.DataFrame(rows).set_index("player_id")
        d = predict(rows, p, t, g)
        # a named goalie with no NHL games this season gets league-average (1.0)
        d.loc[d.opp_goalie == -1, "g_f"] = 1.0
        d["lam_g"] = d.ixg60 / 60 * d.proj_toi * d.fin * d.def_f * d.g_f
        d["lam_p"] = d.oxgf60 / 60 * d.proj_toi * d.def_f * d.g_f * d.ipp
        d["p_goal"] = 1 - np.exp(-d.lam_g)
        d["p_2pts"] = 1 - np.exp(-d.lam_p) * (1 + d.lam_p)
        d["player"] = d.index.map(NAMES)
        d.reset_index().to_csv(os.path.join(OUT, f"props_{cut}.csv"), index=False)
        print("wrote", f"props_{cut}.csv", len(d), "players")
