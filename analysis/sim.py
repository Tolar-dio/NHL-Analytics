"""The game simulator (Nov 2026): one model of a hockey game, played out second by second.

Every number we publish about a game (who wins, how many goals, each skater's goals, points, shots on goal and
blocks, each goalie's saves) used to come from a separate model. Here they all come out of the same simulated
games, so they agree with each other: if a line scores, its players' points rise together; if the game is
expected to be lopsided, the trailing goalie's saves and the empty-net goals follow.

Each simulated game runs 3,600 one-second steps (plus overtime) for N copies at once (numpy, vectorised over
copies). The state of a copy: the clock, the score, who is on the ice for each team (forward line, defense pair,
or power-play / penalty-kill unit), how long the current shift has run, penalty timers, and whether a goalie is
pulled. In each second:

  * each team takes a shot attempt with a rate that depends on strength (5v5, power play, 4v4, 3v3, extra
    attacker), the score (trailing teams push: score effects), home ice, and the team's own rating;
  * an attempt is blocked (a defender on the ice gets the block, in proportion to his block rate), misses, or
    reaches the net; the shooter is one of the attackers on the ice, in proportion to his shot rate;
  * a shot on goal scores with probability = his expected goals per shot x his finishing x the goalie's factor;
    an empty net takes the empty-net scoring rate instead; assists go to on-ice teammates by their assist rates;
  * penalties start power plays; lines change when the shift runs out (lengths and usage from recent games);
  * the trailing team pulls its goalie at the learned time (analysis/winprob.py).

The league-wide rates are measured from both seasons' events (params(), cached in data/derived/sim_params.json).
Player rates come from the props model's fits, team strength from analysis/ratings.py, and each team's shot and
goal levels are scaled so a pilot run reproduces the expected goals and shots the team models say: the simulator
adds structure (who scores, with whom, in which game state), not a second opinion on how good teams are.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASONS = ("20252026", "20262027")
PARAMS_PATH = os.path.join(ROOT, "data", "derived", "sim_params.json")
ATT = ["shot-on-goal", "missed-shot", "blocked-shot", "goal"]


# ------------------------------------------------------------------ league rates

def _states(ev):
    """Per event, from the event team's side: strength label and score difference before the event."""
    is_home = ev.team == ev.home_team
    c = ev.situation_code.astype(str).str.zfill(4)
    own_sk = np.where(is_home, c.str[2], c.str[1]).astype(int)
    opp_sk = np.where(is_home, c.str[1], c.str[2]).astype(int)
    own_g = np.where(is_home, c.str[3], c.str[0]) == "1"
    opp_g = np.where(is_home, c.str[0], c.str[3]) == "1"
    st = np.select([~own_g, ~opp_g, own_sk > opp_sk, own_sk < opp_sk, own_sk == 3, own_sk == 4],
                   ["ea", "ed", "pp", "pk", "3v3", "4v4"], "ev")
    return st, is_home


