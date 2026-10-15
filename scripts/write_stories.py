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

STYLE = """House style, follow exactly:
- Plain, vivid sportswriting for one die-hard fan who knows hockey and analytics. No hype words, no cliches, no exclamation marks.
- Never use em dashes or en dashes. Use commas, periods or parentheses.
- Use ONLY facts in the JSON. Do not invent quotes, injuries, attendance, streaks, records, standings, history, or anything else not present. If something isn't in the data, leave it out.
- Tell the story of the game, and when you cite a number, say why it matters (what it reveals about how the game was really played).
- "Expected goals" means the quality of chances; "deserved to win" is the share of simulated replays of every shot that the team wins. Use them to separate how the game was played from how it ended.
- Use full player names the first time, last names after. Write team abbreviations as given.
- No headings, no bullet points, no sign-off."""

RECAP_TASK = """Write a recap of this NHL game in 3 short paragraphs, 170 to 230 words total.
Open with the decisive moment or the gap between result and play, not with the final score sentence template.
JSON facts:
"""

PREVIEW_TASK = """Write a preview of tonight's NHL game in 3 short paragraphs, 160 to 220 words total.
Cover how the teams compare in chance creation and prevention, special teams, the goalie matchup (this season and last), recent form, and one or two players the model likes tonight (use the probabilities as given). Projected goalies may change; say "projected" when naming them.
JSON facts:
"""


def _score(g, s):
    a, h = s.split("-")
    return f'{g["away"]} {a}, {g["home"]} {h}'


def tidy(o):
    """Round floats so the writer quotes 2.15, not 2.145 (shares and percents keep one decimal)."""
    if isinstance(o, float):
        return round(o, 2)
    if isinstance(o, dict):
        return {k: tidy(v) for k, v in o.items()}
    if isinstance(o, list):
        return [tidy(v) for v in o]
    return o


def recap_facts(g):
    players = [p for p in g["players"]][:8]
    return tidy(dict(
        date=g["date"], venue=g.get("venue"), away=g["away"], home=g["home"],
        final=f'{g["away"]} {g["a"]}, {g["home"]} {g["h"]}', decided_in=g["end"],
        expected_goals={g["away"]: g["xg_a"], g["home"]: g["xg_h"]},
        even_strength_expected_goals={g["away"]: g["xg5_a"], g["home"]: g["xg5_h"]},
        shot_attempts={g["away"]: g["cf_a"], g["home"]: g["cf_h"]},
        deserved_to_win_pct={g["home"]: round(100 * g["dtw_home"]), g["away"]: round(100 * (1 - g["dtw_home"]))},
        expected_goals_by_period=[{"period": x["p"], g["away"]: x["xg_a"], g["home"]: x["xg_h"]} for x in g["periods"]],
        goals=[dict(period=x["period"], time=x["t"], team=x["team"], scorer=x["name"],
                    assists=[a["name"] for a in x["assists"]], strength=x["strength"], shot_type=x["shot"],
                    score_after=_score(g, x["score"]),
                    chance_of_scoring_pct=None if x["xg"] is None else round(100 * x["xg"])) for x in g["goals"]],
        shootout=g["shootout"] or None,
        three_stars=[{k: s[k] for k in ("star", "name", "team", "g", "a")} for s in g["stars"]],
        goalies=[{k: x[k] for k in ("name", "team", "sa", "ga", "xga", "gsax")} | {"saves_above_expected": x["gsax"]}
                 for x in g["goalies"] if x["toi"] and x["toi"] > 5],
        top_performers=[{k: p[k] for k in ("name", "team", "pos", "toi", "g", "a", "sog", "ixg", "xgf", "xga")}
                        for p in players],
        team_stats=g.get("team_stats"),
        earlier_meetings_this_season=[x for x in g["series"] if x["date"] < g["date"] and x["a"] is not None],
    ))


def preview_facts(p):
    return tidy(dict(date=p["date"], away=p["away"], home=p["home"],
                model_expected_goals_tonight={p["away"]: p["away_xg"], p["home"]: p["home_xg"]},
                teams=p["teams"], projected_goalies=p["goalies"],
                season_series=[x for x in p["series"] if x["a"] is not None],
                players_model_likes={t: dict(score_a_goal=[{"name": x["name"], "prob": round(x["p_goal"], 2)} for x in v["goal"]],
                                             two_plus_points=[{"name": x["name"], "prob": round(x["p_2pts"], 2)} for x in v["pts"]])
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
        return finished(json.load(open(path)).get("text"))
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
        json.dump(dict(text=text, model=MODEL, written=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')), open(out, "w"))
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
        json.dump(dict(text=text, model=MODEL, written=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')), open(out, "w"))
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
