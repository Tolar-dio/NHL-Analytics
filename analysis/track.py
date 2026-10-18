"""Live track record: grade the frozen pre-game prices in data/archive/<season>/ against what happened.

Unlike the backtest, these are the numbers the site actually showed, with the lineups and goalies it had
to guess. Only games archived before puck drop count. Prices are conditional on playing, so player
markets are graded on players who dressed; lineup and goalie guesses are graded separately.

    python analysis/track.py            # prints the report
build.py calls track(cur) and puts the result in model.json for the "Trust the model?" page.
"""
import glob, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import models as M  # noqa: E402


def ll(y, p):
    return M.logloss(np.asarray(y), np.asarray(p, dtype=float))


def win_home(la, lh):
    pa, ph = np.exp(-la) * la ** np.arange(15) / np.cumprod([1] + list(range(1, 15))), \
             np.exp(-lh) * lh ** np.arange(15) / np.cumprod([1] + list(range(1, 15)))
    j = np.outer(pa, ph)
    return float(np.triu(j, 1).sum() + np.trace(j) / 2)


def track(cur, season=M.CUR):
    files = sorted(glob.glob(os.path.join(ROOT, "data", "archive", season, "*.json")))
    pg = cur["pg"][cur["pg"].game_type == "regular"]
    gg = cur["gg"]
    games = cur["games"].set_index("game_id")
    rows, grows, lineup, goalies = [], [], [], []
    for f in files:
        arc = json.load(open(f))
        day = arc["date"]
        before = pg[pg.date < day]
        rate = {pos: (q.g.sum() / q.toi.sum(), q.pts.sum() / q.toi.sum()) for pos, q in before.groupby("pos")}
        for gid, g in arc["games"].items():
            gid = int(gid)
            if not g.get("pregame") or gid not in games.index:
                continue
            dressed = pg[pg.game_id == gid].set_index("player_id")
            if dressed.empty:
                continue
            priced = {p["id"]: p for p in g["props"]}
            for pid, p in priced.items():
                lineup.append(dict(tag=p.get("lineup") or "last", dressed=pid in dressed.index))
                if pid not in dressed.index or p.get("p_goal") is None:
                    continue
                d = dressed.loc[pid]
                rg, rp = rate.get(p.get("pos") or d.pos, (np.nan, np.nan))
                lp = rp * p["proj_toi"]
                rows.append(dict(date=day, game=gid, lineup=p.get("lineup") or "last", p_goal=p["p_goal"], p_2pts=p["p_2pts"],
                                 p_1pt=p.get("p_1pt"), p_3pts=p.get("p_3pts"), y_1=int(d.pts >= 1), y_3=int(d.pts >= 3),
                                 base_g=1 - np.exp(-rg * p["proj_toi"]), base_2=1 - np.exp(-lp) * (1 + lp),
                                 y_goal=int(d.g >= 1), y_2=int(d.pts >= 2),
                                 p_sog2=p.get("p_sog2"), p_sog3=p.get("p_sog3"), exp_sog=p.get("exp_sog"),
                                 sog=int(d.sog) if "sog" in d and not pd.isna(d.sog) else None))
            unpriced = [i for i in dressed.index if i not in priced]
            lineup += [dict(tag="unpriced", dressed=True) for _ in unpriced]
            gm = games.loc[gid]
            st = gg[(gg.game_id == gid) & gg.starter].set_index("team").player_id
            for side in ("away", "home"):
                team = g[side]
                if team in st.index and g.get(f"{side}_goalie"):
                    goalies.append(dict(src=g.get(f"{side}_goalie_src") or "model", hit=int(st[team]) == int(g[f"{side}_goalie"])))
            tot = int(gm.home_score + gm.away_score)
            mk = g.get("market") or {}
            grows.append(dict(date=day, total=g["total"], actual=tot, p_home=win_home(g["away_xg"], g["home_xg"]),
                              home_won=int(gm.home_score > gm.away_score), m_total=mk.get("implied_total"),
                              line=mk.get("total"), m_p_over=mk.get("p_over"), p_over=mk.get("model_p_over"),
                              m_p_home=mk.get("p_home")))
    if not rows:
        return dict(nights=0, games=0)
    P, G, L, Q = pd.DataFrame(rows), pd.DataFrame(grows), pd.DataFrame(lineup), pd.DataFrame(goalies)
    nights = P.groupby("date").apply(lambda x: ll(x.y_goal, x.base_g) - ll(x.y_goal, x.p_goal), include_groups=False)
    cal = P.assign(b=pd.cut(P.p_goal, [0, .1, .2, .3, .4, 1])).groupby("b", observed=True) \
           .agg(n=("y_goal", "size"), pred=("p_goal", "mean"), act=("y_goal", "mean"))
    lu = {t: dict(priced=int((L.tag == t).sum()), dressed=int(L[(L.tag == t)].dressed.sum())) for t in ("last", "recent", "returning")}
    return dict(
        first=str(P.date.min()), last=str(P.date.max()), nights=int(P.date.nunique()), games=int(len(G)),
        player_games=int(len(P)),
        goal=dict(pred=round(float(P.p_goal.sum()), 1), act=int(P.y_goal.sum()), ll=round(ll(P.y_goal, P.p_goal), 4),
                  ll_base=round(ll(P.y_goal, P.base_g), 4), nights_beat=int((nights > 0).sum()),
                  cal=[dict(n=int(r.n), pred=round(float(r.pred), 3), act=round(float(r.act), 3)) for r in cal.itertuples()]),
        pts=dict(pred=round(float(P.p_2pts.sum()), 1), act=int(P.y_2.sum()), ll=round(ll(P.y_2, P.p_2pts), 4),
                 ll_base=round(ll(P.y_2, P.base_2), 4)),
        **tails(P), **shots(P),
        lineup=dict(lu, unpriced=int((L.tag == "unpriced").sum())),
        goalies=dict(n=int(len(Q)), hits=int(Q.hit.sum()) if len(Q) else 0,
                     espn_n=int((Q.src == "espn").sum()) if len(Q) else 0,
                     espn_hits=int(Q[Q.src == "espn"].hit.sum()) if len(Q) else 0),
        totals=dict(mae=round(float((G.total - G.actual).abs().mean()), 2), mean_pred=round(float(G.total.mean()), 2),
                    mean_act=round(float(G.actual.mean()), 2)),
        winners=dict(brier=round(float(((G.p_home - G.home_won) ** 2).mean()), 3),
                     fav_won=int(((G.p_home > .5) == (G.home_won == 1)).sum())),
        market=market_grade(G),
    )


