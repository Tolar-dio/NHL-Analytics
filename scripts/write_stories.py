"""Write game recaps and previews with Claude, once per game.

Runs in the nightly workflow after site/build.py. For every finished game
without a recap, and every game on today's slate without a preview, it sends
Claude a compact fact sheet built from the site's own JSON and saves the
result to data/stories/<season>/{recaps,previews/<date>}/<game_id>.json.
Stories are committed, so each game is only ever written (and paid for) once.
It also patches the freshly built site JSON so tonight's deploy shows them.

Needs the ANTHROPIC_API_KEY secret. Without it, this exits quietly and the
site simply shows the numbers.

Env:
  STORY_MODEL   default claude-sonnet-5-5
  STORY_MAX     max stories written per run (default 60), a spending cap
"""
import datetime as dt, glob, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA = os.path.join(ROOT, "site", "data")
SEASON = "20262027"
MODEL = os.environ.get("STORY_MODEL", "claude-sonnet-5-5")
MAX_STORIES = int(os.environ.get("STORY_MAX", "60"))

STORY_VERSION = 2   # bump to rewrite every cached story on the next run (v2: labelled fact sheets after v1 swapped teams)

STYLE = """House style, follow exactly:
- Plain, vivid sportswriting for one die-hard fan who knows hockey and analytics. No hype words, no cliches, no exclamation marks.
- Never use em dashes or en dashes. Use commas, periods or parentheses.
- Use ONLY facts in the JSON. Do not invent quotes, injuries, attendance, streaks, records, standings, history, line combinations, or anything else not present. If something isn't in the data, leave it out.
- Never count, add, subtract or convert anything yourself. Quote numbers exactly as the JSON gives them, and when the JSON gives a summary (a record, a count, a total), use the summary instead of tallying a list.
- Every team number is labelled with its team abbreviation. Check the label before you attribute a number to a team or its goalie.
- Keep events in the order they happened. Goals are listed in time order; don't describe an earlier goal as a response to a later one.
- Tell the story of the game, and when you cite a number, say why it matters (what it reveals about how the game was really played).
- "Expected goals" means the quality of chances; "deserved to win" is the share of simulated replays of every shot that the team wins. Use them to separate how the game was played from how it ended.
- Use full player names the first time, last names after. Write team abbreviations as given.
- No headings, no bullet points, no sign-off."""

RECAP_TASK = """Write a recap of this NHL game in 3 short paragraphs, 170 to 230 words total.
Open with the decisive moment or the gap between result and play, not with the final score sentence template.
JSON facts:
"""

PREVIEW_TASK = """Write a preview of tonight's NHL game in 3 short paragraphs, 160 to 220 words total.
Cover how the teams compare in chance creation and prevention, special teams, the goalie matchup (this season and last), recent form (use each team's last_five summary), and one or two players worth watching (use the probabilities and reasons as given). Work in the one or two storylines that matter most, as written in the facts, and when a storyline says the model doesn't price it, don't claim it will decide the game. Projected goalies may change; say "projected" when naming them.
JSON facts:
"""


def _score(g, s):
    a, h = s.split("-")
    return f'{g["away"]} {a}, {g["home"]} {h}'


def _mmss(minutes):
    if minutes is None:
        return None
    sec = int(round(minutes * 60))
    return f"{sec // 60}:{sec % 60:02d}"


def _sv(x):
    return None if x is None else f"{x:.3f}".lstrip("0")    # ".934", the way save percentage is written


def tidy(o):
    """Round floats to 2 places so the writer quotes 2.15, not 2.145. Anything that needs more
    precision (save percentage) is passed as a preformatted string."""
    if isinstance(o, float):
        return int(o) if o.is_integer() else round(o, 2)   # counts stored as floats read as 7, not 7.0
    if isinstance(o, dict):
        return {k: tidy(v) for k, v in o.items()}
    if isinstance(o, list):
        return [tidy(v) for v in o]
    return o


def _by_team(g, pair):
    """NHL team stats come as [away, home]; label them so the writer can't swap teams."""
    return None if not pair else {g["away"]: pair[0], g["home"]: pair[1]}


