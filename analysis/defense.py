"""Defensive and deployment numbers per skater, from the NHL's events and shift charts (our own data).

For each skater in a season (regular season only):
  5v5 ice time (from shifts crossed with the game's 5v5 stretches), on-ice shot attempts, expected goals and goals
  against per 60 at 5v5, and the same for his team while he was on the bench ("relative": negative is better);
  high-danger chances against (unblocked shots worth 0.15 xG or more);
  individual blocks, hits, takeaways, giveaways, penalties taken and drawn (all situations);
  penalty-kill ice time per game;
  deployment: 5v5 faceoffs he was on the ice for by zone (his team's offensive / neutral / defensive end).

xG per shot: MoneyPuck's where the shot matches (credit MoneyPuck.com), else our own (shots_with_xg from
player_flags.py). Writes analysis/output/<season>/defense.csv.

  python analysis/defense.py 20262027
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HD = 0.15


def _xg(season, att):
    ours = os.path.join(ROOT, "analysis", "output", "shots_with_xg.csv.gz")
    att["xg"] = np.nan
    if os.path.exists(ours):
        o = pd.read_csv(ours, usecols=["game_id", "event_id", "xg"])
        att = att.drop(columns="xg").merge(o, on=["game_id", "event_id"], how="left")
    files = glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", season, "*.csv.gz"))
    if files:
        mp = pd.concat([pd.read_csv(f, usecols=["game_id", "time", "shooterPlayerId", "xGoal", "period"]) for f in files])
        mp = mp[mp.period <= 4]
        mp["game_id"] = int(season[:4]) * 1000000 + mp.game_id
        mp = mp.rename(columns={"time": "game_seconds", "shooterPlayerId": "player1_id"}).drop_duplicates(
            ["game_id", "game_seconds", "player1_id"])
        att = att.merge(mp[["game_id", "game_seconds", "player1_id", "xGoal"]], on=["game_id", "game_seconds", "player1_id"], how="left")
        att["xg"] = att.xGoal.fillna(att.xg)
    att["xg"] = att.xg.fillna(0.0)
    att.loc[att.event == "blocked-shot", "xg"] = 0.0
    return att


def build(season):
    T = os.path.join(ROOT, "data", "tables", season)
    ev = pd.read_csv(os.path.join(T, "events.csv.gz"))
    ev = ev[(ev.game_type == "regular") & (ev.period_type != "SO")].copy()
    ev["sc"] = ev.situation_code.fillna(0).astype(int).astype(str).str.zfill(4)
    ev["psec"] = ev.game_seconds - (ev.period.clip(upper=4) - 1) * 1200
    sh = pd.read_csv(os.path.join(T, "shifts.csv.gz")).dropna(subset=["player_id"])
    pos = pd.read_csv(os.path.join(T, "players.csv.gz")).drop_duplicates("player_id").set_index("player_id").position
    sh["player_id"] = sh.player_id.astype(int)
    sh = sh[sh.player_id.map(pos) != "G"]
    sh = sh[sh.game_id.isin(ev.game_id.unique())]

    att = ev[ev.event.isin(["shot-on-goal", "missed-shot", "goal", "blocked-shot"])].copy()
    att = _xg(season, att)
    att["opp"] = np.where(att.team == att.home_team, att.away_team, att.home_team)

    out = {}
    def add(pid, key, v):
        d = out.setdefault(pid, {})
        d[key] = d.get(key, 0.0) + v

    for (gid, per), e in ev.groupby(["game_id", "period"]):
        s = sh[(sh.game_id == gid) & (sh.period == per)]
        if s.empty:
            continue
        home = e.home_team.iloc[0]
        e = e.sort_values(["psec", "sort_order"])
        # stretches of play: each event's code describes the state leading into it
        t = e.psec.values.astype(float)
        codes = e.sc.values
        edges = np.concatenate([[0.0], t])
        segs = [(edges[i], edges[i + 1], codes[i]) for i in range(len(t)) if edges[i + 1] > edges[i]]
        five = [(a, b) for a, b, c in segs if c == "1551"]
        pk = {}   # team -> shorthanded stretches (own skaters fewer, both goalies in)
        for a, b, c in segs:
            if c[0] == "1" and c[3] == "1" and c[1] != c[2]:
                short = home if int(c[2]) < int(c[1]) else e.away_team.iloc[0]
                pk.setdefault(short, []).append((a, b))
        st, en = s.start_sec.values.astype(float), s.end_sec.values.astype(float)
        for i, r in enumerate(s.itertuples()):
            ov = sum(max(0.0, min(en[i], b) - max(st[i], a)) for a, b in five)
            if ov:
                add(r.player_id, "toi5", ov / 60)
            ovk = sum(max(0.0, min(en[i], b) - max(st[i], a)) for a, b in pk.get(r.team, []))
            if ovk:
                add(r.player_id, "toi_pk", ovk / 60)
        out_team = dict(zip(s.player_id, s.team))
        # on-ice 5v5 events: shots against and faceoffs by zone
        e5 = e[e.sc == "1551"]
        a5 = att[(att.game_id == gid) & (att.period == per) & (att.sc == "1551")]
        for x in a5.itertuples():
            on = s[(s.start_sec < x.psec) & (s.end_sec >= x.psec)]
            for p in on.itertuples():
                if p.team == x.team:
                    add(p.player_id, "cf", 1)
                    add(p.player_id, "xgf", x.xg)
                    add(p.player_id, "gf", int(x.event == "goal"))
                else:
                    add(p.player_id, "ca", 1)
                    add(p.player_id, "xga", x.xg)
                    add(p.player_id, "ga", int(x.event == "goal"))
                    add(p.player_id, "hdca", int(x.xg >= HD))
        for x in e5[e5.event == "faceoff"].itertuples():
            on = s[(s.start_sec <= x.psec) & (s.end_sec > x.psec)]     # on for the draw: changed on at or before it
            for p in on.itertuples():
                z = x.zone if p.team == x.team else {"O": "D", "D": "O"}.get(x.zone, x.zone)
                add(p.player_id, {"O": "fo_oz", "D": "fo_dz"}.get(z, "fo_nz"), 1)
        for pid, team in out_team.items():
            out.setdefault(pid, {}).setdefault("team", team)

    d = pd.DataFrame.from_dict(out, orient="index")
    for c in ["toi5", "toi_pk", "cf", "xgf", "gf", "ca", "xga", "ga", "hdca", "fo_oz", "fo_dz", "fo_nz"]:
        if c not in d:
            d[c] = 0.0
    d = d.fillna({c: 0.0 for c in d.columns if c != "team"})
    # individual events, all situations
    cnt = lambda ev_name, col="player1_id": ev[ev.event == ev_name].groupby(col).size()
    d["blk"] = d.index.map(cnt("blocked-shot", "player2_id")).fillna(0)
    d["hits"] = d.index.map(cnt("hit")).fillna(0)
    d["take"] = d.index.map(cnt("takeaway")).fillna(0)
    d["give"] = d.index.map(cnt("giveaway")).fillna(0)
    pen = ev[ev.event == "penalty"]
    d["pen_taken"] = d.index.map(pen.groupby("player1_id").size()).fillna(0)
    d["pen_drawn"] = d.index.map(pen.groupby("player2_id").size()).fillna(0)
    gp = sh.groupby("player_id").game_id.nunique()
    toi = sh.assign(dur=sh.end_sec - sh.start_sec).groupby("player_id").dur.sum() / 60
    d["gp"], d["toi"] = d.index.map(gp).fillna(0), d.index.map(toi).fillna(0)
    d["pos"] = d.index.map(pos).fillna("F")
    d["pos"] = np.where(d.pos == "D", "D", "F")
    # team totals at 5v5, to get the team's numbers with him off the ice (toi from his teammates' shares)
    t5 = att[att.sc == "1551"]
    team_xga = t5.groupby("opp").xg.sum()
    team_ca = t5.groupby("opp").size()
    team_toi5 = d.groupby("team").toi5.sum() / 5          # five skaters on the ice
    off_toi = d.team.map(team_toi5) - d.toi5
    d["xga60"] = d.xga / d.toi5.replace(0, np.nan) * 60
    d["ca60"] = d.ca / d.toi5.replace(0, np.nan) * 60
    d["hdca60"] = d.hdca / d.toi5.replace(0, np.nan) * 60
    d["xga60_off"] = (d.team.map(team_xga) - d.xga) / off_toi.replace(0, np.nan) * 60
    d["ca60_off"] = (d.team.map(team_ca) - d.ca) / off_toi.replace(0, np.nan) * 60
    d["xga60_rel"] = d.xga60 - d.xga60_off
    d["ca60_rel"] = d.ca60 - d.ca60_off
    d["oz_share"] = d.fo_oz / (d.fo_oz + d.fo_dz).replace(0, np.nan)
    d["pk_pg"] = d.toi_pk / d.gp.replace(0, np.nan)
    for c in ["blk", "hits", "take", "give"]:
        d[c + "60"] = d[c] / d.toi.replace(0, np.nan) * 60
    d.index.name = "player_id"
    path = os.path.join(ROOT, "analysis", "output", season, "defense.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d.round(4).to_csv(path)
    print(f"defense {season}: {len(d)} skaters, 5v5 minutes {d.toi5.sum() / 10:.0f} per side")
    return d


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "20262027")


# ------------------------------------------------------------------ cards for the site

ROWS = [  # key, label, unit, lower is better
    ("xga60_rel", "Chances allowed vs team without him (xGA/60)", "rate", True),
    ("hdca60", "High-danger chances against per 60", "rate", True),
    ("ca60_rel", "Shot attempts allowed vs without him (per 60)", "rate1", True),
    ("blk60", "Blocks per 60", "rate1", False),
    ("take60", "Takeaways per 60", "rate1", False),
    ("give60", "Giveaways per 60", "rate1", True),
    ("pk_pg", "Penalty-kill minutes a game", "min", False),
    ("dz_share", "Share of 5v5 faceoffs in his own end", "share", False),
]
MAP_KEYS = ["supp", "dz_share", "blk60", "pk_pg"]
MIN5 = {"cur": 40, "prev": 300}       # 5v5 minutes to be ranked: early-season pools are small


def _label(season):
    return f"{season[:4]}-{season[6:]}"


def _nth(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _frame(path, names):
    d = pd.read_csv(path, index_col=0)
    d["dz_share"] = d.fo_dz / (d.fo_oz + d.fo_dz).replace(0, np.nan)
    d["supp"] = -d.xga60_rel                          # up is good on the map
    d["name"] = d.index.map(names) if names is not None else None
    return d


def _pct(d, keys, min5):
    out = {}
    for pg, g in d.groupby("pos"):
        ref = g[g.toi5 >= min5]
        for k in keys:
            vals = np.sort(ref[k].dropna().values)
            if len(vals) < 25:
                continue
            p = np.searchsorted(vals, g[k].values, side="right") / len(vals)
            out.setdefault(k, pd.Series(np.nan, index=d.index)).loc[g.index] = p
    return out


def notes(c):
    """Plain sentences on how he defends and how he's used. Each names its season."""
    S, one = c["season"], ("defenseman" if c["pos"] == "D" else "forward")
    pos = "defensemen" if c["pos"] == "D" else "forwards"
    v, P, out = c["v"], c["p"], []
    if (P.get("pk_pg") or 0) >= 0.8 and (v.get("pk_pg") or 0) >= 1.0:
        out.append(f"Trusted when shorthanded: {v['pk_pg']:.1f} penalty-kill minutes a game in {S} ({_nth(round(100 * P['pk_pg']))} percentile among {pos}).")
    dz = v.get("dz_share")
    if dz is not None and (P.get("dz_share") or 0) >= 0.85:
        out.append(f"He gets the hard starts: {round(100 * dz)}% of the 5v5 faceoffs he's out for are in his own end, which drags on his shot and chance numbers.")
    elif dz is not None and (P.get("dz_share") or 1) <= 0.15:
        out.append(f"He's sheltered toward offense: only {round(100 * dz)}% of his 5v5 faceoffs are in his own end, so his defensive numbers come in easier minutes.")
    r = v.get("xga60_rel")
    if r is not None and (P.get("xga60_rel") or 0) >= 0.8:
        out.append(f"The team defends better with him out there: {abs(r):.2f} fewer expected goals against per 60 at 5v5 than when he sits ({_nth(round(100 * P['xga60_rel']))} percentile).")
    elif r is not None and P.get("xga60_rel") is not None and P["xga60_rel"] <= 0.2:
        out.append(f"Chances against go up with him on the ice: {r:+.2f} expected goals against per 60 at 5v5 compared with when he sits.")
    if c["pos"] == "D" and (P.get("blk60") or 0) >= 0.85:
        out.append(f"A shot blocker: {v['blk60']:.1f} blocks per 60 ({_nth(round(100 * P['blk60']))} percentile among defensemen).")
    tk, gv = v.get("take60") or 0, v.get("give60") or 0
    if tk and gv and tk / gv >= 1.0 and (P.get("take60") or 0) >= 0.8:
        out.append(f"He wins pucks back: {tk:.1f} takeaways per 60 against {gv:.1f} giveaways. (Rinks record both unevenly, so treat it as a lean.)")
    if c["toi5"] < 150:
        out.append(f"Small sample: {round(c['toi5'])} minutes at 5v5 in {S}. Defensive numbers take months to settle.")
    return out[:5]


