"""Hourly news job: gather headlines, newsletters, podcasts and videos (scripts/media.py), group the same
story across outlets, and have Claude write one short take per story from the outlets' headlines and
teasers plus this site's own numbers. No web search, no full article text (about 1 cent per take).

Writes data/news/index.json (stories with takes, worth reading, listen, watch, game highlights) and
data/news/<story id>.json per take. The site reads the index from raw.githubusercontent.com, so it
updates without a redeploy.

Env: ANTHROPIC_API_KEY (without it the feed still updates, just without takes), STORY_MODEL,
NEWS_MAX (takes per run, default 8), YOUTUBE_API_KEY (optional fallback when YouTube's feeds fail),
SITE_DATA_URL.
"""
import datetime as dt, glob, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from write_stories import STYLE, MODEL, clean, finished, tidy  # noqa: E402
import media  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "news")
SITE = os.environ.get("SITE_DATA_URL", "https://tolar-dio.github.io/NHL-Analytics/data/")
NEWS_MAX = int(os.environ.get("NEWS_MAX", "8"))
MOVES_MAX = int(os.environ.get("MOVES_MAX", "4"))   # Claude notes on trades and staff changes per run

NEWS_TASK = """Write a short take on this NHL news story for a hockey analytics site, 2 short paragraphs, 120 to 180 words total.
First, state what happened in one or two sentences, credited to the outlet that reported it ("per ESPN", "The Athletic reports"), using only the headlines and summaries given. Do not add details they don't contain.
Then spend the rest on what this site's numbers say about the players or teams involved and why that matters: for the team's strength, a player's real level versus his results, fantasy value, or what changes on the ice. Only use numbers from the JSON, and say "so far this season" where the sample is small.
If a player in the story is hurt or out, end with who should see more ice time or power-play time while he's out, from `who_gets_his_minutes`: when it's based on games already played without him, say so; when it's a projection, say it's going by how the coach has used his players.
JSON facts:
"""


MOVE_TASK = """Write a short note on this NHL roster or front-office move for a hockey analytics site: 2 to 4 sentences, 50 to 110 words.
Start by restating the move plainly from the transaction text (credit it to the team's announcement). Then say what this site's numbers show about the players or teams involved and what changes for them. For an injury move, say who should get the player's minutes, from `who_gets_his_minutes` (a projection from how the coach has used his players, or what has happened in games already played without him). Only use the transaction text and the numbers in the JSON. Do not guess at reasons, contracts, salary cap, health or motives, and say nothing about a player's quality if the JSON has no numbers for him.
JSON facts:
"""


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NHL-Analytics news job)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(s):
    import unicodedata, re
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def player_card(x):
    return dict(name=x["name"], team=x["team"], pos=x.get("pos"), games=x.get("gp"), goals=x.get("g"), assists=x.get("a"),
                points=x.get("pts"), ice_time_per_game_min=x.get("toi_pg"), own_expected_goals=x.get("ixg"),
                goals_minus_expected=x.get("g_minus_xg"), five_on_five_share_of_expected_goals_pct=x.get("xgf5"),
                team_share_better_with_him_pct_points=x.get("rel5"), model_expected_goals_per_60=x.get("m_ixg60"),
                last_season=dict(team=x.get("p_team"), games=x.get("p_gp"), goals=x.get("p_g"), points=x.get("p_pts"))
                if x.get("p_gp") else None)


def goalie_card(x):
    return dict(name=x["name"], team=x["team"], games=x.get("gp"), save_pct=None if x.get("sv_pct") is None else f'{x["sv_pct"]:.3f}'.lstrip("0"),
                goals_saved_above_expected=x.get("gsax"), last_season_games=x.get("prev_gp"),
                last_season_goals_saved_above_expected=x.get("prev_gsax"))


