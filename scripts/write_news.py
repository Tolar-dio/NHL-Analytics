"""Hourly: a short Claude take on each new NHL headline, built from ESPN's headline and summary
plus this site's own numbers for the players and teams involved. No web search (about 1 cent each).

Reads ESPN's public news feed and the site's published data (skaters, goalies, teams, team profiles)
from GitHub Pages, so it needs no model run. Writes data/news/<espn id>.json and data/news/index.json;
the site reads the index from raw.githubusercontent.com, so new takes show up without a redeploy.

Env: ANTHROPIC_API_KEY (skips quietly without it), STORY_MODEL, NEWS_MAX (per run, default 8).
"""
import datetime as dt, glob, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from write_stories import STYLE, MODEL, clean, finished, tidy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "news")
ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news?limit=40"
SITE = os.environ.get("SITE_DATA_URL", "https://tolar-dio.github.io/NHL-Analytics/data/")
NEWS_MAX = int(os.environ.get("NEWS_MAX", "8"))
KEEP = {"HeadlineNews", "Story"}
ESPN_TEAM = {1: "BOS", 2: "BUF", 3: "CGY", 4: "CHI", 5: "DET", 6: "EDM", 7: "CAR", 8: "LAK", 9: "DAL", 10: "MTL",
             11: "NJD", 12: "NYI", 13: "NYR", 14: "OTT", 15: "PHI", 16: "PIT", 17: "COL", 18: "SJS", 19: "STL", 20: "TBL",
             21: "TOR", 22: "VAN", 23: "WSH", 25: "ANA", 26: "FLA", 27: "NSH", 28: "WPG", 29: "CBJ", 30: "MIN", 37: "VGK",
             124292: "SEA", 129764: "UTA"}

NEWS_TASK = """Write a short take on this NHL news item for a hockey analytics site, 2 short paragraphs, 120 to 180 words total.
First, state what happened in one or two sentences, credited to ESPN ("per ESPN"), using only the headline and summary given. Do not add details the summary doesn't contain.
Then spend the rest on what this site's numbers say about the players or teams involved and why that matters: for the team's strength, a player's real level versus his results, fantasy value, or what changes on the ice. Only use numbers from the JSON, and say "so far this season" where the sample is small.
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
        if not key:
            print("No ANTHROPIC_API_KEY set; skipping news takes.")
            return
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    os.makedirs(OUT, exist_ok=True)
    news = get(ESPN_NEWS).get("articles", [])
    skaters, goalies, teams = get(SITE + "skaters.json"), get(SITE + "goalies.json"), get(SITE + "teams.json")
    try:
        prof = get(SITE + "team_profiles.json")
    except Exception:
        prof = {}
    sk_by = {norm(x["name"]): x for x in skaters}
    gl_by = {norm(x["name"]): x for x in goalies}
    tm_by = {t["team"]: t for t in teams}

    written, fails = 0, 0
    for a in news:
        if a.get("type") not in KEEP or written >= NEWS_MAX:
            continue
        path = os.path.join(OUT, f'{a["id"]}.json')
        if os.path.exists(path):
            continue
        cats = a.get("categories", [])
        names = [c.get("description") for c in cats if c.get("type") == "athlete"]
        # ESPN team ids repeat across leagues (Arizona State is 9, like Dallas), so check the uid's league (l:90 is the NHL)
        nhl_team = lambda c: c.get("type") == "team" and "~l:90~" in (c.get("uid") or "")
        team_ab = sorted({ESPN_TEAM.get(c.get("teamId")) for c in cats if nhl_team(c)} - {None})
        players = [sk_by[norm(n)] for n in names if norm(n) in sk_by]
        gks = [gl_by[norm(n)] for n in names if norm(n) in gl_by]
        base = dict(id=a["id"], type=a["type"], headline=a.get("headline"), description=a.get("description"),
                    published=a.get("published"), link=(a.get("links") or {}).get("web", {}).get("href"), teams=team_ab,
                    players=[dict(id=x["id"], name=x["name"], team=x["team"]) for x in players + gks])
        other_league = any(c.get("type") == "team" and not nhl_team(c) for c in cats)
        # worth a take: a player we track, or a hard-news item about one or two teams; never roundups or other leagues
        newsy = bool(players or gks) or (a["type"] == "HeadlineNews" and 1 <= len(team_ab) <= 2)
        if other_league or len(team_ab) > 3 or not newsy:
            json.dump(base | dict(take=None, skipped="not a story about NHL players or teams we track"), open(path, "w"))
            continue
        facts = tidy(dict(headline=a.get("headline"), summary=a.get("description"), published=a.get("published"), source="ESPN",
                          players=[player_card(x) for x in players[:4]], goalies=[goalie_card(x) for x in gks[:2]],
                          teams=[team_card(tm_by[t], prof) for t in team_ab[:3] if t in tm_by]))
        try:
            msg = client.messages.create(model=MODEL, max_tokens=1500, system=STYLE, thinking={"type": "between_tools"},
                                         messages=[{"role": "user", "content": NEWS_TASK + json.dumps(facts, separators=(",", ":"))}])
            text = clean("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
            if getattr(msg, "stop_reason", "end_turn") != "end_turn" or not finished(text):
                raise RuntimeError(f"unfinished take ({len(text.split())} words)")
        except Exception as e:
            fails += 1
            print(f"  ! take {a['id']} failed: {e!r}", file=sys.stderr)
            if fails >= 3:
                print("::warning::Stopping news takes after three failures in a row.", file=sys.stderr)
                break
            continue
        fails = 0
        json.dump(base | dict(take=text, model=MODEL, written=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
                  open(path, "w"))
        written += 1
        time.sleep(0.5)

    items = []
    for f in glob.glob(os.path.join(OUT, "[0-9]*.json")):
        d = json.load(open(f))
        if d.get("take"):
            items.append({k: d.get(k) for k in ("id", "headline", "description", "published", "link", "teams", "players", "take")})
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    json.dump(dict(updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), items=items[:80]),
              open(os.path.join(OUT, "index.json"), "w"), separators=(",", ":"))
    print(f"news takes written: {written}, index holds {min(len(items), 80)}")


if __name__ == "__main__":
    main()
