"""All Three Zones (Corey Sznajder's hand tracking) in the model and on the site.

The raw files and the tables built from them live in the private repo (Tolar-dio/nhl-private, a3z/tables/<season>/);
the nightly checks the tables out into private/ (gitignored). This file is code only. Nothing it reads is
committed here, and the site shows only derived, credited numbers ("Data: All Three Zones").

    python analysis/a3z.py xg       does pre-shot passing improve MoneyPuck's xG on tracked shots? (out of fold, by game)
    python analysis/a3z.py props    do tracked playmaking and shooting rates improve the goal, 1+ and 2+ point prices?
                                    (walk-forward over the 2025-26 season backtest, last season's tracking as the prior)

Env: A3Z_DIR (default <repo>/private/a3z/tables).
"""
import glob, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A3Z_DIR = os.environ.get("A3Z_DIR", os.path.join(ROOT, "private", "a3z", "tables"))
CREDIT = "Passing, entry and exit tracking: All Three Zones (Corey Sznajder, allthreezones.com)."
LABEL = {"20232024": "2023-24", "20242025": "2024-25", "20252026": "2025-26", "20262027": "2026-27"}
COUNTS = ["shots", "sog", "goals5", "chances", "shots_hd_pass", "shots_rush", "shots_forecheck", "shots_cycle", "shots_onetimer",
          "sa1", "sa2", "sa3", "chance_assists", "hd_assists", "rush_assists", "assists_behind_net", "assists_royal_road",
          "pp_shots", "pp_setups", "pp_chance_setups", "entries", "carries", "dumps", "failed_entries", "carries_chance",
          "entries_passing", "targeted", "carries_allowed", "denials", "recoveries", "retrievals", "botched", "exits",
          "exits_carried", "exits_passed", "exits_clear", "exits_failed", "forecheck_pressures"]


def available(season):
    return os.path.exists(os.path.join(A3Z_DIR, LABEL.get(season, season), "player_games.csv.gz"))


def load(season, what="player_games"):
    p = os.path.join(A3Z_DIR, LABEL.get(season, season), f"{what}.csv.gz")
    return pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()


def game_dates(season):
    g = pd.read_csv(os.path.join(ROOT, "data", "tables", season, "games.csv.gz"), usecols=["game_id", "date"])
    return dict(zip(g.game_id, g.date))


def season_totals(pg):
    """Per player: tracked games, 5v5 minutes and every count."""
    pg = pg.dropna(subset=["player_id"]).copy()
    pg["player_id"] = pg.player_id.astype(int)
    pos = pg.groupby("player_id").pos.agg(lambda s: s.dropna().iloc[-1] if s.notna().any() else None)
    agg = pg.groupby("player_id").agg(games=("game_id", "nunique"), toi5=("toi5", "sum"), team=("team", "last"),
                                      **{c: (c, "sum") for c in COUNTS if c in pg})
    agg["pos"] = pos.map(lambda p: "D" if str(p).upper().startswith("D") else ("G" if str(p).upper() == "G" else "F"))
    return agg


# ------------------------------------------------------------------ the site's "how he creates offense" card

CARD = [  # (key, label, numerator, denominator or None for per 60, higher is better)
    ("shots60", "Shot attempts", "shots", None, True),
    ("chances60", "Scoring chances", "chances", None, True),
    ("sa1_60", "Primary shot assists", "sa1", None, True),
    ("chance_ast60", "Chance assists", "chance_assists", None, True),
    ("hd_shots60", "Shots off high-danger passes", "shots_hd_pass", None, True),
    ("entries60", "Zone entries", "entries", None, True),
    ("carry_pct", "Entries carried in", "carries", "entries", True),
    ("exit_poss_pct", "Exits with possession", ("exits_carried", "exits_passed"), "exits", True),
    ("denial_pct", "Entries denied (defending)", "denials", "targeted", True),
    ("rush_share", "Shots off the rush", "shots_rush", "shots", None),
]
MIN_TOI = 60.0     # 5v5 tracked minutes before a player gets a card
PCTILE_TOI = 150.0  # and before he counts in the league percentiles