TEAM_STAT_NAMES = {"sog": "shots_on_goal", "powerPlay": "power_play_goals_for_chances", "pim": "penalty_minutes",
                   "hits": "hits", "blockedShots": "blocked_shots", "giveaways": "giveaways", "takeaways": "takeaways",
                   "faceoffWins": "faceoffs_won_of_total"}


def recap_facts(g):
    players = [p for p in g["players"]][:8]
    ts = g.get("team_stats") or {}
    return tidy(dict(
        date=g["date"], venue=g.get("venue"), away=g["away"], home=g["home"],
        final=f'{g["away"]} {g["a"]}, {g["home"]} {g["h"]}', decided_in=g["end"],
        expected_goals={g["away"]: g["xg_a"], g["home"]: g["xg_h"]},
        even_strength_expected_goals={g["away"]: g["xg5_a"], g["home"]: g["xg5_h"]},
        shot_attempts={g["away"]: g["cf_a"], g["home"]: g["cf_h"]},
        deserved_to_win_pct={g["home"]: round(100 * g["dtw_home"]), g["away"]: round(100 * (1 - g["dtw_home"]))},
        expected_goals_by_period=[{"period": x["p"], g["away"]: x["xg_a"], g["home"]: x["xg_h"]} for x in g["periods"]],
        goals_in_time_order=[dict(period=x["period"], time=x["t"], team=x["team"], scorer=x["name"],
                                  assists=[a["name"] for a in x["assists"]], strength=x["strength"], shot_type=x["shot"],
                                  score_after=_score(g, x["score"]),
                                  chance_of_scoring_pct=None if x["xg"] is None else round(100 * x["xg"]))
                             for x in g["goals"]],
        shootout_in_order=[dict(round=i // 2 + 1, team=x["team"], shooter=x["name"],
                                result="scored" if x["result"] == "goal" else "stopped") for i, x in enumerate(g["shootout"])] or None,
        three_stars=[{k: s[k] for k in ("star", "name", "team", "g", "a")} for s in g["stars"]],
        goalies=[dict(name=x["name"], team=x["team"], shots_faced=x["sa"], goals_allowed=x["ga"], saves=x["sa"] - x["ga"],
                      expected_goals_against=x["xga"], goals_saved_above_expected=x["gsax"])
                 for x in g["goalies"] if x["toi"] and x["toi"] > 5],
        top_performers=[dict(name=p["name"], team=p["team"], pos=p["pos"], ice_time=_mmss(p["toi"]), goals=p["g"],
                             assists=p["a"], shots_on_goal=p["sog"], own_expected_goals=p["ixg"],
                             on_ice_expected_goals_for=p["xgf"], on_ice_expected_goals_against=p["xga"])
                        for p in players],
        team_stats={TEAM_STAT_NAMES.get(k, k): _by_team(g, v) for k, v in ts.items()
                    if k in TEAM_STAT_NAMES},
        data_notes=g.get("notes") or None,
        earlier_meetings_this_season=[dict(date=x["date"], final=f'{x["away"]} {x["a"]}, {x["home"]} {x["h"]}', decided_in=x["end"])
                                      for x in g["series"] if x["date"] < g["date"] and x["a"] is not None],
    ))


def _last_five(t):
    games = []
    for x in t["last5"]:
        res = "W" if x["gf"] > x["ga"] else ("OTL" if x["end"] != "REG" else "L")
        games.append(dict(date=x["date"], opponent=x["opp"], where="home" if x["home"] else "away", result=res,
                          score=f'{x["gf"]}-{x["ga"]}', decided_in=x["end"], share_of_expected_goals_pct=round(100 * x["xg_share"]),
                          won_the_chance_battle=x["xg_share"] > 0.5))
    w = sum(g["result"] == "W" for g in games)
    otl = sum(g["result"] == "OTL" for g in games)
    return dict(record=f"{w}-{len(games) - w - otl}-{otl}", games=len(games),
                games_with_more_expected_goals=sum(g["won_the_chance_battle"] for g in games),
                average_share_of_expected_goals_pct=round(sum(g["share_of_expected_goals_pct"] for g in games) / max(len(games), 1)),
                games_newest_last=games)


