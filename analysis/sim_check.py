"""Walk-forward test of the game simulator against the separate models (Nov 2026).

For every 2026-27 regular-season game (from Oct 20, once teams have recent lineups), price the game two ways
using only games before it:

  separate models: the props model (models.run_backtest, with last season's priors) for goals and points,
                   sog.py, blocks.py and saves.py for shots, blocks and saves, ratings.py for winners and totals
  simulator:       sim.py, its team levels calibrated to the same ratings and expected shots

Both use the real lineups and starting goalies (as the backtest always has). Scores: log loss and calibration
per market, plus the thing only the simulator can do: whether teammates' outcomes move together the way it says.

Usage: python analysis/sim_check.py [n_sims] [first_date] [last_date]
"""
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models as M  # noqa: E402
import ratings as RT  # noqa: E402
import saves as SV  # noqa: E402
import sim as SIM  # noqa: E402
import sog as SOG  # noqa: E402
import blocks as BLK  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = os.path.join(ROOT, "analysis", "output")
NS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 800
FIRST = sys.argv[2] if len(sys.argv) > 2 else "2026-10-20"
LAST = sys.argv[3] if len(sys.argv) > 3 else "2099-01-01"
OUT = os.path.join(O, "sim_check")


def main():
    os.makedirs(OUT, exist_ok=True)
    P = SIM.params()
    cur, prev = M.load(M.CUR), M.load(M.PREV)
    pri = M.build_prev_priors(prev)
    pg26, pg25 = pd.read_csv(os.path.join(O, M.CUR, "player_games.csv")), pd.read_csv(os.path.join(O, M.PREV, "player_games.csv"))
    tg26, tg25 = pd.read_csv(os.path.join(O, M.CUR, "team_games.csv")), pd.read_csv(os.path.join(O, M.PREV, "team_games.csv"))
    gg26, gg25 = pd.read_csv(os.path.join(O, M.CUR, "goalie_games.csv")), pd.read_csv(os.path.join(O, M.PREV, "goalie_games.csv"))
    ctx26, ctx25 = pd.read_csv(os.path.join(O, M.CUR, "context_games.csv")), pd.read_csv(os.path.join(O, M.PREV, "context_games.csv"))
    games = pd.read_csv(os.path.join(ROOT, "data", "tables", M.CUR, "games.csv.gz"))
    games = games[(games.game_type == "regular") & (games.date >= FIRST) & (games.date <= LAST)]
    Rr, _, _ = RT.run([M.PREV, M.CUR])
    mu = Rr.set_index("game_id")[["mu_h", "mu_a"]]
    tired = M.back_to_back(cur["games"])
    prow, grow, pair_rows = [], [], []
    t0 = time.time()
    for cut, day in games.groupby("date"):
        try:
            fp = M.fit_players(cur, cut, pri)
        except Exception:
            continue
        rosters = {t: g.player_id.tolist() for t, g in cur["pg"][cur["pg"].date == cut].groupby("team")}
        tm = M.fit_teams(cur, cut, fp, pri, M.K, rosters)
        rates, pos_avg = SIM.player_rates(pg26, pg25, cut, ctx_cur=ctx26, ctx_prev=ctx25)
        st = cur["gg"][(cur["gg"].date == cut) & cur["gg"].starter].set_index(["game_id", "team"]).player_id
        fin = fp["fin"].to_dict() if "fin" in fp else None
        # separate models' player prices (props model, then shots and blocks on its projected minutes)
        dpg = cur["pg"][(cur["pg"].date == cut) & (cur["pg"].game_type == "regular")]
        rows = dpg[["game_id", "player_id", "team", "opp"]].copy()
        rows["opp_goalie"] = [st.get((g, o)) for g, o in zip(rows.game_id, rows.opp)]
        rows["b2b"] = [tired.get((g, t), False) for g, t in zip(rows.game_id, rows.team)]
        rows["opp_b2b"] = [tired.get((g, o), False) for g, o in zip(rows.game_id, rows.opp)]
        hm = cur["games"].set_index("game_id").home
        rows["home"] = [hm.get(g) == t for g, t in zip(rows.game_id, rows.team)]
        sep = M.price_players(rows.set_index("player_id"), fp, tm).reset_index()
        sep = SOG.prices(sep, pg26, pg25, cut)
        sep = BLK.prices(sep, pg26, pg25, tg26, cut)
        sep = sep.set_index(["game_id", "player_id"])
        for g in day.itertuples():
            gid = g.game_id
            if gid not in mu.index:
                continue
            dh, da = set(dpg[(dpg.game_id == gid) & (dpg.team == g.home)].player_id), set(dpg[(dpg.game_id == gid) & (dpg.team == g.away)].player_id)
            try:
                uh, ua = SIM.units(ctx26, g.home, dh, cut), SIM.units(ctx26, g.away, da, cut)
                if len(uh["lines"]) < 4 or len(ua["lines"]) < 4 or len(uh["pairs"]) < 3 or len(ua["pairs"]) < 3:
                    continue
            except Exception:
                continue
            ta, th = tired.get((gid, g.away), False), tired.get((gid, g.home), False)
            gh_st, ga_st = st.get((gid, g.home)), st.get((gid, g.away))
            lh = mu.loc[gid, "mu_h"] * M.goalie_factor(tm, g.away, ga_st) * M.b2b_factor(th, ta)
            la = mu.loc[gid, "mu_a"] * M.goalie_factor(tm, g.home, gh_st) * M.b2b_factor(ta, th)
            sv = SV.prices(pd.DataFrame([dict(team=g.home, opp=g.away, home=True, goalie_id=gh_st), dict(team=g.away, opp=g.home, home=False, goalie_id=ga_st)]),
                           tg26, gg26, tg25, gg25, cut)
            sog_h, sog_a = float(sv.exp_sa.iloc[1]) / SV.SCALE, float(sv.exp_sa.iloc[0]) / SV.SCALE   # home shots = away goalie's shots faced
            G = SIM.Game(g.home, g.away, uh, ua, rates, pos_avg, fin)
            tg_p = {pid: dict(g=float(sep.loc[(gid, pid)].lam_g), pts=float(sep.loc[(gid, pid)].lam_p),
                              sog=float(sep.loc[(gid, pid)].exp_sog), blk=float(sep.loc[(gid, pid)].exp_blk))
                    for pid in G.ids if (gid, pid) in sep.index}
            SIM.calibrate(G, P, (lh, la), (sog_h, sog_a), n=300, rounds=3, players=tg_p)
            out = SIM.simulate(G, P, NS, seed=gid % 100000)
            pts = out["g"] + out["a"]
            yg = (g.home_score > g.away_score)
            sc = out["score"]
            tot = sc.sum(1) + out["tied"]          # a shootout winner adds one graded goal
            grow.append(dict(game_id=gid, date=cut, home=g.home, away=g.away, y_home=int(yg), y_total=int(g.home_score + g.away_score),
                             sim_p_home=float((out["winner"] == 0).mean()), sim_total=float(tot.mean()),
                             sim_o55=float((tot >= 6).mean()), sim_o65=float((tot >= 7).mean()), sim_ot=float(out["tied"].mean() + ((sc[:, 0] == sc[:, 1]) & False).mean()),
                             rt_p_home=float(RT.win_prob(la, lh)), la=la, lh=lh,
                             sim_sv_h=float(out["saves"][:, 0].mean()), sim_sv_a=float(out["saves"][:, 1].mean()),
                             sep_sv_h=float(sv.exp_saves.iloc[0]), sep_sv_a=float(sv.exp_saves.iloc[1]),
                             # the assumption scorecard: what the simulated games look like, to compare with real ones
                             sc_ot=float(out["went_ot"].mean()), sc_so=float(out["tied"].mean()), sc_en=float(out["en_goals"].sum(1).mean()),
                             sc_ppg=float(out["pp_goals"].sum(1).mean()), sc_ppo=float(out["pp_opps"].sum(1).mean()),
                             sc_1goal=float((np.abs(sc[:, 0] - sc[:, 1]) == 1).mean()), sc_3plus=float((np.abs(sc[:, 0] - sc[:, 1]) >= 3).mean()),
                             sc_blk=float(out["blocked"].sum(1).mean()), sc_att=float(out["attempts"].sum(1).mean())))
            # linemates: joint chance two forwards on the same line both get a point, vs independence
            for t, u in ((0, uh), (1, ua)):
                for line in u["lines"][:3]:
                    for a_, b_ in ((line[0], line[1]), (line[0], line[2]), (line[1], line[2])):
                        i, k_ = G.ix[a_], G.ix[b_]
                        pa, pb_ = pts[:, i] >= 1, pts[:, k_] >= 1
                        pair_rows.append(dict(game_id=gid, a=a_, b=b_, p_a=pa.mean(), p_b=pb_.mean(), p_both=(pa & pb_).mean()))
            for p, i in G.ix.items():
                if (gid, p) not in sep.index:
                    continue
                s = sep.loc[(gid, p)]
                prow.append(dict(game_id=gid, date=cut, player_id=p, pos=s.get("pos"),
                                 sim_g1=(out["g"][:, i] >= 1).mean(), sim_p1=(pts[:, i] >= 1).mean(), sim_p2=(pts[:, i] >= 2).mean(), sim_p3=(pts[:, i] >= 3).mean(),
                                 sim_s2=(out["s"][:, i] >= 2).mean(), sim_s3=(out["s"][:, i] >= 3).mean(), sim_s4=(out["s"][:, i] >= 4).mean(),
                                 sim_b1=(out["b"][:, i] >= 1).mean(), sim_b2=(out["b"][:, i] >= 2).mean(),
                                 sep_g1=s.p_goal, sep_p1=s.p_1pt, sep_p2=s.p_2pts, sep_p3=s.p_3pts, sep_s2=s.p_sog2, sep_s3=s.p_sog3, sep_s4=s.p_sog4,
                                 sep_b1=s.p_blk1, sep_b2=s.p_blk2))
        print(f"{cut}: {len(grow)} games, {len(prow)} player-games, {time.time() - t0:.0f}s", flush=True)
        pd.DataFrame(prow).to_csv(os.path.join(OUT, "players.csv"), index=False)
        pd.DataFrame(grow).to_csv(os.path.join(OUT, "games.csv"), index=False)
        pd.DataFrame(pair_rows).to_csv(os.path.join(OUT, "pairs.csv"), index=False)


