"""Prop (anytime goal, 2+ points) and game-total models, any season, optional
last-season priors.

Inputs: analysis/output/<season>/{player,team,goalie}_games.csv from props_data.py.

Player rates are shrunk toward a prior. Without last season the prior is a
league regression on ice time and power-play role. With last season, the prior
blends the player's own (shrunk) last-season rate with that regression, so it
follows the PLAYER across trades, while current TOI/PP role still counts.

Team totals: team offense/defense priors are built from tonight's roster
(TOI-weighted last-season on-ice rates), so roster changes carry through.

CLI:
  python analysis/models.py season-backtest 20252026     # walk-forward, no priors
  python analysis/models.py prior-backtest               # 2026-27 with vs without 2025-26 priors
  python analysis/models.py tonight                      # reads analysis/slate.csv
"""
import os, sys
import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTROOT = os.path.join(ROOT, "analysis", "output")
CUR, PREV = "20262027", "20252026"

K = dict(Kx=300, Ko=600, Ki=20, Kf=30, Kt=600, Kg=60,       # current-season shrinkage
         alpha=0.7,                                       # weight on last season vs role prior
         Kt_prior=1200, beta=0.7, Kg0=100)                # team/goalie prior settings
MAXG = 15
PTS_CAL = 1.03


# ------------------------------------------------------------------ data

def load(season):
    d = os.path.join(OUTROOT, season)
    pg = pd.read_csv(os.path.join(d, "player_games.csv"))
    tg = pd.read_csv(os.path.join(d, "team_games.csv"))
    gg = pd.read_csv(os.path.join(d, "goalie_games.csv"))
    games = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "games.csv.gz"))
    names = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "players.csv.gz")) \
              .drop_duplicates("player_id").set_index("player_id").player
    return dict(pg=pg, tg=tg, gg=gg, games=games, names=names)


def wls(df, y, cols, w):
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols])
    W = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * W[:, None], y * W, rcond=None)
    return beta


def player_agg(pg):
    p = pg.groupby("player_id").agg(team=("team", "last"), pos=("pos", "last"), gp=("game_id", "nunique"),
                                   toi=("toi", "sum"), ixg=("ixg", "sum"), g=("g", "sum"), pts=("pts", "sum"),
                                   xgf=("xgf", "sum"), xga=("xga", "sum"), gf=("gf", "sum"),
                                   pp_xgf=("pp_xgf", "sum"), team_pp=("team_pp_xgf", "sum"))
    p["toi_pg"] = p.toi / p.gp
    p["pp_share"] = (p.pp_xgf / p.team_pp.replace(0, np.nan)).fillna(0).clip(0, 1)
    return p


def role_priors(p):
    """League regression of each rate on TOI/game and PP share, by position."""
    out = pd.DataFrame(index=p.index)
    for pos in ("F", "D"):
        m = p.pos == pos
        q = p[m & (p.toi >= 40)]
        for col, num, floor in (("x", "ixg", 0.03), ("o", "xgf", 0.5), ("a", "xga", 0.5)):
            b = wls(q, (q[num] / q.toi * 60).values, ["toi_pg", "pp_share"], q.toi.values)
            out.loc[m, col] = (b[0] + b[1] * p.loc[m, "toi_pg"] + b[2] * p.loc[m, "pp_share"]).clip(lower=floor)
        out.loc[m, "ipp"] = q.pts.sum() / q.gf.sum()
    return out


