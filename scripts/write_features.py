"""Ice Sheet's own writing: a weekly "Around the league" column plus player and team deep dives, written by Claude
from this site's numbers only (no web search, no reporting, no quotes).

Runs in the nightly workflow after site/build.py and write_stories.py. At most one scheduled piece a night, so the
three kinds settle into their own days: the column when the last one is a week old, then a player deep dive, then
a team deep dive, each about a week after its last. Requests in data/features/requests.json jump the queue
(up to two a night) and are removed once written:

    [{"kind": "player", "name": "Cale Makar"}, {"kind": "team", "team": "COL"}, {"kind": "column"}]

Pieces are saved under data/features/<season>/<slug>.json (committed, so each is written once) and published to
site/data/features.json (the list) and site/data/features/<slug>.json (the text) on every run, key or not.

Env: ANTHROPIC_API_KEY, STORY_MODEL, FEATURE_MAX (default 3, a spending cap per run).
"""
import datetime as dt, glob, json, math, os, re, sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from write_stories import STYLE, MODEL, SEASON, clean, tidy  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA = os.path.join(ROOT, "site", "data")
FDIR = os.path.join(ROOT, "data", "features", SEASON)
REQ = os.path.join(ROOT, "data", "features", "requests.json")
FEATURE_MAX = int(os.environ.get("FEATURE_MAX", "3"))
FEATURE_VERSION = 1
KIND_LABEL = {"column": "Around the league", "player": "Player deep dive", "team": "Team deep dive"}

FEATURE_STYLE = STYLE.replace("- No headings, no bullet points, no sign-off.",
                              "- Break the piece up with 2 to 4 short subheads, each on its own line starting with '## '. "
                              "No bullet points, no sign-off.") + """
- This site does not report. There are no interviews, quotes, locker-room details, contracts, injuries or backstory beyond what the JSON states. Never imply otherwise ("sources say", "he said", "the coach believes").
- Small samples: when a number covers a handful of games, say so in plain words, and lean on chances (expected goals) over goals when they disagree.
- Start with exactly two lines: "TITLE: " (a specific headline under 70 characters) and "DEK: " (one sentence under 160 characters). Then a blank line, then the piece."""

COLUMN_TASK = """Write "Around the league", this site's weekly column, 650 to 900 words, covering the week in the JSON.
Lead with the most interesting story of the week, then move through the best and strangest games, the players and goalies who owned the week (and whether their chances back it up), the teams trending up and down, milestones and streaks, and the week's notable roster or staff moves if any are listed (state those plainly from the transaction text). Keep it lively and specific; every claim must come from the JSON.
JSON facts:
"""
PLAYER_TASK = """Write a deep dive on this NHL player for this site, 900 to 1,300 words.
Cover who he is (age, where he's from, how he was drafted and his path so far, from the JSON only), what his season looks like, and what is really driving it: his chances versus his results, his role and ice time, where his shots come from, how he skates and shoots if tracking data is given, and how the model sees him. End with what to watch for next and what would change the picture. Use the exact numbers given, and explain why each one matters.
JSON facts:
"""
TEAM_TASK = """Write a deep dive on this NHL team for this site, 900 to 1,300 words.
Cover the record and how it was built: chance creation and prevention, special teams, goaltending, finishing luck, the game-by-game arc, and the players driving it (and any who are running hot or cold). Say whether the record is likely to hold, with the reasons from the numbers. End with what to watch for next. Use the exact numbers given, and explain why each one matters.
JSON facts:
"""


def load(name, default=None):
    try:
        with open(os.path.join(SITE_DATA, name)) as f:
            return json.load(f)
    except Exception:
        return default


def today_local():
    return dt.datetime.now(ZoneInfo("America/Denver")).date()


# ------------------------------------------------------------------ fact sheets

def rank(rows, key, value, high=True):
    vals = sorted((r[key] for r in rows if r.get(key) is not None), reverse=high)
    return vals.index(value) + 1 if value in vals else None