def cards(season):
    """{player_id: card} for the site: per-60 rates and shares with league percentiles by position."""
    pg = load(season)
    if pg.empty:
        return {}
    T = season_totals(pg)
    T = T[T.toi5 >= MIN_TOI]
    vals = pd.DataFrame(index=T.index)
    for key, _, num, den, _ in CARD:
        n = T[list(num)].sum(axis=1) if isinstance(num, tuple) else T[num]
        vals[key] = (n / T[den].where(T[den] > 0)) if den else n / T.toi5 * 60
    out = {}
    pool = T.toi5 >= PCTILE_TOI
    for pid, x in T.iterrows():
        same = pool & (T.pos == x.pos)
        rows = []
        for key, label, num, den, hib in CARD:
            v = vals.at[pid, key]
            if v is None or pd.isna(v) or (den and T.at[pid, den if isinstance(den, str) else den[0]] < 8):
                continue
            ref = vals.loc[same, key].dropna()
            pct = float((ref < v).mean() + 0.5 * (ref == v).mean()) if len(ref) >= 20 else None
            rows.append(dict(k=key, label=label, v=round(float(v), 3 if den else 2), share=bool(den), pctile=None if pct is None else round(pct, 2),
                             hib=hib, lg=round(float(ref.median()), 3 if den else 2) if len(ref) else None))
        out[int(pid)] = dict(season=LABEL.get(season, season), games=int(x.games), toi5=round(float(x.toi5), 1), pos=x.pos, rows=rows,
                             style=style(x))
    return out


def style(x):
    """One plain sentence on how a skater creates offense, from his tracked shares (only when the sample allows)."""
    bits = []
    if x.shots >= 20:
        rush = x.shots_rush / x.shots
        if rush >= 0.4:
            bits.append(f"{round(100 * rush)}% of his shots come off the rush")
        elif x.shots_forecheck + x.shots_cycle >= 0.75 * x.shots:
            bits.append("most of his shots come from forecheck and cycle play, not the rush")
    if x.sa1 + x.shots >= 30:
        if x.sa1 >= 1.1 * x.shots:
            bits.append("he sets up more shots than he takes")
        elif x.shots >= 2 * x.sa1:
            bits.append("he's a shooter first, with two attempts for every shot he sets up")
    if x.entries >= 20:
        cp = x.carries / x.entries
        if cp >= 0.6:
            bits.append(f"he carries the puck in on {round(100 * cp)}% of his entries")
        elif cp <= 0.3:
            bits.append(f"he dumps it in more often than he carries it ({round(100 * cp)}% carried)")
    if x.sa1 >= 10 and x.assists_behind_net >= 0.25 * x.sa1:
        bits.append("a lot of his setups come from behind the net")
    return (bits[0][0].upper() + bits[0][1:] + (", and " + ", and ".join(bits[1:2]) if len(bits) > 1 else "") + ".") if bits else None


# ------------------------------------------------------------------ test 1: passing features on top of MoneyPuck xG

def mp_shots(season):
    files = glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", season, "*.csv.gz"))
    cols = ["game_id", "period", "time", "shooterPlayerId", "xGoal", "goal"]
    mp = pd.concat([pd.read_csv(f, usecols=lambda c: c in cols) for f in files], ignore_index=True)
    mp["game_id"] = int(season[:4]) * 1000000 + mp.game_id
    mp["elapsed"] = mp.time - (mp.period.clip(upper=4) - 1) * 1200
    return mp.rename(columns={"shooterPlayerId": "shooter_id"})


def match_shots(season):
    """A3Z shot rows joined to MoneyPuck's unblocked shots: same game, period and shooter, within 3 seconds."""
    S = load(season, "shots").dropna(subset=["shooter_id", "elapsed"])
    mp = mp_shots(season)
    S = S[S.game_id.isin(mp.game_id)].copy()
    S["shooter_id"] = S.shooter_id.astype(int)
    S["k"] = np.arange(len(S))
    m = S.merge(mp, on=["game_id", "period", "shooter_id"], suffixes=("", "_mp"))
    m["d"] = (m.elapsed - m.elapsed_mp).abs()
    m = m[m.d <= 3].sort_values("d").drop_duplicates("k").drop_duplicates(["game_id", "period", "shooter_id", "elapsed_mp"])
    return m, len(S)


