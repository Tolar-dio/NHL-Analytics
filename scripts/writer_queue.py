"""The writer's queue: fact sheets for everything Claude should write (or rewrite) in its own voice.

Runs in the nightly workflow after site/build.py and write_stories.py, and publishes site/data/writer/queue.json
with the site (so nothing is committed and nothing secret is in it: only the derived, credited numbers the site
already shows). A scheduled Claude session reads it from the live site, writes in the voice described in
WRITING.md, and commits its pieces to data/stories/ and data/news/. The API writer (write_stories.py) stays as
the safety net: its version shows until the session's version lands, and fills in if a session never runs.

Items:
  recap     every game from the last three days without a session recap
  preview   every game on today's slate without a session preview for the current projected goalies
  player    skaters and goalies whose writeup is missing or stale (tonight's players and the Pulse names first)
  team      teams whose writeup is missing or older than a week (or who played since it was written)
  take      news stories from the last day whose take was written by the API, not the session
"""
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from write_stories import SEASON, STORY_VERSION, preview_facts, recap_facts, tidy  # noqa: E402
from writer_context import coverage, path as wpath, said, team_coverage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "data")
STORIES = os.path.join(ROOT, "data", "stories", SEASON)
PLAYERS_PER_RUN = int(os.environ.get("WRITER_PLAYERS", "60"))
PLAYER_STALE_DAYS, TEAM_STALE_DAYS = 14, 7