def params(refit=False):
    if os.path.exists(PARAMS_PATH) and not refit:
        return json.load(open(PARAMS_PATH))
    rows = []
    for S in SEASONS:
        ev = pd.read_csv(os.path.join(ROOT, "data", "tables", S, "events.csv.gz"), low_memory=False)
        ev = ev[(ev.period_type != "SO") & (ev.game_id.astype(str).str[4:6] == "02")].sort_values(["game_id", "sort_order"])
        ev["hs"] = ev.groupby("game_id").home_score.shift(1).groupby(ev.game_id).ffill().fillna(0)
        ev["as_"] = ev.groupby("game_id").away_score.shift(1).groupby(ev.game_id).ffill().fillna(0)
        rows.append(ev)
    ev = pd.concat(rows, ignore_index=True)
    ev = ev[ev.team.notna() | ev.event.isin(["period-start", "period-end"])]
    st, is_home = _states(ev)
    ev["st"], ev["is_home"] = st, is_home
    ev["diff"] = np.clip(np.where(is_home, ev.hs - ev.as_, ev.as_ - ev.hs), -2, 2)
    ngames = ev.game_id.nunique()
    # time spent in each strength state from each team's side, from the situation code over time
    g = ev[["game_id", "period", "game_seconds", "situation_code", "home_team", "away_team", "hs", "as_"]].copy()
    g["dt"] = g.groupby("game_id").game_seconds.shift(-1) - g.game_seconds
    g = g[g.dt.notna() & (g.dt >= 0) & (g.dt < 1300)]
    sec = {}
    for side in ("home", "away"):
        g2 = g.assign(team=g[side + "_team"])
        s2, _ = _states(g2)
        d2 = np.clip(np.where(side == "home", g2.hs - g2.as_, g2.as_ - g2.hs), -2, 2)
        for (a, b), v in pd.DataFrame(dict(st=s2, diff=d2, dt=g2.dt, home=side == "home")).groupby(["st", "diff"]).dt.sum().items():
            sec[(a, int(b))] = sec.get((a, int(b)), 0) + v
    att = ev[ev.event.isin(ATT)]
    rate = {}
    for (a, b), n in att.groupby(["st", "diff"]).size().items():
        if sec.get((a, int(b)), 0) > 600:
            rate[f"{a}|{int(b)}"] = n / sec[(a, int(b))]
    unb = att[att.event != "blocked-shot"]
    p_block = (att.groupby("st").event.apply(lambda e: (e == "blocked-shot").mean())).to_dict()
    p_net = (unb.groupby("st").event.apply(lambda e: e.isin(["shot-on-goal", "goal"]).mean())).to_dict()
    goals = ev[ev.event == "goal"]
    nast = goals.player2_id.notna().astype(int) + goals.player3_id.notna().astype(int)
    p_ast = nast.value_counts(normalize=True).sort_index().reindex([0, 1, 2]).fillna(0).tolist()
    home_att = att.is_home.mean() * 2 - 1          # share above 50% of attempts by home teams
    pens = ev[(ev.event == "penalty") & ev.penalty_minutes.isin([2, 4])]
    pen_rate = len(pens) / (ngames * 2 * 3600)
    sh = pd.concat([pd.read_csv(os.path.join(ROOT, "data", "tables", S, "shifts.csv.gz"), usecols=["game_id", "player_id", "start_sec", "end_sec"]) for S in SEASONS])
    sh["len"] = sh.end_sec - sh.start_sec
    sh = sh[(sh.len > 5) & (sh.len < 180)]
    p = dict(rate=rate, p_block=p_block, p_net=p_net, p_ast=p_ast, home_att=float(home_att), pen_rate=float(pen_rate),
             pp4_share=float((pens.penalty_minutes == 4).mean()), shift_mean=float(sh.len.mean()),
             wp=json.load(open(os.path.join(ROOT, "data", "derived", "winprob.json"))))
    os.makedirs(os.path.dirname(PARAMS_PATH), exist_ok=True)
    json.dump(p, open(PARAMS_PATH, "w"), indent=1)
    return p


if __name__ == "__main__" and sys.argv[1:2] == ["params"]:
    p = params(refit=True)
    print(json.dumps({k: v for k, v in p.items() if k != "wp"}, indent=1)[:2500])


# ------------------------------------------------------------------ lineups and player rates