def build_prev_priors(prev):
    """Last-season per-player rates (shrunk) and goalie ratios."""
    pg = prev["pg"][prev["pg"].game_type == "regular"]
    p = player_agg(pg)
    r = role_priors(p)
    pr = pd.DataFrame(index=p.index)
    pr["x"] = (p.ixg + K["Kx"] * r.x / 60) / (p.toi + K["Kx"]) * 60
    pr["o"] = (p.xgf + K["Ko"] * r.o / 60) / (p.toi + K["Ko"]) * 60
    pr["a"] = (p.xga + K["Ko"] * r.a / 60) / (p.toi + K["Ko"]) * 60
    pr["ipp"] = (p.pts + K["Ki"] * r.ipp) / (p.gf + K["Ki"])
    pr["fin"] = ((p.g + K["Kf"]) / (p.ixg + K["Kf"])).clip(0.8, 1.25)
    pr["toi_pg"] = p.toi_pg
    pr["pos"], pr["pp_share"], pr["team"] = p.pos, p.pp_share, p.team
    gg = prev["gg"][prev["gg"].game_type == "regular"]
    g = gg.groupby("player_id").agg(xga=("xga", "sum"), ga=("ga", "sum"))
    gpr = (g.ga + K["Kg0"]) / (g.xga + K["Kg0"])
    tg = prev["tg"][prev["tg"].game_type == "regular"]
    lg60 = tg.xgf.sum() / tg.toi.sum() * 60
    return dict(players=pr, goalies=gpr, lg60=lg60)


# ------------------------------------------------------------------ props

def fit_players(cur, cut, priors=None, k=K, extra=None):
    """extra: {player_id: team} for players expected back who have no games yet this season (back from
    injury, say). With priors they get a row of zeros, so every rate below falls back to last season's."""
    pg = cur["pg"][(cur["pg"].date < cut) & (cur["pg"].game_type == "regular")]
    p = player_agg(pg)
    if extra and priors is not None:
        pp = priors["players"]
        add = [i for i in extra if i not in p.index and i in pp.index]
        if add:
            z = pd.DataFrame({c: 0.0 for c in p.columns}, index=pd.Index(add, name=p.index.name))
            z["team"] = [extra[i] for i in add]
            z["pos"] = pp.pos.reindex(add).values
            z["gp"] = 0
            z["toi_pg"] = pp.toi_pg.reindex(add).values
            z["pp_share"] = pp.pp_share.reindex(add).fillna(0).values
            p = pd.concat([p, z])
    last3 = pg.sort_values("date").groupby("player_id").tail(3).groupby("player_id").toi.mean()
    p["proj_toi"] = (0.6 * last3.reindex(p.index) + 0.4 * p.toi_pg).fillna(p.toi_pg)
    r = role_priors(p)
    prior = r.copy()
    lg_fin = pg.g.sum() / max(pg.ixg.sum(), 1e-9)
    prior["fin"] = lg_fin
    if priors is not None:
        pp = priors["players"].reindex(p.index)
        has = pp.x.notna()
        for c in ("x", "o", "a", "ipp"):
            prior.loc[has, c] = k["alpha"] * pp.loc[has, c] + (1 - k["alpha"]) * r.loc[has, c]
        prior.loc[has, "fin"] = pp.loc[has, "fin"]
    p["ixg60"] = (p.ixg + k["Kx"] * prior.x / 60) / (p.toi + k["Kx"]) * 60
    p["oxgf60"] = (p.xgf + k["Ko"] * prior.o / 60) / (p.toi + k["Ko"]) * 60
    p["oxga60"] = (p.xga + k["Ko"] * prior.a / 60) / (p.toi + k["Ko"]) * 60
    p["ipp"] = (p.pts + k["Ki"] * prior.ipp) / (p.gf + k["Ki"])
    p["fin"] = ((p.g + k["Kf"] * prior.fin) / (p.ixg + k["Kf"])).clip(0.8, 1.25)
    return p


