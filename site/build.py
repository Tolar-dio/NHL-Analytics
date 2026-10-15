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
    dump("teams.json", standings(games, cur["tg"]))
    goalie_rows = goalies(cur["gg"], ev, names, prev["gg"])
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
    sk = sk.reset_index().rename(columns={"player_id": "id"})
    cols = ["id", "name", "team", "pos", "num", "gp", "toi_pg", "g", "a", "pts", "ppp", "sog", "hits", "blk",
            "ixg", "ixg60", "pts60", "g_minus_xg", "oi_luck", "cf5", "xgf5", "rel5",
            "p_team", "p_gp", "p_g", "p_a", "p_pts", "p_ixg60", "p_pts60", "m_ixg60", "m_oxgf60", "m_ipp",
            "max_speed_mph", "max_speed_pctile", "bursts_20mph", "bursts_pctile", "top_shot_mph",
            "top_shot_pctile", "distance_pctile", "oz_time_ev_pct"]
    cols = [c for c in cols if c in sk.columns]
    dump("skaters.json", records(sk.sort_values("pts", ascending=False), cols))

    # ---- shot maps (this season): {player_id: [[x, y, xg_milli, goal], ...]}
    s = shot_coords(ev)
    mpx = pd.read_csv(os.path.join(AN, "shots_with_xg.csv.gz"), usecols=["game_id", "event_id", "xg"])
    s = s.merge(mpx, on=["game_id", "event_id"], how="left")
    # prefer MoneyPuck xG where available (same join as props_data)
    mp = pd.concat([pd.read_csv(f, usecols=["game_id", "time", "shooterPlayerId", "xGoal", "period"])
                    for f in glob.glob(os.path.join(ROOT, "data", "external", "moneypuck", CUR, "*.csv.gz"))])
    mp = mp[mp.period <= 4]
    mp["game_id"] = int(CUR[:4]) * 1000000 + mp.game_id
    mp = mp.rename(columns={"time": "game_seconds", "shooterPlayerId": "player1_id"}) \
           .drop_duplicates(["game_id", "game_seconds", "player1_id"])
    s = s.merge(mp[["game_id", "game_seconds", "player1_id", "xGoal"]], on=["game_id", "game_seconds", "player1_id"],
                how="left")
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
                             shifts=shifts_all, plist=plist)
    # ---- per-player game logs (one small file each, loaded when a player page opens)
    plog = os.path.join(OUTD, "players")
    os.makedirs(plog, exist_ok=True)
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
                             xgf=r(x.xgf, 2), xga=r(x.xga, 2)))
        with open(os.path.join(plog, f"{int(pid)}.json"), "w") as f:
            json.dump(rows, f, separators=(",", ":"))
    print(f"  players/: {cur['pg'].player_id.nunique()} game logs")

    all_shots = s
    s = s[s.nx > 0]
    shots = {}
    for pid, grp in s.groupby("player1_id"):
        shots[str(int(pid))] = [[int(round(x)), int(round(y)), int(round(v * 1000)), int(e == "goal")]
                                for x, y, v, e in zip(grp.nx, grp.ny, grp.xgv, grp.event)]
    dump("shots.json", shots)

    # ---- tonight
    sched = fetch_schedule(today)
    slate = [g for g in sched if g["date"] == str(today)]
    gss = cur["gg"][cur["gg"].starter].sort_values("date")
    def proj_goalie(team):
        last5 = gss[gss.team == team].tail(5)
        if last5.empty:
            return None
        c = last5.player_id.value_counts()
        top = c[c == c.max()].index
        return int(last5[last5.player_id.isin(top)].player_id.iloc[-1])
    pgc = cur["pg"][cur["pg"].date < str(today)]
    rosters, rows, gm_out = {}, [], []
    for g in slate:
        for team in (g["away"], g["home"]):
            last = pgc[pgc.team == team].game_id.max()
            rosters[team] = pgc[(pgc.game_id == last) & (pgc.team == team)].player_id.tolist()
    if slate:
        fpt = M.fit_players(cur, str(today), pri)
        tm = M.fit_teams(cur, str(today), fpt, pri, M.K, rosters)
        for g in slate:
            ga_, gh_ = proj_goalie(g["away"]), proj_goalie(g["home"])
            for team, opp, og in ((g["away"], g["home"], gh_), (g["home"], g["away"], ga_)):
                rows += [{"player_id": i, "team": team, "opp": opp, "opp_goalie": og, "game": g["id"]}
                         for i in rosters[team]]
            la = M.team_lambda(tm, g["away"], g["home"], gh_)
            lh = M.team_lambda(tm, g["home"], g["away"], ga_)
            dist = M.total_dist(la, lh)
            k = np.arange(len(dist))
            def options(team, chosen):
                ids = list(dict.fromkeys(([chosen] if chosen else []) +
                                         gss[gss.team == team].player_id.astype(int).tolist()[::-1]))[:3]
                return [dict(id=i, name=names.get(i), factor=r(M.goalie_factor(tm, team, i), 4),
                             starts=int((gss.player_id == i).sum())) for i in ids]
            gm_out.append(dict(id=g["id"], start=g["start"], away=g["away"], home=g["home"],
                               away_goalie=ga_, home_goalie=gh_,
                               away_goalies=options(g["away"], ga_), home_goalies=options(g["home"], gh_),
                               away_xg=r(la, 3), home_xg=r(lh, 3), total=r((dist * k).sum()),
                               o55=r(dist[k >= 6].sum(), 3), o65=r(dist[k >= 7].sum(), 3)))
        d = M.price_players(pd.DataFrame(rows).set_index("player_id"), fpt, tm).reset_index()
        d["name"] = d.player_id.map(names)
        # under the radar: real chances, goals lagging, outside the slate's top 12 favourites
        rank = d.p_goal.rank(ascending=False)
        fwd = d[(d.pos == "F") & (d.g - d.ixg <= -1.0) & (d.p_goal >= 0.22) & (rank > 12)].nlargest(8, "p_goal")
        dmen = d[(d.pos == "D") & (d.g - d.ixg <= -0.3)].nlargest(3, "p_goal")
        d["radar"] = d.player_id.isin(set(fwd.player_id) | set(dmen.player_id))
        d = d.rename(columns={"player_id": "id"}).sort_values("p_goal", ascending=False)
        props = records(d, ["id", "name", "team", "opp", "game", "pos", "gp", "g", "pts", "ixg", "proj_toi",
                            "pp_share", "p_goal", "p_2pts", "lam_g", "lam_p", "g_f", "radar"])
    else:
        props = []
    if gm_out:
        from previews import build_previews
        shifts = shifts_all
        posmap = plist.position.map(lambda p: "D" if p == "D" else ("G" if p == "G" else "F"))
        build_previews(slate, props, gm_out, all_shots, cur["tg"], ev, game_index, goalie_rows, pgc, shifts,
                       posmap, names, os.path.join(OUTD, "previews"),
                       os.path.join(ROOT, "data", "stories", CUR, "previews", str(today)), str(today))
    # ---- per-team profile (special teams, penalties, 5v5 share) for the Teams page
    from previews import team_profile
    dump("team_profiles.json", {t: {k: v for k, v in team_profile(t, all_shots, cur["tg"], ev, game_index).items() if k != "last5"}
                                for t in sorted(set(cur["tg"].team))})
    dump("tonight.json", dict(date=str(today), games=gm_out, props=props,
                              goalie_note="Projected goalies = most starts in each team's last five games. "
                                          "Check confirmations before betting."))

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
    dump("model.json", model)

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
