"""What the hockey world is saying about every player and team. Run hourly by the news job (scripts/write_news.py).

Four streams, all public and free:
  headlines   Google News search per player ("Name" plus NHL or hockey, last 30 days), a rotation that reaches every
              rostered player about once a day, tonight's players first. Headline, outlet, date and link only.
  reporters   public Bluesky posts from the reporters in scripts/buzz_sources.json (public AppView, no login). A post
              counts for a player when it names him in full, or by last name alone when the reporter covers his team and
              the name is unique on that roster. Replies, reposts, labelled posts and strong language are skipped, as is
              anyone who asks Bluesky not to show their posts to logged-out viewers. Posts drop off when they leave the
              reporter's latest feed (so deletions disappear on the next run) or after 10 days.
  fans        Reddit thread titles and links from r/hockey and each team's subreddit (multireddit RSS, a few feeds a run
              because Reddit rate-limits). Titles and links only: shown on the site, never sent to Claude.
  videos      each team's official YouTube channel feed: press conferences and interviews tagged to the players they name.
              They play only through YouTube's own embed.

House rules (CLAUDE.md, News rules): never fetch or store article text; the AI writers get headlines, reporters' posts
and video titles with attribution, and may quote only words that appear in them.

Outputs (committed by the news job; the site reads them from raw.githubusercontent.com, the nightly build reads them
from the checkout):
  data/coverage/players/<id>.json   {id, name, team, checked, news, posts, threads, videos}
  data/coverage/teams/<TEAM>.json   {team, updated, posts, threads, videos}
  data/coverage/buzz.json           {players: {id: [news 5d, news 30d, outlets 5d, posts 5d, threads 5d]}, top}
The site shows only the last BUZZ_DAYS (5) days; the longer KEEP windows are for the AI writers' deep dives.
  data/coverage/state.json          rotation state
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import media  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "coverage")
SRC = json.load(open(os.path.join(HERE, "buzz_sources.json")))
NEWS_PER_RUN = int(os.environ.get("COVERAGE_NEWS", "45"))
NEWS_EVERY_H = 20
BSKY = "https://public.api.bsky.app/xrpc/"
NOW = dt.datetime.now(dt.timezone.utc)

BUZZ_DAYS = 5     # what counts as buzz: the site shows this window and the counts use it
KEEP = dict(news=(45, 30), posts=(10, 15), threads=(21, 15), videos=(60, 12))    # days, max items per player (writers look back further)
TEAM_KEEP = dict(posts=(10, 20), threads=(7, 12), videos=(30, 15))
# betting and promo headlines aren't news, and the site never touts
NOT_NEWS = re.compile(r"\b(props?|odds|best bets?|bet365|draftkings|fanduel|betmgm|caesars|sportsbook|parlay|promo|bonus code|"
                      r"picks? (and|&) predictions?|prediction|anytime goal ?scorer|player to score)\b", re.I)
# machine-made filler: "X October 24 Preview vs. the Flyers", "Fantasy Outlook & Stats", player-profile pages
SPONSORED = re.compile(r"\b(presented by|brought to you by|sponsored by|in partnership with)\b", re.I)
FILLER = re.compile(r"\b(preview vs\.?|fantasy outlook|outlook & stats|stats & fantasy|player profile|stats, news|"
                    r"fantasy (news|value|stats)|game logs?|career stats|bio, stats)\b", re.I)
STRONG = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt\w*|asshole\w*|motherf\w*|dickhead\w*)\b|\bf[-*@#_]{1,2}c?k\w*|\bf\*+\w*|"
                    r"\bsh[-*@#_]t\w*|\bwtf\b|\bstfu\b", re.I)
PRESSER = re.compile(r"\b(post-?game|pre-?game|press conference|presser|media availability|availability|practice|morning skate|"
                     r"interview|1-on-1|one-on-one|talks|speaks|on the|reacts|mic'?d|media day|sound|scrum|q&a)\b", re.I)
RECAP = re.compile(r"\b(recap|highlights?)\b", re.I)
MEGATHREAD = re.compile(r"^(game thread|pre-?game thread|post ?game thread|daily (discussion|thread)|off-?day thread|"
                        r"free talk|weekly|trade (talk|rumou?rs?) thread)", re.I)
# last names that are also ordinary words: never matched on their own
COMMON = set("""power hart stone wood rust bear king price white brown little black green young rich may case hall hunt lee long
love march page park pool ward wise walker bell cole cross dean day fox gray grey hughes jones smith wolf hill lake moore rose
roy sharp sands snow strong trouba ritchie miller martin mills best bridge burns carter chase cook cooper dunn east fast frost
gold good grant hope house knight lamb lane low lord mason may north mercer moss nash noble page parker pierce reed rice ross
russell sharp shaw short simon sloan steel stephens storm street sutter swift terry thompson turner vale wall wallace webb
west wells wheeler wild wilson wing worth york kane kyle""".split())


AMBIG = {"will smith", "josh anderson", "ryan johnson", "adam fox", "jack johnson", "luke evans", "michael mcleod", "matt grzelcyk",
         "david kampf", "chris tierney", "nick robertson", "jake evans", "andrew peeke", "connor murphy", "ryan murphy", "sam reinhart"}
HOCKEY = re.compile(r"\b(nhl|hockey|goal|assist|shift|power play|pp1|line|d-?pair|morning skate|warmups?|game|scratch|injur\w*)\b", re.I)


def now_iso():
    return NOW.isoformat(timespec="seconds")


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def save(path, obj):
    """Write only when the content changed, so quiet hours make no commit."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except Exception:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def prune(items, days, cap, key="d"):
    """Newest first, inside the window, one copy of each link and of each headline (wire blurbs run in several places)."""
    seen, out = set(), []
    for x in sorted(items, key=lambda x: x.get(key) or "", reverse=True):
        ks = {x.get("u"), media.norm((x.get("t") or "").split(":", 1)[-1])[:90]} - {None, ""}
        if ks & seen or media.age_days(x.get(key)) > days:
            continue
        seen |= ks
        out.append(x)
    return out[:cap]


