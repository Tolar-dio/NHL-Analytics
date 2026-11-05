"""Deserved standings and playoff odds.

Deserved points: every game replayed from its chances. Each team's unblocked shots, with their expected goals,
give a distribution of goals (each shot goes in or it doesn't: Poisson-binomial); from the two distributions,
P(win in regulation), P(tied after 60) and P(loss). A regulation win is worth 2 points, a tie 1 plus the overtime
coin (home teams win about 51%), so a game you dominated but lost still earns you most of the points you deserved.

Playoff odds: the rest of the schedule played 10,000 times. Each team's scoring and preventing rates blend
expected goals (70%) with real goals (30%) per game, shrunk toward last season's rates and the league with 20 games
of weight; each simulated season also draws every team's true strength from that uncertainty, so a hot start
doesn't become a sure thing. Home ice (models.HOME), overtime by the home-team share, standings by points then
regulation wins; the top three in each division and two wild cards per conference make it.

    python analysis/race.py [--check]  # today's table; --check scores 2025-26 odds at four dates against who made it
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import models as M  # noqa: E402
from defense import _xg  # noqa: E402

DIVISIONS = {"Atlantic": "BOS BUF DET FLA MTL OTT TBL TOR", "Metropolitan": "CAR CBJ NJD NYI NYR PHI PIT WSH",
             "Central": "CHI COL DAL MIN NSH STL UTA WPG", "Pacific": "ANA CGY EDM LAK SEA SJS VAN VGK"}
DIV = {t: d for d, ts in DIVISIONS.items() for t in ts.split()}
CONF = {d: ("East" if d in ("Atlantic", "Metropolitan") else "West") for d in DIVISIONS}
ATT = ["shot-on-goal", "missed-shot", "goal"]
OT_HOME = 0.514
K_GAMES, XG_W, SIMS = 20, 0.7, 10000
SD = float(os.environ.get("RACE_SD", "0.30"))


def goal_dist(xgs, n=15):
    d = np.zeros(n); d[0] = 1.0
    for p in xgs:
        p = min(max(float(p), 0.0), 0.99)
        d[1:] = d[1:] * (1 - p) + d[:-1] * p
        d[0] *= 1 - p
    return d


def deserved(season, upto=None):
    """Per regular-season game: each side's deserved points (and the real result)."""
    T = os.path.join(ROOT, "data", "tables", season)
    ev = pd.read_csv(os.path.join(T, "events.csv.gz"), usecols=["game_id", "game_type", "event_id", "event", "period_type",
                                                                 "game_seconds", "player1_id", "team", "home_team"])
    ev = ev[(ev.game_type == "regular") & (ev.period_type != "SO") & ev.event.isin(ATT)].copy()
    att = _xg(season, ev)
    games = pd.read_csv(os.path.join(T, "games.csv.gz"))
    games = games[games.game_type == "regular"]
    if upto:
        games = games[games.date < upto]
    rows = []
    by = {gid: a for gid, a in att.groupby("game_id")}
    for g in games.itertuples():
        a = by.get(g.game_id)
        if a is None:
            continue
        dh, da = goal_dist(a[a.team == g.home].xg), goal_dist(a[a.team == g.away].xg)
        j = np.outer(dh, da)                     # [home goals, away goals]
        ph, tie = float(np.tril(j, -1).sum()), float(np.trace(j))
        pa = 1 - ph - tie
        xh, xa = 2 * ph + tie * (1 + OT_HOME), 2 * pa + tie * (1 + (1 - OT_HOME))
        hw = g.home_score > g.away_score
        reg = g.decided_in == "REG"
        rows.append(dict(game_id=g.game_id, date=g.date, home=g.home, away=g.away, xpts_h=xh, xpts_a=xa,
                         pts_h=2 if hw else (1 if not reg else 0), pts_a=2 if not hw else (1 if not reg else 0),
                         rw_h=int(hw and reg), rw_a=int((not hw) and reg),
                         xgf_h=float(a[a.team == g.home].xg.sum()), xgf_a=float(a[a.team == g.away].xg.sum()),
                         gf_h=g.home_score, gf_a=g.away_score))
    return pd.DataFrame(rows)