def fit_teams(cur, cut, players, priors=None, k=K, rosters=None):
    """Team xGF/xGA per 60 (shrunk) and goalie GA/xGA ratios.

    rosters: {team: [player_id,...]} for the game being priced (needed for priors).
    """
    tg = cur["tg"][(cur["tg"].date < cut) & (cur["tg"].game_type == "regular")]
    gg = cur["gg"][(cur["gg"].date < cut) & (cur["gg"].game_type == "regular")]
    t = tg.groupby("team").agg(xgf=("xgf", "sum"), xga=("xga", "sum"), gf=("gf", "sum"), toi=("toi", "sum"))
    lg60 = t.xgf.sum() / t.toi.sum() * 60 if len(t) else (priors or {}).get("lg60", 3.1)
    calib = t.gf.sum() / t.xgf.sum() if len(t) else 1.0
    off_prior = pd.Series(lg60, index=t.index)
    def_prior = pd.Series(lg60, index=t.index)
    kt = k["Kt"]
    if priors is not None and rosters:
        kt = k["Kt_prior"]
        pp = priors["players"]
        for team, ids in rosters.items():
            ids = [i for i in ids]
            w = np.array([players.proj_toi.get(i, pp.toi_pg.get(i, 15.0)) for i in ids], dtype=float)
            w = np.nan_to_num(w, nan=15.0)
            o = np.array([pp.o.get(i, np.nan) for i in ids], dtype=float)
            a = np.array([pp.a.get(i, np.nan) for i in ids], dtype=float)
            o, a = np.nan_to_num(o, nan=priors["lg60"]), np.nan_to_num(a, nan=priors["lg60"])
            # scale last season's level to this season's scoring environment
            s = lg60 / priors["lg60"]
            off_prior[team] = s * (priors["lg60"] + k["beta"] * (np.average(o, weights=w) - priors["lg60"]))
            def_prior[team] = s * (priors["lg60"] + k["beta"] * (np.average(a, weights=w) - priors["lg60"]))
    t = t.reindex(t.index.union(off_prior.index)).fillna(0)
    t["off60"] = (t.xgf + kt * off_prior.reindex(t.index).fillna(lg60) / 60) / (t.toi + kt) * 60
    t["def60"] = (t.xga + kt * def_prior.reindex(t.index).fillna(lg60) / 60) / (t.toi + kt) * 60
    g = gg.groupby("player_id").agg(team=("team", "last"), xga=("xga", "sum"), ga=("ga", "sum"),
                                   starts=("starter", "sum"))
    gprior = pd.Series(1.0, index=g.index)
    if priors is not None:
        gprior = priors["goalies"].reindex(g.index).fillna(1.0)
    g["ratio"] = (g.ga + k["Kg"] * gprior) / (g.xga + k["Kg"])
    return dict(t=t, lg60=lg60, calib=calib, g=g, gprior=None if priors is None else priors["goalies"])


def goalie_factor(tm, team, goalie):
    if goalie is not None and goalie in tm["g"].index:
        return tm["g"].ratio[goalie]
    if goalie is not None and tm["gprior"] is not None and goalie in tm["gprior"].index:
        return tm["gprior"][goalie]           # no games this season, has last season
    if goalie == -1 or goalie is None:
        return 1.0
    sub = tm["g"][tm["g"].team == team]
    return np.average(sub.ratio, weights=sub.starts.clip(lower=0.5)) if len(sub) else 1.0


def price_players(rows, p, tm):
    """rows: DataFrame(player_id, team, opp, opp_goalie)."""
    d = rows.join(p[["pos", "gp", "proj_toi", "ixg60", "oxgf60", "ipp", "fin", "pp_share", "g", "pts", "ixg"]],
                  on="player_id", how="inner")
    lg = tm["lg60"]
    d["def_f"] = d.opp.map(tm["t"].def60).fillna(lg) / lg
    d["g_f"] = [goalie_factor(tm, o, g) for o, g in zip(d.opp, d.opp_goalie)]
    d["lam_g"] = d.ixg60 / 60 * d.proj_toi * d.fin * d.def_f * d.g_f
    # PTS_CAL: Poisson slightly under-predicts 2+ point games (game-level
    # correlation); 1.03 was the best fit across the full 2025-26 backtest
    d["lam_p"] = d.oxgf60 / 60 * d.proj_toi * d.def_f * d.g_f * d.ipp * PTS_CAL
    d["p_goal"] = 1 - np.exp(-d.lam_g)
    d["p_2pts"] = 1 - np.exp(-d.lam_p) * (1 + d.lam_p)
    return d


# ------------------------------------------------------------------ totals

def team_lambda(tm, off, dfn, goalie):
    t, lg = tm["t"], tm["lg60"]
    o = t.off60.get(off, lg)
    d = t.def60.get(dfn, lg)
    return o * d / lg * goalie_factor(tm, dfn, goalie) * tm["calib"]