# ------------------------------------------------------------------ who's who

def deaccent(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


class Roster:
    """Full-name matching league-wide (media.Tagger), plus capitalised last names inside one team's context
    ("Stenberg-Misa-Sherwood" counts for San Jose's beat writer; "back in North America" never finds Oskar Bäck)."""

    def __init__(self, skaters, goalies):
        self.all = {x["id"]: dict(id=x["id"], name=x["name"], team=x["team"]) for x in skaters + goalies}
        self.tagger = media.Tagger(skaters, goalies)
        self.team_re = {}
        by_team = {}
        for x in self.all.values():
            last = media.norm(x["name"]).split()[-1] if x["name"] else ""
            by_team.setdefault(x["team"], {}).setdefault(last, []).append(x)
        for t, d in by_team.items():
            uniq = {k: v[0] for k, v in d.items() if len(v) == 1 and len(k) >= 4 and k not in COMMON}
            if uniq:
                forms = {deaccent(v["name"]).split()[-1]: v for v in uniq.values()}
                self.team_re[t] = (re.compile(r"(?<![\w'’])(" + "|".join(map(re.escape, sorted(forms, key=len, reverse=True))) + r")(?![\w'’])"), forms)
        dup = {}
        for x in self.all.values():
            dup.setdefault(media.norm(x["name"]), []).append(x["id"])
        self.shared = {i for ids in dup.values() if len(ids) > 1 for i in ids}   # two Sebastian Ahos

    def tag(self, text, team=None):
        teams, players = self.tagger.tag(text)
        # names shared with famous people need hockey around them ("I don't feel like Will Smith in an empty living room")
        hockey = bool(teams) or bool(HOCKEY.search(text))
        players = [p for p in players if hockey or media.norm(p["name"]) not in AMBIG]
        ids = {p["id"] for p in players}
        if team and team in self.team_re:
            rx, forms = self.team_re[team]
            for m in dict.fromkeys(rx.findall(deaccent(text))):
                p = forms[m]
                if p["id"] not in ids:
                    players.append(p)
                    ids.add(p["id"])
        return teams, players


# ------------------------------------------------------------------ headlines (Google News)

def junk(title, name):
    """Spam re-uploads ("THESE SWEDES ARE TERRIFYING ... (emAd8RrZNR)") and profile pages ("Ivar Stenberg Home")."""
    letters = [c for c in title if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6 and len(letters) > 25:
        return True
    if re.search(r"\((?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{8,}\)", title):
        return True
    return bool(re.fullmatch(re.escape(name) + r"\s*[-|:]?\s*(home|stats|bio|profile|news|player page)?", title.strip(), re.I))


def google_news(name, team=None):
    en = dict(FULL, MTL="Montreal Canadiens", LAK="Los Angeles Kings").get(team)
    q = f'"{name}" ("{en}" OR {en.split()[-1]})' if en else f'"{name}" (NHL OR hockey)'
    q += " when:30d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(dict(q=q, hl="en-US", gl="US", ceid="US:en"))
    root = ET.fromstring(media.fetch(url, tries=1))
    last = media.norm(name).split()[-1]
    out = []
    for it in root.iter("item"):
        title = html.unescape(it.findtext("title") or "")
        src = it.find("source")
        outlet = (src.text if src is not None else "") or ""
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3]
        if not title or last not in media.norm(title) or NOT_NEWS.search(title) or FILLER.search(title) or junk(title, name):
            continue
        out.append(dict(t=media.plain(title, 220), o=outlet[:60], d=media.iso(it.findtext("pubDate")), u=it.findtext("link")))
    return out


def run_news(R, state, tonight_ids):
    checked = state.setdefault("news_checked", {})
    def due(pid):
        c = checked.get(str(pid))
        return not c or media.age_days(c) * 24 >= NEWS_EVERY_H
    order = sorted((p for p in R.all if due(p)), key=lambda p: (p not in tonight_ids, checked.get(str(p), "")))
    done, fails, got = 0, 0, {}
    for pid in order[:NEWS_PER_RUN]:
        x = R.all[pid]
        try:
            got[pid] = google_news(x["name"], x["team"] if pid in R.shared else None)
            checked[str(pid)] = now_iso()
            done += 1
            fails = 0
        except Exception as e:
            fails += 1
            if fails >= 3 or "429" in str(e) or "503" in str(e):
                print(f"  ! Google News stopped after {done}: {e!r}")
                break
        time.sleep(2.5)
    print(f"  headlines: {done} players checked, {sum(map(len, got.values()))} headlines, {len(order) - done} still due")
    return got


# ------------------------------------------------------------------ reporters (Bluesky)

def bsky(method, **q):
    return json.loads(media.fetch(BSKY + method + "?" + urllib.parse.urlencode(q), tries=1))


def run_bluesky(R):
    by_player, by_team, authors = {}, {}, 0
    for a in SRC.get("bluesky", []):
        try:
            feed = bsky("app.bsky.feed.getAuthorFeed", actor=a["handle"], limit=40, filter="posts_no_replies").get("feed", [])
        except Exception:
            continue
        authors += 1
        for item in feed:
            if item.get("reason"):              # a repost: someone else's words
                continue
            p = item.get("post") or {}
            au = p.get("author") or {}
            if any(l.get("val") == "!no-unauthenticated" for l in au.get("labels") or []):
                break                            # the author asked not to be shown to logged-out viewers
            if p.get("labels") or (p.get("record") or {}).get("reply"):
                continue
            text = (p.get("record") or {}).get("text") or ""
            when = media.iso((p.get("record") or {}).get("createdAt") or p.get("indexedAt"))
            if len(text) < 30 or STRONG.search(text) or media.age_days(when) > KEEP["posts"][0]:   # "Stenberg ENG" says little
                continue
            if NOT_NEWS.search(text) or media.AD_RE.search(text) or SPONSORED.search(text):   # sportsbook reads and sponsored clips
                continue
            teams, players = R.tag(text, a.get("team"))
            if not players and not (a.get("team") and a["team"] in teams):
                continue
            rkey = p.get("uri", "").rsplit("/", 1)[-1]
            post = dict(t=text[:600], d=when, u=f"https://bsky.app/profile/{au.get('handle') or a['handle']}/post/{rkey}",
                        a=a["name"], h=au.get("handle") or a["handle"], o=a.get("outlet"))
            if len(players) <= 4:     # a lineup post names everyone; it belongs on the team page, not on 18 player pages
                for pl in players:
                    by_player.setdefault(pl["id"], []).append(post)
            for t in set(teams) | ({a["team"]} if a.get("team") and players and all(pl["team"] == a["team"] for pl in players) else set()):
                by_team.setdefault(t, []).append(post)
        time.sleep(0.3)
    print(f"  reporters: {authors} feeds read; posts for {len(by_player)} players and {len(by_team)} teams")
    return by_player, by_team


# ------------------------------------------------------------------ fans (Reddit thread titles)

def reddit_feed(subs):
    url = f"https://www.reddit.com/r/{'+'.join(subs)}/hot.rss?limit=100"
    root = ET.fromstring(media.fetch(url, tries=1))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns):
        cat = e.find("a:category", ns)
        link = e.find("a:link", ns)
        out.append(dict(t=media.plain(e.findtext("a:title", "", ns), 220), sub=cat.get("term") if cat is not None else "",
                        d=media.iso(e.findtext("a:published", None, ns) or e.findtext("a:updated", None, ns)),
                        u=link.get("href") if link is not None else None))
    return out