def jl(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default


def by_session(p, goalies=None):
    d = jl(p)
    if not d or d.get("by") != "session":
        return False
    return not goalies or not d.get("goalies") or d["goalies"] == goalies


def age_days(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds() / 86400
    except Exception:
        return 999


def player_facts(row, f, goalie=False):
    """One skater or goalie: season numbers, form, ranges, wins added, comps, path to the NHL, what's being said."""
    st = (f or {}).get("story") or {}
    log = (f or {}).get("log") or []
    eh, a3 = (f or {}).get("eh") or {}, (f or {}).get("a3z") or {}
    return tidy(dict(
        name=row["name"], team=row["team"], position="G" if goalie else row.get("pos"),
        season=row, bio=st.get("bio"), form=st.get("form"), flags=st.get("flags"), story_lines=st.get("lines"),
        talent_range=(f or {}).get("range"), wins_added=(f or {}).get("wins"),
        plays_like=[dict(name=c["name"], team=c["team"], match=c["match"], shared=c["shared"]) for c in ((f or {}).get("like") or {}).get("comps", [])] or None,
        last_ten_games=[{k: g.get(k) for k in ("date", "opp", "home", "res", "gf", "ga", "toi", "g", "a", "sog", "ixg", "sv", "ga_g", "gsax")} for g in log[-10:]] or None,
        value_by_evolving_hockey=dict(season=eh.get("season"), war=eh.get("war"), notes=eh.get("notes")) if eh else None,
        hand_tracking_by_all_three_zones=dict(season=a3.get("season"), notes=a3.get("notes")) if a3 else None,
        **wpath((f or {}).get("dossier"), notes=4, seasons=3, wiki_chars=600), **said(coverage(row["id"]), news=5, posts=3, videos=2, days=10),
    ))


def main():
    now = dt.datetime.now(dt.timezone.utc)
    items = []
    idx = jl(os.path.join(SITE, "games", "index.json"), [])
    cutoff = (now - dt.timedelta(days=3)).date().isoformat()
    for row in idx:
        if row["date"] < cutoff:
            continue
        out = os.path.join(STORIES, "recaps", f"{row['id']}.json")
        if by_session(out):
            continue
        g = jl(os.path.join(SITE, "games", f"{row['id']}.json"))
        if not g:
            continue
        facts = recap_facts(g)
        facts["win_probability"] = tidy(dict(goals_that_swung_it=[dict(team=x["team"], scorer=x.get("name"), period=x["period"],
                                                                       win_chance_before_pct=round(100 * x["before"]), after_pct=round(100 * x["after"]))
                                                                  for x in sorted((g.get("wp") or {}).get("goals", []), key=lambda x: -abs(x["swing"]))[:3]],
                                             biggest_save=(g.get("wp") or {}).get("save"), most_wins_added=(g.get("wp") or {}).get("top")))
        items.append(dict(kind="recap", id=row["id"], date=row["date"], out=f"data/stories/{SEASON}/recaps/{row['id']}.json",
                          current=(jl(out) or {}).get("text"), facts=facts))

    tonight = jl(os.path.join(SITE, "tonight.json"), {})
    race = {r["team"]: r for r in (jl(os.path.join(SITE, "race.json"), {}) or {}).get("rows", [])}
    for p_path in sorted(glob.glob(os.path.join(SITE, "previews", "*.json"))):
        p = jl(p_path)
        if not p or p["id"] not in {g["id"] for g in tonight.get("games", [])}:
            continue
        goalies = [((p.get("goalies") or {}).get(t) or {}).get("id") for t in (p["away"], p["home"])]
        out = os.path.join(STORIES, "previews", tonight.get("date", ""), f"{p['id']}.json")
        if by_session(out, goalies):
            continue
        facts = preview_facts(p)
        facts["playoff_race"] = {t: {k: race[t].get(k) for k in ("pts", "xpts", "proj", "playoffs", "division")} for t in (p["away"], p["home"]) if t in race} or None
        items.append(dict(kind="preview", id=p["id"], date=tonight.get("date"), goalies=goalies,
                          out=f"data/stories/{SEASON}/previews/{tonight.get('date')}/{p['id']}.json",
                          current=(jl(out) or {}).get("text"), facts=facts))

    # players: tonight's first, then the Pulse names, then everyone else with a stale or missing writeup
    sk = {r["id"]: r for r in jl(os.path.join(SITE, "skaters.json"), [])}
    gk = {r["id"]: r for r in jl(os.path.join(SITE, "goalies.json"), [])}
    pulse = jl(os.path.join(SITE, "pulse.json"), {}) or {}
    tonight_ids = [p["id"] for p in sorted(tonight.get("props", []), key=lambda p: -p.get("p_1pt", 0))]
    tonight_ids += [g.get(f"{s}_goalie") for g in tonight.get("games", []) for s in ("away", "home")]
    pulse_ids = [x.get("id") for lst in pulse.values() if isinstance(lst, list) for x in lst if isinstance(x, dict)]
    order = list(dict.fromkeys([i for i in tonight_ids + pulse_ids if i] + sorted(sk, key=lambda i: -sk[i].get("pts", 0)) + list(gk)))
    n = 0
    for pid in order:
        if n >= PLAYERS_PER_RUN:
            break
        goalie = pid in gk and pid not in sk
        row = gk.get(pid) if goalie else sk.get(pid)
        if not row or (row.get("gp") or 0) < 3:
            continue
        out = os.path.join(STORIES, "writeups", "players", f"{pid}.json")
        old = jl(out) or {}
        if old.get("by") == "session" and age_days(old.get("written")) < PLAYER_STALE_DAYS and old.get("gp") == row.get("gp") and pid not in tonight_ids[:40]:
            continue
        if old.get("by") == "session" and age_days(old.get("written")) < 2:
            continue
        f = jl(os.path.join(SITE, "goalies" if goalie else "players", f"{pid}.json"))
        items.append(dict(kind="player", id=pid, gp=row.get("gp"), out=f"data/stories/{SEASON}/writeups/players/{pid}.json",
                          current=old.get("text"), facts=player_facts(row, f, goalie)))
        n += 1

    teams = {t["team"]: t for t in jl(os.path.join(SITE, "teams.json"), [])}
    prof = jl(os.path.join(SITE, "team_profiles.json"), {}) or {}
    for t, row in sorted(teams.items()):
        out = os.path.join(STORIES, "writeups", "teams", f"{t}.json")
        old = jl(out) or {}
        if old.get("by") == "session" and age_days(old.get("written")) < TEAM_STALE_DAYS and old.get("gp") == row.get("gp"):
            continue
        tp = jl(os.path.join(SITE, "tactics", f"{t}.json"), {}) or {}
        items.append(dict(kind="team", id=t, gp=row.get("gp"), out=f"data/stories/{SEASON}/writeups/teams/{t}.json", current=old.get("text"),
                          facts=tidy(dict(team=t, standings=row, profile=prof.get(t), playoff_race=race.get(t),
                                          top_lines=(tp.get("lines") or [])[:3], top_pairs=(tp.get("pairs") or [])[:2], style=tp.get("style"),
                                          **said(team_coverage(t), news=6, posts=4, videos=3, days=10)))))

    news = jl(os.path.join(ROOT, "data", "news", "index.json"), {}) or {}
    for st in (news.get("stories") or [])[:40]:
        if not st.get("take") or age_days(st.get("published") or st.get("date")) > 1.5:
            continue
        ids = st.get("ids") or [st.get("id")]
        cache = next((os.path.join("data", "news", f"{i}.json") for i in ids if os.path.exists(os.path.join(ROOT, "data", "news", f"{i}.json"))), None)
        if not cache or (jl(os.path.join(ROOT, cache)) or {}).get("by") == "session":
            continue
        players = [sk.get(p["id"]) or gk.get(p["id"]) for p in st.get("players", []) if (sk.get(p["id"]) or gk.get(p["id"]))]
        items.append(dict(kind="take", id=st.get("id"), out=cache, current=st["take"],
                          facts=tidy(dict(reports=[dict(outlet=i.get("source"), headline=i.get("title"), summary=i.get("desc"), published=i.get("published"))
                                                   for i in (st.get("items") or [])[:5]],
                                          players=players[:4] or None, teams=[teams[t] for t in st.get("teams", []) if t in teams] or None))))

    os.makedirs(os.path.join(SITE, "writer"), exist_ok=True)
    q = dict(made=now.isoformat(timespec="seconds"), season=SEASON, story_version=STORY_VERSION, slate_date=tonight.get("date"),
             counts={k: sum(1 for i in items if i["kind"] == k) for k in ("recap", "preview", "player", "team", "take")}, items=items)
    json.dump(q, open(os.path.join(SITE, "writer", "queue.json"), "w"), separators=(",", ":"), default=str)
    print("writer queue:", q["counts"], f"{os.path.getsize(os.path.join(SITE, 'writer', 'queue.json')) // 1024} KB")


if __name__ == "__main__":
    main()
