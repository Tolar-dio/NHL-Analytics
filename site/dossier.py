"""Player dossiers: where each player came from, how he got here, and what the hockey world is saying about him.

Built nightly by build.py into players/<id>.json (and goalies/<id>.json) as `dossier`, and handed to the AI writers.
Sources, all credited where shown:
  NHL.com player pages (scripts/fetch_external.py bios): every league season, international tournaments, awards, draft
  NHL records API and Central Scouting (data/external/draft/<year>.json): the pick, who went around him, his CS rank
  first two rounds of every draft since 2005 (data/external/draft/careers.jsonl): comparisons that include the misses
  NHL equivalency (analysis/nhle.py): what a pre-NHL scoring rate is worth in NHL terms
  Wikipedia (data/external/wiki/summaries.jsonl, CC BY-SA 4.0): the article's lead, credited and linked
  coverage (data/coverage/players/<id>.json, scripts/buzz.py): headlines, reporters' posts, team videos
Every sentence in `notes` is built from those numbers; nothing is guessed.
"""
import datetime as dt
import json
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "site"))
import nhle as NH  # noqa: E402
from narrative import COUNTRY, NICK, age_on, ordinal, ordinalw  # noqa: E402


def pl(n, word):
    """Stat lines keep digits: '33 points (11 goals)'."""
    return f"{n} {word if n == 1 else word + 's'}"

LEAGUE_NAME = {"SHL": "SHL", "Liiga": "Liiga", "KHL": "KHL", "NL": "Swiss National League", "Czechia": "Czech Extraliga",
               "DEL": "DEL", "Allsvenskan": "HockeyAllsvenskan", "AHL": "AHL", "ECHL": "ECHL", "NCAA": "NCAA",
               "OHL": "OHL", "WHL": "WHL", "QMJHL": "QMJHL", "USHL": "USHL", "NTDP": "U.S. NTDP",
               "J20 Nationell": "Swedish juniors (J20)", "U20 SM-sarja": "Finnish juniors (U20)", "MHL": "Russian juniors (MHL)",
               "VHL": "VHL", "NHL": "NHL", "BCHL": "BCHL", "AJHL": "AJHL", "OJHL": "OJHL", "NAHL": "NAHL", "Mestis": "Mestis",
               "Slovakia": "Slovak Extraliga", "ICEHL": "ICE Hockey League"}
# the records API names European leagues by country ("SWEDEN"); the club name says enough there
COUNTRY_LEAGUES = {"SWEDEN", "FINLAND", "RUSSIA", "CZECH", "CZECHIA", "GERMANY", "SWISS", "SWITZERLAND", "SLOVAKIA", "AUSTRIA",
                   "LATVIA", "DENMARK", "NORWAY", "BELARUS", "FRANCE", "KAZAKHSTAN", "SLOVENIA", "UKRAINE", "ITALY", "POLAND"}
CS_CAT = {1: "North American skaters", 2: "international skaters", 3: "North American goalies", 4: "international goalies"}
BIG_INTL = {"World Juniors", "World Championship", "Olympics", "4 Nations Face-Off", "World Cup", "U18 Worlds", "Hlinka Gretzky Cup"}
INTL_RANK = {"Olympics": 6, "4 Nations Face-Off": 5, "World Cup": 5, "World Championship": 4, "World Juniors": 3, "U18 Worlds": 2,
             "Hlinka Gretzky Cup": 1}
# tournaments played in the calendar year that starts the season keep the first year; the rest are named by the second
FIRST_YEAR = {"World Cup", "Hlinka Gretzky Cup", "U17 World Challenge", "World Junior A Challenge"}