def run_reddit(R, state):
    subs = SRC.get("subreddits", {})
    team_of_sub = {v.lower(): k for k, v in subs.items() if k != "league"}
    teams = sorted(k for k in subs if k != "league")
    groups = [teams[i::4] for i in range(4)]
    k = state.get("reddit_next", 0) % len(groups)
    plan = [[subs["league"]]] if subs.get("league") else []
    plan.append([subs[t] for t in groups[k]])
    state["reddit_next"] = k + 1
    by_player, by_team, n, fetched = {}, {}, 0, []
    for group in plan:
        try:
            items = reddit_feed(group)
        except Exception as e:     # Reddit rate-limits shared cloud addresses often; the last good threads stay up
            print(f"  ! Reddit {'+'.join(group)[:40]}: {e!r}")
            continue
        fetched += [t for t, sub in subs.items() if sub in group and t != "league"]
        for it in items:
            if not it["u"] or NOT_NEWS.search(it["t"]) or STRONG.search(it["t"]) or media.AD_RE.search(it["t"]):
                continue
            team = team_of_sub.get((it["sub"] or "").lower())
            tteams, players = R.tag(it["t"], team)
            thread = dict(t=it["t"], d=it["d"], u=it["u"], sub=it["sub"])
            for pl in players:
                by_player.setdefault(pl["id"], []).append(thread)
            if team and not MEGATHREAD.search(it["t"]):
                by_team.setdefault(team, []).append(thread)
            n += 1
        time.sleep(6)
    print(f"  fans: {n} threads from {len(plan)} feeds; {len(by_player)} players named")
    return by_player, by_team, fetched


