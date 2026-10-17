"""Roster and staff moves for the News page's Moves tab, from ESPN's public transactions feed (stdlib only).

ESPN lists every call-up, assignment, signing, trade, waiver claim, injured-reserve move and front-office change
as one line of text per team. This keeps the last few weeks, sorts each line into a kind, pulls out the players
it names and matches them to this site's player ids, and folds the two sides of a trade into one entry.
The text is ESPN's own one-line description, shown as written and credited.
"""
import datetime as dt, hashlib, re

import espn

DAYS = 30
KINDS = [   # first match wins within one sentence; staff before the rest because "Hired ... from" reads like a player move
    ("staff", r"\b(head coach|assistant coach|associate coach|goaltending coach|coach|general manager|president of hockey|"
              r"hockey operations|scout)\b"),
    ("trade", r"^(Acquired|Acquire|Traded)\b"),
    ("suspension", r"\bsuspend"),
    ("injury", r"injured reserve|non-roster|\bLTIR\b|long-term"),
    ("waivers", r"^(Waived|Claimed|Released|Placed .* on waivers|Placed .* on unconditional)"),
    ("signing", r"^(Signed|Agreed|Re-signed|Re signed|Extended)"),
    ("up", r"^(Recalled|Called up|Activated|Reinstated)"),
    ("down", r"^(Assigned|Sent|Loaned|Reassigned|Returned)"),
]
# an entry can hold several moves ("Placed F Miles Wood on injured reserve. Acquired F Aatu Raty from ..."); it is
# filed under the biggest one
RANK = ["staff", "trade", "signing", "waivers", "suspension", "injury", "up", "down", "other"]
POS = r"(?:[LR]?[CWD](?:/[LR]?[CWD])?|F|G)s?"   # C, LW, RD, C/LW, Fs, Gs ...
STOP = r"\s+(?:from|to|on|in|for|with|as|after|back|off|under)\b|[.;(]|$"


def kind_of(text):
    found = []
    for sentence in re.split(r"(?<=\.)\s+(?=[A-Z])", text):
        k = next((k for k, pat in KINDS if re.search(pat, sentence.strip(), re.I if k in ("staff", "injury", "suspension") else 0)), "other")
        found.append(k)
    return min(found, key=RANK.index) if found else "other"


def names_in(text):
    """Player names after position tags: 'Assigned Gs Niklas Kokko and Victor Ostman and F Jani Nyman to ...'."""
    out = []
    for m in re.finditer(rf"\b{POS}\s+(?=[A-ZÀ-Þ])", text):
        seg = re.split(STOP, text[m.end():], maxsplit=1)[0]
        for part in re.split(r",\s*|\s+and\s+", seg):
            part = re.sub(rf"^{POS}\s+", "", part.strip())
            if re.match(r"^[A-ZÀ-Þ][\w'.\-À-ÿ]+(\s+[A-ZÀ-Þa-z][\w'.\-À-ÿ]+){1,3}$", part) and part not in out:
                out.append(part)
    return out


def fetch(days=DAYS, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=days)).date().isoformat()
    rows, page = [], 1
    while page <= 10:
        d = espn.get(f"transactions?limit=200&page={page}")
        batch = d.get("transactions", [])
        rows += batch
        if not batch or batch[-1].get("date", "")[:10] < cutoff or page >= d.get("pageCount", 1):
            break
        page += 1
    return [r for r in rows if r.get("date", "")[:10] >= cutoff and r.get("description")]


def gather(skaters, goalies, days=DAYS):
    """[{id, date, kind, teams, items: [{team, text}], players: [{id, name, team, pos}], names}] newest first."""
    by_name = {}
    for x in list(skaters.values()) + list(goalies.values()):
        by_name.setdefault(espn.bare(x["name"]), []).append(x)
    entries = []
    for r in fetch(days):
        team = espn.ESPN_TEAM.get(int((r.get("team") or {}).get("id") or 0))
        text = r["description"].strip()
        names = names_in(text)
        players = []
        for n in names:
            c = by_name.get(espn.bare(n), [])
            pick = next((x for x in c if x["team"] == team), None) or (c[0] if len(c) == 1 else None)
            if pick:
                players.append(dict(id=pick["id"], name=pick["name"], team=pick["team"], pos=pick.get("pos", "G")))
        entries.append(dict(date=r["date"][:10], kind=kind_of(text), team=team, text=text, names=names, players=players))
    # one trade, two lines (one per team): fold lines from the same day that name the same player
    out, used = [], set()
    for i, e in enumerate(entries):
        if i in used:
            continue
        group = [e]
        if e["kind"] == "trade":
            for j in range(i + 1, len(entries)):
                f = entries[j]
                if j not in used and f["kind"] == "trade" and f["date"] == e["date"] and f["team"] != e["team"] and \
                        set(map(espn.bare, f["names"])) & set(map(espn.bare, e["names"])):
                    group.append(f)
                    used.add(j)
        items = [dict(team=g["team"], text=g["text"]) for g in group]
        pl, seen = [], set()
        for g in group:
            for p in g["players"]:
                if p["id"] not in seen:
                    seen.add(p["id"])
                    pl.append(p)
        key = "|".join(sorted(f"{g['date']}|{g['team']}|{g['text']}" for g in group))
        out.append(dict(id=hashlib.sha1(key.encode()).hexdigest()[:12], date=e["date"], kind=e["kind"],
                        teams=list(dict.fromkeys(g["team"] for g in group if g["team"])), items=items, players=pl,
                        names=list(dict.fromkeys(n for g in group for n in g["names"]))))
    return out


if __name__ == "__main__":
    import json, collections, urllib.request
    site = "https://tolar-dio.github.io/NHL-Analytics/data/"
    load = lambda f: {x["id"]: x for x in json.load(urllib.request.urlopen(site + f, timeout=30))}
    mv = gather(load("skaters.json"), load("goalies.json"))
    print(len(mv), collections.Counter(m["kind"] for m in mv))
    for m in mv[:15]:
        print(m["date"], m["kind"], m["teams"], [p["name"] for p in m["players"]], "|", " / ".join(i["text"] for i in m["items"]))
