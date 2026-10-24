"""Depth chart from the shift charts, and who steps in when a regular is out.

Roles come from analysis/output/<season>/context_games.csv (analysis/context.py): each skater's minutes at 5v5, on
the power play and on the penalty kill, his 5v5 rank on his team that night and the linemates he shared the most
5v5 time with. A team's depth chart is its last six games.

ripple() answers "who gets his minutes?" for an absent player. If the team has already played without him, it
reports what happened (who took his spot beside his linemates, who moved onto the first power-play unit, whose
minutes jumped). If not, it names the likeliest candidates from the depth chart and says that it's a projection.
Everything is descriptive: the prop model doesn't move minutes around (tested Oct 2026; see CLAUDE.md).
"""
import numpy as np
import pandas as pd

RECENT = 6


def _line(rank, pos):
    if pos == "D":
        return 1 if rank <= 2 else 2 if rank <= 4 else 3
    return 1 if rank <= 3 else 2 if rank <= 6 else 3 if rank <= 9 else 4


def _mmss(x):
    m = int(x)
    return f"{m}:{int(round((x - m) * 60)):02d}"


def team_games(C, team):
    return C[C.team == team].drop_duplicates("game_id").sort_values(["date", "game_id"]).game_id.tolist()


def roles(C, team, gids):
    """Per player over the given games: games, minutes, 5v5 rank, line, power-play unit, usual linemates."""
    q = C[(C.team == team) & C.game_id.isin(gids)]
    out = {}
    for pid, g in q.groupby("player_id"):
        pos = g.pos.iloc[-1]
        rank = float(g.rank5.median())
        pp = float(g.toipp.mean())
        ppr = float(g.pp_rank.median())
        mates = pd.concat([g.mate1, g.mate2]).dropna().astype(int).value_counts() if pos == "F" else g.dmate.dropna().astype(int).value_counts()
        out[int(pid)] = dict(pos=pos, gp=int(g.game_id.nunique()), toi=float(g.toi_sh.mean()), toi5=float(g.toi5.mean()), pp=pp,
                             pk=float(g.toipk.mean()), rank=rank, line=_line(round(rank), pos),
                             pp_unit=1 if (ppr <= 5 and pp >= 1.0) else (2 if pp >= 0.3 else None),
                             mates=[int(m) for m in mates.index[:2 if pos == "F" else 1]])
    return out


def describe_role(r):
    if not r:
        return ""
    what = (f"{['first', 'second', 'third', 'fourth'][r['line'] - 1]}-line forward" if r["pos"] == "F"
            else f"{['top', 'second', 'third'][r['line'] - 1]}-pair defenseman")
    bits = [f"{what}, {_mmss(r['toi'])} a night"]
    if r["pp_unit"] == 1:
        bits.append("on the first power-play unit")
    elif r["pp_unit"] == 2:
        bits.append("on the second power-play unit")
    if r["pk"] >= 1.2:
        bits.append("kills penalties")
    return ", ".join(bits)


