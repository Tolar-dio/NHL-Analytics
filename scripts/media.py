"""Gather hockey news, newsletters, podcasts and videos into one index for the News tab.

Sources live in scripts/news_sources.json. Everything is fetched server-side by the hourly
news job (most of these feeds don't allow browser requests). Only headlines, short teasers,
links, podcast audio links (what any podcast app uses) and YouTube video ids (played through
YouTube's own embed) are kept; full article text is never stored or shown.

Builds:
  stories   the same news grouped across outlets (ESPN + RSS), newest first
  reads     analysis and features one outlet has, plus newsletters ("worth reading")
  listen    latest podcast episodes
  watch     latest videos from the channels we follow
  highlights NHL YouTube highlight video per game id (persisted)
Every item is tagged with the teams and players it mentions.
"""
import datetime as dt, email.utils, hashlib, html, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; NHL-Analytics news job; +https://github.com/Tolar-dio/NHL-Analytics)"
NOW = dt.datetime.now(dt.timezone.utc)

TEAMS = {
    "ANA": ["Anaheim Ducks", "Ducks"], "BOS": ["Boston Bruins", "Bruins"], "BUF": ["Buffalo Sabres", "Sabres"],
    "CGY": ["Calgary Flames", "Flames"], "CAR": ["Carolina Hurricanes", "Hurricanes", "Canes"],
    "CHI": ["Chicago Blackhawks", "Blackhawks"], "COL": ["Colorado Avalanche", "Avalanche", "Avs"],
    "CBJ": ["Columbus Blue Jackets", "Blue Jackets"], "DAL": ["Dallas Stars", "Stars"], "DET": ["Detroit Red Wings", "Red Wings"],
    "EDM": ["Edmonton Oilers", "Oilers"], "FLA": ["Florida Panthers", "Panthers"], "LAK": ["Los Angeles Kings", "Kings"],
    "MIN": ["Minnesota Wild", "Wild"], "MTL": ["Montreal Canadiens", "Canadiens", "Habs"], "NSH": ["Nashville Predators", "Predators", "Preds"],
    "NJD": ["New Jersey Devils", "Devils"], "NYI": ["New York Islanders", "Islanders"], "NYR": ["New York Rangers", "Rangers"],
    "OTT": ["Ottawa Senators", "Senators", "Sens"], "PHI": ["Philadelphia Flyers", "Flyers"], "PIT": ["Pittsburgh Penguins", "Penguins"],
    "SJS": ["San Jose Sharks", "Sharks"], "SEA": ["Seattle Kraken", "Kraken"], "STL": ["St. Louis Blues", "Blues"],
    "TBL": ["Tampa Bay Lightning", "Lightning"], "TOR": ["Toronto Maple Leafs", "Maple Leafs", "Leafs"],
    "UTA": ["Utah Mammoth", "Mammoth"], "VAN": ["Vancouver Canucks", "Canucks"], "VGK": ["Vegas Golden Knights", "Golden Knights"],
    "WSH": ["Washington Capitals", "Capitals", "Caps"], "WPG": ["Winnipeg Jets", "Jets"],
}
NICK = {n: ab for ab, names in TEAMS.items() for n in names}
TEAM_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, NICK), key=len, reverse=True)) + r")\b")
ESPN_TEAM = {1: "BOS", 2: "BUF", 3: "CGY", 4: "CHI", 5: "DET", 6: "EDM", 7: "CAR", 8: "LAK", 9: "DAL", 10: "MTL",
             11: "NJD", 12: "NYI", 13: "NYR", 14: "OTT", 15: "PHI", 16: "PIT", 17: "COL", 18: "SJS", 19: "STL", 20: "TBL",
             21: "TOR", 22: "VAN", 23: "WSH", 25: "ANA", 26: "FLA", 27: "NSH", 28: "WPG", 29: "CBJ", 30: "MIN", 37: "VGK",
             124292: "SEA", 129764: "UTA"}