def scorecard(Gg, j=None):
    """Simulated vs real: overtime, empty-net goals, power plays, margins, blocks and attempts per game."""
    ids = set(Gg.game_id)
    ev = pd.read_csv(os.path.join(ROOT, "data", "tables", M.CUR, "events.csv.gz"), low_memory=False)
    ev = ev[ev.game_id.isin(ids)]
    c = ev.situation_code.astype(str).str.zfill(4)
    goals = ev[(ev.event == "goal") & (ev.period_type != "SO")]
    gc = c[goals.index]
    home = goals.team == goals.home_team
    en = np.where(home, gc.str[0] == "0", gc.str[3] == "0")
    own = np.where(home, gc.str[2], gc.str[1]).astype(int)
    opp = np.where(home, gc.str[1], gc.str[2]).astype(int)
    own_g = np.where(home, gc.str[3] == "1", gc.str[0] == "1")
    pp = (own > opp) & ~en & own_g          # a delayed-penalty six-on-five isn't a power play
    per_game = lambda m: pd.Series(m, index=goals.index).groupby(goals.game_id).sum().reindex(list(ids)).fillna(0)
    ot = ev[ev.period_type.isin(["OT", "SO"])].game_id.unique()
    pens = ev[(ev.event == "penalty") & ev.penalty_minutes.isin([2, 4])].groupby("game_id").size().reindex(list(ids)).fillna(0)
    att = ev[ev.event.isin(ATT_EV)].groupby("game_id").size().reindex(list(ids)).fillna(0)
    blk = ev[ev.event == "blocked-shot"].groupby("game_id").size().reindex(list(ids)).fillna(0)
    g = pd.read_csv(os.path.join(ROOT, "data", "tables", M.CUR, "games.csv.gz")).set_index("game_id")
    gm = g.loc[list(ids)]
    margin = (gm.home_score - gm.away_score).abs()
    so = ev[ev.period_type == "SO"].game_id.unique()
    rows = [("Games that reach overtime", Gg.sc_ot.mean(), np.isin(list(ids), ot).mean(), "share"),
            ("Games decided in a shootout", Gg.sc_so.mean(), np.isin(list(ids), so).mean(), "share"),
            ("Empty-net goals a game", Gg.sc_en.mean(), per_game(en).mean(), "per game"),
            ("Power-play goals a game", Gg.sc_ppg.mean(), per_game(pp).mean(), "per game"),
            ("Minor penalties a game", Gg.sc_ppo.mean(), pens.mean(), "per game"),
            ("One-goal games", Gg.sc_1goal.mean(), (margin == 1).mean(), "share"),
            ("Games decided by 3+", Gg.sc_3plus.mean(), (margin >= 3).mean(), "share"),
            ("Shot attempts a game", Gg.sc_att.mean(), att.mean(), "per game"),
            ("Blocked shots a game", Gg.sc_blk.mean(), blk.mean(), "per game")]
    return pd.DataFrame(rows, columns=["assumption", "simulated", "actual", "unit"]).round(3)