def tails(P):
    """1+ and 3+ points, graded only where the archive has them (added Oct 16, 2026)."""
    q = P.dropna(subset=["p_1pt", "p_3pts"]) if "p_1pt" in P else P.iloc[0:0]
    if q.empty:
        return {}
    return dict(pts1=dict(pred=round(float(q.p_1pt.sum()), 1), act=int(q.y_1.sum()), ll=round(ll(q.y_1, q.p_1pt), 4)),
                pts3=dict(pred=round(float(q.p_3pts.sum()), 1), act=int(q.y_3.sum()), ll=round(ll(q.y_3, q.p_3pts), 4)))


def shots(P):
    """2+ and 3+ shots on goal, graded where the archive has them (added Oct 18, 2026)."""
    q = P.dropna(subset=["p_sog2", "sog"]) if "p_sog2" in P else P.iloc[0:0]
    if q.empty:
        return {}
    y2, y3 = (q.sog >= 2).astype(int), (q.sog >= 3).astype(int)
    return dict(sog=dict(n=int(len(q)), exp=round(float(q.exp_sog.sum()), 1), act=int(q.sog.sum()),
                         p2=round(float(q.p_sog2.sum()), 1), act2=int(y2.sum()), ll2=round(ll(y2, q.p_sog2), 4),
                         p3=round(float(q.p_sog3.sum()), 1), act3=int(y3.sum()), ll3=round(ll(y3, q.p_sog3), 4)))


def market_grade(G):
    """The model against DraftKings' lines (from the NHL API) on the games where both exist."""
    m = G.dropna(subset=["m_total", "m_p_home", "m_p_over", "p_over"]) if "m_total" in G else G.iloc[0:0]
    if m.empty:
        return dict(games=0)
    over = (m.actual > m.line).astype(int)
    push = m.actual == m.line
    o = m[~push]
    return dict(games=int(len(m)),
                total_mae_model=round(float((m.total - m.actual).abs().mean()), 2),
                total_mae_market=round(float((m.m_total - m.actual).abs().mean()), 2),
                over_ll_model=round(ll(over[~push], o.p_over), 4), over_ll_market=round(ll(over[~push], o.m_p_over), 4),
                win_brier_model=round(float(((m.p_home - m.home_won) ** 2).mean()), 4),
                win_brier_market=round(float(((m.m_p_home - m.home_won) ** 2).mean()), 4))


if __name__ == "__main__":
    print(json.dumps(track(M.load(M.CUR)), indent=1))
