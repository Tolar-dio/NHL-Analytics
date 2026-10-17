"""Evolving-Hockey season tables (paid, private): player value cards for the site, and a prior test for the model.

The tables live only in the private repo (Tolar-dio/nhl-private, eh/tables/, built from Tolar's CSV exports by its
scripts/eh_tables.py) and are checked out to private/eh/tables by the nightly job. Evolving-Hockey approved (Oct 17,
2026) showing their numbers on the site with credit and a link; the raw tables still never go in this public repo.

  python analysis/eh.py props            # does last season's EH profile improve goal/point prices? (no: see CLAUDE.md)
  python analysis/eh.py cards            # build the player value cards and print a few
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EH_DIR = os.environ.get("EH_DIR", os.path.join(ROOT, "private", "eh", "tables"))
CREDIT = "Player value and impact models (GAR, WAR, xGAR, RAPM): Evolving-Hockey (evolving-hockey.com)."
QUAL = 500      # all-situations minutes to be ranked and to sit on the league map
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


def _label(season):
    s = str(season)
    return f"{s[:4]}-{s[6:]}"


def _nth(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _ordn(p):
    return _nth(min(99, max(1, round(100 * p))))


PARTS = [("evo_gar", "Even-strength offense"), ("evd_gar", "Even-strength defense"), ("ppo_gar", "Power play"),
         ("shd_gar", "Penalty kill"), ("pen_gar", "Penalties drawn and taken")]
ROWS = [("war", "Wins above replacement", "wins", False), ("rapm_off", "Chances created (xGF/60)", "rate", False),
        ("rapm_def", "Chances allowed (xGA/60)", "rate", True), ("finish", "Finishing (goals above average)", "goals", False),
        ("qot", "Teammate quality", "rate", False), ("qoc", "Competition quality", "rate", False)]
MAP_KEYS = ["rapm_off", "rapm_def", "evo60", "evd60", "war"]


def _season_frame(sk, season):
    d = sk[sk.season == int(season)].copy()
    d["pg"] = np.where(d.pos.astype(str).str.upper().str.startswith("D"), "D", "F")
    d["toi"] = d.toi_all.fillna(d.all_toi)
    d["pen_gar"] = d.take_gar.fillna(0) + d.draw_gar.fillna(0)
    d["rapm_off"] = d.rapm_xgf60
    d["rapm_def"] = -d.rapm_xga60                      # flipped so that up is good on the map
    d["evo60"] = d.evo_gar / d.toi * 60
    d["evd60"] = d.evd_gar / d.toi * 60
    d["finish"] = d.shot_all_sh_goals
    d["qot"] = d.qot_rapm_xg_pm60
    d["qoc"] = d.qoc_rapm_xg_pm60
    d["rank_war"] = np.nan
    for k in ["war", "rapm_off", "rapm_def", "finish", "qot", "qoc", "pen_gar"] + [c for c, _ in PARTS]:
        d[k + "_p"] = np.nan
        for pg, grp in d.groupby("pg"):
            ref = np.sort(grp[grp.toi >= QUAL][k].dropna().values)
            if len(ref) < 25:
                continue
            d.loc[grp.index, k + "_p"] = np.searchsorted(ref, grp[k].values, side="right") / len(ref)
            if k == "war":
                d.loc[grp.index, "rank_war"] = [int((ref > v).sum()) + 1 for v in grp[k].values]
    return d


def value_notes(c):
    """Plain sentences for a fan: what he's worth, what changes when he's on the ice, luck and context. Each names
    its season; strengths first, at most one weak spot."""
    pos, one = ("defensemen", "defenseman") if c["pos"] == "D" else ("forwards", "forward")
    S, P = c["season"], c["p"]
    out = []
    war, xwar = c["war"], c["xwar"]
    if war is not None:
        parts = sorted(c["parts"], key=lambda x: -abs(x[1]))
        big = parts[0] if parts else None
        if war > 0.05:
            rank = f", {_nth(c['rank'])} among {c['qual']} {pos} with {QUAL}+ minutes" if c.get("rank") and c["toi"] >= QUAL else ""
            src = f" Most of it came from {big[0].lower()} ({big[1]:+.1f} goals)." if big and big[1] > 0 else ""
            out.append(f"Worth {war:.1f} wins above a replacement-level {one} in {S} ({c['gar']:.1f} goals above replacement){rank}.{src}")
        else:
            out.append(f"Around replacement level in {S} ({war:+.1f} wins): a typical call-up would have given about as much.")
    strong = []
    if (P.get("rapm_off") or 0) >= 0.85:
        strong.append(f"He drives play. With teammates, opponents, score and zone starts accounted for, his team created "
                      f"{c['rapm_xgf60']:+.2f} expected goals per 60 with him on the ice ({_ordn(P['rapm_off'])} percentile among {pos}).")
    if (P.get("rapm_def") or 0) >= 0.85:
        strong.append(f"He takes chances away: on the same adjusted basis, opponents got {-c['rapm_xga60']:.2f} fewer expected goals "
                      f"per 60 with him out there ({_ordn(P['rapm_def'])} percentile).")
    out += strong
    if xwar is not None and war is not None:
        if xwar - war >= 1.0:
            out.append(f"He was better than his goals: {xwar:.1f} expected wins (built from chance quality instead of goals) against "
                       f"{war:.1f} actual. The chances were there; the finishing or the goaltending behind him wasn't.")
        elif war - xwar >= 1.0:
            out.append(f"His results ran ahead of his chances: {war:.1f} wins against {xwar:.1f} expected, so some of {S} came from "
                       f"hot shooting or hot goaltending that may not carry over.")
    if (P.get("qot") or 0) >= 0.9:
        out.append(f"He plays with strong teammates ({_ordn(P['qot'])} percentile by their impact), which flatters raw on-ice numbers; "
                   f"GAR and RAPM take that out.")
    elif P.get("qot") is not None and P["qot"] <= 0.1:
        out.append(f"He plays with weaker teammates (bottom {round(100 * P['qot'])}% by their impact), which makes his raw on-ice "
                   f"numbers look worse than his own effect.")
    if (P.get("qoc") or 0) >= 0.9:
        out.append(f"He draws the other team's best: his competition ranks in the {_ordn(P['qoc'])} percentile.")
    if c["pen"] >= 2.0:
        out.append(f"He's worth {c['pen']:+.1f} goals from penalties alone: he draws more than he takes.")
    elif c["pen"] <= -2.0:
        out.append(f"Penalties cost him {c['pen']:.1f} goals: he takes more than he draws.")
    weak = None
    if P.get("rapm_def") is not None and P["rapm_def"] <= 0.12 and not strong[1:]:
        weak = (f"The cost: opponents got {c['rapm_xga60']:+.2f} expected goals per 60 more with him on the ice "
                f"(bottom {max(1, round(100 * P['rapm_def']))}% of {pos}).")
    elif P.get("rapm_off") is not None and P["rapm_off"] <= 0.12:
        weak = (f"Offense isn't his game: his team created {c['rapm_xgf60']:+.2f} expected goals per 60 with him on the ice "
                f"(bottom {max(1, round(100 * P['rapm_off']))}% of {pos}).")
    out = out[:4] + ([weak] if weak else [])
    if c["toi"] < QUAL:
        out.append(f"Small sample: {round(c['toi'])} minutes in {S}, so treat the ranks loosely.")
    return out


def cards(names=None, min_toi=100):
    """Per-player value card from the newest season he played at least min_toi minutes, plus the league table for
    the map. Returns (cards {player_id: card}, league {season label: {keys, rows}})."""
    if not available():
        return {}, {}
    sk = load()
    seasons = sorted(int(s) for s in sk.dropna(subset=["war"]).season.unique())
    frames = {s: _season_frame(sk, s) for s in seasons}
    hist_all = sk[["player_id", "season", "gp_ev", "toi_all", "war", "xwar"]]
    out, league = {}, {}
    for s in seasons:
        d = frames[s]
        lab = _label(s)
        pool = d[d.toi >= QUAL]
        league[lab] = dict(season=lab, keys=["id", "name", "team", "pos"] + MAP_KEYS,
                           rows=[[int(r.player_id), (names or {}).get(int(r.player_id), r.name), str(r.teams).split("/")[-1], r.pg]
                                 + [None if pd.isna(getattr(r, k)) else round(float(getattr(r, k)), 3) for k in MAP_KEYS]
                                 for r in pool.itertuples()],
                           median={pg: {k: round(float(g[k].median()), 3) for k in ["rapm_off", "rapm_def", "war", "finish", "qot", "qoc",
                                                                                     "pen_gar"] + [c for c, _ in PARTS]}
                                   for pg, g in pool.groupby("pg")})
        qual = pool.groupby("pg").size().to_dict()
        for r in d[d.toi >= min_toi].itertuples():
            f = lambda k: None if pd.isna(getattr(r, k)) else round(float(getattr(r, k)), 3)
            c = dict(season=lab, pos=r.pg, name=(names or {}).get(int(r.player_id), r.name), team=str(r.teams), toi=round(float(r.toi), 1),
                     gp=None if pd.isna(r.gp_ev) else int(r.gp_ev), war=f("war"), xwar=f("xwar"), gar=f("gar"), xgar=f("xgar"),
                     rank=None if pd.isna(r.rank_war) else int(r.rank_war), qual=int(qual.get(r.pg, 0)),
                     parts=[[lbl, round(float(getattr(r, k)), 1), league[lab]["median"].get(r.pg, {}).get(k)] for k, lbl in PARTS
                            if not pd.isna(getattr(r, k))],
                     pen=round(float(r.pen_gar), 1), rapm_xgf60=f("rapm_xgf60"), rapm_xga60=f("rapm_xga60"),
                     p={k: (None if pd.isna(getattr(r, k + "_p")) else round(float(getattr(r, k + "_p")), 3))
                        for k in ["war", "rapm_off", "rapm_def", "finish", "qot", "qoc"]},
                     map={k: f(k) for k in MAP_KEYS})
            c["rows"] = [dict(k=k, label=lbl, unit=u, v=(c["rapm_xga60"] if k == "rapm_def" else f(k)), lower_better=lb,
                              pctile=c["p"].get(k), lg=(-(league[lab]["median"].get(r.pg, {}).get(k) or 0) if k == "rapm_def"
                                                        else league[lab]["median"].get(r.pg, {}).get(k)))
                         for k, lbl, u, lb in ROWS if f(k) is not None]
            h = hist_all[hist_all.player_id == r.player_id].sort_values("season")
            c["history"] = [dict(season=_label(x.season), gp=None if pd.isna(x.gp_ev) else int(x.gp_ev),
                                 war=None if pd.isna(x.war) else float(x.war), xwar=None if pd.isna(x.xwar) else float(x.xwar))
                            for x in h.itertuples() if not (pd.isna(x.war) and pd.isna(x.xwar))]
            c["notes"] = value_notes(c)
            out[int(r.player_id)] = c        # newer seasons overwrite older ones
    return out, league


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
    if mode == "cards":
        c, lg = cards()
        print(len(c), "cards;", {k: len(v["rows"]) for k, v in lg.items()}, "players on each season's map")
        for pid in (8477492, 8478402, 8480069, 8481557):
            if pid in c:
                print(c[pid]["name"], c[pid]["season"], c[pid]["war"], *c[pid]["notes"], sep="\n  ")
    elif mode == "props":
        bt = pd.read_csv(os.path.join(ROOT, "analysis", "output", "20252026", "bt_players.csv"))
        props_test(bt, "20242025", label="2025-26 backtest (no in-model priors)")
        late = bt[bt.date >= "2026-01-01"]
        props_test(late, "20242025", label="2025-26 from January (current season dominates)", start=1)
        if len(sys.argv) > 2:      # a 2026-27 backtest priced WITH 2025-26 priors (the live setup), e.g. from prior-backtest
            props_test(pd.read_csv(sys.argv[2]), "20252026", fold="date", start=3, label="2026-27 with priors")