ATT_EV = ["shot-on-goal", "missed-shot", "blocked-shot", "goal"]


def report():
    """Score the simulator against the separate models on the games the test has finished."""
    Pp = pd.read_csv(os.path.join(OUT, "players.csv"))
    Gg = pd.read_csv(os.path.join(OUT, "games.csv"))
    pg = pd.read_csv(os.path.join(O, M.CUR, "player_games.csv")).set_index(["game_id", "player_id"])
    j = Pp.join(pg[["g", "pts", "box_sog", "blk"]], on=["game_id", "player_id"]).dropna(subset=["g"])
    ll = lambda y, p: float(-np.mean(y * np.log(np.clip(p, 1e-4, 1 - 1e-4)) + (1 - y) * np.log(np.clip(1 - p, 1e-4, 1 - 1e-4))))
    print(f"{len(Gg)} games, {len(j)} player-games")
    for key, y in (("g1", j.g >= 1), ("p1", j.pts >= 1), ("p2", j.pts >= 2), ("p3", j.pts >= 3), ("s2", j.box_sog >= 2),
                   ("s3", j.box_sog >= 3), ("s4", j.box_sog >= 4), ("b1", j.blk >= 1), ("b2", j.blk >= 2)):
        y = y.astype(int)
        a, b = j["sim_" + key], j["sep_" + key]
        d = (lambda p: -(y * np.log(np.clip(p, 1e-4, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-4, 1))))
        diff = d(b) - d(a)
        t = diff.mean() / (diff.std() / np.sqrt(len(diff)))
        print(f"  {key}: actual {y.mean():.3f} | sim {a.mean():.3f} ll {ll(y, a):.5f} | separate {b.mean():.3f} ll {ll(y, b):.5f} | sim better by {diff.mean():+.5f} (t {t:+.1f})")
    # stars and depth: points calibration by the separate model's 1+ point chance
    j["band"] = pd.cut(j.sep_p1, [0, 0.3, 0.45, 0.6, 0.75, 1])
    print(j.groupby("band", observed=True).apply(lambda d: pd.Series(dict(n=len(d), actual=(d.pts >= 1).mean(), sim=d.sim_p1.mean(), sep=d.sep_p1.mean()))).round(3).to_string())
    y = Gg.y_home
    print(f"  winner: sim ll {ll(y, Gg.sim_p_home):.5f} | ratings ll {ll(y, Gg.rt_p_home):.5f}; sim home win {Gg.sim_p_home.mean():.3f} vs actual {y.mean():.3f}")
    print(f"  totals: sim mean {Gg.sim_total.mean():.2f} vs actual {Gg.y_total.mean():.2f}; corr sim {np.corrcoef(Gg.sim_total, Gg.y_total)[0, 1]:.3f}, "
          f"ratings {np.corrcoef(Gg.la + Gg.lh, Gg.y_total)[0, 1]:.3f}; over 5.5 sim {Gg.sim_o55.mean():.3f} actual {(Gg.y_total >= 6).mean():.3f}; "
          f"over 6.5 sim {Gg.sim_o65.mean():.3f} actual {(Gg.y_total >= 7).mean():.3f}")
    gg = pd.read_csv(os.path.join(O, M.CUR, "goalie_games.csv"))
    st = gg[gg.starter].set_index(["game_id", "team"]).saves
    hs = [st.get((g, t)) for g, t in zip(Gg.game_id, Gg.home)]
    as_ = [st.get((g, t)) for g, t in zip(Gg.game_id, Gg.away)]
    S = pd.DataFrame(dict(act=np.r_[hs, as_], sim=np.r_[Gg.sim_sv_h, Gg.sim_sv_a], sep=np.r_[Gg.sep_sv_h, Gg.sep_sv_a])).dropna()
    print(f"  starter saves: actual {S.act.mean():.2f}; sim {S.sim.mean():.2f} MAE {np.abs(S.sim - S.act).mean():.3f}; separate {S.sep.mean():.2f} MAE {np.abs(S.sep - S.act).mean():.3f}")
    if "sc_ot" in Gg:
        print(scorecard(Gg, j).to_string(index=False))
    pr = os.path.join(OUT, "pairs.csv")
    if os.path.exists(pr):
        Q = pd.read_csv(pr).join(pg[["pts"]].rename(columns={"pts": "ya"}), on=["game_id", "a"]).join(pg[["pts"]].rename(columns={"pts": "yb"}), on=["game_id", "b"]).dropna()
        both = ((Q.ya >= 1) & (Q.yb >= 1)).mean()
        print(f"  linemates both get a point: actual {both:.3f} | simulator joint {Q.p_both.mean():.3f} | if independent {(Q.p_a * Q.p_b).mean():.3f} ({len(Q)} pairs)")


if __name__ == "__main__":
    report() if sys.argv[1:2] == ["report"] else main()