def event_year(s, event):
    s = int(s)
    if event in ("Champions Hockey League", "Euro Hockey Tour"):
        return season_label(s)
    return str(s // 10000 if event in FIRST_YEAR else s % 10000)


def season_label(s):
    s = int(s)
    return f"{s // 10000}-{str(s % 10000)[2:]}"


def jsonl(path):
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    k, v = json.loads(line)
                    out[int(k)] = v
    return out


class Context:
    """Everything the dossiers need, loaded once."""

    def __init__(self, season, bios):
        self.season = season
        self.bios = bios
        self.careers = jsonl(os.path.join(ROOT, "data", "external", "draft", "careers.jsonl"))
        self.wiki = jsonl(os.path.join(ROOT, "data", "external", "wiki", "summaries.jsonl"))
        try:
            self.nhle = NH.build(season)["leagues"]
        except Exception:
            self.nhle = {}
        self.picks, self.by_id = {}, {}
        ddir = os.path.join(ROOT, "data", "external", "draft")
        for f in sorted(os.listdir(ddir)) if os.path.isdir(ddir) else []:
            if f[:4].isdigit() and f.endswith(".json"):
                d = json.load(open(os.path.join(ddir, f)))
                self.picks[d["year"]] = d["picks"]
                for i, p in enumerate(d["picks"]):
                    if p.get("id"):
                        self.by_id[int(p["id"])] = (d["year"], i)
        # every career we know, for comparisons: this season's bios win over the draft-career cache
        self.all = {**{k: v for k, v in self.careers.items()}, **{k: v for k, v in bios.items() if v.get("career")}}
        self.cov_dir = os.path.join(ROOT, "data", "coverage", "players")

    def coverage(self, pid):
        try:
            return json.load(open(os.path.join(self.cov_dir, f"{pid}.json")))
        except Exception:
            return None


def _first_season(career):
    s = sorted({r["s"] for r in career if r.get("lg") == "NHL" and r.get("gt") == 2 and (r.get("gp") or 0) > 0})
    return s[0] if s else None


def path_rows(career, nhle, upto=None):
    """Pre-NHL and NHL league seasons (regular season, playoffs folded in), translated where we have a factor."""
    acc = {}
    for r in career:
        lg = NH.canon(r.get("lg"))
        if not lg or r.get("gt") not in (2, 3):
            continue
        k = (r["s"], lg)
        a = acc.setdefault(k, dict(s=r["s"], season=season_label(r["s"]), lg=lg, league=LEAGUE_NAME.get(lg, lg), teams=[],
                                   gp=0, g=0, a=0, p=0, po=None, w=0, gaa=None, sv=None))
        if r["gt"] == 2:
            if r.get("tm") and r["tm"] not in a["teams"]:
                a["teams"].append(r["tm"])
            for x in ("gp", "g", "a", "p", "w"):
                a[x] += r.get(x) or 0
            if r.get("sv") is not None:
                a["sv"], a["gaa"] = r.get("sv"), r.get("gaa")
        else:
            po = a["po"] or dict(gp=0, g=0, a=0, p=0)
            for x in ("gp", "g", "a", "p"):
                po[x] += r.get(x) or 0
            a["po"] = po
    out = []
    for k in sorted(acc):
        a = acc[k]
        if not a["gp"] and not a["po"]:
            continue
        if upto and a["s"] > upto:
            continue
        f = nhle.get(a["lg"])
        if a["lg"] != "NHL" and f and a["gp"] >= 10:
            a["nhle82"] = round(a["p"] / a["gp"] * f["factor"] * 82)
        a["ppg"] = round(a["p"] / a["gp"], 2) if a["gp"] else None
        out.append({x: v for x, v in a.items() if v not in (None, [], 0) or x in ("g", "a", "p", "gp")})
    return out


def intl_rows(career):
    out = {}
    for r in career:
        ev = NH.INTERNATIONAL.get(r.get("lg"))
        if not ev or r.get("gt") != 2 or not r.get("gp"):
            continue
        k = (r["s"], ev)
        team = re.sub(r"\s+Olympics?$", "", r.get("tm") or "") or None
        a = out.setdefault(k, dict(s=r["s"], season=event_year(r["s"], ev), event=ev, team=team, gp=0, g=0, a=0, p=0))
        for x in ("gp", "g", "a", "p"):
            a[x] += r.get(x) or 0
        if r.get("sv") is not None:
            a["sv"] = r["sv"]
    return [out[k] for k in sorted(out)]


def draft_info(pid, bio, C):
    d = (bio or {}).get("draft") or {}
    loc = C.by_id.get(pid)
    if not loc and not d.get("year"):
        return None
    if not loc:
        return dict(year=d.get("year"), round=d.get("round"), overall=d.get("overall"), team=d.get("team"))
    year, i = loc
    picks = C.picks[year]
    p = picks[i]
    lg = p.get("league")
    out = dict(year=year, round=p.get("round"), overall=p.get("overall"), team=p.get("team"),
               club=club_name(dict(club=p["club"], year=year), bio) if p.get("club") else None,
               league=None if (lg or "").upper().replace("-", " ").split(" ")[0] in COUNTRY_LEAGUES else lg)
    if p.get("cs"):
        out["cs"] = dict(cat=CS_CAT.get(p["cs"]["cat"]), final=p["cs"].get("final"), mid=p["cs"].get("mid"))
    near = lambda j: dict(name=picks[j]["name"], team=picks[j]["team"], id=picks[j].get("id"), overall=picks[j]["overall"]) \
        if 0 <= j < len(picks) else None
    out["before"], out["after"] = near(i - 1), near(i + 1)
    return out


def comps(pid, bio, C, his_season=None):
    """Players taken around the same spot in drafts since 2005, same position group, and how their first NHL
    season went (including the ones who never played). Only for first- and second-rounders in their first three seasons."""
    d = (bio or {}).get("draft") or {}
    o, year = d.get("overall"), d.get("year")
    if not o or o > 64 or not year:
        return None
    nhl_prev = [r for r in bio.get("career") or [] if r.get("lg") == "NHL" and r.get("gt") == 2 and str(r["s"]) < C.season]
    if len({r["s"] for r in nhl_prev}) > 2:
        return None
    goalie = bio.get("pos") == "G"
    if goalie:
        return None
    dman = bio.get("pos") == "D"
    band = (max(1, o - 2), o + 2) if o <= 10 else (max(1, o - 5), o + 5) if o <= 32 else (max(1, o - 10), o + 10)
    rows = []
    last_ok = int(C.season[:4]) - 2      # drafted at least two summers before this season: time to have played
    for y, picks in C.picks.items():
        if y > last_ok:
            continue
        for p in picks:
            if not p.get("id") or int(p["id"]) == pid or not (band[0] <= (p.get("overall") or 999) <= band[1]):
                continue
            if (p.get("pos") == "D") != dman or p.get("pos") == "G":
                continue
            car = (C.all.get(int(p["id"])) or {}).get("career")
            if car is None:
                continue
            nhl = [r for r in car if r.get("lg") == "NHL" and r.get("gt") == 2]
            gp_tot = sum(r.get("gp") or 0 for r in nhl)
            by_s = {}
            for r in nhl:
                b = by_s.setdefault(r["s"], [0, 0, 0, 0])
                b[0] += r.get("gp") or 0; b[1] += r.get("g") or 0; b[2] += r.get("a") or 0; b[3] += r.get("p") or 0
            first = min(by_s) if by_s else None
            full = next((s for s in sorted(by_s) if by_s[s][0] >= 20), None)
            rows.append(dict(id=int(p["id"]), name=p["name"], year=y, overall=p["overall"], team=p.get("team"), nhl_gp=gp_tot,
                             first=dict(season=season_label(first), gp=by_s[first][0], g=by_s[first][1], a=by_s[first][2],
                                        p=by_s[first][3]) if first else None,
                             first_full=dict(season=season_label(full), gp=by_s[full][0], p=by_s[full][3],
                                             ppg=round(by_s[full][3] / by_s[full][0], 2)) if full else None,
                             years_to_debut=(int(str(first)[:4]) - y) if first else None))
    if len(rows) < 5:
        return None
    played = [r for r in rows if r["nhl_gp"] > 0]
    full = [r["first_full"]["ppg"] for r in rows if r["first_full"]]
    est = [r for r in rows if r["year"] <= last_ok - 4]       # had four-plus seasons to get there
    out = dict(group=f"{'defensemen' if dman else 'forwards'} picked {band[0]}-{band[1]} overall, {min(C.picks)}-{last_ok}",
               n=len(rows), played=len(played), established_n=len(est), reached_200=sum(1 for r in est if r["nhl_gp"] >= 200),
               first_full_ppg_median=round(statistics.median(full), 2) if full else None, first_full_n=len(full),
               debut_year_median=statistics.median([r["years_to_debut"] for r in played]) if played else None)
    # the closest five by pick, newest first among ties, for the table
    rows.sort(key=lambda r: (abs(r["overall"] - o), -r["year"]))
    out["list"] = rows[:6]
    if his_season and his_season.get("gp"):
        out["his"] = dict(gp=his_season["gp"], p=his_season["pts"], ppg=round(his_season["pts"] / his_season["gp"], 2))
    return out


def _awards(bio):
    return [dict(name=a["name"], seasons=[season_label(s) for s in a.get("seasons") or []]) for a in (bio or {}).get("awards") or []]


def build(pid, C, season_tot=None, today=None):
    bio = C.bios.get(pid)
    if not bio:
        return None
    today = today or dt.date.today()
    career = bio.get("career") or []
    first = _first_season(career)
    rows = path_rows(career, C.nhle)
    pre = [r for r in rows if r["lg"] != "NHL" and (not first or r["s"] < first)]
    nhl = [r for r in rows if r["lg"] == "NHL"]
    intl = intl_rows(career)
    dr = draft_info(pid, bio, C)
    w = C.wiki.get(pid)
    out = dict(
        nhl_url=f"https://www.nhl.com/player/{pid}",
        pos=bio.get("pos"),
        age=age_on(bio.get("birth_date"), today),
        country=COUNTRY.get(bio.get("birth_country"), bio.get("birth_country")),
        draft=dr,
        pre=pre[-8:],                  # the last eight pre-NHL league seasons (the full list is on NHL.com)
        pre_total=len(pre),
        nhl=[dict(season=r["season"], teams=r.get("teams"), gp=r["gp"], g=r["g"], a=r["a"], p=r["p"], po=r.get("po"),
                  sv=r.get("sv"), gaa=r.get("gaa"), w=r.get("w")) for r in nhl],
        debut=season_label(first) if first else None,
        intl=[r for r in intl if r["event"] in BIG_INTL or r["event"] in ("World Junior A Challenge", "U17 World Challenge",
                                                                         "Memorial Cup", "Champions Hockey League", "Euro Hockey Tour")],
        awards=_awards(bio),
        hhof=bio.get("hhof") or None, top100=bio.get("top100") or None,
        wiki=dict(title=w["title"].replace("_", " "), url=w["url"], desc=w.get("desc"), extract=w["extract"]) if w else None,
        comps=comps(pid, bio, C, season_tot),
    )
    out["notes"] = notes(out, bio, season_tot)
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def _best_pre(pre):
    """His best translated pre-NHL season among the last three, with at least 15 games."""
    cand = [r for r in pre[-3:] if r.get("nhle82") and r["gp"] >= 15]
    return max(cand, key=lambda r: r["nhle82"]) if cand else None


def _plain(x):
    import unicodedata
    x = unicodedata.normalize("NFD", x or "")
    return "".join(c for c in x if unicodedata.category(c) != "Mn").lower()


def club_name(dr, bio):
    """The records API spells clubs plainly ("FROLUNDA"); his NHL.com career has the proper name for that season."""
    club = dr["club"]
    want = int(f"{dr['year'] - 1}{dr['year']}")
    for r in (bio or {}).get("career") or []:
        if r.get("s") == want and r.get("tm") and _plain(club) in _plain(r["tm"]):
            return r["tm"]
    return club.title() if club.isupper() else club


def min_year(c):
    return c["group"].rsplit(", ", 1)[-1].split("-")[0]


def notes(d, bio, season_tot):
    """Plain, checkable sentences: the draft, the last stop before the NHL, international pedigree, awards."""
    out = []
    dr = d.get("draft")
    if dr and dr.get("overall"):
        by = f"the {NICK[dr['team']]}" if dr.get("team") in NICK else dr.get("team")
        s = f"Drafted {ordinal(dr['overall'])} overall by {by} in {dr['year']}"
        if dr.get("club"):
            s += f" out of {dr['club']}"
        cs = dr.get("cs")
        if cs and cs.get("final"):
            s += f"; Central Scouting's final ranking had him No. {cs['final']} among {cs['cat']}"
            if cs.get("mid") and cs["mid"] != cs["final"]:
                s += f" (No. {cs['mid']} at midterm)"
        if dr.get("before") and dr["overall"] <= 10:
            s += f". {dr['before']['name']} went one pick earlier"
            if dr.get("after"):
                s += f" and {dr['after']['name']} one pick later"
        out.append(s + ".")
    elif bio.get("career") and any(r.get("lg") == "NHL" for r in bio["career"]):
        out.append("Never drafted: he earned his way to the NHL as a free agent.")
    pre = [r for r in d.get("pre") or [] if r.get("gp")]
    goalie = bio.get("pos") == "G"
    if pre and goalie:
        last = pre[-1]
        team = (last.get("teams") or [""])[0]
        s = f"Last stop before the NHL: {pl(last['gp'], last['league'] + ' game')}" + (f" for {team}" if team else "") + f" in {last['season']}"
        if last.get("sv"):
            s += f", with a {last['sv']:.3f} save percentage".replace("0.", ".", 1)
        out.append(s + ".")
    elif pre:
        last = pre[-1]
        team = (last.get("teams") or [""])[0]
        s = f"Last stop before the NHL: {pl(last['p'], 'point')} ({pl(last['g'], 'goal')}) in {last['gp']} {last['league']} games" + \
            (f" for {team}" if team else "") + f" in {last['season']}"
        if last.get("nhle82"):
            s += f", worth roughly {last['nhle82']} points over 82 NHL games by our league translation"
        out.append(s + ".")
    if pre and not goalie:
        best = _best_pre(pre)
        if best and best is not last and best["nhle82"] >= (last.get("nhle82") or 0) + 6:
            out.append(f"His best translated season came in {best['season']}: {pl(best['p'], 'point')} in {best['gp']} {best['league']} games "
                       f"(about {best['nhle82']} over 82 NHL games).")
    big = [r for r in d.get("intl") or [] if r["event"] in BIG_INTL and r["gp"] >= 3]
    if big:
        goalie = bio.get("pos") == "G"
        def say(r):
            return (f"the {r['season']} {r['event']}" if goalie else
                    f"{pl(r['p'], 'point')} in {r['gp']} games at the {r['season']} {r['event']}") + (f" for {r['team']}" if r.get("team") else "")
        top = max(big, key=lambda r: (INTL_RANK.get(r["event"], 0), r["p"], r["s"]))
        s = ("Internationally he played " if goalie else "Internationally: ") + say(top)
        young = len(d.get("nhl") or []) <= 2
        jr = [r for r in big if r["event"] in ("World Juniors", "U18 Worlds", "Hlinka Gretzky Cup") and r is not top]
        if young and jr and not goalie:
            j = max(jr, key=lambda r: (r["p"] / max(r["gp"], 1), INTL_RANK.get(r["event"], 0)))
            if j["p"] >= j["gp"]:
                s += f", and {say(j)}"
        out.append(s + ".")
    if d.get("awards"):
        names = [f"{a['name']} ({', '.join(a['seasons'])})" for a in d["awards"][:4]]
        out.append("NHL awards: " + "; ".join(names) + ".")
    c = d.get("comps")
    if c and c.get("reached_200") is not None and c.get("established_n"):
        who = c["group"].split(",")[0]
        if c["reached_200"] == c["established_n"]:
            s = f"All {c['established_n']} {who} since {min_year(c)} who've had four-plus seasons reached 200 NHL games"
        else:
            s = (f"Of the {c['established_n']} {who} since {min_year(c)} who've had four-plus seasons, "
                 f"{c['reached_200']} reached 200 NHL games")
        if c.get("first_full_ppg_median") is not None:
            s += f"; in their first season of 20+ games they scored a median {c['first_full_ppg_median']:.2f} points a game"
        if c.get("his"):
            s += f". He's at {c['his']['ppg']:.2f} through {c['his']['gp']} games"
        out.append(s + ".")
    return out