def units(ctx, team, dressed, before, n_games=3):
    """Lines, pairs and special-teams units for a team from its last few games (context_games.csv), limited to
    tonight's dressed skaters. Returns dict of lists of player-id tuples and their usage weights."""
    c = ctx[(ctx.team == team) & (ctx.date < before) & ctx.player_id.isin(dressed)]
    last = sorted(c.game_id.unique())[-n_games:]
    c = c[c.game_id.isin(last)]
    agg = c.groupby("player_id").agg(toi5=("toi5", "mean"), toipp=("toipp", "mean"), toipk=("toipk", "mean"), pos=("pos", "last"))
    newest = c[c.game_id == (last[-1] if last else None)].set_index("player_id")
    pos = {p: agg.pos.get(p) for p in dressed}
    for p in dressed:          # skaters with no recent games: depth by default
        if p not in agg.index:
            agg.loc[p] = dict(toi5=6.0, toipp=0.0, toipk=0.0, pos=None)
    F = [p for p in agg.sort_values("toi5", ascending=False).index if pos.get(p, agg.pos.get(p)) != "D"]
    D = [p for p in agg.sort_values("toi5", ascending=False).index if pos.get(p, agg.pos.get(p)) == "D"]
    lines, used = [], set()
    for p in F:
        if p in used or len(lines) == 4:
            continue
        line = [p]
        for m in ("mate1", "mate2"):
            q = newest[m].get(p) if p in newest.index and m in newest else None
            if q is not None and not pd.isna(q) and int(q) in F and int(q) not in used and int(q) not in line:
                line.append(int(q))
        for q in F:
            if len(line) == 3:
                break
            if q not in used and q not in line:
                line.append(q)
        if len(line) == 3:
            lines.append(tuple(line)); used.update(line)
    pairs, usedd = [], set()
    for p in D:
        if p in usedd or len(pairs) == 3:
            continue
        q = newest["dmate"].get(p) if p in newest.index and "dmate" in newest else None
        mate = int(q) if q is not None and not pd.isna(q) and int(q) in D and int(q) not in usedd and int(q) != p else next((x for x in D if x not in usedd and x != p), None)
        if mate is None:
            break
        pairs.append((p, mate)); usedd.update((p, mate))
    wl = np.array([agg.toi5.reindex(list(l)).sum() for l in lines]) + 1e-6
    wp = np.array([agg.toi5.reindex(list(l)).sum() for l in pairs]) + 1e-6
    ppo = list(agg.sort_values("toipp", ascending=False).index)
    pp = [tuple(ppo[0:5]), tuple(ppo[5:10])] if len(ppo) >= 10 else [tuple(ppo[0:5])] * 2
    wpp = np.array([agg.toipp.reindex(list(pp[0])).sum(), agg.toipp.reindex(list(pp[1])).sum()]) + 1e-6
    pkF = [p for p in agg.sort_values("toipk", ascending=False).index if p in F][:4]
    pkD = [p for p in agg.sort_values("toipk", ascending=False).index if p in D][:4]
    pk = [tuple(pkF[0:2] + pkD[0:2]), tuple(pkF[2:4] + pkD[2:4])] if len(pkF) >= 4 and len(pkD) >= 4 else [tuple((F[:2] + D[:2]))] * 2
    ot = [(lines[0][0], lines[0][1], pairs[0][0]), (lines[1][0], lines[1][1], pairs[0][1]),
          (lines[0][2], lines[1][2], pairs[1][0] if len(pairs) > 1 else pairs[0][0])] if len(lines) >= 2 and pairs else None
    return dict(lines=lines, wl=wl / wl.sum(), pairs=pairs, wp=wp / wp.sum(), pp=pp, wpp=wpp / wpp.sum(), pk=pk, ot=ot)