def ripple(C, team, pid, names, today=None, unavailable=()):
    """Who absorbs an absent player's role. Returns None if he hasn't played for this team this season.
    unavailable: ids out injured right now; they're never named as the one stepping in."""
    unavailable = {int(x) for x in unavailable} | {int(pid)}
    gids = team_games(C, team)
    mine = C[(C.player_id == pid) & (C.team == team)]
    if mine.empty or not gids:
        return None
    last_with = mine.sort_values("date").game_id.iloc[-1]
    i = gids.index(last_with) if last_with in gids else len(gids) - 1
    without = gids[i + 1:][-5:]
    with_ = [g for g in gids[: i + 1] if g in set(mine.game_id)][-RECENT:]
    R_with = roles(C, team, with_)
    me = R_with.get(pid)
    if not me:
        return None
    nm = lambda x: names.get(int(x), "")
    res = dict(id=int(pid), team=team, name=nm(pid), role=describe_role(me), line=me["line"], pos=me["pos"],
               pp_unit=me["pp_unit"], games_missed=len(without), steps_in=[], evidence=bool(without))
    if without:
        R_wo = roles(C, team, without)
        cand = []
        # his spot beside his usual linemates
        linemates = [m for m in me["mates"] if m in R_wo]
        if linemates and me["pos"] == "F":
            q = C[C.game_id.isin(without) & C.player_id.isin(linemates)]
            cnt = pd.concat([q.mate1, q.mate2]).dropna().astype(int)
            cnt = cnt[~cnt.isin(linemates + [pid]) & ~cnt.isin(unavailable)].value_counts()
            if len(cnt):
                x = int(cnt.index[0])
                cand.append(dict(id=x, name=nm(x), how="line", with_=[nm(m) for m in linemates]))
        elif me["pos"] == "D" and me["mates"] and me["mates"][0] in R_wo:
            partner = me["mates"][0]
            q = C[C.game_id.isin(without) & (C.player_id == partner)].dmate.dropna().astype(int).value_counts()
            q = q[~q.index.isin(unavailable)]
            if len(q):
                x = int(q.index[0])
                cand.append(dict(id=x, name=nm(x), how="pair", with_=[nm(partner)]))
        # his first-unit power-play spot
        if me["pp_unit"] == 1:
            newpp = [x for x, r in R_wo.items() if r["pp_unit"] == 1 and (R_with.get(x) or {}).get("pp_unit") != 1 and x not in unavailable]
            newpp.sort(key=lambda x: (R_wo[x]["pos"] != me["pos"], -R_wo[x]["pp"]))   # same position first
            if newpp:
                cand.append(dict(id=newpp[0], name=nm(newpp[0]), how="pp"))
        # biggest jumps in minutes
        jumps = []
        for x, r in R_wo.items():
            b = R_with.get(x)
            if b and r["pos"] == me["pos"] and r["toi"] - b["toi"] >= 1.5 and x not in unavailable:
                jumps.append((r["toi"] - b["toi"], x))
        for dlt, x in sorted(jumps, reverse=True)[:2]:
            cand.append(dict(id=x, name=nm(x), how="minutes"))
        seen, steps = set(), []
        for c in cand:
            x = c["id"]
            b, a = R_with.get(x) or {}, R_wo.get(x) or {}
            c.update(toi_before=round(b.get("toi", 0), 2) if b else None, toi_after=round(a.get("toi", 0), 2),
                     pp_before=round(b.get("pp", 0), 2) if b else None, pp_after=round(a.get("pp", 0), 2), new=not b)
            if x in seen:
                prev = next(s for s in steps if s["id"] == x)
                prev.setdefault("also", []).append(c["how"])
                continue
            seen.add(x)
            steps.append(c)
        res["steps_in"] = steps[:3]
    else:
        # projection from the depth chart: next man up for his line, and the second unit's top power-play man
        R = roles(C, team, gids[-RECENT:])
        same = sorted(((r["toi"], x) for x, r in R.items() if r["pos"] == me["pos"] and x not in unavailable and r["line"] > me["line"]), reverse=True)
        if same:
            x = same[0][1]
            res["steps_in"].append(dict(id=x, name=nm(x), how="next", toi_before=round(R[x]["toi"], 2), line=R[x]["line"]))
        if me["pp_unit"] == 1:
            pp2 = sorted(((r["pos"] == me["pos"], r["pp"], x) for x, r in R.items() if r["pp_unit"] == 2 and x not in unavailable), reverse=True)
            pp2 = [(a, c) for _, a, c in pp2]
            if pp2:
                x = pp2[0][1]
                if x not in {s["id"] for s in res["steps_in"]}:
                    res["steps_in"].append(dict(id=x, name=nm(x), how="pp_next", pp_before=round(R[x]["pp"], 2)))
    res["text"] = ripple_text(res)
    return res


def ripple_text(r):
    """One or two plain sentences on who gets his minutes."""
    if not r or not r["steps_in"]:
        return ""
    last = r["name"].split()[-1] if r["name"] else "him"
    parts = []
    if r["evidence"]:
        n = r["games_missed"]
        span = "the game since he went out" if n == 1 else f"the {n} games since he went out"
        for s in r["steps_in"]:
            if s["how"] == "line":
                parts.append(f"{s['name']} has taken his spot beside {' and '.join(w.split()[-1] for w in s['with_'])}")
            elif s["how"] == "pair":
                parts.append(f"{s['name']} has moved in beside {s['with_'][0].split()[-1]}")
            elif s["how"] == "pp":
                parts.append(f"{s['name']} has moved onto the first power-play unit")
            elif s["how"] == "minutes":
                if s.get("new"):
                    parts.append(f"{s['name']} has come into the lineup at {_mmss(s['toi_after'])} a night")
                else:
                    parts.append(f"{s['name']} is up to {_mmss(s['toi_after'])} a night from {_mmss(s['toi_before'])}")
            if s.get("also") and "minutes" in s["also"] and s["how"] != "minutes" and s.get("toi_before"):
                parts[-1] += f" and is up to {_mmss(s['toi_after'])} a night from {_mmss(s['toi_before'])}"
        if not parts:
            return ""
        lead = f"In {span}, " if n <= 5 else "Since he went out, "
        return lead + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + "."
    for s in r["steps_in"]:
        if s["how"] == "next":
            parts.append(f"{s['name']} ({_mmss(s['toi_before'])} a night) is next in line for his minutes")
        elif s["how"] == "pp_next":
            parts.append(f"{s['name']}, the busiest man on the second power-play unit, is the likeliest to move up there")
    if not parts:
        return ""
    return "Going by how the coach has used them, " + (", and ".join(parts)) + "."


def build(C, inj, names, today=None):
    """Depth info for every injured regular: {pid: ripple}. inj: {pid: {team, out, ...}} (ESPN, matched to ids)."""
    out = {}
    for pid, v in inj.items():
        if not v.get("out") and (v.get("status") or "").lower() not in ("day-to-day",):
            continue
        r = ripple(C, v["team"], int(pid), names, today, {int(k) for k, w in inj.items() if w.get("out")})
        if r and (r["line"] <= 3 or r["pp_unit"] == 1):
            r["status"] = v.get("status")
            out[int(pid)] = r
    return out
