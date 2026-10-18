"""Goalie pages: one JSON per goalie (data/goalies/<id>.json) plus a few fields added to goalies.json.

From our own data (MoneyPuck xG where the shot matches, our model otherwise):
  season line: starts, record, saves, goals against, expected goals against, goals saved above expected (GSAx)
  by danger: unblocked shots split by chance quality (low < 0.06 xG, mid 0.06-0.15, high >= 0.15), save rate on
    shots on goal in each band against the league, GSAx per band
  rebound control: share of his saves followed by another unblocked shot from the same team within 3 seconds
  shots-against map (normalised to one net, same arrays as the skater shot maps)
  start log: every game with shots, goals, xG against, GSAx and the decision
  last season's line, NHL EDGE save rates by area, Evolving-Hockey GSAx and GAR by season (credited) when present
Plus plain notes and percentiles among goalies with enough shots.
"""
import json
import os

import numpy as np
import pandas as pd

BANDS = [("low", 0, 0.06, "Low danger"), ("mid", 0.06, 0.15, "Medium danger"), ("high", 0.15, 1.01, "High danger")]
MIN_SHOTS = 150      # unblocked shots faced to be ranked


def _nth(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _sv(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}".lstrip("0")


def _band_table(s):
    """s: unblocked shots against one goalie (or the league). Returns per-band shots, sog, goals, xg."""
    out = {}
    for key, lo, hi, _ in BANDS:
        b = s[(s.xgv >= lo) & (s.xgv < hi)]
        sog = b[b.event.isin(["shot-on-goal", "goal"])]
        out[key] = dict(shots=int(len(b)), sog=int(len(sog)), goals=int((b.event == "goal").sum()), xg=float(b.xgv.sum()))
        out[key]["sv"] = 1 - out[key]["goals"] / out[key]["sog"] if out[key]["sog"] else None
        out[key]["gsax"] = out[key]["xg"] - out[key]["goals"]
    return out


def _rebounds(s):
    """Saves by each goalie and how many were followed by another unblocked shot from the same team within 3 s."""
    s = s.sort_values(["game_id", "game_seconds"])
    nxt_t = s.groupby(["game_id", "period"]).game_seconds.shift(-1)
    nxt_team = s.groupby(["game_id", "period"]).team.shift(-1)
    saved = s.event == "shot-on-goal"
    reb = saved & (nxt_team == s.team) & ((nxt_t - s.game_seconds) <= 3)
    return pd.DataFrame(dict(goalie_id=s.goalie_id, saved=saved, reb=reb)).groupby("goalie_id")[["saved", "reb"]].sum()


def build(shots, gg, prev_gg, games, names, out_dir, box=None, edge_areas=None, eh=None, shot_code=None, teams_of=None):
    """shots: unblocked attempts (all situations, goalie in net) with nx, ny, xgv, goalie_id, event, game_id,
    game_seconds, period, team, shot_type. gg: this season's goalie games. Returns {goalie_id: summary} for goalies.json."""
    os.makedirs(out_dir, exist_ok=True)
    s = shots.dropna(subset=["goalie_id"]).copy()
    s["goalie_id"] = s.goalie_id.astype(int)
    lg = _band_table(s)
    rb = _rebounds(s)
    lg_reb = float(rb.reb.sum() / max(rb.saved.sum(), 1))
    gg = gg[gg.game_type == "regular"].copy()
    if box is not None and len(box):
        gg = gg.merge(box[["game_id", "player_id", "dec", "sa"]], on=["game_id", "player_id"], how="left")
    else:
        gg["dec"], gg["sa"] = None, np.nan
    gm = games.set_index("game_id")
    pg = prev_gg[prev_gg.game_type == "regular"] if prev_gg is not None and len(prev_gg) else pd.DataFrame()
    # league pools for percentiles
    per = {}
    for gid, x in s.groupby("goalie_id"):
        bt = _band_table(x)
        t = gg[gg.player_id == gid]
        toi = float(t.toi.sum())
        if len(x) < 1 or toi <= 0:
            continue
        per[gid] = dict(shots=len(x), gsax60=(float(x.xgv.sum()) - int((x.event == "goal").sum())) / toi * 60,
                        hd=bt["high"]["sv"], reb=float(rb.reb.get(gid, 0) / max(rb.saved.get(gid, 0), 1)))
    pool = {k: np.sort([v[k] for v in per.values() if v["shots"] >= MIN_SHOTS and v[k] is not None]) for k in ("gsax60", "hd", "reb")}
    pctile = lambda k, v, low=False: (None if v is None or len(pool[k]) < 12 else
                                      round(float((1 - np.searchsorted(pool[k], v, side="right") / len(pool[k])) if low
                                                  else np.searchsorted(pool[k], v, side="right") / len(pool[k])), 3))
    summary = {}
    for gid, t in gg.groupby("player_id"):
        gid = int(gid)
        x = s[s.goalie_id == gid]
        t = t.sort_values(["date", "game_id"])
        toi, ga, xga = float(t.toi.sum()), int(t.ga.sum()), float(t.xga.sum())
        sa = float(t.sa.fillna(0).sum())
        dec = t.dec.fillna("").tolist()
        bt = _band_table(x)
        reb = float(rb.reb.get(gid, 0) / max(rb.saved.get(gid, 0), 1)) if gid in rb.index else None
        p = per.get(gid, {})
        starts = t[t.starter]
        log = []
        for g in t.itertuples():
            row = gm.loc[g.game_id] if g.game_id in gm.index else None
            home = row is not None and row.home == g.team
            log.append(dict(game=int(g.game_id), date=g.date, opp=None if row is None else (row.away if home else row.home), home=bool(home),
                            start=bool(g.starter), toi=round(float(g.toi), 1), sa=None if pd.isna(g.sa) else int(g.sa), ga=int(g.ga),
                            xga=round(float(g.xga), 2), gsax=round(float(g.xga - g.ga), 2), dec=g.dec if isinstance(g.dec, str) else None))
        if shot_code is not None:
            xs = x[x.nx > 0]
            mp = [[int(round(a)), int(round(b)), int(round(v * 1000)), int(e == "goal"), int(gi) % 10000, int(sec), shot_code.get(st, ""), 0]
                  for a, b, v, e, gi, sec, st in zip(xs.nx, xs.ny, xs.xgv, xs.event, xs.game_id, xs.game_seconds, xs.shot_type)]
        else:
            mp = []
        prev = None
        if len(pg):
            q = pg[pg.player_id == gid]
            if len(q):
                prev = dict(gp=int(q.game_id.nunique()), starts=int(q.starter.sum()), xga=round(float(q.xga.sum()), 1),
                            ga=int(q.ga.sum()), gsax=round(float(q.xga.sum() - q.ga.sum()), 1))
        areas = []
        if edge_areas is not None and len(edge_areas):
            a = edge_areas[(edge_areas.goalie_id == gid) & edge_areas.shots_against.notna()]
            areas = [dict(area=r.area, sa=int(r.shots_against), sv=None if pd.isna(r.save_pct) else round(float(r.save_pct), 3),
                          pctile=None if pd.isna(r.save_pct_pctile) else round(float(r.save_pct_pctile), 3),
                          lg=None if pd.isna(r.league_save_pct) else round(float(r.league_save_pct), 3))
                     for r in a.sort_values("shots_against", ascending=False).itertuples()]
        ehist = []
        if eh is not None and len(eh):
            for r in eh[eh.player_id == gid].sort_values("season").itertuples():
                ehist.append(dict(season=f"{str(r.season)[:4]}-{str(r.season)[6:]}", gp=None if pd.isna(r.gp) else int(r.gp),
                                  gsax=None if pd.isna(r.gsax) else round(float(r.gsax), 1),
                                  gar=None if pd.isna(getattr(r, "gar_gar", np.nan)) else round(float(r.gar_gar), 1)))
        c = dict(id=gid, name=names.get(gid), team=t.team.iloc[-1], gp=int(t.game_id.nunique()), starts=int(len(starts)),
                 rec=f"{dec.count('W')}-{dec.count('L')}-{dec.count('O')}", toi=round(toi, 1), sa=int(sa), ga=ga, xga=round(xga, 2),
                 gsax=round(xga - ga, 2), gsax60=round((xga - ga) / toi * 60, 3) if toi else None,
                 sv=round(1 - ga / sa, 3) if sa else None, shots=int(len(x)),
                 bands=[dict(key=k, label=lbl, shots=bt[k]["shots"], sog=bt[k]["sog"], goals=bt[k]["goals"],
                             xg=round(bt[k]["xg"], 2), sv=None if bt[k]["sv"] is None else round(bt[k]["sv"], 3),
                             lg_sv=None if lg[k]["sv"] is None else round(lg[k]["sv"], 3), gsax=round(bt[k]["gsax"], 2))
                        for k, lo, hi, lbl in BANDS],
                 reb=None if reb is None else round(reb, 3), lg_reb=round(lg_reb, 3),
                 pct=dict(gsax60=pctile("gsax60", p.get("gsax60")), hd=pctile("hd", p.get("hd")), reb=pctile("reb", reb, low=True)),
                 ranked=bool(len(x) >= MIN_SHOTS), last5=round(float((starts.tail(5).xga - starts.tail(5).ga).sum()), 2) if len(starts) else None,
                 log=log[::-1], prev=prev, areas=areas, eh=ehist, map=mp)
        c["notes"] = notes(c)
        with open(os.path.join(out_dir, f"{gid}.json"), "w") as f:
            json.dump(c, f, separators=(",", ":"), default=lambda o: o.item() if hasattr(o, "item") else str(o))
        summary[gid] = dict(rec=c["rec"], hd_sv_own=c["bands"][2]["sv"], reb=c["reb"], last5=c["last5"])
    return summary


def notes(c):
    out = []
    n = c["shots"]
    if c["gsax"] is not None and c["gp"]:
        rank = f" ({_nth(round(100 * c['pct']['gsax60']))} percentile per 60 among goalies with {MIN_SHOTS}+ shots)" if c["pct"]["gsax60"] is not None and c["ranked"] else ""
        if c["gsax"] >= 1:
            out.append(f"He has saved {c['gsax']:.1f} goals more than the shots he faced usually allow{rank}: {c['ga']} allowed on {c['xga']:.1f} expected.")
        elif c["gsax"] <= -1:
            out.append(f"He has allowed {-c['gsax']:.1f} goals more than his shots usually produce{rank}: {c['ga']} allowed on {c['xga']:.1f} expected.")
        else:
            out.append(f"He's stopping about what the shots deserve: {c['ga']} allowed on {c['xga']:.1f} expected.")
    hd = c["bands"][2]
    if hd["sog"] >= 15 and hd["sv"] is not None and hd["lg_sv"] is not None:
        diff = hd["sv"] - hd["lg_sv"]
        if abs(diff) >= 0.03:
            out.append(f"{'Big' if diff > 0 else 'Shaky'} on the hard ones: {_sv(hd['sv'])} on high-danger shots against a league {_sv(hd['lg_sv'])} "
                       f"({hd['sog']} shots). That's where goalies separate, though it takes a full season to trust.")
    lo = c["bands"][0]
    if lo["sog"] >= 40 and lo["sv"] is not None and lo["lg_sv"] is not None and lo["sv"] - lo["lg_sv"] <= -0.02:
        out.append(f"Soft goals: {_sv(lo['sv'])} on low-danger shots against a league {_sv(lo['lg_sv'])}. Those are the ones teams can't live with.")
    if c["reb"] is not None and c["pct"]["reb"] is not None and c["ranked"]:
        if c["pct"]["reb"] >= 0.8:
            out.append(f"Good rebound control: {100 * c['reb']:.1f}% of his saves lead to another shot within three seconds (league {100 * c['lg_reb']:.1f}%).")
        elif c["pct"]["reb"] <= 0.2:
            out.append(f"Rebounds are an issue: {100 * c['reb']:.1f}% of his saves lead to another shot within three seconds (league {100 * c['lg_reb']:.1f}%).")
    if c["prev"] and c["prev"]["gp"] >= 10:
        out.append(f"Last season: {c['prev']['gsax']:+.1f} goals saved above expected in {c['prev']['gp']} games.")
    if n < MIN_SHOTS:
        out.append(f"Small sample: {n} unblocked shots faced. Goalie numbers swing hard until several hundred shots; one season barely predicts the next.")
    return out
