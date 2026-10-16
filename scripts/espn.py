"""ESPN's public injury report and probable goalies, plus a running injury history (stdlib only).

The history (data/injuries/history.json) is what lets the build spot players coming BACK: someone listed
Out or on IR in the last three weeks who has since been cleared. ESPN only shows who is hurt right now.
Updated by the hourly news job and by the site build.
"""
import datetime as dt, json, os, re, unicodedata, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "injuries", "history.json")
BASE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/"
ESPN_TEAM = {1: "BOS", 2: "BUF", 3: "CGY", 4: "CHI", 5: "DET", 6: "EDM", 7: "CAR", 8: "LAK", 9: "DAL", 10: "MTL",
             11: "NJD", 12: "NYI", 13: "NYR", 14: "OTT", 15: "PHI", 16: "PIT", 17: "COL", 18: "SJS", 19: "STL", 20: "TBL",
             21: "TOR", 22: "VAN", 23: "WSH", 25: "ANA", 26: "FLA", 27: "NSH", 28: "WPG", 29: "CBJ", 30: "MIN", 37: "VGK",
             124292: "SEA", 129764: "UTA"}
OUT_STATUSES = ("Out", "Injured Reserve", "Suspension", "Suspended")
KEEP_DAYS = 60


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def bare(s):
    """'Elias N. Pettersson' -> 'elias pettersson' (drops middle initials)."""
    return " ".join(w for w in norm(s).split() if len(w) > 1)


def posgroup(p):
    p = (p or "").upper()
    return "G" if p == "G" else "D" if p == "D" else "F"


def get(path, timeout=20):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0 (NHL-Analytics)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def injuries():
    """Everyone on ESPN's report right now: [{key, name, team, pos, status, out, back, kind, note, date}]."""
    d = get("injuries")
    out = []
    for t in d.get("injuries", []):
        team = ESPN_TEAM.get(int(t.get("id", 0) or 0))
        for x in t.get("injuries", []):
            a = x.get("athlete") or {}
            href = next((l.get("href", "") for l in a.get("links", []) if "/id/" in l.get("href", "")), "")
            m = re.search(r"/id/(\d+)", href)
            st = x.get("status") or ""
            out.append(dict(key=m.group(1) if m else f'{norm(a.get("displayName"))}|{team}', name=a.get("displayName"), team=team,
                            pos=posgroup((a.get("position") or {}).get("abbreviation")), status=st,
                            out=st in OUT_STATUSES, back=(x.get("details") or {}).get("returnDate"),
                            kind=(x.get("details") or {}).get("type"),
                            note=x.get("shortComment") or "", date=x.get("date")))
    return out


def probables(day):
    """{team: goalie display name} from ESPN's scoreboard for `day` (a date)."""
    d = get(f"scoreboard?dates={day:%Y%m%d}")
    out = {}
    for e in d.get("events", []):
        for c in e["competitions"][0]["competitors"]:
            team = ESPN_TEAM.get(int(c["team"]["id"]))
            p = next((p for p in c.get("probables", []) if p.get("name") == "probableStartingGoalie"), None)
            if team and p and p.get("athlete"):
                out[team] = p["athlete"].get("displayName")
    return out


def roster(team):
    """Current NHL roster for one team: [(display name, position group)]. ESPN keeps it current through trades
    and call-ups (its per-player injury flags lag, so they are not used here)."""
    tid = next(k for k, v in ESPN_TEAM.items() if v == team)
    d = get(f"teams/{tid}/roster")
    return [(a.get("displayName"), posgroup((a.get("position") or {}).get("abbreviation")))
            for grp in d.get("athletes", []) for a in grp.get("items", [])]


def load_history():
    try:
        return json.load(open(HIST))
    except Exception:
        return {}


def update_history(current, now=None, write=True):
    """Fold the current report into the history. Each entry keeps its latest status and when it was last
    listed; a player missing from today's report keeps his old entry, which is how a return shows up.
    Only the hourly news job writes the file (write=True); the site build folds in memory, because a
    changed tracked file in the build's checkout makes its later `git pull --rebase` refuse to run."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.isoformat(timespec="minutes")
    h = load_history()
    for x in current:
        e = h.get(x["key"], dict(first=stamp))
        e.update(name=x["name"], team=x["team"], pos=x["pos"], status=x["status"], out=x["out"], back=x["back"], last=stamp)
        if x["out"]:
            e["last_out"] = stamp
        h[x["key"]] = e
    cutoff = now - dt.timedelta(days=KEEP_DAYS)
    h = {k: v for k, v in h.items() if dt.datetime.fromisoformat(v["last"]) >= cutoff}
    if not write:
        return h
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "w") as f:
        json.dump(h, f, separators=(",", ":"), sort_keys=True)
    return h


def returning(history, current, now=None, days=21):
    """Players listed Out/IR in the last `days` days who are no longer listed, or are now only day-to-day."""
    now = now or dt.datetime.now(dt.timezone.utc)
    listed = {x["key"]: x for x in current}
    out = []
    for k, e in history.items():
        if not e.get("last_out") or now - dt.datetime.fromisoformat(e["last_out"]) > dt.timedelta(days=days):
            continue
        cur = listed.get(k)
        if cur is None:
            out.append(dict(e, key=k, why="cleared from the injury report"))
        elif not cur["out"]:
            out.append(dict(e, key=k, why=f"now {cur['status'].lower()}"))
    return out


if __name__ == "__main__":
    cur = injuries()
    h = update_history(cur)
    print(f"{len(cur)} on the report, {len(h)} in history, {len(returning(h, cur))} returning")
