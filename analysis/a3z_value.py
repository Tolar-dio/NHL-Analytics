"""Possession value from All Three Zones tracking: what each zone entry and exit is worth, and who adds it.

Every tracked 5v5 entry and exit is followed for WINDOW seconds, counting expected goals for and against the team
that made the play (MoneyPuck xG on unblocked attempts). An entry's window stops early at the next tracked entry by
either team; an exit's at the same team's next exit (they were pinned back again, and that exit starts its own).
The average net xG after each kind of play is what that play is worth:

    entries: carried in, dumped in, failed at the line
    exits:   carried out, passed out, cleared (no possession), failed

A player is credited with each play's value above the average entry (or exit), so a carry-in where most players
would dump earns him the difference; a defender who denies an entry at his blue line gets the reverse of what the
attacker lost. Totals are per 60 tracked 5v5 minutes, measured against the typical player at his position (zero),
with percentiles among his position (150 tracked minutes).
Values are fit on every tracked game in the seasons we have events for (2025-26 on).

Never print or commit rows: the tracking is paid and private (see CLAUDE.md). Only derived, credited numbers go out.

    python analysis/a3z_value.py      # the values table and the top players by position (names only, no rows)
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import a3z as A3  # noqa: E402
from defense import _xg  # noqa: E402

WINDOW = 20.0
ENTRY = {"c": "Carried in", "d": "Dumped in", "f": "Failed at the line"}
EXIT = {"cex": "Carried out", "pex": "Passed out", "cle": "Cleared, no possession", "fex": "Failed", "mex": "Failed"}
ATT = ["shot-on-goal", "missed-shot", "goal"]
MIN_TOI, PCT_TOI = 60.0, 150.0


def shots(season):
    p = os.path.join(ROOT, "data", "tables", season, "events.csv.gz")
    if not os.path.exists(p):
        return None
    ev = pd.read_csv(p, usecols=["game_id", "event_id", "event", "period", "period_type", "game_seconds", "player1_id", "team"])
    ev = ev[(ev.period_type != "SO") & ev.event.isin(ATT)].copy()
    ev = _xg(season, ev)
    ev["elapsed"] = ev.game_seconds - (ev.period.clip(upper=4) - 1) * 1200
    return ev[["game_id", "period", "elapsed", "team", "xg"]]


def _windows(plays, sh, team_col, stop_any):
    """Net xG for the play's team in (t, t + WINDOW], cut at the next play (by anyone, or by the same team)."""
    plays = plays.sort_values(["game_id", "period", "elapsed"]).copy()
    key = ["game_id", "period"] if stop_any else ["game_id", "period", team_col]
    nxt = plays.groupby(key).elapsed.shift(-1)
    plays["end"] = np.minimum(plays.elapsed + WINDOW, nxt.fillna(1e9))
    by = {k: g for k, g in sh.groupby(["game_id", "period"])}
    net = np.zeros(len(plays))
    for i, (gid, per, t, end, tm) in enumerate(zip(plays.game_id, plays.period, plays.elapsed, plays.end, plays[team_col])):
        s = by.get((gid, per))
        if s is None:
            continue
        w = s[(s.elapsed > t) & (s.elapsed <= end)]
        if len(w):
            net[i] = w.xg[w.team == tm].sum() - w.xg[w.team != tm].sum()
    plays["net"] = net
    return plays


def plays(season):
    """5v5 entries and exits of one season with the net xG that followed. None if no events or tracking."""
    sh = shots(season)
    E, X = A3.load(season, "entries"), A3.load(season, "exits")
    if sh is None or E.empty:
        return None, None
    tracked = set(E.game_id) & set(sh.game_id)
    sh = sh[sh.game_id.isin(tracked)]
    E = E[(E.strength == "5v5") & E.type.isin(list(ENTRY)) & E.game_id.isin(tracked)].dropna(subset=["elapsed"])
    X = X[(X.strength == "5v5") & X.exit_result.isin(list(EXIT)) & X.game_id.isin(tracked)].dropna(subset=["elapsed"])
    X = X.assign(exit_result=X.exit_result.replace({"mex": "fex"}))
    return _windows(E, sh, "team", True), _windows(X, sh, "team", False)