def xg_test(seasons=("20252026", "20262027")):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    parts = []
    for s in seasons:
        if available(s):
            m, n = match_shots(s)
            print(f"{s}: {len(m)} of {n} tracked shot attempts matched to MoneyPuck's unblocked shots")
            parts.append(m)
    D = pd.concat(parts, ignore_index=True)
    D = D[D.strength.isin(["5v5", "5v4", "4v5"])]
    z = D.a1_zone.fillna("")
    lx = np.log(D.xGoal.clip(1e-4, 1 - 1e-4) / (1 - D.xGoal.clip(1e-4, 1 - 1e-4)))
    F = pd.DataFrame(dict(lx=lx, passed=D.a1_no.notna(), two_pass=D.a2_no.notna(), royal=z.str.contains("rr"),
                          behind=z.str.contains("el"), slot=z.str.startswith("s"), point=z.str.contains("p") & ~z.str.contains("el"),
                          onetimer=D.shot_type == "o", rush=D.play == "r", oddman=D.oddman.notna(), screen=D.screen == 1,
                          pp=D.strength == "5v4")).astype(float)
    y = D.goal_mp.values if "goal_mp" in D else D.goal.values
    g = D.game_id.values
    def cv(cols):
        p = np.zeros(len(F))
        for tr, te in GroupKFold(5).split(F, y, g):
            mdl = LogisticRegression(C=1.0, max_iter=2000).fit(F.iloc[tr][cols], y[tr])
            p[te] = mdl.predict_proba(F.iloc[te][cols])[:, 1]
        return p
    from sklearn.metrics import log_loss, roc_auc_score
    p0, p1 = cv(["lx"]), cv(list(F.columns))
    raw = D.xGoal.clip(1e-4, 1 - 1e-4).values
    print(f"tracked unblocked shots: {len(F)}, goals {int(y.sum())}")
    print(f"MoneyPuck xG as is:     log loss {log_loss(y, raw):.4f}  AUC {roc_auc_score(y, raw):.4f}")
    print(f"MoneyPuck recalibrated: log loss {log_loss(y, p0):.4f}  AUC {roc_auc_score(y, p0):.4f}")
    print(f"plus A3Z passing:       log loss {log_loss(y, p1):.4f}  AUC {roc_auc_score(y, p1):.4f}")
    full = LogisticRegression(C=1.0, max_iter=2000).fit(F, y)
    print("coefficients:", {c: round(float(b), 3) for c, b in zip(F.columns, full.coef_[0])})
    return D, F


# ------------------------------------------------------------------ test 2: tracked rates in the props prices

FEATS = ["sa1", "chance_assists", "hd_assists", "shots", "chances", "shots_hd_pass", "entries", "carries"]
K_TOI = 200.0   # minutes of league-average play mixed into every player's tracked rate


def walk_rates(season, prev):
    """For every (player, date): his tracked 5v5 rates from this season's games before that date plus half of last
    season's, shrunk toward his position's average with K_TOI minutes. Returns a date-sorted frame for merge_asof."""
    pg = load(season)
    pg = pg.dropna(subset=["player_id"]).copy()
    pg["player_id"] = pg.player_id.astype(int)
    pg["date"] = pg.game_id.map(game_dates(season))
    pg = pg.dropna(subset=["date"]).sort_values("date")
    P = season_totals(load(prev)) if available(prev) else pd.DataFrame()
    cols = ["toi5"] + FEATS
    daily = pg.groupby(["player_id", "date"])[cols].sum().groupby(level=0).cumsum().reset_index()
    if not P.empty:
        prior = P[cols].mul(0.5)
        daily = daily.join(prior, on="player_id", rsuffix="_p").fillna(0)
        for c in cols:
            daily[c] = daily[c] + daily[f"{c}_p"]
    pos = pg.groupby("player_id").pos.last().map(lambda p: "D" if str(p).upper().startswith("D") else "F")
    daily["pos"] = daily.player_id.map(pos)
    lg = pg.assign(pos=pg.pos.map(lambda p: "D" if str(p).upper().startswith("D") else "F")).groupby("pos")[cols].sum()
    for c in FEATS:
        mu = daily.pos.map(lg[c] / lg.toi5)
        daily[c + "_r"] = (daily[c] + K_TOI * mu) / (daily.toi5 + K_TOI) * 60
        daily[c + "_z"] = (daily[c + "_r"] - mu * 60) / (mu * 60).replace(0, np.nan)   # rate / position average - 1
    daily["date"] = pd.to_datetime(daily.date)
    return daily.sort_values("date")