def column_facts(day):
    week = load("week.json", {})
    pulse = load("pulse.json", {})
    teams = load("teams.json", [])
    try:
        with open(os.path.join(ROOT, "data", "news", "index.json")) as f:
            moves = json.load(f).get("moves", [])
    except Exception:
        moves = []
    notable = [dict(date=m["date"], kind=m["kind"], teams=m["teams"], announcements=[i["text"] for i in m["items"]], note=m.get("take"))
               for m in moves if week.get("start", "9") <= m["date"] <= week.get("end", "0") and m["kind"] in ("trade", "staff", "signing")]
    table = sorted(teams, key=lambda t: (-t["pts"], t["gp"]))
    return tidy(dict(week=week, standings_top_five=[dict(team=t["team"], record=f"{t['w']}-{t['l']}-{t['otl']}", points=t["pts"]) for t in table[:5]],
                     standings_bottom_three=[dict(team=t["team"], record=f"{t['w']}-{t['l']}-{t['otl']}", points=t["pts"]) for t in table[-3:]],
                     season_note=pulse.get("note"), notable_moves=notable[:8],
                     due_for_more=[dict(name=x["name"], team=x["team"], why=x["text"]) for x in pulse.get("due", [])[:3]],
                     due_to_cool=[dict(name=x["name"], team=x["team"], why=x["text"]) for x in pulse.get("cooling", [])[:3]]))


def shot_profile(shots):
    """Where a skater's unblocked shots come from: [x, y, xg_milli, goal, ...], x toward the net at +89."""
    if not shots:
        return None
    d = [math.hypot(89 - abs(s[0]), s[1]) for s in shots]
    rows = list(zip(d, shots))
    band = lambda lo, hi: [s for dd, s in rows if lo <= dd < hi]
    out = {}
    for label, lo, hi in (("inside_15_ft", 0, 15), ("15_to_30_ft", 15, 30), ("beyond_30_ft", 30, 999)):
        b = band(lo, hi)
        out[label] = dict(shots=len(b), goals=sum(s[3] for s in b), expected_goals=round(sum(s[2] for s in b) / 1000, 1))
    out["unblocked_shots"] = len(shots)
    out["average_distance_ft"] = round(sum(d) / len(d), 1)
    return out


def form_card(f):
    if not f or not f.get("n"):
        return None
    return dict(games=f["n"], points=f["pts"], goals=f["g"], points_the_model_expected=f.get("xpts"), goals_the_model_expected=f.get("xg"),
                own_expected_goals=f.get("ixg"), his_usual_own_expected_goals_for_that_ice_time=f.get("e_ix"),
                on_ice_expected_goals_for=f.get("ox"), his_usual_on_ice_expected_goals_for=f.get("e_ox"),
                ice_time_minutes_per_game=f.get("toi"), ice_time_change_minutes_per_game=f.get("dtoi"), state=f.get("state"), verdict=f.get("verdict"),
                summary=f.get("text"), streaks=[s["text"] for s in f.get("streaks", [])] or None)


