"""What the AI writers may know about a player beyond our numbers, and the rule for quoting it.

  path    his path to the NHL: the dossier site/dossier.py writes into players/<id>.json (goalies/<id>.json)
  said    what's being said about him: data/coverage/players/<id>.json from scripts/buzz.py
          (headlines, reporters' public posts, his team's video titles; Reddit threads are never included)

Standard library only: the hourly news job runs without pandas.
"""
import datetime as dt
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COV = os.path.join(ROOT, "data", "coverage")

QUOTE_RULE = ("- Quotes: only words that appear verbatim in a headline, reporter's post or video title in the JSON, attributed to the "
              "outlet or reporter (\"as Corey Masisak of the Denver Post posted, ...\"). Never put words in anyone's mouth, never present "
              "a paraphrase as a quote, and never imply we spoke to anyone. Headlines and posts are other people's reporting: say whose "
              "it is when you use it.")


def _age_days(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds() / 86400
    except Exception:
        return 999


def coverage(pid):
    try:
        with open(os.path.join(COV, "players", f"{int(pid)}.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def team_coverage(team):
    try:
        with open(os.path.join(COV, "teams", f"{team}.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def dossier_local(pid, site_data):
    for sub in ("players", "goalies"):
        try:
            with open(os.path.join(site_data, sub, f"{int(pid)}.json")) as f:
                d = json.load(f).get("dossier")
            if d:
                return d
        except Exception:
            continue
    return None


def dossier_remote(pid, site_url):
    for sub in ("players", "goalies"):
        try:
            req = urllib.request.Request(f"{site_url}{sub}/{int(pid)}.json", headers={"User-Agent": "NHL-Analytics news job"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r).get("dossier")
            if d:
                return d
        except Exception:
            continue
    return None


def said(cov, news=4, posts=2, videos=2, days=21):
    """Recent headlines, reporters' posts and team video titles, attributed. Never Reddit."""
    if not cov:
        return {}
    out = dict(
        recent_headlines=[dict(headline=n["t"], outlet=n.get("o"), date=(n.get("d") or "")[:10])
                          for n in cov.get("news", []) if _age_days(n.get("d")) <= days][:news] or None,
        reporters_posts=[dict(text=p["t"][:400], reporter=p.get("a"), outlet=p.get("o"), date=(p.get("d") or "")[:10])
                         for p in cov.get("posts", []) if _age_days(p.get("d")) <= min(days, 10)][:posts] or None,
        team_videos=[dict(title=v["t"], date=(v.get("d") or "")[:10]) for v in cov.get("videos", [])
                     if _age_days(v.get("d")) <= days][:videos] or None,
    )
    return {k: v for k, v in out.items() if v}


def path(d, notes=3, wiki_chars=0, seasons=0):
    """Path to the NHL: the dossier's sentences, optionally his last pre-NHL seasons, international play and the
    lead of his Wikipedia article (CC BY-SA; the writer may use facts from it)."""
    if not d:
        return {}
    out = dict(path_to_the_nhl=(d.get("notes") or [])[:notes] or None)
    if seasons:
        out["pre_nhl_seasons"] = [{k: r.get(k) for k in ("season", "league", "teams", "gp", "g", "a", "p", "nhle82") if r.get(k) is not None}
                                  for r in (d.get("pre") or [])[-seasons:]] or None
        out["international"] = [{k: r.get(k) for k in ("season", "event", "team", "gp", "g", "a", "p")} for r in (d.get("intl") or [])[-5:]] or None
        out["nhl_awards"] = d.get("awards") or None
        c = d.get("comps")
        if c:
            out["players_drafted_around_him"] = dict(group=c["group"], players=c["n"], with_four_plus_seasons=c.get("established_n"),
                                                     reached_200_nhl_games=c.get("reached_200"),
                                                     median_points_per_game_first_full_season=c.get("first_full_ppg_median"),
                                                     closest=[dict(name=r["name"], draft=f"{r['year']} #{r['overall']}", nhl_games=r["nhl_gp"],
                                                                   first_full_season=r.get("first_full")) for r in c.get("list", [])[:4]])
    if wiki_chars and d.get("wiki"):
        text = d["wiki"]["extract"][:wiki_chars]
        out["background_from_wikipedia"] = text if len(d["wiki"]["extract"]) <= wiki_chars else text.rsplit(". ", 1)[0] + "."
    return {k: v for k, v in out.items() if v}