def current_z(season, prev):
    """{player_id: {chance_assists, chances, carries}} as of every tracked game so far (plus half of last season), and the
    TOI-weighted league mean of the multiplier, for models.A3Z_Z / A3Z_NORM."""
    import models as M
    if not available(season) and not available(prev):
        return {}, 1.0
    if available(season):
        R = walk_rates(season, prev)
        last = R.sort_values("date").groupby("player_id").tail(1).set_index("player_id")
    else:
        T = season_totals(load(prev))
        last = T.assign(**{c: T[c] * 0.5 for c in ["toi5"] + FEATS})
        lg = T.groupby("pos")[["toi5"] + FEATS].sum()
        for c in FEATS:
            mu = last.pos.map(lg[c] / lg.toi5)
            last[c + "_z"] = ((last[c] + K_TOI * mu) / (last.toi5 + K_TOI)) / mu - 1
    z = {}
    for pid, x in last.iterrows():
        z[int(pid)] = {k: float(np.clip(x[k + "_z"], -1, 3)) for k in M.A3Z_B if pd.notna(x.get(k + "_z"))}
    w = last.toi5.clip(lower=0)
    f = np.exp(sum(b * last[k + "_z"].clip(-1, 3).fillna(0) for k, b in M.A3Z_B.items()))
    return z, float((f * w).sum() / w.sum()) if w.sum() else 1.0


def props_test(season="20252026", prev="20242025"):
    from sklearn.linear_model import LogisticRegression
    bt = pd.read_csv(os.path.join(ROOT, "analysis", "output", season, "bt_players.csv"))
    bt["date"] = pd.to_datetime(bt.date)
    R = walk_rates(season, prev)
    zc = [c + "_z" for c in FEATS]
    d = pd.merge_asof(bt.sort_values("date"), R[["player_id", "date", "toi5"] + zc].rename(columns={"toi5": "a3z_toi"}),
                      on="date", by="player_id", allow_exact_matches=False)
    d[zc] = d[zc].fillna(0.0)
    d["a3z_toi"] = d.a3z_toi.fillna(0.0)
    d["y_1"] = (d.y_pts >= 1).astype(int)
    d["month"] = d.date.dt.strftime("%Y-%m")
    print(f"{season}: {len(d)} player-games, {(d.a3z_toi > 0).mean():.0%} with some tracked history (this season or last)")
    lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
    out = {}
    for target, pcol, feats in (("goal", "p_goal", ["shots_z", "chances_z", "shots_hd_pass_z"]),
                                ("1+ points", "p_1pt", ["sa1_z", "chance_assists_z", "hd_assists_z", "chances_z", "entries_z", "carries_z"]),
                                ("2+ points", "p_2pts", ["sa1_z", "chance_assists_z", "hd_assists_z", "chances_z", "entries_z", "carries_z"])):
        y = d["y_goal" if target == "goal" else ("y_1" if target == "1+ points" else "y_2")].values
        X0 = pd.DataFrame(dict(lp=lg(d[pcol].values)))
        X1 = X0.join(d[feats].reset_index(drop=True).clip(-3, 3))
        months = sorted(d.month.unique())
        ll = dict(model=[], recal=[], a3z=[])
        n = 0
        for m in months[2:]:            # expanding window: train on every earlier month, score this one
            tr, te = (d.month < m).values, (d.month == m).values
            if te.sum() == 0:
                continue
            for name, X in (("recal", X0), ("a3z", X1)):
                mdl = LogisticRegression(C=1.0, max_iter=2000).fit(X[tr], y[tr])
                p = mdl.predict_proba(X[te])[:, 1]
                ll[name].append(-np.sum(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)))
            p = np.clip(d[pcol].values[te], 1e-4, 1 - 1e-4)
            ll["model"].append(-np.sum(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)))
            n += te.sum()
        res = {k: round(sum(v) / n, 5) for k, v in ll.items()}
        full = LogisticRegression(C=1.0, max_iter=2000).fit(X1, y)
        res["coef"] = {c: round(float(b), 3) for c, b in zip(X1.columns, full.coef_[0])}
        res["n"] = int(n)
        out[target] = res
        print(f"  {target:10s} n={n}: model {res['model']:.5f}  recalibrated {res['recal']:.5f}  + A3Z {res['a3z']:.5f}  "
              f"gain {res['recal'] - res['a3z']:+.5f}   {res['coef']}")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "props"
    if mode == "xg":
        xg_test()
    elif mode == "props":
        props_test()
    elif mode == "cards":
        c = cards(sys.argv[2] if len(sys.argv) > 2 else "20262027")
        print(len(c), "cards")
