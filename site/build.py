"""Build the JSON the dashboard reads (site/data/*.json).

Run after the nightly pull and analysis steps:
    python analysis/player_flags.py
    python analysis/onice.py
    python analysis/props_data.py 20252026   (once; cheap to repeat)
    python analysis/props_data.py 20262027
    python site/build.py [--date YYYY-MM-DD]

Everything here is derived from public NHL data and MoneyPuck shot data
(credit MoneyPuck.com). No paid or private data goes into this public site.
"""
import argparse, base64, datetime as dt, glob, gzip, hashlib, json, os, sys, urllib.request
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import models as M  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SITE = os.path.join(ROOT, "site")
OUTD = os.path.join(SITE, "data")
CUR, PREV = M.CUR, M.PREV
TBL = lambda s, f: os.path.join(ROOT, "data", "tables", s, f)
AN = os.path.join(ROOT, "analysis", "output")
HEADERS = {"User-Agent": "nhl-analytics-personal-research/1.0"}


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


FANTASY_SALT = hashlib.sha256(b"ice-sheet-fantasy-v1").digest()[:16]   # fixed, so a browser that unlocked once stays unlocked
FANTASY_ITER = 600_000


def write_fantasy(payload):
    """The My team page is never published in the clear. With FANTASY_PASSWORD set (a GitHub secret) it is
    AES-GCM encrypted under a PBKDF2 key and the browser decrypts it after the password is typed; without the
    secret nothing is written at all, so a missing secret can't leak the page."""
    for stale in ("fantasy.json", "fantasy.lock.json"):
        if os.path.exists(os.path.join(OUTD, stale)):
            os.remove(os.path.join(OUTD, stale))
    pw = os.environ.get("FANTASY_PASSWORD", "").strip()
    if not pw:
        print("  fantasy: no FANTASY_PASSWORD set, My team page not published")
        return
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=FANTASY_SALT, iterations=FANTASY_ITER).derive(pw.encode())
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    dump("fantasy.lock.json", dict(v=1, iter=FANTASY_ITER, salt=b64(FANTASY_SALT), iv=b64(iv), ct=b64(ct)))


