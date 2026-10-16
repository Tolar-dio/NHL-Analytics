"""Rebuild site/static/backtest_20252026.json (the Trust page's season backtest) from the walk-forward run.

    python analysis/models.py season-backtest 20252026     # writes bt_players.csv / bt_totals.csv
    python analysis/backtest_static.py 20252026
"""
import json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from models import logloss  # noqa: E402

GOAL_BINS = [0, .05, .1, .15, .2, .25, .3, .35, .4, 1]
PTS_BINS = [0, .03, .06, .1, .15, .2, .25, .3, .4, 1]


def cal(P, col, y, bins):
    g = P.assign(b=pd.cut(P[col], bins)).groupby("b", observed=True).agg(n=(y, "size"), pred=(col, "mean"), act=(y, "mean"))
    return [dict(n=int(r.n), pred=round(float(r.pred), 4), act=round(float(r.act), 4)) for r in g.itertuples()]


def main(season):
    d = os.path.join(ROOT, "analysis", "output", season)
    P, T = pd.read_csv(os.path.join(d, "bt_players.csv")), pd.read_csv(os.path.join(d, "bt_totals.csv"))
    P["y_1"], P["y_3"] = (P.y_pts >= 1).astype(int), (P.y_pts >= 3).astype(int)
    P["month"], T["month"] = P.date.str[:7], T.date.str[:7]
    months = []
    for m, q in P.groupby("month"):
        t = T[T.month == m]
        months.append(dict(month=m, goal_gain=round(logloss(q.y_goal, q.base_g) - logloss(q.y_goal, q.p_goal), 4),
                           pts_gain=round(logloss(q.y_2, q.base_2) - logloss(q.y_2, q.p_2pts), 4),
                           tot_corr=round(float(np.corrcoef(t.pred, t.actual)[0, 1]), 3) if len(t) > 2 else None, games=int(len(t))))
    out = dict(season=f"{season[:4]}-{season[6:]}", games=int(len(T)), player_games=int(len(P)),
               goal=dict(pred=int(round(P.p_goal.sum())), act=int(P.y_goal.sum()), ll=round(logloss(P.y_goal, P.p_goal), 4),
                         ll_base=round(logloss(P.y_goal, P.base_g), 4), cal=cal(P, "p_goal", "y_goal", GOAL_BINS)),
               pts=dict(pred=int(round(P.p_2pts.sum())), act=int(P.y_2.sum()), ll=round(logloss(P.y_2, P.p_2pts), 4),
                        ll_base=round(logloss(P.y_2, P.base_2), 4), cal=cal(P, "p_2pts", "y_2", PTS_BINS)),
               pts1=dict(pred=int(round(P.p_1pt.sum())), act=int(P.y_1.sum()), ll=round(logloss(P.y_1, P.p_1pt), 4)),
               pts3=dict(pred=int(round(P.p_3pts.sum())), act=int(P.y_3.sum()), ll=round(logloss(P.y_3, P.p_3pts), 4)),
               totals=dict(rmse=round(float(np.sqrt(((T.pred - T.actual) ** 2).mean())), 3),
                           rmse_base=round(float(np.sqrt(((T.base - T.actual) ** 2).mean())), 3),
                           corr=round(float(np.corrcoef(T.pred, T.actual)[0, 1]), 3)),
               months=months)
    path = os.path.join(ROOT, "site", "static", f"backtest_{season}.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote {path}: goal {out['goal']['pred']} vs {out['goal']['act']}, 2+ {out['pts']['pred']} vs {out['pts']['act']}, "
          f"1+ {out['pts1']['pred']} vs {out['pts1']['act']}, 3+ {out['pts3']['pred']} vs {out['pts3']['act']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "20252026")