# ------------------------------------------------------------------ videos (team YouTube channels)

def resolve_channels(state):
    """Teams without a channel id in buzz_sources.json: one Data API search per team, cached (needs YOUTUBE_API_KEY)."""
    ids = dict(state.get("yt_resolved", {}))
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return ids
    for t, cid in SRC.get("youtube", {}).items():
        if cid or t in ids:
            continue
        full = FULL.get(t, t)
        try:
            q = urllib.parse.urlencode(dict(part="snippet", type="channel", q=full, maxResults=5, key=key))
            d = json.loads(media.fetch("https://www.googleapis.com/youtube/v3/search?" + q, tries=1))
            for x in d.get("items", []):
                if (x["snippet"].get("channelTitle") or "").strip().lower() == full.lower():
                    ids[t] = x["snippet"]["channelId"]
                    break
        except Exception as e:
            print(f"  ! YouTube lookup {t}: {e!r}")
            break
    state["yt_resolved"] = ids
    return ids


FULL = {"ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres", "CGY": "Calgary Flames", "CAR": "Carolina Hurricanes",
        "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche", "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars",
        "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers", "FLA": "Florida Panthers", "LAK": "LA Kings", "MIN": "Minnesota Wild",
        "MTL": "Canadiens de Montréal", "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders",
        "NYR": "New York Rangers", "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers", "PIT": "Pittsburgh Penguins",
        "SJS": "San Jose Sharks", "SEA": "Seattle Kraken", "STL": "St. Louis Blues", "TBL": "Tampa Bay Lightning",
        "TOR": "Toronto Maple Leafs", "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights",
        "WSH": "Washington Capitals", "WPG": "Winnipeg Jets"}