FAMILIES = {
    "trade": r"\b(trades?|traded|acquires?|acquired)\b",
    "sign": r"\b(signs?|signed|signing|extension|re-signs?|contract|tryout|PTO)\b",
    "injury": r"\b(injur\w*|surgery|day-to-day|week-to-week|month-to-month|IR|LTIR|out for|out indefinitely|to miss|will miss|sidelined|leaves game)\b|\b\d+(-to-|-| to )\d+ (weeks|months)\b",
    "rumor": r"(^report\b|\binterested in\b|\bin talks\b|\beyeing\b)",
    "waiver": r"\b(waivers?|claims?|claimed|placed on)\b",
    "roster": r"\b(recalls?|recalled|assigns?|assigned|reassigned|loaned|activated|healthy scratch\w*|season debut)\b",
    "discipline": r"\b(suspend\w*|fined|hearing|ejected)\b",
    "staff": r"\b(fires?|fired|hires?|hired|named (head )?coach|general manager)\b",
}
# headlines that read as analysis or features, whatever words they contain
FEATURE_RE = re.compile(r"^(how|why|what|which|who|where|could|can|should|would|is|are|does|do|will|ranking|rankings|tiering|grading|grades|"
                        r"power rankings|takeaways|observations|three|four|five|six|seven|eight|nine|ten|\d+)\b|\?\s*$|"
                        r"\b(roundup|mailbag|rankings|trivia|podcast)\b", re.I)
NAME_RE = re.compile(r"\b([A-Z][\w'’.-]+ [A-Z][\w'’-]+)\b")
STOP = set("a an the to of for in on at by with from and or vs vs. as is are be after before over into out his their its".split())


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


AD_RE = re.compile(r"promo code|#\w*partner\b|#ad\b|#sponsored|use code\b", re.I)