def player_rates(pg_cur, pg_prev, before, k=dict(att=150, xgs=40, net=60, ast=150, blk=250, oxf=150), ctx_cur=None, ctx_prev=None):
    """Per skater: unblocked shot rate weight, xG per unblocked shot, on-net share, assist and block rates,
    this season (before the date) blended with last season at half weight, shrunk toward the position."""
    cur = pg_cur[(pg_cur.date < before) & (pg_cur.game_id.astype(str).str[4:6] == "02")]
    prv = pg_prev[pg_prev.game_id.astype(str).str[4:6] == "02"] if pg_prev is not None else cur.iloc[0:0]
    cols = ["toi", "ush", "sog", "ixg", "a1", "a2", "blk"]
    a = cur.groupby("player_id")[cols].sum().add(prv.groupby("player_id")[cols].sum() * 0.5, fill_value=0)
    pos = pd.concat([prv.groupby("player_id").pos.last(), cur.groupby("player_id").pos.last()])
    a["pos"] = pos[~pos.index.duplicated(keep="last")].reindex(a.index)
    lg = pd.concat([cur, prv]).groupby("pos")[cols].sum()
    out = pd.DataFrame(index=a.index)
    P = a.pos.fillna("F")
    def shr(num, den, K, lg_rate):
        return (a[num] + K * P.map(lg_rate)) / (a[den] + K)
    out["att60"] = shr("ush", "toi", k["att"], lg.ush / lg.toi) * 60
    out["xgs"] = shr("ixg", "ush", k["xgs"], lg.ixg / lg.ush)
    out["net"] = shr("sog", "ush", k["net"], lg.sog / lg.ush)
    out["a160"] = shr("a1", "toi", k["ast"], lg.a1 / lg.toi) * 60
    out["a260"] = shr("a2", "toi", k["ast"], lg.a2 / lg.toi) * 60
    out["blk60"] = shr("blk", "toi", k["blk"], lg.blk / lg.toi) * 60
    # on-ice expected goals for per 60 away from the power play (how much his line generates), from the lineup context
    if ctx_cur is not None:
        cc = ctx_cur[(ctx_cur.date < before) & (ctx_cur.game_type == "regular")]
        cx = cc.merge(pg_cur[["game_id", "player_id", "toi"]], on=["game_id", "player_id"])
        o = cx.groupby("player_id").apply(lambda d: pd.Series(dict(x=d.xgf_np.sum(), t=(d.toi - d.toipp).sum())))
        if ctx_prev is not None:
            px = ctx_prev[ctx_prev.game_type == "regular"].merge(pg_prev[["game_id", "player_id", "toi"]], on=["game_id", "player_id"])
            op = px.groupby("player_id").apply(lambda d: pd.Series(dict(x=d.xgf_np.sum(), t=(d.toi - d.toipp).sum()))) * 0.5
            o = o.add(op, fill_value=0)
        lgx = o.x.sum() / o.t.sum()
        out["oxf"] = ((o.x + k["oxf"] * lgx) / (o.t + k["oxf"]) / lgx).reindex(out.index).fillna(1.0)
    else:
        out["oxf"] = 1.0
    out["pos"] = P
    return out, {p: dict(att60=float(lg.loc[p].ush / lg.loc[p].toi * 60), xgs=float(lg.loc[p].ixg / lg.loc[p].ush),
                         net=float(lg.loc[p].sog / lg.loc[p].ush), a160=float(lg.loc[p].a1 / lg.loc[p].toi * 60),
                         a260=float(lg.loc[p].a2 / lg.loc[p].toi * 60), blk60=float(lg.loc[p].blk / lg.loc[p].toi * 60), oxf=1.0) for p in lg.index}


# ------------------------------------------------------------------ the simulation

class Game:
    """Inputs for one game. sides: {'home': {...}, 'away': {...}} each with units() output, rates (DataFrame
    indexed by player id), fin (dict id -> finishing factor), m_att and m_g (team multipliers)."""
    def __init__(self, home, away, uh, ua, rates, pos_avg, fin=None):
        self.ids = sorted(set(sum([list(x) for x in uh["lines"] + uh["pairs"] + ua["lines"] + ua["pairs"] + uh["pp"] + ua["pp"] + uh["pk"] + ua["pk"]], [])))
        self.ix = {p: i for i, p in enumerate(self.ids)}
        self.team = {}
        for p in sum([list(x) for x in uh["lines"] + uh["pairs"] + uh["pp"] + uh["pk"]], []):
            self.team[p] = 0
        for p in sum([list(x) for x in ua["lines"] + ua["pairs"] + ua["pp"] + ua["pk"]], []):
            self.team[p] = 1
        R = rates.reindex(self.ids)
        for c in ("att60", "xgs", "net", "a160", "a260", "blk60", "oxf"):
            R[c] = R[c].fillna(pd.Series({p: pos_avg.get(R.pos.get(p) if isinstance(R.pos.get(p), str) else "F", pos_avg["F"])[c] for p in self.ids}))
        self.w_att, self.xgs, self.net = (R.att60.to_numpy(float).copy(), R.xgs.to_numpy(float).copy(), R.net.to_numpy(float).copy())
        self.w_a1, self.w_a2, self.w_blk = (R.a160.to_numpy(float) + 1e-6, R.a260.to_numpy(float) + 1e-6, R.blk60.to_numpy(float) + 1e-6)
        self.fin = np.array([(fin or {}).get(p, 1.0) for p in self.ids])
        self.oxf = np.append(R.oxf.to_numpy(float), np.nan)        # index -1 (an empty slot) reads as missing
        self.u = [uh, ua]
        self.names = (home, away)
        self.m_att = np.array([1.0, 1.0])
        self.m_g = np.array([1.0, 1.0])

    def arr(self, tuples):
        return np.array([[self.ix[p] for p in t] for t in tuples])