def dump(name, obj):
    os.makedirs(OUTD, exist_ok=True)
    with open(os.path.join(OUTD, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"), allow_nan=False)
    print(f"  {name}: {os.path.getsize(os.path.join(OUTD, name)) / 1024:.0f} KB")


def clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 3)
    return v


def records(df, cols):
    return [{c: clean(v) for c, v in zip(cols, row)} for row in df[cols].itertuples(index=False, name=None)]


# ------------------------------------------------------------------ expected lineups

def expected_lineups(teams, pgc, prev_pg, gg_cur, gg_prev, names, today):
    """Who to price tonight, per team, and which goalies start.

    Pool: everyone who dressed in any of the team's last three games, minus players ESPN lists Out, on IR
    or suspended, plus players coming back (Out/IR in the last three weeks and since cleared, or day-to-day
    without a recent game). Each gets a lineup tag: "last" (dressed last game), "recent" (missed the last
    game or more) or "returning". Prices are conditional on playing, like a sportsbook prop.
    Team strength uses last game's lineup minus the injured plus the returning.
    Without ESPN's report it falls back to last game's lineup, as before.
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import espn
    lu = dict(pool={}, strength={}, extra={}, out=set(), inj={}, probable={}, returning=[], source="last game's lineup (ESPN unavailable)")
    cols = ["player_id", "team", "pos", "date"]
    sk = pd.concat([prev_pg[cols], pgc[cols]]).sort_values("date").groupby("player_id").last()
    gl = pd.concat([gg_prev[["player_id", "team", "date"]], gg_cur[["player_id", "team", "date"]]]).sort_values("date").groupby("player_id").last()
    idx = {}
    for i, row in sk.iterrows():
        idx.setdefault(espn.bare(names.get(i, "")), []).append((int(i), row.team, row.pos))
    for i, row in gl.iterrows():
        idx.setdefault(espn.bare(names.get(i, "")), []).append((int(i), row.team, "G"))

    def match(name, team, pos):
        c = idx.get(espn.bare(name), [])
        for f in (lambda x: x[1] == team and x[2] == pos, lambda x: x[1] == team, lambda x: x[2] == pos):
            m = {x[0] for x in c if f(x)}
            if len(m) == 1:
                return m.pop()
        return None

    ok = False
    try:
        cur_inj = espn.injuries()
        hist = espn.update_history(cur_inj, write=False)   # the news job owns data/injuries
        back = espn.returning(hist, cur_inj)
        ok = True
    except Exception as e:
        print(f"  ESPN injury report unavailable ({e!r}); pricing last game's lineups")
        cur_inj, back = [], []
    try:
        for team, nm in espn.probables(today).items():
            gid = match(nm, team, "G")
            if gid:
                lu["probable"][team] = gid
    except Exception as e:
        print(f"  ESPN probable goalies unavailable ({e!r})")

    for x in cur_inj:
        i = match(x["name"], x["team"], x["pos"])
        if i:   # status, injury type and ESPN's expected return, for the storylines (site/narrative.py)
            lu["inj"][i] = dict(team=x["team"], status=x["status"], out=x["out"], kind=x.get("kind"), back=x["back"])
        if i and x["out"]:
            lu["out"].add(i)
    ret = {}
    for x in back:
        i = match(x["name"], x["team"], x["pos"])
        if i and x["pos"] != "G":
            ret[i] = (x["team"], f"Back from injury: {x['why']}")
    for x in cur_inj:   # day-to-day and no recent game: could be back tonight
        i = match(x["name"], x["team"], x["pos"])
        if i and not x["out"] and x["pos"] != "G" and i not in ret and (not x["back"] or x["back"][:10] <= str(today)):
            ret[i] = (x["team"], "Day-to-day; could return")

    last_team = pgc.sort_values("date").groupby("player_id").team.last()
    last_date = pgc.groupby("player_id").date.max()
    rost = {}
    if ok:
        for team in teams:
            try:
                rost[team] = {i for i in (match(nm, team, pos) for nm, pos in espn.roster(team)) if i}
            except Exception as e:
                print(f"  ESPN roster for {team} unavailable ({e!r})")
    for team in teams:
        tg = pgc[pgc.team == team]
        gids = tg.sort_values("date").game_id.drop_duplicates().tolist()
        if not gids:
            continue
        last1 = set(tg[tg.game_id == gids[-1]].player_id)
        if not ok:
            lu["pool"][team] = {i: ("last", "") for i in sorted(last1)}
            lu["strength"][team] = sorted(last1)
            continue
        last3 = {i for i in tg[tg.game_id.isin(gids[-3:])].player_id if last_team.get(i) == team}
        on = rost.get(team)
        if on:
            last1 &= on              # traded, waived or sent down since
            last3 &= on
        pool = {}
        for i in sorted(last3):
            if i in lu["out"]:
                continue
            if i in last1:
                pool[i] = ("last", "")
            else:
                played = set(tg[tg.player_id == i].game_id)
                missed = len(gids) - 1 - max(gids.index(g) for g in played)
                pool[i] = ("recent", "Missed the last game" if missed == 1 else f"Missed the last {missed} games")
        for i, (t, note) in ret.items():
            if t == team and i not in lu["out"] and pool.get(i, ("",))[0] != "last":
                pool[i] = ("returning", note)
                lu["extra"][i] = team
        # just traded or claimed: on this roster, last played for someone else in the past ten days
        for i in on or ():
            old = last_team.get(i)
            if old and old != team and i not in lu["out"] and i not in pool and \
                    (today - dt.date.fromisoformat(last_date[i])).days <= 10 and i in sk.index and sk.pos[i] != "G":
                pool[i] = ("returning", f"Just joined from {old}")
        lu["pool"][team] = pool
        lu["strength"][team] = [i for i, (st, _) in pool.items() if st in ("last", "returning")]
        lu["returning"] += [dict(id=i, team=team, name=names.get(i), note=n) for i, (st, n) in pool.items() if st == "returning"]
    if ok:
        lu["source"] = "last three games, ESPN injury report"
    n = lambda st: sum(1 for p in lu["pool"].values() for s, _ in p.values() if s == st)
    print(f"  lineups: {n('last')} from last game, {n('recent')} recent, {n('returning')} returning; "
          f"{len(lu['out'])} on ESPN's Out/IR list; {len(lu['probable'])} ESPN probable goalies")
    return lu


ARCHIVE = os.path.join(ROOT, "data", "archive", CUR)


def archive_tonight(day, games, props, lu):
    """Keep each game's pre-game numbers so the live track record can be graded later.

    A game's entry is rewritten on every build until puck drop, then frozen. If the first build that sees
    a game comes after puck drop, the entry is kept but marked pregame=false and left out of grading.
    (data/archive/<season>/<date>.json, committed by the nightly workflow.)
    """
    path = os.path.join(ARCHIVE, f"{day}.json")
    arc = json.load(open(path)) if os.path.exists(path) else dict(date=day, games={})
    now = dt.datetime.now(dt.timezone.utc)
    keep = ["id", "name", "team", "pos", "lineup", "p_goal", "p_1pt", "p_2pts", "p_3pts", "proj_toi", "g_f"]
    for g in games:
        gid = str(g["id"])
        start = dt.datetime.fromisoformat(g["start"].replace("Z", "+00:00")) if g.get("start") else None
        pre = start is None or now < start
        if gid in arc["games"] and not pre:
            continue
        arc["games"][gid] = dict(
            built=now.isoformat(timespec="minutes"), pregame=pre, start=g.get("start"), away=g["away"], home=g["home"],
            away_goalie=g["away_goalie"], home_goalie=g["home_goalie"], away_goalie_src=g.get("away_goalie_src"),
            home_goalie_src=g.get("home_goalie_src"), away_xg=g["away_xg"], home_xg=g["home_xg"], total=g["total"],
            o55=g["o55"], o65=g["o65"], lineup_source=lu["source"], market=g.get("market"),
            props=[{k: p.get(k) for k in keep} for p in props if p["game"] == g["id"]])
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(arc, f, separators=(",", ":"))


# ------------------------------------------------------------------ NHL EDGE extras

AREA_ORDER = ["Low Slot", "Crease", "L Net Side", "R Net Side", "High Slot", "L Circle", "R Circle", "L Corner",
              "R Corner", "Behind the Net", "Center Point", "L Point", "R Point", "Outside L", "Outside R",
              "Beyond Red Line", "Offensive Neutral Zone"]


def load_edge(season):
    """The tables scripts/fetch_external.py keeps from NHL EDGE (missing files just mean empty extras)."""
    d = os.path.join(ROOT, "data", "external", "edge", season)
    rd = lambda f: pd.read_csv(os.path.join(d, f)) if os.path.exists(os.path.join(d, f)) else pd.DataFrame()
    areas, hard, dist, gareas = rd("shot_areas.csv.gz"), rd("hard_shots.csv.gz"), rd("distance_games.csv.gz"), rd("goalie_areas.csv.gz")
    out = dict(speed={}, game_top={}, miles={}, player={}, goalie_hd={})
    for x in hard.itertuples() if len(hard) else []:
        if pd.isna(x.mph) or pd.isna(x.period):
            continue
        out["speed"][(int(x.game_id), int(x.player_id), int(x.period), str(x.time_in_period))] = round(float(x.mph), 1)
        k = (int(x.player_id), int(x.game_id))
        out["game_top"][k] = max(out["game_top"].get(k, 0), round(float(x.mph), 1))
    for x in dist.itertuples() if len(dist) else []:
        if not pd.isna(x.miles_all):
            out["miles"][(int(x.player_id), int(x.game_id))] = round(float(x.miles_all), 2)
    for pid, grp in areas.groupby("player_id") if len(areas) else []:
        rows = [dict(area=a.area, sog=int(a.sog), g=int(a.goals or 0), sh=r(a.sh_pct, 3), sh_pct=r(a.sh_pctile, 2),
                     sog_pct=r(a.sog_pctile, 2)) for a in grp.itertuples()]
        rows.sort(key=lambda a: (-a["sog"], AREA_ORDER.index(a["area"]) if a["area"] in AREA_ORDER else 99))
        out["player"].setdefault(int(pid), {})["areas"] = rows
    for pid, grp in hard.groupby("player_id") if len(hard) else []:
        top = grp.sort_values("mph", ascending=False).head(3)
        out["player"].setdefault(int(pid), {})["hard"] = [dict(mph=r(h.mph, 1), game=int(h.game_id), date=h.date,
                                                                 period=int(h.period), t=h.time_in_period) for h in top.itertuples()]
    for x in gareas.itertuples() if len(gareas) else []:
        if x.area == "all:high" and not pd.isna(x.save_pct):
            out["goalie_hd"][int(x.goalie_id)] = dict(save_pct=r(x.save_pct, 3), pctile=r(x.save_pct_pctile, 2),
                                                      lg=r(x.league_save_pct, 3))
    print(f"  edge extras: {len(out['player'])} skaters with area/speed data, {len(out['miles'])} player-games with distance, "
          f"{len(out['goalie_hd'])} goalies")
    return out


# ------------------------------------------------------------------ market lines

def american_p(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def fetch_market(slate):
    """DraftKings lines the NHL API publishes for today's games (moneyline, total, puck line). Free, live only.
    Returns {game_id: {...}} with the vig removed from each two-way market and the total goals the over
    price implies (the mean that gives that over probability under the same tie rule the model uses)."""
    out = {}
    try:
        req = urllib.request.Request("https://api-web.nhle.com/v1/partner-game/US/now", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            js = json.load(resp)
    except Exception as e:
        print(f"  market lines unavailable ({e!r})")
        return out
    ids = {g["id"] for g in slate}
    for g in js.get("games", []):
        if g.get("gameId") not in ids:
            continue
        odds = {side: {(o["description"], o.get("qualifier") or ""): o["value"] for o in g[side + "Team"].get("odds", [])}
                for side in ("home", "away")}
        m = dict(book="DraftKings", updated=js.get("lastUpdatedUTC"))
        mh, ma = odds["home"].get(("MONEY_LINE_2_WAY", "")), odds["away"].get(("MONEY_LINE_2_WAY", ""))
        if mh is not None and ma is not None:
            ph, pa = american_p(mh), american_p(ma)
            m.update(ml_home=int(mh), ml_away=int(ma), p_home=round(ph / (ph + pa), 4))
        ov = next(((q, v) for (d, q), v in odds["home"].items() if d == "OVER_UNDER" and q.startswith("O")), None)
        un = next(((q, v) for (d, q), v in odds["away"].items() if d == "OVER_UNDER" and q.startswith("U")), None)
        if ov and un:
            line = float(ov[0][1:])
            po, pu = american_p(ov[1]), american_p(un[1])
            p_over = po / (po + pu)
            m.update(total=line, over=int(ov[1]), under=int(un[1]), p_over=round(p_over, 4))
            # the expected total that makes P(goals > line) = p_over, both teams equal, ties adding a goal
            lo, hi = 3.0, 10.0
            for _ in range(40):
                mid = (lo + hi) / 2
                d = M.total_dist(mid / 2, mid / 2)
                (lo, hi) = (mid, hi) if d[np.arange(len(d)) > line].sum() < p_over else (lo, mid)
            m["implied_total"] = round((lo + hi) / 2, 2)
        out[g["gameId"]] = m
    print(f"  market lines: {len(out)} of {len(ids)} games")
    return out


# ------------------------------------------------------------------ schedule

def fetch_schedule(day):
    """Two schedule weeks starting at `day`. Falls back to SCHEDULE_CACHE (json) offline."""
    games = []
    try:
        for start in (day, day + dt.timedelta(days=7)):
            req = urllib.request.Request(f"https://api-web.nhle.com/v1/schedule/{start}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                js = json.load(resp)
            for wk in js.get("gameWeek", []):
                for g in wk.get("games", []):
                    if g.get("gameType") in (2, 3):
                        games.append({"id": g["id"], "date": wk["date"], "start": g.get("startTimeUTC"),
                                      "away": g["awayTeam"]["abbrev"], "home": g["homeTeam"]["abbrev"],
                                      "state": g.get("gameState")})
    except Exception as e:  # sandbox / offline
        cache = os.environ.get("SCHEDULE_CACHE")
        print(f"  schedule fetch failed ({e!r}); cache={cache}")
        if cache and os.path.exists(cache):
            games = json.load(open(cache))
    seen, out = set(), []
    for g in games:
        if g["id"] not in seen:
            seen.add(g["id"])
            out.append(g)
    return sorted(out, key=lambda g: (g["date"], g["start"] or ""))


# ------------------------------------------------------------------ pieces

def standings(games, tg):
    reg = games[games.game_type == "regular"]
    rows = []
    for _, g in reg.iterrows():
        so = g.decided_in == "SO"
        for team, gf, ga in ((g.home, g.home_score, g.away_score), (g.away, g.away_score, g.home_score)):
            win = gf > ga
            rows.append(dict(team=team, w=int(win), l=int(not win and g.decided_in == "REG"),
                             otl=int(not win and g.decided_in != "REG"),
                             gf=gf - int(so and win), ga=ga - int(so and not win)))
    s = pd.DataFrame(rows).groupby("team").sum()
    s["gp"] = s.w + s.l + s.otl
    s["pts"] = 2 * s.w + s.otl
    t = tg[tg.game_type == "regular"].groupby("team").agg(xgf=("xgf", "sum"), xga=("xga", "sum"), toi=("toi", "sum"))
    s = s.join(t)
    s["xgf60"] = s.xgf / s.toi * 60
    s["xga60"] = s.xga / s.toi * 60
    s["xg_pct"] = 100 * s.xgf / (s.xgf + s.xga)
    s["g_minus_xg"] = s.gf - s.xgf          # finishing luck (+ = scoring above chances)
    s["ga_minus_xga"] = s.ga - s.xga        # goaltending luck (+ = allowing more than chances)
    s["pts_pct"] = s.pts / (2 * s.gp)
    s = s.reset_index().sort_values(["pts", "gp"], ascending=[False, True])
    return records(s, ["team", "gp", "w", "l", "otl", "pts", "pts_pct", "gf", "ga", "xgf", "xga",
                       "xgf60", "xga60", "xg_pct", "g_minus_xg", "ga_minus_xga"])


def goalies(gg, ev, names, prev_gg):
    sog = ev[ev.event.isin(["shot-on-goal", "goal"]) & ev.goalie_id.notna()]
    sa = sog.groupby("goalie_id").size()
    g = gg[gg.game_type == "regular"].groupby("player_id").agg(
        team=("team", "last"), gp=("game_id", "nunique"), starts=("starter", "sum"),
        toi=("toi", "sum"), xga=("xga", "sum"), ga=("ga", "sum"))
    g["sa"] = sa.reindex(g.index).fillna(0)
    g["sv_pct"] = 1 - g.ga / g.sa.replace(0, np.nan)
    g["gsax"] = g.xga - g.ga
    g["gsax60"] = g.gsax / g.toi * 60
    p = prev_gg[prev_gg.game_type == "regular"].groupby("player_id").agg(prev_gp=("game_id", "nunique"),
                                                                         prev_xga=("xga", "sum"), prev_ga=("ga", "sum"))
    g = g.join(p)
    g["prev_gsax"] = g.prev_xga - g.prev_ga
    g["name"] = g.index.map(names)
    g = g.reset_index().rename(columns={"player_id": "id"}).sort_values("gsax", ascending=False)
    return records(g[g.toi > 0], ["id", "name", "team", "gp", "starts", "sa", "ga", "xga", "gsax", "gsax60",
                                 "sv_pct", "prev_gp", "prev_gsax"])


def shot_coords(ev):
    """Unblocked shots, normalised so every team attacks the right-hand net."""
    s = ev[ev.event.isin(["shot-on-goal", "missed-shot", "goal"]) & ev.x.notna()].copy()
    is_home = s.team == s.home_team
    side = s.home_defending_side
    known = side.isin(["left", "right"])
    attack_right = np.where(known, np.where(is_home, side == "left", side == "right"), s.x >= 0)
    flip = np.where(attack_right, 1, -1)
    s["nx"], s["ny"] = s.x * flip, s.y * flip
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="slate date (default: today in Denver)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(ZoneInfo("America/Denver")).date()
    print(f"building site data for {today}")

    cur, prev = M.load(CUR), M.load(PREV)
    pri = M.build_prev_priors(prev)
    names = pd.concat([prev["names"], cur["names"]])
    names = names[~names.index.duplicated(keep="last")]
    plist = pd.read_csv(TBL(CUR, "players.csv.gz")).drop_duplicates("player_id").set_index("player_id")
    ev = pd.read_csv(TBL(CUR, "events.csv.gz"))
    ev = ev[ev.period_type != "SO"]
    ev["sc"] = ev.situation_code.fillna(0).astype(int).astype(str).str.zfill(4)
    games = cur["games"]

    # ---- meta
    last_game = games.date.max()
    meta = dict(updated=dt.datetime.now(ZoneInfo("America/Denver")).strftime("%Y-%m-%d %H:%M"),
                slate_date=str(today), season=CUR, games_played=int(len(games)), last_game=last_game,
                credit="Shot data and expected goals courtesy of MoneyPuck.com. Game data from the NHL API.")

    # ---- teams and goalies
    teams_rows = standings(games, cur["tg"])
    dump("teams.json", teams_rows)
    goalie_rows = goalies(cur["gg"], ev, names, prev["gg"])
    edge = load_edge(CUR)
    for g in goalie_rows:   # EDGE: high-danger save % from the NHL's tracked shot locations
        hd = edge["goalie_hd"].get(g["id"])
        if hd:
            g.update(hd_sv=hd["save_pct"], hd_sv_pctile=hd["pctile"], hd_sv_lg=hd["lg"])
    dump("goalies.json", goalie_rows)

    # ---- skaters: this season (all situations, MoneyPuck xG)
    pg = cur["pg"][cur["pg"].game_type == "regular"]
    sk = pg.groupby("player_id").agg(team=("team", "last"), pos=("pos", "last"), gp=("game_id", "nunique"),
                                     toi=("toi", "sum"), g=("g", "sum"), a=("a", "sum"), pts=("pts", "sum"),
                                     sog=("sog", "sum"), ixg=("ixg", "sum"), xgf=("xgf", "sum"), xga=("xga", "sum"),
                                     gf=("gf", "sum"), ga=("ga", "sum"))
    is_home = ev.team == ev.home_team
    own = np.where(is_home, ev.sc.str[2], ev.sc.str[1]).astype(int)
    opp = np.where(is_home, ev.sc.str[1], ev.sc.str[2]).astype(int)
    goals = ev[(ev.event == "goal")]
    ppg = goals[(own > opp)[ev.event.values == "goal"]]
    cnt = lambda s: s.dropna().astype(int).value_counts()
    sk["ppp"] = pd.concat([ppg.player1_id, ppg.player2_id, ppg.player3_id]).dropna().astype(int) \
                  .value_counts().reindex(sk.index).fillna(0)
    sk["hits"] = cnt(ev[ev.event == "hit"].player1_id).reindex(sk.index).fillna(0)
    sk["blk"] = cnt(ev[ev.event == "blocked-shot"].player2_id).reindex(sk.index).fillna(0)
    sk["toi_pg"] = sk.toi / sk.gp
    sk["ixg60"] = sk.ixg / sk.toi * 60
    sk["pts60"] = sk.pts / sk.toi * 60
    sk["g_minus_xg"] = sk.g - sk.ixg
    sk["oi_luck"] = (sk.gf - sk.ga) - (sk.xgf - sk.xga)   # on-ice goal diff vs expected, all situations
    # 5v5 on-ice from onice.py
    oi = pd.read_csv(os.path.join(AN, "onice_5v5.csv"), index_col=0)
    sk = sk.join(oi[["CF%", "xGF%", "xGF%_rel"]].rename(columns={"CF%": "cf5", "xGF%": "xgf5", "xGF%_rel": "rel5"}))
    # last season
    pp = prev["pg"][prev["pg"].game_type == "regular"].groupby("player_id").agg(
        p_team=("team", "last"), p_gp=("game_id", "nunique"), p_toi=("toi", "sum"), p_g=("g", "sum"),
        p_a=("a", "sum"), p_pts=("pts", "sum"), p_ixg=("ixg", "sum"))
    sk = sk.join(pp)
    sk["p_ixg60"] = sk.p_ixg / sk.p_toi * 60
    sk["p_pts60"] = sk.p_pts / sk.p_toi * 60
    # model-shrunk true-talent estimates (what the prop model believes)
    fp = M.fit_players(cur, str(today), pri)
    sk = sk.join(fp[["ixg60", "oxgf60", "ipp"]].rename(columns={"ixg60": "m_ixg60", "oxgf60": "m_oxgf60", "ipp": "m_ipp"}))
    # NHL Edge
    edge_path = os.path.join(ROOT, "data", "external", "edge", CUR, "skaters.csv.gz")
    if os.path.exists(edge_path):
        ed = pd.read_csv(edge_path).set_index("player_id")
        sk = sk.join(ed[["max_speed_mph", "max_speed_pctile", "bursts_20mph", "bursts_pctile", "top_shot_mph",
                         "top_shot_pctile", "distance_pctile", "oz_time_ev_pct"]])
    sk["name"] = sk.index.map(names)
    sk["num"] = plist.number.reindex(sk.index)
    sk_idx = sk.copy()                 # by player id, for the narrative layer
    sk = sk.reset_index().rename(columns={"player_id": "id"})
    cols = ["id", "name", "team", "pos", "num", "gp", "toi_pg", "g", "a", "pts", "ppp", "sog", "hits", "blk",
            "ixg", "ixg60", "pts60", "g_minus_xg", "oi_luck", "cf5", "xgf5", "rel5",
            "p_team", "p_gp", "p_g", "p_a", "p_pts", "p_ixg60", "p_pts60", "m_ixg60", "m_oxgf60", "m_ipp",
            "max_speed_mph", "max_speed_pctile", "bursts_20mph", "bursts_pctile", "top_shot_mph",
            "top_shot_pctile", "distance_pctile", "oz_time_ev_pct"]
    cols = [c for c in cols if c in sk.columns]
    sk_rows = records(sk.sort_values("pts", ascending=False), cols)   # written once the narrative layer adds form

    # ---- shot maps (this season): {player_id: [[x, y, xg_milli, goal], ...]}
    s = shot_coords(ev)
    mpx = pd.read_csv(os.path.join(AN, "shots_with_xg.csv.gz"), usecols=["game_id", "event_id", "xg"])
    s = s.merge(mpx, on=["game_id", "event_id"], how="left")
    # prefer MoneyPuck xG where available (same join as props_data)
    mpcols = ["game_id", "time", "shooterPlayerId", "xGoal", "period", "shotRebound", "shotRush", "shooterTimeOnIce"]
    mp = pd.concat([pd.read_csv(f, usecols=lambda c: c in mpcols)
                    for f in glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", CUR, "*.csv.gz"))])
    for c in ("shotRebound", "shotRush", "shooterTimeOnIce"):
        if c not in mp:
            mp[c] = np.nan
    mp = mp[mp.period <= 4]
    mp["game_id"] = int(CUR[:4]) * 1000000 + mp.game_id
    mp = mp.rename(columns={"time": "game_seconds", "shooterPlayerId": "player1_id"}) \
           .drop_duplicates(["game_id", "game_seconds", "player1_id"])
    s = s.merge(mp[["game_id", "game_seconds", "player1_id", "xGoal", "shotRebound", "shotRush", "shooterTimeOnIce"]],
                on=["game_id", "game_seconds", "player1_id"], how="left")
    s["xgv"] = s.xGoal.fillna(s.xg).fillna(0.05)
    # strength state from the shooter's side (EN = into an empty net, EA = shooter's goalie pulled)
    ih = s.team == s.home_team
    own_sk = np.where(ih, s.sc.str[2], s.sc.str[1]).astype(int)
    opp_sk = np.where(ih, s.sc.str[1], s.sc.str[2]).astype(int)
    own_g = np.where(ih, s.sc.str[3], s.sc.str[0]) == "1"
    opp_g = np.where(ih, s.sc.str[0], s.sc.str[3]) == "1"
    s["state"] = np.select([~opp_g, ~own_g, own_sk > opp_sk, own_sk < opp_sk], ["EN", "EA", "PP", "SH"], "EV")

    # ---- game catalogue (every game this season)
    from games import build_games
    stories = os.path.join(ROOT, "data", "stories", CUR, "recaps")
    shifts_all = pd.read_csv(TBL(CUR, "shifts.csv.gz"))
    game_index = build_games(CUR, ev, s, cur["pg"], cur["gg"], games, names, os.path.join(OUTD, "games"), stories,
                             shifts=shifts_all, plist=plist, speeds=edge["speed"])
    # ---- per-player game logs (one small file each, loaded when a player page opens)
    plog = os.path.join(OUTD, "players")
    os.makedirs(plog, exist_ok=True)
    plogs = {}
    gh = games.set_index("game_id")
    for pid, grp in cur["pg"].groupby("player_id"):
        rows = []
        for x in grp.sort_values(["date", "game_id"]).itertuples():
            if x.game_id not in gh.index:
                continue
            gm = gh.loc[x.game_id]
            home = gm.home == x.team
            gf_, ga_ = (int(gm.home_score), int(gm.away_score)) if home else (int(gm.away_score), int(gm.home_score))
            rows.append(dict(id=int(x.game_id), date=x.date, opp=x.opp, home=bool(home),
                             res="W" if gf_ > ga_ else ("OTL" if gm.decided_in != "REG" else "L"), gf=gf_, ga=ga_,
                             toi=r(x.toi, 1), g=int(x.g), a=int(x.a), sog=int(x.sog), ixg=r(x.ixg, 2),
                             xgf=r(x.xgf, 2), xga=r(x.xga, 2), miles=edge["miles"].get((int(pid), int(x.game_id))),
                             mph=edge["game_top"].get((int(pid), int(x.game_id)))))
        plogs[int(pid)] = rows

    # ---- All Three Zones (hand tracking, from the private repo when the nightly could fetch it): a "how he creates
    # offense" card per skater; this season's card replaces last season's once he has enough tracked minutes
    a3z_cards = {}
    try:
        import a3z as A3
        for season in (PREV, CUR):
            if A3.available(season):
                a3z_cards.update(A3.cards(season))
        if a3z_cards:
            meta["credit"] += " " + A3.CREDIT
            print(f"  a3z: {len(a3z_cards)} skater cards")
    except Exception as e:
        print(f"  a3z cards skipped: {e!r}")

    # ---- narrative layer: form, streaks, breakouts, regression, milestones (site/narrative.py)
    import narrative as N
    from previews import team_profile
    profiles = {t: {k: v for k, v in team_profile(t, s, cur["tg"], ev, game_index).items() if k != "last5"}
                for t in sorted(set(cur["tg"].team))}
    bios = N.load_bios(CUR)
    P = N.season_pulse(CUR, PREV, cur, prev, names, fp, pri["players"], sk_idx, teams_rows, goalie_rows, profiles, bios, today)
    for row in sk_rows:
        f = P["skater"].get(row["id"], {}).get("form", {})
        row["form"], row["fv"] = f.get("state"), f.get("verdict")
    dump("skaters.json", sk_rows)

    all_shots = s
    s = s[s.nx > 0]
    # [x, y, xg_milli, goal, game number (last 4 digits of the game id), game second, shot type code, mph or 0]
    from games import SHOT_CODE
    shots = {}
    for pid, grp in s.groupby("player1_id"):
        shots[str(int(pid))] = [[int(round(x)), int(round(y)), int(round(v * 1000)), int(e == "goal"), int(gid) % 10000,
                                 int(sec), SHOT_CODE.get(t, ""), edge["speed"].get((int(gid), int(pid), int(per), tip), 0)]
                                for x, y, v, e, gid, sec, t, per, tip in zip(grp.nx, grp.ny, grp.xgv, grp.event, grp.game_id,
                                                                             grp.game_seconds, grp.shot_type, grp.period,
                                                                             grp.time_in_period)]
    dump("shots.json", shots)

    # ---- tonight
    sched = fetch_schedule(today)
    slate = [g for g in sched if g["date"] == str(today)]
    gss = cur["gg"][cur["gg"].starter].sort_values("date")
    pgc = cur["pg"][cur["pg"].date < str(today)]
    teams_tonight = sorted({t for g in slate for t in (g["away"], g["home"])})
    lu = expected_lineups(teams_tonight, pgc, prev["pg"], cur["gg"], prev["gg"], names, today)
    def proj_goalie(team):
        """ESPN's probable starter when it's posted; otherwise most starts in the last five, skipping anyone hurt."""
        if team in lu["probable"]:
            return lu["probable"][team], "espn"
        last5 = gss[(gss.team == team) & ~gss.player_id.isin(lu["out"])].tail(5)
        if last5.empty:
            return None, "model"
        c = last5.player_id.value_counts()
        top = c[c == c.max()].index
        return int(last5[last5.player_id.isin(top)].player_id.iloc[-1]), "model"
    rows, gm_out = [], []
    rosters = lu["strength"]
    market = fetch_market(slate) if slate else {}
    yesterday = str(today - dt.timedelta(days=1))
    played = set(games[games.date == yesterday].home) | set(games[games.date == yesterday].away)
    tired = lambda t: t in played    # second night of a back-to-back
    if slate:
        fpt = M.fit_players(cur, str(today), pri, extra=lu["extra"])
        tm = M.fit_teams(cur, str(today), fpt, pri, M.K, rosters)
        for g in slate:
            (ga_, gas), (gh_, ghs) = proj_goalie(g["away"]), proj_goalie(g["home"])
            for team, opp, og in ((g["away"], g["home"], gh_), (g["home"], g["away"], ga_)):
                rows += [{"player_id": i, "team": team, "opp": opp, "opp_goalie": og, "game": g["id"],
                          "lineup": st, "lineup_note": note, "b2b": tired(team), "opp_b2b": tired(opp)}
                         for i, (st, note) in lu["pool"].get(team, {}).items()]
            la = M.team_lambda(tm, g["away"], g["home"], gh_) * M.b2b_factor(tired(g["away"]), tired(g["home"]))
            lh = M.team_lambda(tm, g["home"], g["away"], ga_) * M.b2b_factor(tired(g["home"]), tired(g["away"]))
            dist = M.total_dist(la, lh)
            k = np.arange(len(dist))
            def options(team, chosen):
                ids = list(dict.fromkeys(([chosen] if chosen else []) +
                                         gss[gss.team == team].player_id.astype(int).tolist()[::-1]))[:5]   # enough to match ESPN's probable starter
                return [dict(id=i, name=names.get(i), factor=r(M.goalie_factor(tm, team, i), 4),
                             starts=int((gss.player_id == i).sum()), out=bool(i in lu["out"])) for i in ids]
            mk = market.get(g["id"])
            if mk:   # how the model's own numbers compare with the market's
                mk["model_p_home"] = r(M.win_prob(la, lh), 4)
                mk["model_p_over"] = r(dist[np.arange(len(dist)) > mk["total"]].sum(), 4) if "total" in mk else None
            gm_out.append(dict(id=g["id"], start=g["start"], away=g["away"], home=g["home"], market=mk,
                               away_b2b=tired(g["away"]), home_b2b=tired(g["home"]),
                               away_goalie=ga_, home_goalie=gh_, away_goalie_src=gas, home_goalie_src=ghs,
                               away_goalies=options(g["away"], ga_), home_goalies=options(g["home"], gh_),
                               away_xg=r(la, 3), home_xg=r(lh, 3), total=r((dist * k).sum()),
                               o55=r(dist[k >= 6].sum(), 3), o65=r(dist[k >= 7].sum(), 3)))
        try:   # All Three Zones playmaking nudge on the points means (models.A3Z_B); off when the tables aren't here
            import a3z as A3
            M.A3Z_Z, M.A3Z_NORM = A3.current_z(CUR, PREV)
            if M.A3Z_Z:
                print(f"  a3z: points nudge for {len(M.A3Z_Z)} skaters (league mean factor {M.A3Z_NORM:.3f})")
        except Exception as e:
            print(f"  a3z points nudge skipped: {e!r}")
        d = M.price_players(pd.DataFrame(rows).set_index("player_id"), fpt, tm).reset_index()
        d["name"] = d.player_id.map(names)
        # under the radar: real chances, goals lagging, outside the slate's top 12 favourites
        rank = d.p_goal.rank(ascending=False)
        regular = d.lineup == "last"
        fwd = d[regular & (d.pos == "F") & (d.g - d.ixg <= -1.0) & (d.p_goal >= 0.22) & (rank > 12)].nlargest(8, "p_goal")
        dmen = d[regular & (d.pos == "D") & (d.g - d.ixg <= -0.3)].nlargest(3, "p_goal")
        d["radar"] = d.player_id.isin(set(fwd.player_id) | set(dmen.player_id))
        d = d.rename(columns={"player_id": "id"}).sort_values("p_goal", ascending=False)
        props = records(d, ["id", "name", "team", "opp", "game", "pos", "gp", "g", "pts", "ixg", "proj_toi",
                            "pp_share", "p_goal", "p_1pt", "p_2pts", "p_3pts", "lam_g", "lam_p", "g_f", "radar",
                            "lineup", "lineup_note"])
        archive_tonight(str(today), gm_out, props, lu)
        for p in props:
            f = P["skater"].get(p["id"], {}).get("form", {})
            p["form"], p["fv"] = f.get("state"), f.get("verdict")
    else:
        props = []
    stories, headlines = N.game_stories(P, gm_out, props, lu, sched, cur, prev, names, profiles, teams_rows, game_index,
                                        bios, today, CUR) if gm_out else ({}, [])
    for g in gm_out:
        g["storylines"] = stories.get(g["id"], {}).get("storylines", [])[:3]
    if gm_out:
        from previews import build_previews
        shifts = shifts_all
        posmap = plist.position.map(lambda p: "D" if p == "D" else ("G" if p == "G" else "F"))
        build_previews(slate, props, gm_out, all_shots, cur["tg"], ev, game_index, goalie_rows, pgc, shifts,
                       posmap, names, os.path.join(OUTD, "previews"),
                       os.path.join(ROOT, "data", "stories", CUR, "previews", str(today)), str(today), stories=stories)
    # ---- per-team profile (special teams, penalties, 5v5 share) plus storylines, for the Teams page
    for t, prof in profiles.items():
        T = P["team"].get(t, {})
        prof.update(story=[x["text"] for x in T.get("lines", []) if x["k"] != "luck"][:4],   # the page's lede covers luck
                    last10=T.get("last10"), xg10=T.get("xg10"))
    dump("team_profiles.json", profiles)
    # ---- the Pulse page, and the story block on each player page
    watch = sorted((dict(w, team=t, game=gid) for gid, x in stories.items() for t, ws in x["watch"].items() for w in ws[:1]),
                   key=lambda w: -(w["p_goal"] + 0.4 * w["p_2pts"]))
    dump("pulse.json", dict(date=str(today), through=last_game, note=P["sample_note"], headlines=headlines, watch=watch[:8],
                            **P["lists"]))
    dump("week.json", N.week_digest(cur, game_index, os.path.join(OUTD, "games"), names, P, bios, today))   # the weekly column's facts
    tonight_lines = {}
    for gid, x in stories.items():
        for line in x["storylines"]:
            if line.get("pid"):
                tonight_lines.setdefault(line["pid"], []).append(line["text"])
    for pid, rows in plogs.items():
        S = P["skater"].get(pid) or P["goalie"].get(pid) or {}
        story = {k: S.get(k) for k in ("bio", "form", "flags", "milestones", "career", "rookie", "age") if S.get(k) is not None}
        if pid in tonight_lines:
            story["tonight"] = tonight_lines[pid]
        with open(os.path.join(plog, f"{pid}.json"), "w") as f:
            json.dump(dict(log=rows, edge=edge["player"].get(pid), story=story or None, a3z=a3z_cards.get(pid)), f, separators=(",", ":"),
                      default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"  players/: {len(plogs)} game logs")
    dump("tonight.json", dict(date=str(today), games=gm_out, props=props, headlines=headlines,
                              lineup_source=lu["source"], disp=M.DISP,
                              goalie_note="Goalies are ESPN's probable starters where posted, otherwise most starts in "
                                          "each team's last five games. Check confirmations before betting."))

    # ---- model report: full-season backtest (static) + this season walk-forward
    bt_static = os.path.join(SITE, "static", "backtest_20252026.json")
    model = json.load(open(bt_static)) if os.path.exists(bt_static) else {}
    try:
        dates = [x for x in sorted(cur["pg"].date.unique()) if x >= f"{CUR[:4]}-10-04"]
        P1, T1 = M.run_backtest(cur, dates, pri)
        model["this_season"] = dict(player_games=int(len(P1)), games=int(len(T1)),
                                    goal_pred=r(P1.p_goal.sum(), 0), goal_actual=int(P1.y_goal.sum()),
                                    pts_pred=r(P1.p_2pts.sum(), 0), pts_actual=int(P1.y_2.sum()),
                                    goal_ll=r(M.logloss(P1.y_goal, P1.p_goal), 4),
                                    goal_ll_base=r(M.logloss(P1.y_goal, P1.base_g), 4))
    except Exception as e:
        print("  this-season backtest skipped:", e)
    try:   # the live record: frozen pre-game prices graded against results (analysis/track.py)
        import track
        model["live"] = track.track(cur)
    except Exception as e:
        print("  live track record skipped:", e)
    dump("model.json", model)

    # ---- in-game xG model for the live game page (ESPN feed, before MoneyPuck's numbers exist)
    import xg_live
    xg_live.train(os.path.join(OUTD, "xg_live.json"))

    # ---- fantasy roster
    cfg = json.load(open(os.path.join(SITE, "config.json")))
    week = [str(today + dt.timedelta(days=i)) for i in range(10)]
    team_days = {}
    for g in sched:
        if g["date"] in week:
            for t, o, h in ((g["away"], g["home"], False), (g["home"], g["away"], True)):
                team_days.setdefault(t, {})[g["date"]] = ("vs " if h else "@ ") + o
    roster = []
    for p in cfg["fantasy"]["roster"]:
        team = plist.team.get(p["id"]) if p["id"] in plist.index else p.get("team")
        roster.append(dict(id=p["id"], slot=p["slot"], team=team, name=names.get(p["id"], p.get("name")),
                           sched={d: team_days.get(team, {}).get(d) for d in week}))
    write_fantasy(dict(team_name=cfg["fantasy"]["team_name"], league=cfg["fantasy"]["league"],
                       days=week, roster=roster))
    meta["favorite_team"] = cfg.get("favorite_team", "COL")
    dump("meta.json", meta)


if __name__ == "__main__":
    main()