def plain(s, n=260):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    # show notes often run into chapter lists ("Intro - 0:00 Avs hire new PP coach - 1:00 ..."); keep the prose before them
    m = re.search(r"(?:\b[A-Z][\w' ]{0,30}[-–—:]\s*)?\(?\b\d{1,2}:\d{2}(?::\d{2})?\b", s)
    if m and len(re.findall(r"\b\d{1,2}:\d{2}\b", s[m.start():])) >= 3:
        if m.start() >= 40:
            s = s[:m.start()].rstrip(" -–—:|(,;")
        else:   # the notes are only a chapter list: keep the chapter titles, drop the times
            s = re.sub(r"\s*\(?\b\d{1,2}:\d{2}(?::\d{2})?\)?\s*[-–—:]?\s*", "; ", s).strip("; ")
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def fetch(url, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            err = e
            time.sleep(2)
    raise err


def iso(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def age_days(iso_s):
    try:
        return (NOW - dt.datetime.fromisoformat(iso_s)).total_seconds() / 86400
    except Exception:
        return 999


def local(tag):
    return tag.split("}")[-1]


def parse_rss(raw):
    """RSS 2.0 items as plain dicts (title, link, published, desc, author, categories, audio, duration, image)."""
    root = ET.fromstring(raw)
    chan_img = None
    for el in root.iter():
        if local(el.tag) == "image" and el.get("href"):
            chan_img = el.get("href")
            break
    out = []
    for it in root.iter("item"):
        d = {"categories": []}
        for c in it:
            t = local(c.tag)
            if t == "title": d["title"] = plain(c.text, 300)
            elif t == "link": d["link"] = (c.text or "").strip()
            elif t == "pubDate": d["published"] = iso(c.text)
            elif t == "description": d["desc"] = plain(c.text)
            elif t == "summary" and not d.get("desc"): d["desc"] = plain(c.text)
            elif t == "creator": d["author"] = plain(c.text, 80)
            elif t == "category": d["categories"].append(plain(c.text, 40))
            elif t == "enclosure" and (c.get("type") or "").startswith("audio"): d["audio"] = c.get("url")
            elif t == "duration": d["duration"] = (c.text or "").strip()
            elif t == "image" and c.get("href"): d["image"] = c.get("href")
            elif t == "guid": d["guid"] = (c.text or "").strip()
        d.setdefault("image", chan_img)
        if d.get("title"):
            out.append(d)
    return out


def secs(duration):
    if not duration:
        return None
    if duration.isdigit():
        return int(duration)
    parts = [int(p) for p in duration.split(":") if p.isdigit()]
    tot = 0
    for p in parts:
        tot = tot * 60 + p
    return tot or None


def youtube(ch, cache):
    """Latest uploads: YouTube's channel feed first (it has failed on and off since Dec 2025), then the
    Data API if YOUTUBE_API_KEY is set, otherwise the last good copy from cache."""
    cid = ch["channel"]
    try:
        root = ET.fromstring(fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", tries=1))
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
        vids = [dict(id=e.find("yt:videoId", ns).text, title=plain(e.find("a:title", ns).text, 200),
                     published=iso(e.find("a:published", ns).text),
                     short="/shorts/" in (e.find("a:link", ns).get("href", "") if e.find("a:link", ns) is not None else ""),
                     desc=plain((e.find("m:group/m:description", ns).text if e.find("m:group/m:description", ns) is not None else ""), 200))
                for e in root.findall("a:entry", ns)]
        cache[cid] = vids
        return vids, "feed"
    except Exception:
        pass
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        try:
            q = urllib.parse.urlencode(dict(part="snippet", playlistId="UU" + cid[2:], maxResults=15, key=key))
            d = json.loads(fetch("https://www.googleapis.com/youtube/v3/playlistItems?" + q, tries=1))
            vids = [dict(id=x["snippet"]["resourceId"]["videoId"], title=plain(x["snippet"]["title"], 200),
                         short="#short" in (x["snippet"]["title"] + x["snippet"].get("description", "")).lower(),
                         published=iso(x["snippet"]["publishedAt"]), desc=plain(x["snippet"].get("description"), 200))
                    for x in d.get("items", [])]
            cache[cid] = vids
            return vids, "api"
        except Exception:
            pass
    return cache.get(cid, []), "cache"


class Tagger:
    """Finds the teams and players an item mentions (full names only; last names alone are too ambiguous)."""

    def __init__(self, skaters, goalies):
        self.people = {}
        for x in skaters + goalies:
            self.people.setdefault(norm(x["name"]), dict(id=x["id"], name=x["name"], team=x["team"]))
        names = sorted(self.people, key=len, reverse=True)
        self.re = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b") if names else None

    def tag(self, text):
        teams = sorted({NICK[m] for m in TEAM_RE.findall(text or "")})
        players = []
        if self.re:
            for m in dict.fromkeys(self.re.findall(norm(text))):
                players.append(self.people[m])
        return teams, players


def proper_names(title):
    """Two-word capitalised names in a headline that aren't team names: catches players we don't track
    (prospects, injured stars, AHL tryouts) so their stories still group across outlets."""
    return {norm(m) for m in NAME_RE.findall(title or "") if m not in NICK and m.split()[-1] not in NICK and not m.split()[0] in ("Report", "Watch", "Ask")}


def family(title):
    return next((k for k, rx in FAMILIES.items() if re.search(rx, title or "", re.I)), None)


def words(title):
    return {w for w in norm(title).split() if w not in STOP and len(w) > 2}


def same_story(a, b):
    """Two news items describe the same event: shared tracked player in the same kind of news,
    the same teams in the same kind of transaction within a day, or near-identical headlines."""
    try:
        gap = abs((dt.datetime.fromisoformat(a["published"]) - dt.datetime.fromisoformat(b["published"])).total_seconds()) / 3600
    except Exception:
        gap = 99
    if gap > 36:
        return False
    wa, wb = words(a["title"]), words(b["title"])
    jac = len(wa & wb) / max(1, len(wa | wb))
    if jac >= 0.45:
        return True
    pa, pb = {p["id"] for p in a["players"]}, {p["id"] for p in b["players"]}
    fa, fb = a["family"], b["family"]
    if (pa & pb or proper_names(a["title"]) & proper_names(b["title"])) and (fa == fb or jac >= 0.2):
        return True
    ta, tb = set(a["teams"]), set(b["teams"])
    return bool(fa and fa == fb and fa in ("trade", "sign", "injury", "waiver", "discipline", "staff")
                and ta & tb and (ta == tb or jac >= 0.15) and gap <= 24)


def story_id(item):
    return str(item["espn_id"]) if item.get("espn_id") else "s" + hashlib.sha1((item.get("link") or item["title"]).encode()).hexdigest()[:10]


def gather(site_url, cache_dir, games_index=None):
    cfg = json.load(open(os.path.join(HERE, "news_sources.json")))
    get_json = lambda u: json.loads(fetch(u))
    skaters, goalies = get_json(site_url + "skaters.json"), get_json(site_url + "goalies.json")
    tagger = Tagger(skaters, goalies)
    log = []

    # ---- news items: ESPN's API plus RSS outlets
    news = []
    try:
        for a in get_json("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news?limit=40").get("articles", []):
            if a.get("type") not in ("HeadlineNews", "Story"):
                continue
            cats = a.get("categories", [])
            nhl_team = lambda c: c.get("type") == "team" and "~l:90~" in (c.get("uid") or "")
            if any(c.get("type") == "team" and not nhl_team(c) for c in cats):
                continue          # college and other leagues share team ids with NHL teams
            text = f'{a.get("headline")} {a.get("description")}'
            teams, players = tagger.tag(text)
            teams = sorted(set(teams) | {ESPN_TEAM.get(c.get("teamId")) for c in cats if nhl_team(c)} - {None})
            for c in cats:
                if c.get("type") == "athlete" and norm(c.get("description")) in tagger.people:
                    p = tagger.people[norm(c.get("description"))]
                    if p not in players:
                        players.append(p)
            news.append(dict(source="ESPN", espn_id=a["id"], espn_type=a["type"], title=a.get("headline"), desc=plain(a.get("description")),
                             link=(a.get("links") or {}).get("web", {}).get("href"), published=iso(a.get("published")),
                             teams=teams, players=players))
        log.append("ESPN ok")
    except Exception as e:
        log.append(f"ESPN failed: {e!r}")
    for src in cfg["news"]:
        try:
            for it in parse_rss(fetch(src["url"]))[:40]:
                teams, players = tagger.tag(f'{it["title"]} {it.get("desc", "")}')
                news.append(dict(source=src["name"], title=it["title"], desc=it.get("desc"), link=it.get("link"),
                                 published=it.get("published"), author=it.get("author"), paywalled=src.get("paywalled", False),
                                 categories=it.get("categories"), teams=teams, players=players))
            log.append(f'{src["name"]} ok')
        except Exception as e:
            log.append(f'{src["name"]} failed: {e!r}')
    news = [x for x in news if x.get("published") and age_days(x["published"]) <= 6]
    for x in news:
        x["family"] = family(x["title"])

    # ---- split: hard news (grouped into stories) vs features worth reading
    def is_news(x):
        if len(x["teams"]) > 3:
            return False                       # roundups ("previews for all 11 games")
        if FEATURE_RE.search(x["title"] or ""):
            return False                       # "How...", "Three ways...", questions: analysis, not news
        if x["source"] == "ESPN" and x.get("espn_type") == "HeadlineNews":
            return True
        return bool(x["family"])
    # other leagues (PWHL, AHL-only) show up in some feeds: a story needs an NHL team or a player we track
    news = [x for x in news if x["teams"] or x["players"]]
    hard = sorted([x for x in news if is_news(x)], key=lambda x: x["published"])
    soft = [x for x in news if not is_news(x) and len(x["teams"]) <= 3]
    clusters = []
    for x in hard:
        for c in clusters:
            if any(same_story(x, y) for y in c):
                c.append(x)
                break
        else:
            clusters.append([x])
    stories = []
    for c in clusters:
        lead = next((y for y in c if y["source"] == "ESPN"), c[0])
        stories.append(dict(
            id=story_id(c[0]), ids=[story_id(y) for y in c], title=lead["title"], desc=lead.get("desc"),
            published=min(y["published"] for y in c), latest=max(y["published"] for y in c),
            teams=sorted({t for y in c for t in y["teams"]}),
            players=list({p["id"]: p for y in c for p in y["players"]}.values()),
            family=lead["family"],
            items=[dict(source=y["source"], title=y["title"], desc=y.get("desc"), link=y.get("link"), published=y["published"],
                        paywalled=y.get("paywalled", False)) for y in sorted(c, key=lambda y: y["published"])]))
    stories.sort(key=lambda s: s["latest"], reverse=True)

    # ---- newsletters join the features
    for src in cfg["newsletters"]:
        try:
            for it in parse_rss(fetch(src["url"]))[:6]:
                teams, players = tagger.tag(f'{it["title"]} {it.get("desc", "")}')
                if src.get("team") and src["team"] not in teams:
                    teams = sorted(set(teams) | {src["team"]})
                soft.append(dict(source=src["name"], kind="newsletter", title=it["title"], desc=it.get("desc"), link=it.get("link"),
                                 published=it.get("published"), author=it.get("author"), teams=teams, players=players))
            log.append(f'{src["name"]} ok')
        except Exception as e:
            log.append(f'{src["name"]} failed: {e!r}')
    reads = sorted([dict(source=x["source"], kind=x.get("kind", "article"), title=x["title"], desc=x.get("desc"), link=x.get("link"),
                         published=x["published"], author=x.get("author"), paywalled=x.get("paywalled", False),
                         teams=x["teams"], players=x["players"])
                    for x in soft if x.get("published") and age_days(x["published"]) <= 14],
                   key=lambda x: x["published"], reverse=True)[:40]

    # ---- podcasts
    listen = []
    for src in cfg["podcasts"]:
        try:
            for it in parse_rss(fetch(src["url"]))[:3]:
                if not it.get("audio") or not it.get("published") or age_days(it["published"]) > 10:
                    continue
                teams, players = tagger.tag(f'{it["title"]} {it.get("desc", "")}')
                if src.get("team"):
                    teams = sorted(set(teams) | {src["team"]})
                listen.append(dict(show=src["name"], title=it["title"], desc=plain(it.get("desc"), 220), audio=it["audio"],
                                   duration=secs(it.get("duration")), published=it["published"], image=it.get("image"),
                                   link=it.get("link") or f'https://podcasts.apple.com/podcast/id{src.get("apple")}',
                                   apple=f'https://podcasts.apple.com/podcast/id{src.get("apple")}' if src.get("apple") else None,
                                   teams=teams, players=players))
            log.append(f'{src["name"]} ok')
        except Exception as e:
            log.append(f'{src["name"]} failed: {e!r}')
    listen.sort(key=lambda x: x["published"], reverse=True)

    # ---- YouTube (with a cache for the feed's outages) and NHL game highlights
    os.makedirs(cache_dir, exist_ok=True)
    cpath = os.path.join(cache_dir, "youtube.json")
    cache = json.load(open(cpath)) if os.path.exists(cpath) else {}
    hpath = os.path.join(cache_dir, "highlights.json")
    highlights = json.load(open(hpath)) if os.path.exists(hpath) else {}
    by_date_teams = {}
    for g in games_index or []:
        by_date_teams[(g["date"], g["away"], g["home"])] = g["id"]
    watch = []
    for ch in cfg["youtube"]:
        vids, how = youtube(ch, cache)
        log.append(f'YouTube {ch["name"]}: {how} ({len(vids)})')
        n = 0
        for v in vids:
            if not v.get("published"):
                continue
            m = re.match(r"^(.+?) vs\.? (.+?) \| NHL Highlights \| (\w{3}) (\d{1,2}), (\d{4})", v["title"])
            if ch.get("highlights") and m:
                a, h = NICK.get(m.group(1).strip()), NICK.get(m.group(2).strip())
                try:
                    day = dt.datetime.strptime(f"{m.group(3)} {m.group(4)} {m.group(5)}", "%b %d %Y").date().isoformat()
                except ValueError:
                    day = None
                gid = by_date_teams.get((day, a, h))
                if gid:
                    highlights[str(gid)] = v["id"]
                continue                      # game highlights go on game pages, not in the Watch list
            # the Watch list is for real segments: no Shorts, no sponsor reads, and the NHL channel only feeds game pages
            if ch.get("highlights_only") or v.get("short") or AD_RE.search(v["title"]) or age_days(v["published"]) > 10 or n >= 4:
                continue
            teams, players = tagger.tag(f'{v["title"]} {v.get("desc", "")}')
            if ch.get("only_team") and ch["only_team"] not in teams:
                continue
            if ch.get("team"):
                teams = sorted(set(teams) | {ch["team"]})
            watch.append(dict(id=v["id"], channel=ch["name"], title=v["title"], published=v["published"], teams=teams, players=players))
            n += 1
    watch.sort(key=lambda x: x["published"], reverse=True)
    json.dump(cache, open(cpath, "w"), separators=(",", ":"))
    json.dump(highlights, open(hpath, "w"), separators=(",", ":"))

    return dict(stories=stories[:50], reads=reads, listen=listen[:40], watch=watch[:40], highlights=highlights), log


if __name__ == "__main__":
    site = os.environ.get("SITE_DATA_URL", "https://tolar-dio.github.io/NHL-Analytics/data/")
    out, log = gather(site, os.path.join(os.path.dirname(HERE), "data", "news", "cache"))
    print("\n".join(log))
    print({k: len(v) for k, v in out.items()})
    for s in out["stories"][:12]:
        print(f'  {len(s["items"])}x {s["title"][:70]} | {s["teams"]} | {[p["name"] for p in s["players"]]} | {[i["source"] for i in s["items"]]}')