def team_table(D):
    long = pd.concat([D.rename(columns=dict(home="team", xpts_h="xpts", pts_h="pts", rw_h="rw", xgf_h="xgf", xgf_a="xga",
                                            gf_h="gf", gf_a="ga"))[["team", "xpts", "pts", "rw", "xgf", "xga", "gf", "ga"]],
                      D.rename(columns=dict(away="team", xpts_a="xpts", pts_a="pts", rw_a="rw", xgf_a="xgf", xgf_h="xga",
                                            gf_a="gf", gf_h="ga"))[["team", "xpts", "pts", "rw", "xgf", "xga", "gf", "ga"]]])
    t = long.groupby("team").agg(gp=("pts", "size"), pts=("pts", "sum"), xpts=("xpts", "sum"), rw=("rw", "sum"),
                                 xgf=("xgf", "sum"), xga=("xga", "sum"), gf=("gf", "sum"), ga=("ga", "sum"))
    return t


def strengths(t, prior=None):
    """Goals for and against per game, blended and shrunk. Returns (for, against, sd of the log rating)."""
    lg = float((t.gf.sum() + t.xgf.sum()) / (2 * t.gp.sum()))
    f = XG_W * t.xgf / t.gp + (1 - XG_W) * t.gf / t.gp
    a = XG_W * t.xga / t.gp + (1 - XG_W) * t.ga / t.gp
    pf = pd.Series(lg, index=t.index) if prior is None else (0.5 * prior["for"].reindex(t.index).fillna(lg) + 0.5 * lg)
    pa = pd.Series(lg, index=t.index) if prior is None else (0.5 * prior["against"].reindex(t.index).fillna(lg) + 0.5 * lg)
    f = (t.gp * f + K_GAMES * pf) / (t.gp + K_GAMES)
    a = (t.gp * a + K_GAMES * pa) / (t.gp + K_GAMES)
    sd = SD / np.sqrt(t.gp + K_GAMES)          # uncertainty in a team's true rate, shrinking as games are played
    return f, a, sd, lg


def simulate(t, sched, f, a, sd, lg, sims=SIMS, seed=7):
    rng = np.random.default_rng(seed)
    teams = list(t.index)
    ix = {x: i for i, x in enumerate(teams)}
    n = len(teams)
    hi, ai = np.array([ix[g["home"]] for g in sched], int), np.array([ix[g["away"]] for g in sched], int)
    F, A = f.reindex(teams).values, a.reindex(teams).values
    zf = np.exp(rng.normal(0, 1, (sims, n)) * sd.reindex(teams).values)
    za = np.exp(rng.normal(0, 1, (sims, n)) * sd.reindex(teams).values)
    lh = (F[hi] * zf[:, hi]) * (A[ai] * za[:, ai]) / lg * (1 + M.HOME)
    la = (F[ai] * zf[:, ai]) * (A[hi] * za[:, hi]) / lg * (1 - M.HOME)
    gh, ga = rng.poisson(lh), rng.poisson(la)
    tie = gh == ga
    home_ot = rng.random(gh.shape) < OT_HOME
    hw = (gh > ga) | (tie & home_ot)
    pts = np.tile(t.pts.reindex(teams).values.astype(float), (sims, 1))
    rw = np.tile(t.rw.reindex(teams).values.astype(float), (sims, 1))
    for arr, idx, val in ((pts, hi, 2 * hw + (tie & ~hw)), (pts, ai, 2 * ~hw + (tie & hw)),
                          (rw, hi, hw & ~tie), (rw, ai, ~hw & ~tie)):
        np.add.at(arr, (np.repeat(np.arange(sims), len(idx)), np.tile(idx, sims)), val.ravel().astype(float))
    key = pts * 1000 + rw + rng.random(pts.shape) * 0.5     # points, then regulation wins, then a coin
    made = np.zeros((sims, n), bool)
    divwin = np.zeros((sims, n), bool)
    for conf in ("East", "West"):
        divs = [d for d in DIVISIONS if CONF[d] == conf]
        conf_ix = [ix[x] for d in divs for x in DIVISIONS[d].split() if x in ix]
        auto = np.zeros((sims, n), bool)
        for d in divs:
            di = np.array([ix[x] for x in DIVISIONS[d].split() if x in ix])
            order = np.argsort(-key[:, di], axis=1)
            for r in range(3):
                auto[np.arange(sims), di[order[:, r]]] = True
            divwin[np.arange(sims), di[order[:, 0]]] = True
        ci = np.array(conf_ix)
        k2 = np.where(auto[:, ci], -np.inf, key[:, ci])
        order = np.argsort(-k2, axis=1)
        wc = np.zeros((sims, n), bool)
        for r in range(2):
            wc[np.arange(sims), ci[order[:, r]]] = True
        made |= auto | wc
    return pd.DataFrame(dict(team=teams, playoffs=made.mean(0), division=divwin.mean(0), proj=pts.mean(0),
                             lo=np.percentile(pts, 10, axis=0), hi=np.percentile(pts, 90, axis=0))).set_index("team")