def team_card(t, prof):
    p = prof.get(t["team"], {})
    return dict(team=t["team"], record=f'{t["w"]}-{t["l"]}-{t["otl"]}', points=t["pts"], games=t["gp"],
                share_of_expected_goals_pct=round(t["xg_pct"], 1), goals_minus_expected=round(t["g_minus_xg"], 1),
                goals_saved_above_expected=round(t["xga"] - t["ga"], 1),
                five_on_five_share_of_expected_goals_pct=None if p.get("xg5_share") is None else round(100 * p["xg5_share"]),
                power_play_expected_goals_per_game=p.get("pp_xg_pg"), penalty_kill_expected_goals_allowed_per_game=p.get("pk_xga_pg"))


def main(client=None):
    if client is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
        else:
            print("No ANTHROPIC_API_KEY set; updating the feed without takes.")
    os.makedirs(OUT, exist_ok=True)
    try:   # hourly snapshot of ESPN's injury report: the build uses the history to spot players coming back
        import espn
        h = espn.update_history(espn.injuries())
        print(f"injury history: {len(h)} players")
    except Exception as e:
        print(f"injury snapshot failed: {e!r}")
    try:
        games = get(SITE + "games/index.json")
    except Exception:
        games = []
    feed, log = media.gather(SITE, os.path.join(OUT, "cache"), games)
    print("\n".join(log))
    goalies_by = {x["id"]: x for x in get(SITE + "goalies.json")}
    skaters_by = {x["id"]: x for x in get(SITE + "skaters.json")}
    teams_by = {t["team"]: t for t in get(SITE + "teams.json")}
    try:
        prof = get(SITE + "team_profiles.json")
    except Exception:
        prof = {}
    try:   # who absorbs an absent regular's minutes (site/depthchart.py), for injury stories and moves
        depth = get(SITE + "depth.json").get("players", {})
    except Exception:
        depth = {}

    def minutes_facts(ids):
        out = []
        for i in ids:
            x = depth.get(str(i))
            if x and x.get("text"):
                out.append(dict(player=x["name"], his_role=x.get("role"), games_missed_so_far=x.get("games_missed"),
                                based_on="games already played without him" if x.get("evidence") else "how the coach has used his players",
                                summary=x["text"]))
        return out or None

    # roster and staff moves (ESPN's transactions feed); Claude adds a short note to trades and staff changes
    mdir = os.path.join(OUT, "moves")
    os.makedirs(mdir, exist_ok=True)
    try:
        import moves
        feed["moves"] = moves.gather(skaters_by, goalies_by)
    except Exception as e:
        print(f"moves failed ({e!r}); keeping the last list")
        try:
            feed["moves"] = json.load(open(os.path.join(OUT, "index.json"))).get("moves", [])
        except Exception:
            feed["moves"] = []
    noted = 0
    for m in feed["moves"]:
        path = os.path.join(mdir, f"{m['id']}.json")
        if os.path.exists(path):
            m["take"] = json.load(open(path)).get("take")
            continue
        injury_note = m["kind"] == "injury" and any(str(p["id"]) in depth for p in m["players"])
        if (m["kind"] not in ("trade", "staff") and not injury_note) or client is None or noted >= MOVES_MAX:
            continue
        facts = tidy(dict(transaction=[dict(team=i["team"], announcement=i["text"]) for i in m["items"]], date=m["date"],
                          who_gets_his_minutes=minutes_facts([p["id"] for p in m["players"]]) if m["kind"] == "injury" else None,
                          players=[player_card(skaters_by[p["id"]]) for p in m["players"] if p["id"] in skaters_by][:4],
                          goalies=[goalie_card(goalies_by[p["id"]]) for p in m["players"] if p["id"] in goalies_by][:2],
                          teams=[team_card(teams_by[t], prof) for t in m["teams"] if t in teams_by]))
        try:
            msg = client.messages.create(model=MODEL, max_tokens=1200, system=STYLE, thinking={"type": "between_tools"},
                                         messages=[{"role": "user", "content": MOVE_TASK + json.dumps(facts, separators=(",", ":"))}])
            text = clean("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
            if getattr(msg, "stop_reason", "end_turn") != "end_turn" or len(text.split()) < 30 or text[-1:] not in '.!?)"\u201d':
                raise RuntimeError(f"unfinished note ({len(text.split())} words)")
        except Exception as e:
            print(f"  ! move note {m['id']} failed: {e!r}", file=sys.stderr)
            break
        m["take"] = text
        json.dump(dict(id=m["id"], date=m["date"], take=text, model=MODEL,
                       written=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")), open(path, "w"))
        noted += 1
    for f in glob.glob(os.path.join(mdir, "*.json")):   # notes on moves older than the list are dropped after 45 days
        try:
            if media.age_days(json.load(open(f)).get("written")) > 45:
                os.remove(f)
        except Exception:
            pass

    written, fails = 0, 0
    for st in feed["stories"]:
        # a take written earlier for any article in this story (ids are stable per article) is reused
        old = next((json.load(open(f)) for f in (os.path.join(OUT, f"{i}.json") for i in st["ids"]) if os.path.exists(f)), None)
        if old is not None:
            st["take"] = old.get("take")
            continue
        players = [skaters_by[p["id"]] for p in st["players"] if p["id"] in skaters_by]
        gks = [goalies_by[p["id"]] for p in st["players"] if p["id"] in goalies_by]
        worth = bool(players or gks) or 1 <= len(st["teams"]) <= 2
        if not worth or client is None or written >= NEWS_MAX or fails >= 3:
            continue
        facts = tidy(dict(reports=[dict(outlet=i["source"], headline=i["title"], summary=i.get("desc"), published=i["published"])
                                   for i in st["items"][:5]],
                          players=[player_card(x) for x in players[:4]], goalies=[goalie_card(x) for x in gks[:2]],
                          teams=[team_card(teams_by[t], prof) for t in st["teams"][:3] if t in teams_by],
                          who_gets_his_minutes=minutes_facts([p["id"] for p in st["players"]]) if st.get("family") == "injury" else None))
        try:
            msg = client.messages.create(model=MODEL, max_tokens=1500, system=STYLE, thinking={"type": "between_tools"},
                                         messages=[{"role": "user", "content": NEWS_TASK + json.dumps(facts, separators=(",", ":"))}])
            text = clean("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
            if getattr(msg, "stop_reason", "end_turn") != "end_turn" or not finished(text):
                raise RuntimeError(f"unfinished take ({len(text.split())} words)")
        except Exception as e:
            fails += 1
            print(f"  ! take {st['id']} failed: {e!r}", file=sys.stderr)
            if fails >= 3:
                print("::warning::Stopping news takes after three failures in a row.", file=sys.stderr)
            continue
        fails = 0
        st["take"] = text
        json.dump(dict(id=st["id"], headline=st["title"], take=text, model=MODEL,
                       written=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")), open(os.path.join(OUT, f"{st['id']}.json"), "w"))
        written += 1
        time.sleep(0.5)

    # takes for stories that have dropped out of the feed are kept three weeks, then removed
    live = {i for st in feed["stories"] for i in st["ids"]}
    for f in glob.glob(os.path.join(OUT, "*.json")):   # (file times are useless after a fresh checkout; use the dates inside)
        stem = os.path.basename(f)[:-5]
        if stem == "index" or stem in live:
            continue
        try:
            d = json.load(open(f))
            if media.age_days(d.get("written") or d.get("published")) > 21:
                os.remove(f)
        except Exception:
            pass

    feed["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(feed, open(os.path.join(OUT, "index.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"takes written: {written}; move notes {noted}; moves {len(feed['moves'])}; stories {len(feed['stories'])}, reads {len(feed['reads'])}, "
          f"listen {len(feed['listen'])}, watch {len(feed['watch'])}, highlights {len(feed['highlights'])}")


if __name__ == "__main__":
    main()