def _choose(rng, A, w):
    """Row-wise weighted choice of a column of A (player indices, -1 = empty) by weights w[player]."""
    W = np.where(A >= 0, w[np.maximum(A, 0)], 0.0)
    c = W.cumsum(1)
    u = rng.random(len(A)) * c[:, -1]
    j = (c < u[:, None]).sum(1)
    return A[np.arange(len(A)), np.minimum(j, A.shape[1] - 1)]


def simulate(G, P, n=1000, seed=0):
    """Play n copies of game G (home = team 0). Returns arrays: score (n,2), winner (n,), tied after OT (n,),
    per-player goals g, assists a, shots on goal s, blocks b (n, players), and per team the saves and shots
    faced by its goalie (n,2; empty-net shots excluded)."""
    rng = np.random.default_rng(seed)
    rate, pb, pn = P["rate"], P["p_block"], P["p_net"]
    pull = {1: P["wp"]["pull"]["1"], 2: P["wp"]["pull"]["2"]}
    NP = len(G.ids)
    st = dict(g=np.zeros((n, NP), np.int16), a=np.zeros((n, NP), np.int16), s=np.zeros((n, NP), np.int16), b=np.zeros((n, NP), np.int16))
    score = np.zeros((n, 2), np.int16)
    sa, ga = np.zeros((n, 2), np.int16), np.zeros((n, 2), np.int16)
    eng, ppg, ppo = np.zeros((n, 2), np.int16), np.zeros((n, 2), np.int16), np.zeros((n, 2), np.int16)   # for the scorecard
    att_n, blk_n = np.zeros((n, 2), np.int32), np.zeros((n, 2), np.int32)
    pad = lambda X, w: np.c_[X, -np.ones((len(X), w - X.shape[1]), int)]
    L = [G.arr(G.u[t]["lines"]) for t in (0, 1)]
    D = [G.arr(G.u[t]["pairs"]) for t in (0, 1)]
    PPu = [pad(G.arr(G.u[t]["pp"]), 6) for t in (0, 1)]
    PKu = [pad(G.arr(G.u[t]["pk"]), 6) for t in (0, 1)]
    OTu = [pad(G.arr(G.u[t]["ot"]), 6) if G.u[t]["ot"] else pad(L[t][:2, :3], 6) for t in (0, 1)]
    wl, wp = [G.u[t]["wl"] for t in (0, 1)], [G.u[t]["wp"] for t in (0, 1)]
    extra = [int(PPu[t][0, 0]) for t in (0, 1)]      # the sixth attacker when the goalie is pulled: top PP player
    cf = [rng.choice(len(wl[t]), n, p=wl[t]) for t in (0, 1)]
    cd = [rng.choice(len(wp[t]), n, p=wp[t]) for t in (0, 1)]
    tf = [rng.uniform(5, 45, n) for _ in (0, 1)]
    td = [rng.uniform(5, 50, n) for _ in (0, 1)]
    pen = np.zeros((n, 2))          # seconds left on a penalty against team t (t is shorthanded)
    alive = np.ones(n, bool)
    went_ot = np.zeros(n, bool)
    home_m = np.array([1 + P["home_att"] / 2, 1 - P["home_att"] / 2])
    rows = np.arange(n)
    def change(cur, timer, w, lo, hi):
        ch = timer <= 0
        if ch.any():
            k = len(w)
            cur[ch] = rng.choice(k, ch.sum(), p=w)      # drawn by usage, so each unit's share of the ice matches its weight
            timer[ch] = rng.uniform(lo, hi, ch.sum())
    for t in range(3600 + 300):
        ot = t >= 3600
        if t == 3600:
            went_ot = score[:, 0] == score[:, 1]
        if ot:
            alive &= score[:, 0] == score[:, 1]
            if not alive.any():
                break
        for k in (0, 1):
            tf[k] -= 1; td[k] -= 1
            change(cf[k], tf[k], wl[k], 30, 60)
            change(cd[k], td[k], wp[k], 35, 65)
        if not ot:
            free = (pen[:, 0] <= 0) & (pen[:, 1] <= 0)
            for k in (0, 1):
                hit = free & (rng.random(n) < P["pen_rate"])
                pen[hit, k] = 120
                ppo[hit, 1 - k] += 1
        pen = np.maximum(pen - 1, 0)
        diff = (score[:, 0] - score[:, 1]).astype(int)
        secs_left = 3600 - t
        # who is on the ice, and in what state, for both teams
        A, LAB, DD = [None, None], [None, None], [None, None]
        pulled = [np.zeros(n, bool), np.zeros(n, bool)]
        if not ot and t >= 3300:
            for k in (0, 1):
                md = diff if k == 0 else -diff
                lim = np.where(md == -1, pull[1], np.where(md == -2, pull[2], -1))
                pulled[k] = secs_left <= lim
        for k in (0, 1):
            o = 1 - k
            md = diff if k == 0 else -diff
            if ot:
                A[k] = np.repeat(OTu[k][(t // 45) % len(OTu[k])][None, :], n, 0)
                LAB[k] = np.full(n, "3v3")
            else:
                Ak = np.c_[L[k][cf[k]], D[k][cd[k]], -np.ones((n, 1), int)]
                pp = (pen[:, o] > 0) & ~(pen[:, k] > 0)
                pk = (pen[:, k] > 0) & ~(pen[:, o] > 0)
                Ak[pp] = PPu[k][np.where(pen[pp, o] > 50, 0, 1)]
                Ak[pk] = PKu[k][np.where(pen[pk, k] > 60, 0, 1)]
                Ak[pulled[k], 5] = extra[k]
                A[k] = Ak
                LAB[k] = np.where(pulled[k], "ea", np.where(pulled[o], "ed", np.where(pp, "pp", np.where(pk, "pk", "ev"))))
            DD[k] = np.clip(md, -2, 2)
        for k in (0, 1):
            o = 1 - k
            lab, dd = LAB[k], DD[k]
            r = np.zeros(n)
            for l in np.unique(lab):
                m = lab == l
                for d in (-2, -1, 0, 1, 2):
                    mm = m & (dd == d)
                    if mm.any():
                        r[mm] = rate.get(f"{l}|{d}", rate.get(f"{l}|0", 0.016))
            # the five (or four, or six) on the ice set the volume: their on-ice chance rate relative to average
            line_f = np.nanmean(G.oxf[A[k]], axis=1)
            line_f = np.where(np.isnan(line_f), 1.0, line_f)
            att = alive & (rng.random(n) < r * line_f * G.m_att[k] * home_m[k])
            if not att.any():
                continue
            idx = np.where(att)[0]
            att_n[idx, k] += 1
            labs = lab[idx]
            shooter = _choose(rng, A[k][idx], G.w_att)
            blocked = rng.random(len(idx)) < np.array([pb.get(l, 0.27) for l in labs])
            if blocked.any():
                bi = idx[blocked]
                blocker = _choose(rng, A[o][bi], G.w_blk)
                np.add.at(st["b"], (bi, blocker), 1)
                blk_n[bi, o] += 1
            ub = ~blocked
            if not ub.any():
                continue
            ui, us, ul = idx[ub], shooter[ub], labs[ub]
            pnet = np.clip(np.array([pn.get(l, 0.65) for l in ul]) * (G.net[us] / 0.66), 0.2, 0.95)
            onnet = rng.random(len(ui)) < pnet
            en = ul == "ed"
            q = np.where(en, 1.0, np.clip(G.xgs[us] * G.fin[us] * G.m_g[k] / pnet, 0, 0.9))
            goal = onnet & (rng.random(len(ui)) < q)
            np.add.at(st["s"], (ui[onnet], us[onnet]), 1)
            gn = onnet & ~en
            sa[ui[gn], o] += 1
            if goal.any():
                gi, gs = ui[goal], us[goal]
                np.add.at(st["g"], (gi, gs), 1)
                score[gi, k] += 1
                ga[gi[~en[goal]], o] += 1
                eng[gi[en[goal]], k] += 1
                ppg[gi[ul[goal] == "pp"], k] += 1
                Ag = A[k][gi].copy()
                Ag[Ag == gs[:, None]] = -1
                na = rng.choice(3, len(gi), p=P["p_ast"])
                a1 = _choose(rng, Ag, G.w_a1)
                has1 = (na >= 1) & (Ag >= 0).any(1)
                np.add.at(st["a"], (gi[has1], a1[has1]), 1)
                Ag2 = Ag.copy(); Ag2[Ag2 == a1[:, None]] = -1
                a2 = _choose(rng, Ag2, G.w_a2)
                has2 = (na == 2) & has1 & (Ag2 >= 0).any(1)
                np.add.at(st["a"], (gi[has2], a2[has2]), 1)
                pen[gi[ul[goal] == "pp"], o] = 0          # a power-play goal ends the penalty
                if ot:
                    alive[gi] = False
    so_home = rng.random(n) < 0.5
    winner = np.where(score[:, 0] > score[:, 1], 0, np.where(score[:, 1] > score[:, 0], 1, np.where(so_home, 0, 1)))
    return dict(score=score, winner=winner, tied=score[:, 0] == score[:, 1], saves=sa - ga, sa=sa,
                en_goals=eng, pp_goals=ppg, pp_opps=ppo, attempts=att_n, blocked=blk_n, went_ot=went_ot, **st)


def calibrate(G, P, target_goals, target_sog, n=600, seed=1, rounds=2, players=None):
    """Scale each team's attempt and finishing levels so a pilot run reproduces the team models' expected goals
    (target_goals = (home, away)) and shots on goal (target_sog).

    players: optional {player_id: dict(g=, pts=, sog=, blk=)} expectations from the props models. Each skater's
    shot weight, finishing, assist weights and block weight are then nudged so his share of his team's shots,
    goals, assists and blocks matches those expectations (the first walk-forward test showed the simulator alone
    flattened stars toward the middle), while the team levels stay with the team models."""
    team_idx = [np.array([G.ix[p] for p in G.ids if G.team.get(p) == t]) for t in (0, 1)]
    for r in range(rounds):
        out = simulate(G, P, n, seed + r)
        sog = out["s"].sum(0) / n
        tsog = np.array([sog[ix].sum() for ix in team_idx])
        g = out["score"].mean(0)
        G.m_att = G.m_att * np.asarray(target_sog) / np.maximum(tsog, 1)
        G.m_g = G.m_g * (np.asarray(target_goals) / np.maximum(g, 0.2)) / (np.asarray(target_sog) / np.maximum(tsog, 1))
        if players:
            gl, ast, blk = out["g"].mean(0), out["a"].mean(0), out["b"].mean(0)
            for t, ix in enumerate(team_idx):
                have = [i for i in ix if G.ids[i] in players]
                if len(have) < 8:
                    continue
                h = np.array(have)
                tg = np.array([players[G.ids[i]] for i in h], dtype=object)
                def nudge(arr, sim_v, want, lo=0.33, hi=3.0, damp=0.8):
                    want = np.asarray(want, float)
                    share_w = want / max(want.sum(), 1e-9)
                    share_s = sim_v[h] / max(sim_v[h].sum(), 1e-9)
                    ratio = np.clip((share_w + 1e-4) / (share_s + 1e-4), lo, hi) ** damp
                    arr[h] = arr[h] * ratio
                nudge(G.w_att, sog, [x["sog"] for x in tg])
                nudge(G.fin, gl / np.maximum(sog, 1e-3), [x["g"] / max(x["sog"], 0.05) for x in tg])   # goals per shot on goal
                nudge(G.w_a1, ast, [max(x["pts"] - x["g"], 0.01) for x in tg])
                nudge(G.w_a2, ast, [max(x["pts"] - x["g"], 0.01) for x in tg])
                nudge(G.w_blk, blk, [x["blk"] for x in tg])
    return G