def prior_rates(prev):
    t = team_table(deserved(prev))
    return dict(**{"for": XG_W * t.xgf / t.gp + (1 - XG_W) * t.gf / t.gp}, against=XG_W * t.xga / t.gp + (1 - XG_W) * t.ga / t.gp)


def race(season=M.CUR, prev=M.PREV, upto=None, sims=SIMS):
    D = deserved(season, upto)
    t = team_table(D)
    sched_all = json.load(open(os.path.join(ROOT, "data", "external", "schedule", f"{season}.json")))["games"]
    played = set(D.game_id)
    cutoff = upto or "0000"
    sched = [g for g in sched_all if g["id"] not in played and g["date"] >= cutoff and g["home"] in t.index and g["away"] in t.index]
    pr = prior_rates(prev) if prev else None
    f, a, sd, lg = strengths(t, pr)
    S = simulate(t, sched, f, a, sd, lg, sims)
    out = t.join(S)
    out["div"] = [DIV.get(x) for x in out.index]
    out["conf"] = [CONF.get(DIV.get(x)) for x in out.index]
    out["luck"] = out.pts - out.xpts
    out["rating_for"], out["rating_against"] = f, a
    return out, len(sched)


def made_it(t):
    """Who makes the playoffs from a finished table (points, then regulation wins)."""
    key = t.pts * 1000 + t.rw
    made = set()
    for conf in ("East", "West"):
        divs = [d for d in DIVISIONS if CONF[d] == conf]
        auto = [x for d in divs for x in sorted(DIVISIONS[d].split(), key=lambda x: -key.get(x, 0))[:3]]
        rest = [x for d in divs for x in DIVISIONS[d].split() if x not in auto]
        made |= set(auto) | set(sorted(rest, key=lambda x: -key.get(x, 0))[:2])
    return made


def check(season="20252026"):
    """Odds at four dates (no prior season) against who made it, next to ranking teams by points percentage.
    2025-26: Brier 0.199 / 0.157 / 0.113 / 0.107 at Nov 5, Dec 15, Feb 1, Mar 10 (ranking: 0.226 / 0.174 / 0.148);
    more rating noise (0.6, 1.0), K 35 and an xG weight of 0.5 were all worse; K 10 and xG 0.85-1.0 tied."""
    D = deserved(season)
    full = team_table(D)
    made = made_it(full)
    y = pd.Series({x: x in made for x in full.index})
    sched = json.load(open(os.path.join(ROOT, "data", "external", "schedule", f"{season}.json")))["games"]
    for upto in ["%s-11-05" % season[:4], "%s-12-15" % season[:4], "%s-02-01" % season[4:], "%s-03-10" % season[4:]]:
        t = team_table(D[D.date < upto])
        f, a, sd, lg = strengths(t, None)
        p = simulate(t, [g for g in sched if g["date"] >= upto], f, a, sd, lg, 3000).playoffs.reindex(y.index)
        naive = (t.pts / t.gp).rank(pct=True).reindex(y.index)
        print(f"{upto}: Brier {((p - y) ** 2).mean():.3f}, by points percentage {((naive - y) ** 2).mean():.3f}")


def publish(out, n_left, season=M.CUR):
    """The table the League tab shows."""
    rows = []
    for x, r in out.sort_values(["conf", "div", "playoffs"], ascending=[True, True, False]).iterrows():
        rows.append(dict(team=x, div=r["div"], conf=r["conf"], gp=int(r.gp), pts=int(r.pts), rw=int(r.rw),
                         xpts=round(float(r.xpts), 1), luck=round(float(r.luck), 1),
                         proj=round(float(r.proj), 1), lo=int(r.lo), hi=int(r.hi),
                         playoffs=round(float(r.playoffs), 3), division=round(float(r.division), 3),
                         gf=round(float(r.rating_for), 2), ga=round(float(r.rating_against), 2)))
    return dict(season=season, games_left=n_left, sims=SIMS, rows=rows)


if __name__ == "__main__":
    out, n = race()
    print(f"{n} games left")
    print(out.sort_values("playoffs", ascending=False)[["gp", "pts", "xpts", "luck", "proj", "lo", "hi", "playoffs", "division"]].round(2))
    if "--check" in sys.argv:
        check()