def values(seasons=("20252026", "20262027")):
    Es, Xs = [], []
    for s in seasons:
        e, x = plays(s)
        if e is not None:
            Es.append(e); Xs.append(x)
    E, X = pd.concat(Es), pd.concat(Xs)
    ve = E.groupby("type").net.agg(["mean", "size", "sem"])
    vx = X.groupby("exit_result").net.agg(["mean", "size", "sem"])
    return dict(entry={k: float(ve.at[k, "mean"]) for k in ve.index}, exit={k: float(vx.at[k, "mean"]) for k in vx.index},
                entry_mean=float(E.net.mean()), exit_mean=float(X.net.mean()),
                n=dict(entries=int(len(E)), exits=int(len(X)), games=int(E.game_id.nunique())),
                sem=dict(entry={k: float(ve.at[k, "sem"]) for k in ve.index}, exit={k: float(vx.at[k, "sem"]) for k in vx.index}))


def players(season, V):
    """{player_id: card} for one tracked season, plus the league rows for percentiles."""
    pg = A3.load(season)
    E, X = A3.load(season, "entries"), A3.load(season, "exits")
    if pg.empty or E.empty:
        return {}
    T = A3.season_totals(pg)
    E = E[(E.strength == "5v5") & E.type.isin(list(ENTRY))]
    X = X[(X.strength == "5v5") & X.exit_result.isin(list(EXIT))].assign(exit_result=lambda d: d.exit_result.replace({"mex": "fex"}))
    e_add = E.type.map(V["entry"]) - V["entry_mean"]
    x_add = X.exit_result.map(V["exit"]) - V["exit_mean"]
    ent = e_add.groupby(E.player_id).sum()
    den = (-e_add).groupby(E.defender_id).sum()
    ext = x_add.groupby(X.exit_id).sum()
    for s in (ent, den, ext):
        s.index = s.index.astype(int)
    T = T[T.toi5 >= MIN_TOI].copy()
    T["entry_v"] = ent.reindex(T.index).fillna(0) / T.toi5 * 60
    T["exit_v"] = ext.reindex(T.index).fillna(0) / T.toi5 * 60
    T["deny_v"] = den.reindex(T.index).fillna(0) / T.toi5 * 60
    T["total_v"] = T.entry_v + T.exit_v + T.deny_v
    pool = T.toi5 >= PCT_TOI
    # zero is the typical player at his position (defensemen dump and clear more by job, not by choice)
    for pos in ("F", "D"):
        ref = T[pool & (T.pos == pos)]
        for k in ("entry_v", "exit_v", "deny_v", "total_v"):
            if len(ref):
                T.loc[T.pos == pos, k] -= float(np.average(ref[k], weights=ref.toi5))
    out = {}
    for pid, r in T.iterrows():
        ref = T[pool & (T.pos == r.pos)]
        pct = lambda k: round(float((ref[k] < r[k]).mean() + 0.5 * (ref[k] == r[k]).mean()), 2) if len(ref) >= 20 else None
        out[int(pid)] = dict(season=A3.LABEL.get(season, season), toi5=round(float(r.toi5), 1), pos=r.pos,
                             rows=[dict(k=k, v=round(float(r[k]), 3), pctile=pct(k), lg=round(float(ref[k].median()), 3) if len(ref) else None)
                                   for k in ("total_v", "entry_v", "exit_v", "deny_v")])
    return out


def table(V):
    """What each play is worth, for the page."""
    return dict(window=WINDOW, n=V["n"],
                entry=[dict(k=k, label=ENTRY[k], net=round(V["entry"][k], 4), vs=round(V["entry"][k] - V["entry_mean"], 4)) for k in ENTRY if k in V["entry"]],
                exit=[dict(k=k, label=EXIT[k], net=round(V["exit"][k], 4), vs=round(V["exit"][k] - V["exit_mean"], 4)) for k in ("cex", "pex", "cle", "fex") if k in V["exit"]],
                credit=A3.CREDIT)


if __name__ == "__main__":
    V = values()
    print(V["n"])
    for k, v in V["entry"].items():
        print(f"entry {ENTRY[k]:28s} {v:+.4f} (se {V['sem']['entry'][k]:.4f})")
    for k, v in V["exit"].items():
        print(f"exit  {EXIT[k]:28s} {v:+.4f} (se {V['sem']['exit'][k]:.4f})")