def player_facts(pid):
    sk = {x["id"]: x for x in load("skaters.json", [])}
    x = sk.get(pid)
    if not x:
        return None
    pf = load(f"players/{pid}.json", {}) or {}
    st, ed, log = pf.get("story") or {}, pf.get("edge") or {}, pf.get("log") or []
    shots = (load("shots.json", {}) or {}).get(str(pid), [])
    peers = [s for s in sk.values() if s["pos"] == x["pos"] and s["gp"] >= max(3, x["gp"] // 2)]
    team = next((t for t in load("teams.json", []) if t["team"] == x["team"]), None)
    pulse = load("pulse.json", {})
    lists = [k for k in ("hot", "cold", "breakouts", "cooling", "due", "rookies", "streaks", "droughts") if any(i.get("id") == pid for i in pulse.get(k, []))]
    return tidy(dict(
        player=dict(name=x["name"], team=x["team"], position="defense" if x["pos"] == "D" else "forward", number=x.get("num")),
        bio=st.get("bio"), rookie=st.get("rookie"), career_totals_including_this_season=st.get("career"),
        this_season=dict(games=x["gp"], goals=x["g"], assists=x["a"], points=x["pts"], power_play_points=x.get("ppp"),
                         ice_time_per_game_min=x.get("toi_pg"), shots_on_goal=x.get("sog"), hits=x.get("hits"), blocks=x.get("blk"),
                         own_expected_goals=x.get("ixg"), goals_minus_expected=x.get("g_minus_xg"),
                         team_goals_vs_expected_with_him_on_ice=x.get("oi_luck"),
                         five_on_five_share_of_expected_goals_pct=x.get("xgf5"), team_share_better_with_him_pct_points=x.get("rel5")),
        league_ranks_among_same_position=dict(points=rank(peers, "pts", x["pts"]), own_expected_goals=rank(peers, "ixg", x["ixg"]),
                                              ice_time=rank(peers, "toi_pg", x["toi_pg"]), out_of=len(peers)),
        last_season=dict(team=x.get("p_team"), games=x.get("p_gp"), goals=x.get("p_g"), assists=x.get("p_a"), points=x.get("p_pts"),
                         expected_goals_per_60=x.get("p_ixg60")) if x.get("p_gp") else None,
        model_view=dict(expected_goals_per_60=x.get("m_ixg60"), on_ice_expected_goals_for_per_60=x.get("m_oxgf60"),
                        share_of_on_ice_goals_he_gets_a_point_on=x.get("m_ipp"),
                        note="The model blends this season with last season and his role, because a few weeks of games is too few to trust alone."),
        form_last_games=form_card(st.get("form")), flags=[dict(label=f["label"], text=f["text"]) for f in st.get("flags") or []] or None, milestones_near=[m["text"] for m in st.get("milestones") or []] or None, on_pulse_lists=lists or None,
        game_log_newest_first=[dict(date=g["date"], opponent=g["opp"], home=g["home"], result=g["res"], score=f"{g['gf']}-{g['ga']}",
                                    ice_time=g["toi"], goals=g["g"], assists=g["a"], shots=g["sog"], own_expected_goals=g["ixg"])
                               for g in log[::-1][:12]],
        shot_locations=shot_profile(shots),
        tracking=dict(top_speed_mph=x.get("max_speed_mph"), top_speed_percentile=x.get("max_speed_pctile"), bursts_over_20_mph=x.get("bursts_20mph"),
                      hardest_shot_mph=x.get("top_shot_mph"), hardest_shot_percentile=x.get("top_shot_pctile"),
                      busiest_shot_areas=[dict(area=a["area"], shots_on_goal=a["sog"], goals=a["g"]) for a in (ed.get("areas") or [])[:5]])
        if x.get("max_speed_mph") is not None else None,
        team=dict(team=team["team"], record=f"{team['w']}-{team['l']}-{team['otl']}", share_of_expected_goals_pct=round(team["xg_pct"], 1)) if team else None))


def team_facts(abbr):
    teams = load("teams.json", [])
    t = next((x for x in teams if x["team"] == abbr), None)
    if not t:
        return None
    prof = (load("team_profiles.json", {}) or {}).get(abbr, {})
    allp = load("team_profiles.json", {}) or {}
    plist = [dict(v, team=k) for k, v in allp.items()]
    idx = [g for g in load("games/index.json", []) if abbr in (g["home"], g["away"])]
    idx.sort(key=lambda g: g["date"])
    games = []
    for g in idx:
        home = g["home"] == abbr
        gf, ga = (g["h"], g["a"]) if home else (g["a"], g["h"])
        xf, xa = (g["xg_h"], g["xg_a"]) if home else (g["xg_a"], g["xg_h"])
        games.append(dict(date=g["date"], opponent=g["away"] if home else g["home"], home=home, score=f"{gf}-{ga}",
                          result="W" if gf > ga else ("OTL" if g["end"] != "REG" else "L"), decided_in=g["end"],
                          expected_goals=f"{xf:.2f}-{xa:.2f}", deserved_to_win_pct=round(100 * (g["dtw_home"] if home else 1 - g["dtw_home"]))))
    sk = [x for x in load("skaters.json", []) if x["team"] == abbr]
    gl = [x for x in load("goalies.json", []) if x["team"] == abbr]
    pulse = load("pulse.json", {})
    card = next((c for c in pulse.get("teams", []) if c["team"] == abbr), {})
    on = lambda k: [dict(name=i["name"], why=i.get("why") or i["text"]) for i in pulse.get(k, []) if i.get("team") == abbr]
    sk_card = lambda x: dict(name=x["name"], position=x["pos"], games=x["gp"], goals=x["g"], points=x["pts"], ice_time=x.get("toi_pg"),
                             own_expected_goals=x.get("ixg"), goals_minus_expected=x.get("g_minus_xg"),
                             team_share_better_with_him_pct_points=x.get("rel5"))
    return tidy(dict(
        team=abbr, record=f"{t['w']}-{t['l']}-{t['otl']}", points=t["pts"], games=t["gp"],
        league_rank_by_points=sorted(teams, key=lambda x: (-x["pts"], x["gp"])).index(t) + 1,
        goals_for=t["gf"], goals_against=t["ga"], expected_goals_for=round(t["xgf"], 1), expected_goals_against=round(t["xga"], 1),
        share_of_expected_goals_pct=round(t["xg_pct"], 1), league_rank_share_of_expected_goals=rank(teams, "xg_pct", t["xg_pct"]),
        finishing_goals_minus_expected=round(t["g_minus_xg"], 1), goaltending_goals_saved_above_expected=round(t["xga"] - t["ga"], 1),
        five_on_five_share_of_expected_goals_pct=None if prof.get("xg5_share") is None else round(100 * prof["xg5_share"]),
        power_play_expected_goals_per_game=prof.get("pp_xg_pg"), power_play_rank=rank(plist, "pp_xg_pg", prof.get("pp_xg_pg")),
        penalty_kill_expected_goals_allowed_per_game=prof.get("pk_xga_pg"), penalty_kill_rank=rank(plist, "pk_xga_pg", prof.get("pk_xga_pg"), high=False),
        penalties_taken_per_game=prof.get("pen_taken_pg"), penalties_drawn_per_game=prof.get("pen_drawn_pg"),
        last_ten=card.get("last10"), current_streak=card.get("streak"), record_vs_chances=card.get("luck_text"), storylines=prof.get("story"),
        games_oldest_first=games,
        goalies=[dict(name=g["name"], games=g["gp"], starts=g.get("starts"), save_pct=f'{g["sv_pct"]:.3f}'.lstrip("0") if g.get("sv_pct") else None,
                      goals_saved_above_expected=g.get("gsax"), last_season_goals_saved_above_expected=g.get("prev_gsax")) for g in gl],
        top_scorers=[sk_card(x) for x in sorted(sk, key=lambda x: (-x["pts"], -x["g"]))[:6]],
        most_chances=[sk_card(x) for x in sorted(sk, key=lambda x: -(x.get("ixg") or 0))[:4]],
        play_drivers=[sk_card(x) for x in sorted((x for x in sk if x.get("rel5") is not None and x["gp"] >= 3), key=lambda x: -x["rel5"])[:3]],
        running_hot=on("hot"), running_cold=on("cold"), breakouts=on("breakouts"), due_for_more=on("due"), due_to_cool=on("cooling")))


# ------------------------------------------------------------------ choosing subjects

def existing():
    out = []
    for f in glob.glob(os.path.join(FDIR, "*.json")):
        try:
            with open(f) as fh:
                out.append(json.load(fh))
        except Exception:
            pass
    return sorted(out, key=lambda x: x.get("date", ""), reverse=True)


def days_since(feats, kind, day, key=None):
    ds = [f["date"] for f in feats if f["kind"] == kind and (key is None or f.get("subject", {}).get("key") == key)]
    return (day - dt.date.fromisoformat(max(ds))).days if ds else 999


def pick_player(feats, day):
    pulse = load("pulse.json", {})
    order = ["breakouts", "hot", "due", "rookies", "cooling"]
    week = day.isocalendar()[1]
    for k in order[week % len(order):] + order[:week % len(order)]:
        for x in pulse.get(k, []):
            if k == "hot" and x.get("verdict") == "bounces":
                continue
            if days_since(feats, "player", day, str(x["id"])) > 90:
                return x["id"]
    return None


def pick_team(feats, day):
    pulse = load("pulse.json", {})
    for c in sorted(pulse.get("teams", []), key=lambda c: -(c.get("weight") or 0)):
        if days_since(feats, "team", day, c["team"]) > 45:
            return c["team"]
    return None


def resolve(req):
    if req.get("kind") == "player":
        if req.get("id"):
            return int(req["id"])
        name = (req.get("name") or "").lower()
        hit = [x for x in load("skaters.json", []) if x["name"].lower() == name]
        return hit[0]["id"] if hit else None
    if req.get("kind") == "team":
        t = (req.get("team") or "").upper()
        return t if any(x["team"] == t for x in load("teams.json", [])) else None
    return "week"


# ------------------------------------------------------------------ writing

def split(text):
    """'TITLE: ...' and 'DEK: ...' lines, then the body."""
    title = re.search(r"^\s*TITLE:\s*(.+)$", text, re.M)
    dek = re.search(r"^\s*DEK:\s*(.+)$", text, re.M)
    body = re.sub(r"^\s*(TITLE|DEK):.*$", "", text, flags=re.M).strip()
    return (title.group(1).strip().strip('"') if title else None), (dek.group(1).strip() if dek else None), body


def write_long(client, task, facts, min_words):
    kw = dict(model=MODEL, max_tokens=8000, system=FEATURE_STYLE,
              messages=[{"role": "user", "content": task + json.dumps(facts, separators=(",", ":"), ensure_ascii=False)}])
    try:
        msg = client.messages.create(thinking={"type": "between_tools"}, **kw)
    except Exception as e:
        if "thinking" not in str(e).lower() or type(e).__name__ != "BadRequestError":
            raise
        msg = client.messages.create(**kw)
    text = clean("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
    title, dek, body = split(text)
    words = len(body.split())
    if getattr(msg, "stop_reason", "end_turn") != "end_turn" or not title or words < min_words or body[-1:] not in '.!?)"”':
        raise RuntimeError(f"unfinished feature (stop_reason={getattr(msg, 'stop_reason', None)}, title={bool(title)}, {words} words)")
    return title, dek, body


def publish(feats):
    """The list and the texts, into site/data for this deploy."""
    os.makedirs(os.path.join(SITE_DATA, "features"), exist_ok=True)
    keep = [f for f in feats if f.get("v", 0) >= 1 and f.get("text")]
    for f in keep:
        with open(os.path.join(SITE_DATA, "features", f"{f['slug']}.json"), "w") as fh:
            json.dump(f, fh, separators=(",", ":"), ensure_ascii=False)
    with open(os.path.join(SITE_DATA, "features.json"), "w") as fh:
        json.dump([{k: f.get(k) for k in ("slug", "kind", "title", "dek", "date", "subject", "teams", "words")} for f in keep], fh,
                  separators=(",", ":"), ensure_ascii=False)
    print(f"features published: {len(keep)}")


def main(client=None):
    os.makedirs(FDIR, exist_ok=True)
    feats = existing()
    publish(feats)
    if client is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            print("No ANTHROPIC_API_KEY set; publishing existing features only.")
            return
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    day = today_local()
    names = {x["id"]: x for x in load("skaters.json", [])}

    jobs = []   # (kind, subject key, from request?)
    try:
        with open(REQ) as f:
            reqs = json.load(f)
    except Exception:
        reqs = []
    for r in reqs[:2]:
        jobs.append((r.get("kind"), resolve(r), r))
    if not jobs:   # one scheduled piece a night: the column, then a player, then a team, each about weekly
        if days_since(feats, "column", day) >= 7 and load("week.json", {}).get("games"):
            jobs.append(("column", "week", None))
        elif days_since(feats, "player", day) >= 7 and (p := pick_player(feats, day)):
            jobs.append(("player", p, None))
        elif days_since(feats, "team", day) >= 7 and (t := pick_team(feats, day)):
            jobs.append(("team", t, None))

    done_reqs, written = [], 0
    for kind, key, req in jobs[:FEATURE_MAX]:
        if key is None:
            print(f"  ! couldn't resolve request {req}")
            done_reqs.append(req)
            continue
        if kind == "column":
            facts, task, minw, subject, teams = column_facts(day), COLUMN_TASK, 450, dict(key="week"), []
            slug = f"column-{day}"
        elif kind == "player":
            facts, task, minw = player_facts(key), PLAYER_TASK, 650
            x = names.get(key, {})
            subject, teams, slug = dict(key=str(key), id=key, name=x.get("name"), team=x.get("team")), [x.get("team")], f"player-{key}-{day}"
        else:
            facts, task, minw = team_facts(key), TEAM_TASK, 650
            subject, teams, slug = dict(key=key, team=key), [key], f"team-{key}-{day}"
        if not facts:
            print(f"  ! no facts for {kind} {key}")
            continue
        try:
            title, dek, body = write_long(client, task, facts, minw)
        except Exception as e:
            print(f"  ! {kind} {key} failed: {e!r}", file=sys.stderr)
            continue
        f = dict(slug=slug, kind=kind, title=title, dek=dek, date=str(day), subject=subject, teams=[t for t in teams if t],
                 text=body, words=len(body.split()), model=MODEL, v=FEATURE_VERSION,
                 written=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        with open(os.path.join(FDIR, f"{slug}.json"), "w") as fh:
            json.dump(f, fh, ensure_ascii=False, indent=1)
        feats.insert(0, f)
        written += 1
        if req is not None:
            done_reqs.append(req)
        print(f"  wrote {kind}: {title} ({f['words']} words)")
    if done_reqs:
        left = [r for r in reqs if r not in done_reqs]
        with open(REQ, "w") as fh:
            json.dump(left, fh, indent=1)
    publish(feats)
    print(f"features written: {written}")


if __name__ == "__main__":
    main()