def _team_card(t):
    return dict(games_played=t["gp"], expected_goals_for_per_60=t["xgf60"], expected_goals_against_per_60=t["xga60"],
                five_on_five_share_of_expected_goals_pct=None if t["xg5_share"] is None else round(100 * t["xg5_share"]),
                goals_for_per_game=t["gf_pg"], goals_against_per_game=t["ga_pg"],
                power_play_expected_goals_per_game=t["pp_xg_pg"], penalty_kill_expected_goals_allowed_per_game=t["pk_xga_pg"],
                penalties_taken_per_game=t["pen_taken_pg"], penalties_drawn_per_game=t["pen_drawn_pg"],
                rest_days_before_tonight=t.get("rest_days"), last_game_date=t.get("last_date"), last_five=_last_five(t))


def _goalie_card(x):
    if not x:
        return None
    return dict(name=x["name"], games_this_season=x["gp"], save_pct_this_season=_sv(x["sv_pct"]),
                goals_saved_above_expected_this_season=x["gsax"],
                games_last_season=None if x["prev_gp"] is None else int(x["prev_gp"]),
                goals_saved_above_expected_last_season=x["prev_gsax"])


def preview_facts(p):
    return tidy(dict(date=p["date"], away=p["away"], home=p["home"],
                     model_expected_goals_tonight={p["away"]: p["away_xg"], p["home"]: p["home_xg"]},
                     teams={t: _team_card(p["teams"][t]) for t in (p["away"], p["home"])},
                     projected_goalies={t: _goalie_card(p["goalies"].get(t)) for t in (p["away"], p["home"])},
                     earlier_meetings_this_season=[dict(date=x["date"], final=f'{x["away"]} {x["a"]}, {x["home"]} {x["h"]}', decided_in=x["end"])
                                                   for x in p["series"] if x["a"] is not None],
                     data_notes=p.get("notes") or None,
                     storylines=[dict(team=x.get("team"), story=x["text"], in_the_model=bool(x.get("priced")))
                                 for x in (p.get("storylines") or [])[:6]] or None,
                     players_to_watch={t: [dict(name=w["name"], reasons=[c["t"] for c in w["chips"]], score_a_goal_pct=round(100 * w["p_goal"]),
                                                point_pct=round(100 * w["p_1pt"])) for w in ws]
                                       for t, ws in (p.get("watch") or {}).items()} or None,
                     players_model_likes={t: dict(score_a_goal=[{"name": x["name"], "pct": round(100 * x["p_goal"])} for x in v["goal"]],
                                                  two_plus_points=[{"name": x["name"], "pct": round(100 * x["p_2pts"])} for x in v["pts"]])
                                          for t, v in p["props"].items()}))


def clean(text):
    text = text.strip()
    text = re.sub(r"\s*[—–]\s*", ", ", text)    # no em/en dashes, house style
    return text


def finished(text):
    """A usable story: long enough and ends on a full sentence. Anything else gets rewritten next run."""
    t = (text or "").strip()
    return len(t.split()) >= 80 and t[-1:] in '.!?)"\u201d'