def cards(cur_path, prev_path, names=None, cur="20262027", prev="20252026"):
    """Per-skater defense card (this season, last season, percentiles, notes) and the league table for the map."""
    keys = [k for k, *_ in ROWS] + ["supp"]
    frames = {}
    for tag, path, season in (("cur", cur_path, cur), ("prev", prev_path, prev)):
        if path and os.path.exists(path):
            d = _frame(path, names)
            for k, p in _pct(d, keys, MIN5[tag]).items():
                # lower-is-better rows are flipped so a long bar is always good, except deployment, which is context
                lower = {k_: lb for k_, _, _, lb in ROWS}.get(k, False)
                d[k + "_p"] = (1 - p) if lower else p
            frames[tag] = (season, d)
    out, league = {}, {}
    for tag, (season, d) in frames.items():
        lab = _label(season)
        pool = d[d.toi5 >= MIN5[tag]]
        league[lab] = dict(season=lab, keys=["id", "name", "team", "pos"] + MAP_KEYS,
                           rows=[[int(i), (names or {}).get(int(i), ""), r.team, r.pos] +
                                 [None if pd.isna(getattr(r, k)) else round(float(getattr(r, k)), 3) for k in MAP_KEYS]
                                 for i, r in pool.iterrows()],
                           median={pg: {k: round(float(g[k].median()), 3) for k in keys if k in g} for pg, g in pool.groupby("pos")})
    for tag in ("prev", "cur"):
        if tag not in frames:
            continue
        season, d = frames[tag]
        lab = _label(season)
        for i, r in d.iterrows():
            if r.toi5 < 10:
                continue
            f = lambda k: None if pd.isna(r.get(k)) else round(float(r[k]), 3)
            block = dict(season=lab, pos=r.pos, gp=int(r.gp), toi=round(float(r.toi), 1), toi5=round(float(r.toi5), 1),
                         v={k: f(k) for k in keys + ["xga60", "ca60", "blk", "hits", "take", "give", "pen_taken", "pen_drawn"]},
                         p={k: f(k + "_p") for k in keys}, lg={k: league[lab]["median"].get(r.pos, {}).get(k) for k in keys})
            block["rows"] = [dict(k=k, label=lbl, unit=u, lower_better=lb, v=block["v"].get(k), pctile=block["p"].get(k),
                                  lg=block["lg"].get(k)) for k, lbl, u, lb in ROWS if block["v"].get(k) is not None]
            block["map"] = {k: f(k) for k in MAP_KEYS}
            card = out.setdefault(int(i), {})
            card[tag] = block
    for pid, c in out.items():
        tag = "cur" if c.get("cur") and c["cur"]["toi5"] >= 150 else ("prev" if c.get("prev") else "cur")
        c["main"] = tag
        c["notes"] = notes(c[tag]) + ([f"This season so far ({c['cur']['toi5']:.0f} minutes at 5v5) is shown next to it; "
                                       f"the ranks and notes use {c[tag]['season']}, the bigger sample."] if tag == "prev" and c.get("cur") else [])
    return out, league