def video_kind(title):
    if PRESSER.search(title):
        return "presser"
    if RECAP.search(title):
        return "recap"
    return "video"


def run_videos(R, state, cache):
    chans = {t: c for t, c in SRC.get("youtube", {}).items() if c}
    chans.update({t: c for t, c in resolve_channels(state).items() if t not in chans})
    teams = sorted(chans)
    if not teams:
        return {}, {}, []
    k = state.get("yt_next", 0)
    pick = [teams[(k + i) % len(teams)] for i in range(min(8, len(teams)))]
    state["yt_next"] = (k + len(pick)) % len(teams)
    by_player, by_team = {}, {}
    for t in pick:
        vids, how = media.youtube(dict(channel=chans[t]), cache)
        for v in vids:
            if v.get("short"):
                continue
            title = v.get("title") or ""
            tteams, players = R.tag(title + " " + (v.get("desc") or "")[:120], t)
            item = dict(id=v["id"], t=title, d=v.get("published"), u=f"https://www.youtube.com/watch?v={v['id']}", k=video_kind(title), team=t)
            by_team.setdefault(t, []).append(item)
            for pl in players:
                if pl["team"] == t:          # a team's channel speaks for its own players
                    by_player.setdefault(pl["id"], []).append(item)
        time.sleep(0.5)
    print(f"  videos: {len(pick)} team channels; {sum(map(len, by_team.values()))} videos; {len(by_player)} players named")
    return by_player, by_team, pick


# ------------------------------------------------------------------ assemble