def write(client, task, facts):
    # Sonnet 5.5 thinks before answering by default, and that hidden thinking counts against max_tokens.
    # With a 600 cap the first run spent the whole budget thinking: 88 blank stories, 30 cut off mid-sentence.
    # These are short writing jobs from a fact sheet, so skip up-front thinking and leave plenty of headroom.
    kw = dict(model=MODEL, max_tokens=2000, system=STYLE,
              messages=[{"role": "user", "content": task + json.dumps(facts, separators=(",", ":"))}])
    try:
        msg = client.messages.create(thinking={"type": "between_tools"}, **kw)
    except Exception as e:
        if "thinking" not in str(e).lower() or type(e).__name__ != "BadRequestError":
            raise
        msg = client.messages.create(**(kw | {"max_tokens": 6000}))   # model without that setting
    text = clean("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
    if getattr(msg, "stop_reason", "end_turn") != "end_turn" or not finished(text):
        raise RuntimeError(f"unfinished story (stop_reason={getattr(msg, 'stop_reason', None)}, {len(text.split())} words)")
    return text, getattr(msg, "usage", None)


def cached(path):
    """True when a good story is already saved; blank or cut-off ones count as missing."""
    if not os.path.exists(path):
        return False
    try:
        d = json.load(open(path))
        return d.get("v", 1) >= STORY_VERSION and finished(d.get("text"))
    except Exception:
        return False


def main(client=None):
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("No ANTHROPIC_API_KEY set; skipping stories.")
            return
        import anthropic
        # Pasted secrets often carry a trailing newline or space; httpx then refuses the header and the SDK
        # reports it as a vague "Connection error." Strip it.
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    budget = MAX_STORIES
    used_in = used_out = 0
    fails = [0]
    stop = False

    def failed(kind, gid, e):
        """Log one failure with its real cause; give up after 3 in a row so a bad key doesn't burn the run."""
        cause = f" (cause: {e.__cause__!r})" if getattr(e, "__cause__", None) else ""
        print(f"  ! {kind} {gid} failed: {e!r}{cause}", file=sys.stderr)
        fails[0] += 1
        if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError", "NotFoundError") or fails[0] >= 3:
            print("::warning::Stopping stories after three failures in a row (see the lines above). Usually the "
                  "ANTHROPIC_API_KEY secret, STORY_MODEL, or an API outage.", file=sys.stderr)
            return True
        return False

    # previews first: they're only useful today
    tonight = json.load(open(os.path.join(SITE_DATA, "tonight.json")))
    pdir = os.path.join(ROOT, "data", "stories", SEASON, "previews", tonight["date"])
    os.makedirs(pdir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(SITE_DATA, "previews", "*.json"))):
        if budget <= 0:
            break
        p = json.load(open(path))
        out = os.path.join(pdir, f"{p['id']}.json")
        if cached(out):
            continue
        try:
            text, usage = write(client, PREVIEW_TASK, preview_facts(p))
        except Exception as e:  # one failure must not sink the run
            if failed("preview", p["id"], e):
                stop = True
                break
            continue
        fails[0] = 0
        json.dump(dict(text=text, v=STORY_VERSION, model=MODEL, written=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')), open(out, "w"))
        p["story"] = text
        json.dump(p, open(path, "w"), separators=(",", ":"))
        budget -= 1
        if usage:
            used_in += usage.input_tokens; used_out += usage.output_tokens
        time.sleep(0.5)

    # recaps, newest games first
    rdir = os.path.join(ROOT, "data", "stories", SEASON, "recaps")
    os.makedirs(rdir, exist_ok=True)
    idx_path = os.path.join(SITE_DATA, "games", "index.json")
    index = json.load(open(idx_path))
    changed = False
    for row in index:
        if budget <= 0 or stop:
            break
        out = os.path.join(rdir, f"{row['id']}.json")
        if cached(out):
            continue
        gpath = os.path.join(SITE_DATA, "games", f"{row['id']}.json")
        g = json.load(open(gpath))
        try:
            text, usage = write(client, RECAP_TASK, recap_facts(g))
        except Exception as e:
            if failed("recap", row["id"], e):
                break
            continue
        fails[0] = 0
        json.dump(dict(text=text, v=STORY_VERSION, model=MODEL, written=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')), open(out, "w"))
        g["story"] = text
        json.dump(g, open(gpath, "w"), separators=(",", ":"))
        row["has_story"], row["blurb"] = True, text.split(". ")[0] + "."
        changed = True
        budget -= 1
        if usage:
            used_in += usage.input_tokens; used_out += usage.output_tokens
        time.sleep(0.5)
    if changed:
        json.dump(index, open(idx_path, "w"), separators=(",", ":"))
    print(f"stories written: {MAX_STORIES - budget}, tokens in {used_in}, out {used_out}, model {MODEL}")


if __name__ == "__main__":
    main()