def total_dist(la, lb):
    pa, pb = poisson.pmf(np.arange(MAXG + 1), la), poisson.pmf(np.arange(MAXG + 1), lb)
    joint = np.outer(pa, pb)
    out = np.zeros(2 * MAXG + 2)
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            out[i + j + (i == j)] += joint[i, j]   # tie adds one graded goal (OT or SO winner)
    return out


# ------------------------------------------------------------------ backtests

def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def run_backtest(cur, dates, priors=None, k=K):
    prow, trow = [], []
    for cut in dates:
        p = fit_players(cur, cut, priors, k)
        day = cur["pg"][(cur["pg"].date == cut) & (cur["pg"].game_type == "regular")]
        if day.empty or p.empty:
            continue
        rosters = {tm: grp.player_id.tolist() for tm, grp in day.groupby("team")}
        tm = fit_teams(cur, cut, p, priors, k, rosters)
        st = cur["gg"][(cur["gg"].date == cut) & cur["gg"].starter].set_index(["game_id", "team"]).player_id
        rows = day[["game_id", "player_id", "team", "opp", "g", "pts"]].rename(columns={"g": "y_g", "pts": "y_pts"})
        rows["opp_goalie"] = [st.get((gid, o)) for gid, o in zip(rows.game_id, rows.opp)]
        d = price_players(rows.set_index("player_id"), p, tm).reset_index()
        pgb = cur["pg"][(cur["pg"].date < cut) & (cur["pg"].game_type == "regular")]
        for pos in ("F", "D"):
            q, m = pgb[pgb.pos == pos], d.pos == pos
            d.loc[m, "base_g"] = 1 - np.exp(-q.g.sum() / q.toi.sum() * d.loc[m, "proj_toi"])
            lp = q.pts.sum() / q.toi.sum() * d.loc[m, "proj_toi"]
            d.loc[m, "base_2"] = 1 - np.exp(-lp) * (1 + lp)
        d["date"] = cut
        prow.append(d)
        base_lam = tm["lg60"] * tm["calib"]
        for _, gm in cur["games"][(cur["games"].date == cut) & (cur["games"].game_type == "regular")].iterrows():
            la = team_lambda(tm, gm.away, gm.home, st.get((gm.game_id, gm.home)))
            lh = team_lambda(tm, gm.home, gm.away, st.get((gm.game_id, gm.away)))
            dm, db = total_dist(la, lh), total_dist(base_lam, base_lam)
            y = int(gm.home_score + gm.away_score)
            kk = np.arange(len(dm))
            trow.append(dict(date=cut, pred=(dm * kk).sum(), base=(db * kk).sum(), actual=y,
                             ll_m=np.log(dm[min(y, len(dm) - 1)]), ll_b=np.log(db[min(y, len(db) - 1)]),
                             p_o55=dm[kk >= 6].sum(), p_o65=dm[kk >= 7].sum()))
    P = pd.concat(prow)
    P["y_goal"], P["y_2"] = (P.y_g >= 1).astype(int), (P.y_pts >= 2).astype(int)
    return P, pd.DataFrame(trow)


def report(P, Tt, label):
    rm = lambda c: np.sqrt(((Tt[c] - Tt.actual) ** 2).mean())
    print(f"\n== {label}: {len(Tt)} games, {len(P)} player-games ==")
    print(f"goal   logloss model {logloss(P.y_goal, P.p_goal):.4f} | baseline {logloss(P.y_goal, P.base_g):.4f}"
          f" | pred {P.p_goal.sum():.0f} vs actual {P.y_goal.sum()} scorers")
    print(f"2+pts  logloss model {logloss(P.y_2, P.p_2pts):.4f} | baseline {logloss(P.y_2, P.base_2):.4f}"
          f" | pred {P.p_2pts.sum():.0f} vs actual {P.y_2.sum()}")
    print(f"totals RMSE model {rm('pred'):.3f} | baseline {rm('base'):.3f} | loglik/game "
          f"{Tt.ll_m.mean():.4f} vs {Tt.ll_b.mean():.4f} | corr {np.corrcoef(Tt.pred, Tt.actual)[0, 1]:.3f}")