def gather(skaters, goalies, tonight_ids=()):
    os.makedirs(os.path.join(OUT, "players"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "teams"), exist_ok=True)
    state = load(os.path.join(OUT, "state.json"), {})
    ycache = load(os.path.join(OUT, "youtube_cache.json"), {})
    R = Roster(skaters, goalies)
    print("coverage:")
    streams = {}
    for name, fn in (("news", lambda: run_news(R, state, set(tonight_ids))), ("bsky", lambda: run_bluesky(R)),
                     ("reddit", lambda: run_reddit(R, state)), ("videos", lambda: run_videos(R, state, ycache))):
        try:
            streams[name] = fn()
        except Exception as e:     # one source failing must not block the others
            print(f"  ! {name} failed: {e!r}")
    news = streams.get("news") or {}
    posts_p, posts_t = streams.get("bsky") or ({}, {})
    threads_p, threads_t, reddit_teams = streams.get("reddit") or ({}, {}, [])
    vids_p, vids_t, vid_teams = streams.get("videos") or ({}, {}, [])
    bsky_ok = "bsky" in streams and streams["bsky"] is not None

    changed = 0
    buzz = {}
    for pid, x in R.all.items():
        path = os.path.join(OUT, "players", f"{pid}.json")
        old = load(path, None)
        if old is None and pid not in news and pid not in posts_p and pid not in threads_p and pid not in vids_p:
            continue
        d = old or dict(id=pid, news=[], posts=[], threads=[], videos=[])
        d.update(id=pid, name=x["name"], team=x["team"])
        if pid in news:
            keep = lambda n: not (junk(n["t"], x["name"]) or NOT_NEWS.search(n["t"]) or FILLER.search(n["t"]))
            d["news"] = prune([n for n in news[pid] + d.get("news", []) if keep(n)], *KEEP["news"])
            d["checked"] = state["news_checked"].get(str(pid))
            # counts from the whole search (up to 100 results), not the 30 we keep, so the busiest players still rank
            full = prune([n for n in news[pid] if keep(n)], 30, 1000)
            d["counts"] = dict(n5=sum(1 for i in full if media.age_days(i["d"]) <= BUZZ_DAYS), n30=len(full),
                               outlets5=len({i["o"] for i in full if i.get("o") and media.age_days(i["d"]) <= BUZZ_DAYS}),
                               fetched=now_iso())
        if bsky_ok:   # this run's reporters' feeds are the whole truth for posts: deleted posts drop off
            d["posts"] = prune(posts_p.get(pid, []), *KEEP["posts"])
        if pid in threads_p or d.get("threads"):
            d["threads"] = prune(threads_p.get(pid, []) + d.get("threads", []), *KEEP["threads"])
        if pid in vids_p or d.get("videos"):
            d["videos"] = prune(vids_p.get(pid, []) + d.get("videos", []), *KEEP["videos"])
        # counts from the last full search while it's fresh (it saw up to 100 results, not just the 30 we keep);
        # a search over a day old has aged, so count what we kept instead
        c = d.get("counts") or {}
        recent = [i for i in d["news"] if media.age_days(i["d"]) <= BUZZ_DAYS]
        if "n5" in c and media.age_days(c.get("fetched")) <= 1:
            n5, outlets = c["n5"], c["outlets5"]
        else:
            n5, outlets = len(recent), len({i["o"] for i in recent if i.get("o")})
        n30 = c.get("n30", len(d["news"]))
        p5 = sum(1 for i in d["posts"] if media.age_days(i["d"]) <= BUZZ_DAYS)
        t5 = sum(1 for i in d.get("threads", []) if media.age_days(i["d"]) <= BUZZ_DAYS)
        v5 = sum(1 for i in d.get("videos", []) if media.age_days(i["d"]) <= BUZZ_DAYS)
        if n5 or p5 or t5 or v5:
            buzz[pid] = [n5, n30, outlets, p5, t5]
        changed += save(path, d)
    for t in FULL:
        path = os.path.join(OUT, "teams", f"{t}.json")
        d = load(path, dict(team=t, posts=[], threads=[], videos=[]))
        if bsky_ok:
            d["posts"] = prune(posts_t.get(t, []), *TEAM_KEEP["posts"])
        if t in reddit_teams:
            d["threads"] = prune(threads_t.get(t, []), *TEAM_KEEP["threads"])
        if t in vid_teams:
            d["videos"] = prune(vids_t.get(t, []) + d.get("videos", []), *TEAM_KEEP["videos"])
        d["team"] = t
        changed += save(path, d)
    score = {pid: b[0] * 3 + b[2] + b[3] * 2 + b[4] for pid, b in buzz.items()}
    top = [dict(id=pid, name=R.all[pid]["name"], team=R.all[pid]["team"], news5=buzz[pid][0], outlets=buzz[pid][2],
                posts5=buzz[pid][3], threads5=buzz[pid][4])
           for pid in sorted(score, key=lambda p: -score[p])[:15] if score[pid] >= 6]
    save(os.path.join(OUT, "buzz.json"), dict(players={str(k): v for k, v in buzz.items()}, top=top,
                                               fields=["news_5d", "news_30d", "outlets_5d", "posts_5d", "threads_5d"]))
    save(os.path.join(OUT, "state.json"), state)
    save(os.path.join(OUT, "youtube_cache.json"), ycache)
    print(f"  coverage files changed: {changed}; buzz for {len(buzz)} players")
    return dict(top=top)


if __name__ == "__main__":
    site = os.environ.get("SITE_DATA_URL", "https://tolar-dio.github.io/NHL-Analytics/data/")
    local = os.path.join(ROOT, "site", "data")
    def get(name):
        p = os.path.join(local, name)
        return json.load(open(p)) if os.path.exists(p) and "--local" in sys.argv else json.loads(media.fetch(site + name))
    tn = get("tonight.json")
    gather(get("skaters.json"), get("goalies.json"), {p["id"] for p in tn.get("props", [])})