def calib_table(P, col, ycol, bins):
    x = P.assign(b=pd.cut(P[col], bins))
    return x.groupby("b", observed=True).agg(n=(ycol, "size"), pred=(col, "mean"), actual=(ycol, "mean")).round(3)


def american(p):
    return f"+{100 * (1 - p) / p:.0f}" if p < 0.5 else f"{-100 * p / (1 - p):.0f}"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "prior-backtest"
    if mode == "season-backtest":
        season = sys.argv[2] if len(sys.argv) > 2 else PREV
        cur = load(season)
        dates = sorted(cur["games"][cur["games"].game_type == "regular"].date.unique())
        dates = [d for d in dates if d >= dates[0][:4] + "-10-17"]
        P, Tt = run_backtest(cur, dates)
        P.to_csv(os.path.join(OUTROOT, season, "bt_players.csv"), index=False)
        Tt.to_csv(os.path.join(OUTROOT, season, "bt_totals.csv"), index=False)
        report(P, Tt, f"{season} full season (no priors)")
    elif mode == "prior-backtest":
        cur, prev = load(CUR), load(PREV)
        pri = build_prev_priors(prev)
        dates = sorted(cur["pg"].date.unique())
        dates = [d for d in dates if d >= "2026-10-04"]
        P0, T0 = run_backtest(cur, dates)
        P1, T1 = run_backtest(cur, dates, pri)
        report(P0, T0, "2026-27 without priors")
        report(P1, T1, "2026-27 with 2025-26 priors")
        print(calib_table(P1, "p_goal", "y_goal", [0, .1, .15, .2, .25, .3, .4, 1]))
        print(calib_table(P1, "p_2pts", "y_2", [0, .05, .1, .15, .2, .3, 1]))
    elif mode == "tonight":
        cur, prev = load(CUR), load(PREV)
        pri = build_prev_priors(prev)
        slate = pd.read_csv(os.path.join(ROOT, "analysis", "slate.csv"))
        cut = slate.date.iloc[0]
        names = pd.concat([prev["names"], cur["names"]])
        names = names[~names.index.duplicated(keep="last")]
        gid = {n.lower(): pid for pid, n in names.items()}
        p = fit_players(cur, cut, pri)
        pgc = cur["pg"][cur["pg"].date < cut]
        rosters, rows = {}, []
        for _, s in slate.iterrows():
            for team, opp, og in ((s.away, s.home, s.home_goalie), (s.home, s.away, s.away_goalie)):
                last = pgc[pgc.team == team].game_id.max()
                ids = pgc[(pgc.game_id == last) & (pgc.team == team)].player_id.tolist()
                rosters[team] = ids
                rows += [{"player_id": i, "team": team, "opp": opp, "opp_goalie": gid.get(str(og).lower(), -1)}
                         for i in ids]
        tm = fit_teams(cur, cut, p, pri, K, rosters)
        d = price_players(pd.DataFrame(rows).set_index("player_id"), p, tm).reset_index()
        d["player"] = d.player_id.map(names)
        d.to_csv(os.path.join(OUTROOT, CUR, f"props_{cut}.csv"), index=False)
        trows = []
        for _, s in slate.iterrows():
            la = team_lambda(tm, s.away, s.home, gid.get(s.home_goalie.lower(), -1))
            lh = team_lambda(tm, s.home, s.away, gid.get(s.away_goalie.lower(), -1))
            dist = total_dist(la, lh)
            kk = np.arange(len(dist))
            o55, o65 = dist[kk >= 6].sum(), dist[kk >= 7].sum()
            trows.append(dict(game=f"{s.away} @ {s.home}", away_xg=round(la, 2), home_xg=round(lh, 2),
                              exp_total=round((dist * kk).sum(), 2), p_over55=round(o55, 3),
                              fair_o55=american(o55), p_over65=round(o65, 3), fair_o65=american(o65)))
        T = pd.DataFrame(trows).sort_values("exp_total", ascending=False)
        T.to_csv(os.path.join(OUTROOT, CUR, f"totals_{cut}.csv"), index=False)
        print(f"priced {len(d)} players, {len(T)} games for {cut}")
