"""The narrative layer: form, streaks, breakouts, regression, milestones and per-game storylines.

Feeds the Pulse page (data/pulse.json), the storylines and players to watch on previews and Tonight,
the story block on player pages and the storylines on team pages. Every sentence is written here from
our own tables, deterministically: no web search and no model calls.

Two rules run through all of it:
  * Process before results. Hot and cold are judged against what the model expected at the player's
    ice time, and every streak says whether the chances behind it are real.
  * Say what the model prices. Each game storyline carries `priced`: True when the prop and game model
    already moves on it (back-to-backs, injuries, goalies), False for stories it ignores on purpose
    (streaks, revenge games, hometowns, milestones), with a sentence on why.
"""
import datetime as dt, glob, gzip, json, math, os, re, sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import models as M  # noqa: E402

NICK = dict(ANA="Ducks", BOS="Bruins", BUF="Sabres", CGY="Flames", CAR="Hurricanes", CHI="Blackhawks", COL="Avalanche",
            CBJ="Blue Jackets", DAL="Stars", DET="Red Wings", EDM="Oilers", FLA="Panthers", LAK="Kings", MIN="Wild",
            MTL="Canadiens", NSH="Predators", NJD="Devils", NYI="Islanders", NYR="Rangers", OTT="Senators", PHI="Flyers",
            PIT="Penguins", SJS="Sharks", SEA="Kraken", STL="Blues", TBL="Lightning", TOR="Maple Leafs", VAN="Canucks",
            VGK="Golden Knights", WSH="Capitals", WPG="Jets", UTA="Mammoth", ARI="Coyotes")
DIVISION = {**{t: "Atlantic" for t in "BOS BUF DET FLA MTL OTT TBL TOR".split()},
            **{t: "Metropolitan" for t in "CAR CBJ NJD NYI NYR PHI PIT WSH".split()},
            **{t: "Central" for t in "CHI COL DAL MIN NSH STL UTA WPG".split()},
            **{t: "Pacific" for t in "ANA CGY EDM LAK SJS SEA VAN VGK".split()}}
# where each team plays, for hometown games: (city as written, states or provinces, the metro's towns)
METRO = {
    "ANA": ("Anaheim", {"California"},
            "Anaheim|Irvine|Orange|Santa Ana|Huntington Beach|Newport Beach|Fullerton|Mission Viejo|Garden Grove|Yorba Linda"),
    "BOS": ("Boston", {"Massachusetts"},
            "Boston|Cambridge|Quincy|Newton|Braintree|Brookline|Somerville|Medford|Weymouth|Framingham|Lowell|Lynn|Woburn|Andover|Hingham|Marshfield|Waltham|North Andover|Lexington|Winchester|Arlington|Dedham|Milton|Needham|Wellesley|Reading"),
    "BUF": ("Buffalo", {"New York"},
            "Buffalo|Amherst|Cheektowaga|Tonawanda|Orchard Park|West Seneca|Lancaster|Williamsville|Hamburg|East Aurora|Grand Island"),
    "CGY": ("Calgary", {"Alberta"},
            "Calgary|Airdrie|Cochrane|Okotoks|Chestermere"),
    "CAR": ("Raleigh", {"North Carolina"},
            "Raleigh|Durham|Cary|Chapel Hill|Apex|Wake Forest|Garner|Morrisville"),
    "CHI": ("Chicago", {"Illinois"},
            "Chicago|Evanston|Naperville|Oak Park|Schaumburg|Arlington Heights|Park Ridge|Hinsdale|Elmhurst|Glenview|Wilmette|Northbrook|Orland Park|Downers Grove|Palatine|Hoffman Estates|Winnetka|Lake Forest|Elk Grove Village|Highland Park|Oak Lawn|Libertyville|Barrington|Deerfield|Western Springs|La Grange"),
    "COL": ("Denver", {"Colorado"},
            "Denver|Aurora|Lakewood|Littleton|Englewood|Arvada|Westminster|Thornton|Boulder|Castle Rock|Parker|Centennial|Highlands Ranch|Broomfield|Golden|Wheat Ridge|Commerce City|Lone Tree|Louisville|Lafayette|Brighton|Evergreen"),
    "CBJ": ("Columbus", {"Ohio"},
            "Columbus|Dublin|Westerville|Hilliard|Upper Arlington|Worthington|Gahanna|Powell|Delaware"),
    "DAL": ("Dallas", {"Texas"},
            "Dallas|Plano|Frisco|Irving|Garland|Richardson|McKinney|Allen|Carrollton|Fort Worth|Arlington|Grapevine|Southlake|Coppell|Flower Mound|Lewisville|Keller|Prosper"),
    "DET": ("Detroit", {"Michigan"},
            "Detroit|Dearborn|Livonia|Troy|Warren|Southfield|Novi|Farmington Hills|Grosse Pointe|Grosse Pointe Woods|Grosse Pointe Farms|Grosse Pointe Park|Royal Oak|Ann Arbor|Canton|Sterling Heights|Rochester Hills|Rochester|Bloomfield Hills|Birmingham|Plymouth|Northville|Clarkston|Macomb|Clinton Township|West Bloomfield|Wyandotte|Trenton|Taylor|Westland|Shelby Township|Grosse Ile|Commerce Township|Belleville|St. Clair Shores|Harrison Township|Wixom|Brighton|Howell|Waterford|Utica|Romeo|Oakland|Fraser|Roseville|Dearborn Heights|Redford|Garden City|Allen Park|Southgate|Lincoln Park|Woodhaven|Monroe"),
    "EDM": ("Edmonton", {"Alberta"},
            "Edmonton|St. Albert|Sherwood Park|Spruce Grove|Leduc|Stony Plain|Fort Saskatchewan|Beaumont|St Albert"),
    "FLA": ("Sunrise", {"Florida"},
            "Sunrise|Fort Lauderdale|Miami|Boca Raton|Coral Springs|Plantation|Weston|Hollywood|Pembroke Pines|Davie|Parkland|Delray Beach|Pompano Beach"),
    "LAK": ("Los Angeles", {"California"},
            "Los Angeles|Santa Monica|Pasadena|Burbank|Glendale|Long Beach|Torrance|Manhattan Beach|Redondo Beach|El Segundo|Encino|Sherman Oaks|Calabasas|Thousand Oaks|Santa Clarita|Valencia|Northridge|Van Nuys|Hermosa Beach|Palos Verdes|Culver City|Woodland Hills"),
    "MIN": ("St. Paul", {"Minnesota"},
            "St. Paul|Saint Paul|Minneapolis|Bloomington|Edina|Eden Prairie|Eagan|Burnsville|Lakeville|Apple Valley|Woodbury|Plymouth|Maple Grove|Minnetonka|Wayzata|Roseville|White Bear Lake|Stillwater|Hastings|Blaine|Coon Rapids|Anoka|Hopkins|Richfield|Shakopee|Prior Lake|Elk River|Farmington|Rosemount|Cottage Grove|Inver Grove Heights|Mahtomedi|North St. Paul|Lino Lakes|Andover|Champlin|Chaska|Chanhassen|Excelsior|Orono|Mound|Rogers|Hugo|Forest Lake|South St. Paul|West St. Paul|Mendota Heights|New Brighton|Shoreview|Fridley|Golden Valley|Crystal|New Hope|St. Louis Park|Brooklyn Park|Osseo"),
    "MTL": ("Montreal", {"Quebec", "Québec"},
            "Montreal|Montréal|Laval|Longueuil|Brossard|Pointe-Claire|Dollard-des-Ormeaux|Terrebonne|Repentigny|Boucherville|Châteauguay|LaSalle|Kirkland|Beaconsfield|Saint-Laurent|Verdun|Lachine|Saint-Jérôme|Blainville|Mirabel|Saint-Eustache|Vaudreuil-Dorion|Mascouche"),
    "NSH": ("Nashville", {"Tennessee"},
            "Nashville|Franklin|Brentwood|Murfreesboro|Hendersonville"),
    "NJD": ("Newark", {"New Jersey"},
            "Newark|Jersey City|Morristown|Montclair|Paramus|Hoboken|Livingston|Wayne|Basking Ridge|Ridgewood|Summit|Short Hills|Chatham|Madison|Westfield|Cranford|Mahwah|Wyckoff|Saddle River|Franklin Lakes|Morris Plains|Parsippany|Randolph|Mendham|Bernardsville|Princeton"),
    "NYI": ("Elmont", {"New York"},
            "Elmont|Uniondale|Hempstead|Garden City|Huntington|Massapequa|Levittown|Smithtown|Commack|Syosset|Manhasset|Rockville Centre|Oceanside|Long Beach|Merrick|Bellmore|Wantagh|Seaford|Port Washington|Great Neck|Glen Cove|Oyster Bay|Bay Shore|Babylon|Northport|Stony Brook|Hauppauge|East Meadow|Valley Stream|Lynbrook|Freeport|Baldwin|Plainview|Jericho|Dix Hills"),
    "NYR": ("New York", {"New York"},
            "New York|Manhattan|Brooklyn|Bronx|Queens|Staten Island|Yonkers|White Plains|New Rochelle|Scarsdale|Rye|Mount Vernon|Larchmont|Mamaroneck|Bronxville|Harrison|Port Chester|Pelham|Tarrytown|Sleepy Hollow|Ossining|Chappaqua|Armonk|Bedford|Katonah|Pound Ridge|Greenwich"),
    "OTT": ("Ottawa", {"Ontario", "Quebec", "Québec"},
            "Ottawa|Kanata|Nepean|Orleans|Orléans|Gloucester|Gatineau|Barrhaven|Stittsville|Manotick|Kemptville|Carleton Place|Arnprior|Rockland|Embrun"),
    "PHI": ("Philadelphia", {"New Jersey", "Pennsylvania"},
            "Philadelphia|Cherry Hill|Haddonfield|Voorhees|King of Prussia|Media|Doylestown|West Chester|Bryn Mawr|Conshohocken|Wayne|Ardmore|Norristown|Marlton|Moorestown|Mount Laurel|Glen Mills|Newtown Square|Blue Bell|Fort Washington|Ambler|Langhorne|Yardley|Newtown|Holland|Abington|Jenkintown|Lansdale|North Wales|Exton|Malvern|Paoli|Berwyn|Havertown|Springfield|Swarthmore"),
    "PIT": ("Pittsburgh", {"Pennsylvania"},
            "Pittsburgh|Mt. Lebanon|Mount Lebanon|Bethel Park|Upper St. Clair|Monroeville|Cranberry Township|Wexford|Sewickley|McKeesport|Moon Township|Murrysville|Penn Hills|Allison Park|Gibsonia|Coraopolis|Canonsburg|McMurray|Peters Township|Bridgeville|Carnegie|Fox Chapel|Oakmont|Plum|Greensburg|Irwin|North Huntingdon|Butler|Mars|Beaver|Aliquippa"),
    "SJS": ("San Jose", {"California"},
            "San Jose|Santa Clara|Sunnyvale|Palo Alto|Mountain View|Cupertino|Los Gatos|Campbell|Milpitas|Fremont|San Mateo|Redwood City|Saratoga|Menlo Park|San Francisco|Oakland|Morgan Hill|Gilroy|Los Altos|Pleasanton|Danville|San Ramon"),
    "SEA": ("Seattle", {"Washington"},
            "Seattle|Bellevue|Redmond|Kirkland|Everett|Tacoma|Renton|Kent|Bothell|Issaquah|Lynnwood|Sammamish|Snohomish|Woodinville|Edmonds|Mercer Island|Federal Way|Auburn|Puyallup|Shoreline"),
    "STL": ("St. Louis", {"Illinois", "Missouri"},
            "St. Louis|Saint Louis|Chesterfield|Kirkwood|Ballwin|Florissant|St. Charles|O'Fallon|Webster Groves|Ladue|Creve Coeur|Town and Country|Wildwood|Fenton|Belleville|Edwardsville|Clayton|Maryland Heights|Manchester|Ellisville|Wentzville|St. Peters|Lake St. Louis|Brentwood|Sunset Hills|Collinsville|Glen Carbon|Affton|Mehlville|Arnold"),
    "TBL": ("Tampa", {"Florida"},
            "Tampa|St. Petersburg|Clearwater|Brandon|Lutz|Wesley Chapel|Largo|Palm Harbor|Riverview|Land O' Lakes|Oldsmar|Dunedin|Seminole"),
    "TOR": ("Toronto", {"Ontario"},
            "Toronto|Mississauga|Brampton|Markham|Vaughan|Richmond Hill|Oakville|Pickering|Ajax|Whitby|Oshawa|Scarborough|Etobicoke|North York|Woodbridge|Thornhill|King City|Aurora|Newmarket|Milton|Burlington|Stouffville|Whitchurch-Stouffville|Maple|Concord|Bolton|Caledon|Georgetown|Halton Hills|East York|York|Uxbridge|Bowmanville|Courtice|Clarington|King|Nobleton|Kleinburg|Unionville|Bradford|East Gwillimbury|Keswick|Georgina"),
    "UTA": ("Salt Lake City", {"Utah"},
            "Salt Lake City|Provo|Ogden|Sandy|West Jordan|Park City|Orem|Draper|Murray|West Valley City|Lehi|Layton"),
    "VAN": ("Vancouver", {"British Columbia"},
            "Vancouver|Burnaby|Richmond|Surrey|North Vancouver|West Vancouver|Coquitlam|Port Coquitlam|Port Moody|Langley|Delta|New Westminster|Maple Ridge|White Rock|Abbotsford|Ladner|Tsawwassen|Pitt Meadows|Mission|Chilliwack|Aldergrove|Cloverdale"),
    "VGK": ("Las Vegas", {"Nevada"},
            "Las Vegas|Henderson|North Las Vegas|Summerlin|Boulder City"),
    "WSH": ("Washington", {"D.C.", "DC", "District of Columbia", "Maryland", "Virginia"},
            "Washington|Arlington|Alexandria|Bethesda|Silver Spring|Rockville|Fairfax|Reston|McLean|Potomac|Gaithersburg|Chevy Chase|Vienna|Falls Church|Herndon|Leesburg|Ashburn|Germantown|Olney|Annandale|Springfield|Burke|Bowie|Laurel|Columbia|Ellicott City|Annapolis|Kensington"),
    "WPG": ("Winnipeg", {"Manitoba"},
            "Winnipeg|Selkirk|Steinbach|Stonewall|Oakbank|East St. Paul|West St. Paul|Lorette"),
}
_METRO = {t: ({s.lower() for s in states}, {x.lower() for x in towns.split("|")}) for t, (_, states, towns) in METRO.items()}

ROUND = {1: "first-round", 2: "second-round", 3: "conference final", 4: "Stanley Cup Final"}
WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()


# ------------------------------------------------------------------ text helpers

def nw(n):
    n = int(n)
    return WORDS[n] if 0 <= n < len(WORDS) else f"{n:,}"


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def mmss(m):
    s = int(round(float(m) * 60))
    return f"{s // 60}:{s % 60:02d}"


def ordinal(n):
    n = int(n)
    return f"{n:,}" + ("th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def pl(n, word, plural=None):
    return f"{nw(n) if n <= 12 else f'{n:,}'} {word if n == 1 else (plural or word + 's')}"


def the(team):
    return f"the {NICK.get(team, team)}"


def theirs(team):
    n = NICK.get(team, team)
    return f"the {n}'" if n.endswith("s") else f"the {n}'s"


def gdiff(x):
    return "an even goal difference" if round(x) == 0 else f"a {sign(x, 0)} goal difference"


STATUS = {"out": "out", "injured reserve": "on injured reserve", "suspension": "suspended", "day-to-day": "day-to-day"}


def sv3(x):
    return f"{x:.3f}"[1:] if x is not None and x < 1 else f"{x:.3f}"


def r(x, n=2):
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def num(x, d=1):
    return f"{x:.{d}f}"


def last_name(name):
    return (name or "").split(" ", 1)[-1]


def sign(x, d=1):
    return ("+" if x > 0 else "-" if x < 0 else "") + f"{abs(x):.{d}f}"


def record(rs):
    w, l, o = rs.count("W"), rs.count("L"), rs.count("OTL")
    return f"{w}-{l}-{o}"


# ------------------------------------------------------------------ inputs

def load_bios(season):
    path = os.path.join(ROOT, "data", "external", "bios", season, "bios.json.gz")
    if not os.path.exists(path):
        return {}
    with gzip.open(path, "rt") as f:
        return {int(k): v for k, v in json.load(f).items()}


def goalie_box(season):
    """Per goalie-game decision and shots against from the raw boxscores: game_id, player_id, team, dec, sa."""
    rows = []
    for f in glob.glob(os.path.join(ROOT, "data", "raw", season, "*", "boxscore.json.gz")):
        try:
            with gzip.open(f, "rt") as fh:
                j = json.load(fh)
        except Exception:
            continue
        gid = int(os.path.basename(os.path.dirname(f)))
        for side in ("homeTeam", "awayTeam"):
            team = (j.get(side) or {}).get("abbrev")
            for g in (j.get("playerByGameStats") or {}).get(side, {}).get("goalies", []):
                rows.append(dict(game_id=gid, player_id=int(g["playerId"]), team=team, dec=g.get("decision"),
                                 sa=g.get("shotsAgainst") or 0))
    return pd.DataFrame(rows, columns=["game_id", "player_id", "team", "dec", "sa"])


def age_on(birth, day):
    try:
        b = dt.date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


def is_rookie(bio, season, day):
    """NHL rule: no more than 25 games in any earlier season, never 6+ in each of two earlier seasons,
    and under 26 on September 15 of the season."""
    if not bio:
        return False
    per = {}
    for s, _, gp in bio.get("nhl_teams") or []:
        if str(s) < season:
            per[s] = per.get(s, 0) + gp
    if any(v > 25 for v in per.values()) or sum(v >= 6 for v in per.values()) >= 2:
        return False
    a = age_on(bio.get("birth_date"), dt.date(int(season[:4]), 9, 15))
    return a is not None and a < 26


def born_in(bio):
    if not bio or not bio.get("birth_city"):
        return None
    where = bio["birth_city"]
    if bio.get("birth_state") and bio.get("birth_country") in ("USA", "CAN"):
        where += f", {bio['birth_state']}"
    elif bio.get("birth_country"):
        where += f", {COUNTRY.get(bio['birth_country'], bio['birth_country'])}"
    return where


COUNTRY = dict(CAN="Canada", USA="USA", SWE="Sweden", RUS="Russia", FIN="Finland", CZE="Czechia", CHE="Switzerland",
               DEU="Germany", SVK="Slovakia", LVA="Latvia", DNK="Denmark", NOR="Norway", AUT="Austria", FRA="France",
               BLR="Belarus", SVN="Slovenia", KAZ="Kazakhstan", UKR="Ukraine", GBR="Britain", AUS="Australia",
               NLD="Netherlands", ITA="Italy", POL="Poland", JPN="Japan", KOR="South Korea", HUN="Hungary", EST="Estonia",
               LTU="Lithuania", BRA="Brazil", JAM="Jamaica", NGA="Nigeria", HTI="Haiti", ZAF="South Africa", KOR_="Korea")


def hometown_team(bio):
    """The NHL team whose metro area a player was born in, if any."""
    if not bio or not bio.get("birth_city") or bio.get("birth_country") not in ("USA", "CAN"):
        return None
    city, state = bio["birth_city"].strip().lower(), (bio.get("birth_state") or "").strip().lower()
    for t, (states, towns) in _METRO.items():
        if state in states and city in towns:
            return t
    return None


# ------------------------------------------------------------------ skaters: form and streaks

def _expected(rows, rate):
    """Per-game expected points and goals at the player's actual ice time, from the prop model's rates."""
    toi = rows.toi.values
    ofin = rate.get("ofin", 1.0)
    ofin = 1.0 if ofin is None or (isinstance(ofin, float) and math.isnan(ofin)) else ofin
    ep = rate["oxgf60"] / 60 * toi * rate["ipp"] * ofin * M.PTS_CAL
    eg = rate["ixg60"] / 60 * toi * rate["fin"]
    return ep, eg


def skater_form(pid, grp, rate, prev_toi, n_max=10):
    """Last-N form against expectation, plus streaks and droughts. grp: this season's games, oldest first."""
    ep_all, eg_all = _expected(grp, rate)
    out = dict(streaks=[])
    # streaks run newest first
    pts, gls = grp.pts.values[::-1], grp.g.values[::-1]
    run = lambda arr, ok: next((i for i, v in enumerate(arr) if not ok(v)), len(arr))
    ps, gs = run(pts, lambda v: v > 0), run(gls, lambda v: v > 0)
    dp, dg = run(pts, lambda v: v == 0), run(gls, lambda v: v == 0)
    if ps >= 4:
        g, a = int(gls[:ps].sum()), int(grp.a.values[::-1][:ps].sum())
        out["streaks"].append(dict(k="points", n=ps, text=f"{ps}-game point streak ({g} G, {a} A)", w=ps))
    if gs >= 3:
        out["streaks"].append(dict(k="goals", n=gs, text=f"Goals in {nw(gs)} straight games ({int(gls[:gs].sum())} in all)", w=gs + 1))
    if dp >= 4:
        e = float(ep_all[::-1][:dp].sum())
        if e >= 2.5:
            tail = grp.iloc[-dp:]
            e_ox_d = rate["oxgf60"] / 60 * float(tail.toi.sum())
            due = float(tail.xgf.sum()) >= 0.95 * e_ox_d
            out["streaks"].append(dict(k="pointless", n=dp, w=e, due=due,
                                       text=f"Pointless in {nw(dp)} straight on {num(e)} expected" +
                                            ("; the chances are there" if due else ", and the chances have thinned out too")))
    if dg >= 5:
        x = float(grp.ixg.values[::-1][:dg].sum())
        if x >= 2.5:
            out["streaks"].append(dict(k="goalless", n=dg, text=f"No goals in {nw(dg)} games on {num(x)} expected goals", w=x,
                                       due=True))   # 2.5+ xG on his own shots: the chances are there by construction

    rows = grp.tail(n_max)
    n = len(rows)
    ep, eg = float(ep_all[-n:].sum()), float(eg_all[-n:].sum())
    P, G, A = int(rows.pts.sum()), int(rows.g.sum()), int(rows.a.sum())
    ixg, ox = float(rows.ixg.sum()), float(rows.xgf.sum())
    tsum = float(rows.toi.sum())
    e_ix, e_ox = rate["ixg60"] / 60 * tsum, rate["oxgf60"] / 60 * tsum
    ro = ox / e_ox if e_ox > 0 else 1.0
    ri = ixg / e_ix if e_ix > 0 else 1.0
    zp = (P - ep) / math.sqrt(max(ep, 0.5) * 1.35)
    zg = (G - eg) / math.sqrt(max(eg, 0.3))
    toi_w = tsum / n if n else 0
    before = grp.iloc[:-n] if len(grp) - n >= 5 else None
    base_toi = float(before.toi.mean()) if before is not None else prev_toi
    dtoi = toi_w - base_toi if base_toi else None
    out.update(n=n, pts=P, g=G, a=A, xpts=r(ep, 1), xg=r(eg, 1), ixg=r(ixg, 1), ox=r(ox, 1), e_ox=r(e_ox, 1),
               e_ix=r(e_ix, 1), toi=r(toi_w, 2), dtoi=r(dtoi, 2), state=None)
    if n < 5:
        return out
    hot_p, hot_g = P - ep >= 3 and zp >= 1.6, G - eg >= 2.5 and zg >= 1.8
    cold_p = ep >= 3 and ep - P >= 2.5 and zp <= -1.5
    cold_g = eg >= 2.2 and G == 0 and P <= ep - 1.5
    ice = ""
    if dtoi is not None and abs(dtoi) >= 1.5:
        ice = f" His ice time is {'up' if dtoi > 0 else 'down'} {mmss(abs(dtoi))} a night over that stretch."
    head = f"{P} points ({G} G) in his last {nw(n)} games; the model expected about {num(ep)} at his ice time."
    # the process check uses one measure, named in the text: his own shots' xG for a goal-only run, otherwise
    # whichever of his own chances and his team's chances with him on the ice moved more
    own = lambda: f"{num(ixg)} xG on his own shots against {num(e_ix)} usual"
    on = lambda: f"{num(ox)} on-ice expected goals against {num(e_ox)} usual"
    if hot_p or hot_g:
        use_own = (hot_g and not hot_p) or ri >= ro
        proc, chances = (ri, own()) if use_own else (ro, on())
        if proc >= 1.15:
            v, why = "earned", (f"Earned: he's getting more chances too ({chances})." if use_own else
                                f"Earned: his team is creating more with him out there too ({chances}).")
        elif proc < 1.0:
            v, why = "bounces", f"Mostly bounces: the chances are normal ({chances}), so expect it to cool."
        else:
            v, why = "partly", f"Partly real: the chances are up a little ({chances}), but finishing is doing most of the work."
        out.update(state="hot", verdict=v, z=r(max(zp, zg), 2), text=f"{head} {why}{ice}", why=f"{why}{ice}")
    elif cold_p or cold_g:
        use_own = cold_g and not cold_p
        proc, chances = (ri, own()) if use_own else (ro, on())
        if proc >= 0.95:
            v, why = "due", f"Due: the chances are still there ({chances}); the pucks aren't going in."
        elif proc < 0.8:
            v, why = "real", f"A real dip: the chances have dried up too ({chances})."
        else:
            v, why = "mixed", f"Some of each: a few fewer chances ({chances}), and the ones he gets aren't going in."
        out.update(state="cold", verdict=v, z=r(min(zp, zg), 2), text=f"{head} {why}{ice}", why=f"{why}{ice}")
    return out


# ------------------------------------------------------------------ the season pulse

def season_pulse(season, prev_season, cur, prev, names, fp, pri_players, sk, standings, goalie_rows, profiles, bios, today):
    """Everything that doesn't depend on tonight's slate: form, streaks, breakouts, regression, milestones,
    goalie and team form. Returns a dict with per-player, per-goalie and per-team pieces plus the Pulse lists."""
    pg = cur["pg"][cur["pg"].game_type == "regular"].sort_values(["date", "game_id"])
    ppg = prev["pg"][prev["pg"].game_type == "regular"]
    prev_tot = ppg.groupby("player_id").agg(p_gp=("game_id", "nunique"), p_toi=("toi", "sum"), p_g=("g", "sum"),
                                            p_sog=("sog", "sum"), p_pts=("pts", "sum"))
    fp = fp.copy()
    fp["ofin"] = fp["ofin"].fillna(1.0) if "ofin" in fp else 1.0
    sk = sk.copy()
    games = cur["games"][cur["games"].game_type == "regular"]
    team_gp = pd.concat([games.home, games.away]).value_counts()
    gp_med = float(team_gp.median()) if len(team_gp) else 0

    P = dict(skater={}, goalie={}, team={}, lists={})
    # --- skaters
    for pid, grp in pg.groupby("player_id"):
        pid = int(pid)
        if pid not in fp.index or grp.pos.iloc[-1] == "G":
            continue
        rate = fp.loc[pid]
        pt = prev_tot.loc[pid] if pid in prev_tot.index else None
        prev_toi = float(pt.p_toi / pt.p_gp) if pt is not None and pt.p_gp >= 10 else None
        f = skater_form(pid, grp, rate, prev_toi)
        bio = bios.get(pid) or {}
        car = bio.get("career_prev") or {}
        season_tot = dict(gp=int(len(grp)), g=int(grp.g.sum()), a=int(grp.a.sum()), pts=int(grp.pts.sum()), ixg=r(grp.ixg.sum(), 1))
        P["skater"][pid] = dict(id=pid, name=names.get(pid), team=grp.team.iloc[-1], pos=grp.pos.iloc[-1], form=f,
                                prev=dict(gp=int(pt.p_gp), pts=int(pt.p_pts), g=int(pt.p_g)) if pt is not None else None,
                                season=season_tot, flags=[], milestones=[],
                                career=dict(gp=car.get("gamesPlayed", 0) + season_tot["gp"], g=car.get("goals", 0) + season_tot["g"],
                                            a=car.get("assists", 0) + season_tot["a"], pts=car.get("points", 0) + season_tot["pts"])
                                if car else None,
                                bio=_bio_card(bio, today, season) if bio else None,
                                role=dict(toi=r(rate["toi_pg"], 2), pp=r(rate.get("pp_share"), 2)),
                                rate=dict(ppg=float(rate["oxgf60"] / 60 * rate.get("proj_toi", rate["toi_pg"]) * rate["ipp"] *
                                                    rate["ofin"] * M.PTS_CAL),
                                          gpg=float(rate["ixg60"] / 60 * rate.get("proj_toi", rate["toi_pg"]) * rate["fin"])))

    # --- breakouts, rookies, regression (season level)
    for pid, x in sk.iterrows():
        pid = int(pid)
        S = P["skater"].get(pid)
        if S is None or x.gp < 4:
            continue
        bio = bios.get(pid) or {}
        age = age_on(bio.get("birth_date"), dt.date(int(season[:4]), 10, 1))
        p_gp = x.get("p_gp") if not pd.isna(x.get("p_gp")) else 0
        pt = prev_tot.loc[pid] if pid in prev_tot.index else None
        rookie = is_rookie(bio, season, today)
        S["rookie"] = rookie
        S["age"] = age
        # breakout: a young player whose role and chances have both stepped up
        if age is not None and age <= 25 and p_gp >= 15 and not rookie:
            prev_toi = x.p_toi / p_gp
            dtoi = x.toi_pg - prev_toi
            pps = fp.loc[pid, "pp_share"] if pid in fp.index else None
            ppp = pri_players.loc[pid, "pp_share"] if pid in pri_players.index else None
            dpp = (pps - ppp) if pps is not None and ppp is not None and not pd.isna(pps) and not pd.isna(ppp) else 0
            dix = (x.ixg60 - x.p_ixg60) if x.toi >= 60 and not pd.isna(x.p_ixg60) else 0
            dpace = x.pts / x.gp - x.p_pts / p_gp
            role_up, prod_up = dtoi >= 1.5 or dpp >= 0.15, dix >= 0.15 or dpace >= 0.2
            score = max(0, dtoi) / 2 + max(0, dpp) / 0.2 + max(0, dix) / 0.25 + max(0, dpace) / 0.3
            if role_up and prod_up and score >= 3.0:
                bits = []
                if dtoi >= 1.0:
                    bits.append(f"playing {mmss(x.toi_pg)} a night, up from {mmss(prev_toi)},")
                if dpp >= 0.12:
                    bits.append(f"on the ice for {round(100 * pps)}% of his team's power-play chances (was {round(100 * ppp)}%)")
                role = (cap(" and ".join(bits)).rstrip(",") + ".") if bits else ""
                prod = (f"{int(x.pts)} points in {int(x.gp)} games ({num(x.pts / x.gp, 2)} a game, {num(x.p_pts / p_gp, 2)} last season)")
                if dix >= 0.15:
                    prod += f", and his own chances are up to {num(x.ixg60, 2)} xG per 60 from {num(x.p_ixg60, 2)}"
                text = f"Age {age}. {role} {prod}.".replace("  ", " ")
                if x.gp < 20:
                    text += f" {cap(nw(int(x.gp)))} games is a small sample; ice time settles faster than scoring does."
                S["flags"].append(dict(k="breakout", label="Breakout", text=text, score=r(score, 2)))
        # regression: finishing far from the chances
        gx = x.g - x.ixg
        if gx >= 2.5 and x.g >= 4:
            sh = x.g / x.sog if x.sog else None
            psh = (pt.p_g / pt.p_sog) if pt is not None and pt.p_sog >= 30 else None
            text = f"{int(x.g)} goals on {num(x.ixg)} expected"
            if sh is not None:
                text += f", shooting {round(100 * sh)}%" + (f" ({round(100 * psh)}% last season)" if psh is not None else "")
            text += ". The chances are real; that finishing rate rarely lasts."
            if x.oi_luck >= 4:
                text += f" His team has also scored {num(x.oi_luck)} more goals than expected with him on the ice."
            S["flags"].append(dict(k="cooling", label="Due to cool", text=text, score=r(gx + 0.5 * max(0, x.oi_luck), 2)))
        elif x.oi_luck >= 5 and x.pts / x.gp >= 0.8:
            S["flags"].append(dict(k="cooling", label="Due to cool",
                                   text=f"His team has scored {num(x.oi_luck)} more goals than the chances deserve with him on the ice, "
                                        f"which is padding his {int(x.pts)} points. On-ice luck like that fades.",
                                   score=r(0.6 * x.oi_luck, 2)))
        if -gx >= 2.0 and x.ixg >= 2.5:
            text = (f"{int(x.g)} goal{'s' if x.g != 1 else ''} on {num(x.ixg)} expected. He keeps getting the looks, "
                    f"and goals tend to follow chances.")
            if x.oi_luck <= -4:
                text += f" His team has also scored {num(-x.oi_luck)} fewer goals than expected with him out there."
            S["flags"].append(dict(k="due", label="Due", text=text, score=r(-gx + 0.4 * max(0, -x.oi_luck), 2)))
        elif x.oi_luck <= -4.5 and x.gp >= 5:
            S["flags"].append(dict(k="due", label="Due",
                                   text=f"His team has scored {num(-x.oi_luck)} fewer goals than the chances deserve with him on the ice, "
                                        f"which has cost him points. That usually swings back.",
                                   score=r(0.6 * -x.oi_luck, 2)))

    # --- skater milestones (career before his next game)
    for pid, S in P["skater"].items():
        if S["career"]:
            S["milestones"] = _milestones(S["career"], S["rate"], S["season"]["gp"], goalie=False)
    # --- goalies
    _goalies(P, season, cur, names, bios, goalie_rows, today)
    # --- teams
    _teams(P, cur, standings, profiles, gp_med)

    # --- the lists for the Pulse page
    sks = [S for S in P["skater"].values() if S["form"].get("n", 0) >= 5]
    item = lambda S, extra: dict(id=S["id"], name=S["name"], team=S["team"], pos=S["pos"], **extra)
    hot = sorted((S for S in sks if S["form"]["state"] == "hot"), key=lambda S: -S["form"]["z"])
    cold = sorted((S for S in sks if S["form"]["state"] == "cold"), key=lambda S: S["form"]["z"] * (0.6 + S["rate"]["ppg"]))
    fcard = lambda S: item(S, dict(n=S["form"]["n"], pts=S["form"]["pts"], g=S["form"]["g"], xpts=S["form"]["xpts"],
                                   verdict=S["form"]["verdict"], text=S["form"]["text"], why=S["form"]["why"]))
    flag = lambda k: sorted(((S, fl) for S in P["skater"].values() for fl in S["flags"] if fl["k"] == k), key=lambda t: -t[1]["score"])
    streak = lambda k: sorted(((S, s) for S in P["skater"].values() for s in S["form"]["streaks"] if s["k"] == k),
                              key=lambda t: (-t[1]["n"], -t[0]["rate"]["ppg"]))
    rookies = sorted((S for S in P["skater"].values() if S.get("rookie") and S["season"]["gp"] >= 3),
                     key=lambda S: -(S["season"]["pts"] / S["season"]["gp"] + 0.5 * S["rate"]["ppg"]))
    ms = [(S, m) for S in P["skater"].values() for m in S["milestones"] if m["reach"]]
    ms += [(G, m) for G in P["goalie"].values() for m in G.get("milestones", [])]
    big = lambda m: (1 if m["stat"] in ("g", "a", "pts", "w") else 0) + (0.5 if m["target"] >= 500 else 0) + \
        (1 if m["target"] >= 1000 else 0) - (1.5 if m["stat"].startswith("first") else 0)
    ms.sort(key=lambda t: min(t[1]["eta"], 6) - big(t[1]))
    sk_by = sk["toi_pg"].to_dict()
    P["lists"] = dict(
        hot=[fcard(S) for S in hot[:12]],
        cold=[fcard(S) for S in cold[:12]],
        streaks=[item(S, dict(k=s["k"], n=s["n"], text=s["text"])) for S, s in (streak("points")[:8] + streak("goals")[:5])],
        droughts=[item(S, dict(k=s["k"], n=s["n"], text=s["text"])) for S, s in
                  sorted(streak("pointless") + streak("goalless"), key=lambda t: -t[1]["w"])[:8]],
        breakouts=[item(S, dict(text=f["text"])) for S, f in flag("breakout")[:10]],
        cooling=[item(S, dict(text=f["text"])) for S, f in flag("cooling")[:8]],
        due=[item(S, dict(text=f["text"])) for S, f in flag("due")[:8]],
        rookies=[item(S, dict(gp=S["season"]["gp"], g=S["season"]["g"], pts=S["season"]["pts"], toi=r(sk_by.get(S["id"]), 1),
                              age=S.get("age"), text=_rookie_text(S, sk_by.get(S["id"]), bios.get(S["id"]))))
                 for S in rookies[:10]],
        milestones=[dict(id=X["id"], name=X["name"], team=X["team"], pos=X.get("pos", "G"), text=m["text"], need=m["need"],
                         stat=m["stat"], target=m["target"]) for X, m in ms[:16]],
        goalies_hot=sorted([G["card"] for G in P["goalie"].values() if G.get("state") == "hot"], key=lambda c: -c["gsax5"])[:6],
        goalies_cold=sorted([G["card"] for G in P["goalie"].values() if G.get("state") == "cold"], key=lambda c: c["gsax5"])[:6],
        teams=sorted([T["card"] for T in P["team"].values()], key=lambda c: -c["weight"]),
    )
    P["gp_med"] = gp_med
    P["sample_note"] = (f"Early season: teams have played about {nw(round(gp_med))} games. Streaks this short are mostly noise, "
                        f"so every verdict here leans on chances, which settle faster than goals."
                        if gp_med < 20 else
                        f"Teams have played about {round(gp_med)} games. Form is the last ten games, judged against what the model "
                        f"expected at each player's ice time.")
    return P


def _bio_card(bio, today, season):
    d = bio.get("draft") or {}
    hh = bio.get("height_in")
    out = dict(age=age_on(bio.get("birth_date"), today), born=born_in(bio), shoots=bio.get("shoots"),
               height=f"{hh // 12}'{hh % 12}\"" if hh else None, weight=bio.get("weight_lb"),
               draft=(f"{d['year']} {ordinal(d['round'])} round, {ordinal(d['overall'])} overall by {d['team']}"
                      if d and d.get("year") and d.get("overall") else "Undrafted" if bio.get("career_prev") is not None else None),
               hometown=hometown_team(bio))
    teams = []
    for s, t, gp in bio.get("nhl_teams") or []:
        if teams and teams[-1][0] == t:
            teams[-1][1] += gp
        else:
            teams.append([t, gp])
    out["teams"] = teams
    car = bio.get("career_prev") or {}
    if car.get("gamesPlayed") is not None:
        out["career_before"] = {k: car.get(k) for k in ("gamesPlayed", "goals", "assists", "points", "wins", "shutouts") if k in car}
    return out


def _rookie_text(S, toi, bio):
    s = S["season"]
    bits = [f"{s['pts']} points ({s['g']} G) in {s['gp']} games"]
    if toi:
        bits.append(f"{mmss(toi)} a night")
    d = (bio or {}).get("draft") or {}
    if d.get("overall"):
        bits.append(f"{ordinal(d['overall'])} pick in {d['year']}")
    f = S["form"]
    tail = ""
    if f.get("ixg") is not None and f.get("n"):
        tail = f" Chances: {num(f['ixg'])} expected goals on his own shots in his last {nw(f['n'])}."
    return ", ".join(bits) + "." + tail


LABEL = dict(gp="NHL game", g="goal", a="assist", pts="point", w="win")


def _milestones(car, rate, season_gp, goalie):
    """Round-number milestones near at hand. car: career totals before the next game. Each comes with `need`
    (how many more), `eta` (games away at his rate) and `reach` (close enough to talk about)."""
    out = []
    rate = rate or {}
    per_game = dict(gp=1.0, g=rate.get("gpg", 0.0), pts=rate.get("ppg", 0.0), a=rate.get("ppg", 0.0) - rate.get("gpg", 0.0), w=0.5)
    for k in (("gp", "w") if goalie else ("gp", "g", "a", "pts")):
        have = car.get(k)
        if have is None:
            continue
        step = 50 if k in ("g", "w") and have < 100 else 100     # 50 goals or wins first, then every hundred
        target = (int(have) // step + 1) * step
        need = target - int(have)
        eta = need / max(per_game[k], 1e-3)
        limit = dict(gp=3, g=3, a=3, pts=4, w=2)[k]
        reach = need <= limit and (eta <= 8 or need == 1)
        if k == "gp":
            text = f"{ordinal(target)} NHL game" + (" next time he plays" if need == 1 else f" in {nw(need)} games")
        else:
            text = f"{pl(need, LABEL[k])} from {target:,} career {LABEL[k]}s"
        out.append(dict(stat=k, have=int(have), target=int(target), need=int(need), eta=r(eta, 1), reach=bool(reach), text=text))
    if not goalie and season_gp >= 3:
        if car.get("g", 1) == 0:
            out.append(dict(stat="first_g", have=0, target=1, need=1, eta=r(1 / max(per_game["g"], 1e-3), 1), reach=True,
                            text=f"Still looking for his first NHL goal ({pl(int(car['gp']), 'game')} in)"))
        elif car.get("pts", 1) == 0:
            out.append(dict(stat="first_p", have=0, target=1, need=1, eta=r(1 / max(per_game["pts"], 1e-3), 1), reach=True,
                            text=f"Still looking for his first NHL point ({pl(int(car['gp']), 'game')} in)"))
    return [m for m in out if m["reach"]]


# ------------------------------------------------------------------ goalies

def _goalies(P, season, cur, names, bios, goalie_rows, today):
    gg = cur["gg"][cur["gg"].game_type == "regular"].copy()
    box = goalie_box(season) if len(gg) else pd.DataFrame()
    if len(box):
        gg = gg.merge(box[["game_id", "player_id", "dec", "sa"]], on=["game_id", "player_id"], how="left")
    else:
        gg["dec"], gg["sa"] = None, np.nan
    gg = gg.sort_values(["date", "game_id"])
    starts_by_team = gg[gg.starter].groupby("team").size()
    rows = {g["id"]: g for g in goalie_rows}
    for pid, g in gg.groupby("player_id"):
        pid = int(pid)
        st = g[g.starter]
        dec = g.dec.fillna("").tolist()
        w, l, o = dec.count("W"), dec.count("L"), dec.count("O")
        team = g.team.iloc[-1]
        last5 = st.tail(5)
        gsax5 = float((last5.xga - last5.ga).sum()) if len(last5) else 0.0
        sa5, ga5 = float(last5.sa.fillna(0).sum()), float(last5.ga.sum())
        sv5 = (sa5 - ga5) / sa5 if sa5 > 0 else None
        d5 = last5.dec.fillna("").tolist()
        rec5 = f"{d5.count('W')}-{d5.count('L')}-{d5.count('O')}"
        bio = bios.get(pid) or {}
        car = bio.get("career_prev") or {}
        G = dict(id=pid, name=names.get(pid), team=team, starts=int(len(st)), team_starts=int(starts_by_team.get(team, 0)),
                 rec=f"{w}-{l}-{o}", w=w, gsax5=r(gsax5, 1), sv5=r(sv5, 3), rec5=rec5, n5=int(len(last5)),
                 gsax=rows.get(pid, {}).get("gsax"), sv=rows.get(pid, {}).get("sv_pct"), bio=_bio_card(bio, today, season) if bio else None,
                 state=None)
        if len(last5) >= 4 and sv5 is not None:
            span = f"over his last {nw(len(last5))} starts ({rec5})"
            if gsax5 >= 3.5:
                G["state"] = "hot"
                G["text"] = (f"{G['name']} is on a heater: {sv3(sv5)} with {num(gsax5)} goals saved above expected {span}."
                             if sv5 >= 0.925 else
                             f"{G['name']} is better than his save rate looks: {sv3(sv5)} against hard shots, {num(gsax5)} goals "
                             f"saved above expected {span}.")
            elif gsax5 <= -3.5:
                G["state"] = "cold"
                G["text"] = (f"{G['name']} is struggling: {sv3(sv5)} and {num(-gsax5)} goals worse than expected {span}."
                             if sv5 <= 0.885 else
                             f"{G['name']} is leakier than his save rate looks: {sv3(sv5)} against easy shots, {num(-gsax5)} goals "
                             f"worse than expected {span}.")
        if G["state"]:
            G["card"] = dict(id=pid, name=G["name"], team=team, gsax5=G["gsax5"], sv5=G["sv5"], rec5=rec5, n5=G["n5"],
                             text=G["text"], gsax=G["gsax"], rec=G["rec"])
        if car.get("gamesPlayed") is not None:
            cg = dict(gp=car.get("gamesPlayed", 0) + int(len(g[g.toi > 0])), w=car.get("wins", 0) + w)
            G["career"] = cg
            ms = _milestones(cg, None, int(len(g)), goalie=True)
            for m in ms:
                m["eta"] = m["need"] * (2.0 if m["stat"] == "w" else 1.6)   # starters play most nights and win about half
            G["milestones"] = [m for m in ms if m["need"] <= (2 if m["stat"] == "w" else 1)]
        P["goalie"][pid] = G


# ------------------------------------------------------------------ teams

def _results(cur, team):
    g = cur["games"][(cur["games"].game_type == "regular") & ((cur["games"].home == team) | (cur["games"].away == team))]
    g = g.sort_values(["date", "game_id"])
    out = []
    tg = cur["tg"].set_index(["game_id", "team"])
    for x in g.itertuples():
        home = x.home == team
        gf, ga = (x.home_score, x.away_score) if home else (x.away_score, x.home_score)
        res = "W" if gf > ga else ("OTL" if x.decided_in != "REG" else "L")
        k = (x.game_id, team)
        xf, xa = (float(tg.loc[k, "xgf"]), float(tg.loc[k, "xga"])) if k in tg.index else (None, None)
        out.append(dict(id=int(x.game_id), date=x.date, opp=x.away if home else x.home, home=home, gf=int(gf), ga=int(ga),
                        res=res, end=x.decided_in, xf=xf, xa=xa))
    return out


def _streak(res):
    """Current run from the newest game: ('W', n), ('winless', n, record) or ('points', n, record)."""
    if not res:
        return None
    rs = [x["res"] for x in res][::-1]
    run = lambda ok: next((i for i, v in enumerate(rs) if not ok(v)), len(rs))
    w, nw_, pts = run(lambda v: v == "W"), run(lambda v: v != "W"), run(lambda v: v != "L")
    if w >= 3:
        return ("W", w, res[-w:])
    if nw_ >= 3:
        return ("winless", nw_, res[-nw_:])
    if pts >= 5:
        return ("points", pts, res[-pts:])
    return None


def _teams(P, cur, standings, profiles, gp_med):
    st = {t["team"]: t for t in standings}
    pp_rank = _rank({t: p.get("pp_xg_pg") for t, p in profiles.items()}, high=True)
    pk_rank = _rank({t: p.get("pk_xga_pg") for t, p in profiles.items()}, high=False)
    pen_rank = _rank({t: p.get("pen_taken_pg") for t, p in profiles.items()}, high=True)
    for team in sorted(st):
        res = _results(cur, team)
        T = dict(team=team, res=res, lines=[], pp_rank=pp_rank.get(team), pk_rank=pk_rank.get(team), pen_rank=pen_rank.get(team))
        s = _streak(res)
        weight = 0
        if s:
            kind, n, games = s
            gf, ga = sum(x["gf"] for x in games), sum(x["ga"] for x in games)
            xf, xa = sum(x["xf"] or 0 for x in games), sum(x["xa"] or 0 for x in games)
            share = xf / (xf + xa) if xf + xa else 0.5
            gsax = xa - ga
            if kind == "W":
                head = f"{cap(the(team))} have won {nw(n)} straight, outscoring teams {gf}-{ga}."
                carry = (f", with the goaltending saving {num(gsax)} goals above expected." if gsax >= 2 else
                         f", with finishing doing the rest ({gf} goals on {num(xf)} expected)." if gf - xf >= 2 else ".")
                tail = (f" The chances back it: {round(100 * share)}% of the expected goals in those games." if share >= 0.53 else
                        f" The chances only half back it: {round(100 * share)}% of the expected goals" + carry if share >= 0.47 else
                        f" The chances don't back it: {round(100 * share)}% of the expected goals" + carry)
            elif kind == "winless":
                head = f"{cap(the(team))} are winless in {nw(n)} ({record([x['res'] for x in games])}), outscored {ga}-{gf}."
                tail = (f" The chances say it's mostly bad luck: they got {round(100 * share)}% of the expected goals." if share >= 0.5 else
                        f" The chances say it's partly real: {round(100 * share)}% of the expected goals." if share >= 0.45 else
                        f" The chances say it's real: {round(100 * share)}% of the expected goals.")
            else:
                head = f"{cap(the(team))} have points in {nw(n)} straight ({record([x['res'] for x in games])})."
                tail = f" They got {round(100 * share)}% of the expected goals in that run."
            T["streak"] = dict(kind=kind, n=n, share=r(share, 3), text=head + tail)
            T["lines"].append(dict(k="streak", text=head + tail, w=30 + 4 * n))
            weight = max(weight, 30 + 4 * n)
        t = st[team]
        luck = (t["gf"] - t["ga"]) - (t["xgf"] - t["xga"])
        T["luck"] = r(luck, 1)
        if abs(luck) >= 4 and t["gp"] >= 5:
            fin, gk = t["gf"] - t["xgf"], t["xga"] - t["ga"]
            same = lambda v: v * luck > 0 and abs(v) >= 1.5
            parts = ([f"finishing ({sign(fin)} goals against the chances)"] if same(fin) else []) + \
                    ([f"goaltending ({sign(gk)} saved above expected)"] if same(gk) else [])
            by = " and ".join(parts)
            verb = "are" if len(parts) > 1 else "is"
            if luck > 0:
                text = (f"Results ahead of the chances: {gdiff(t['gf'] - t['ga'])} on {sign(t['xgf'] - t['xga'])} "
                        f"expected, {round(t['xg_pct'])}% of the expected goals." + (f" {cap(by)} {verb} doing the lifting." if by else ""))
            else:
                text = (f"Better than the record: {gdiff(t['gf'] - t['ga'])} on {sign(t['xgf'] - t['xga'])} expected, "
                        f"{round(t['xg_pct'])}% of the expected goals." +
                        (f" {cap(by)} {'have' if len(parts) > 1 else 'has'} cost them." if by else ""))
            T["luck_text"] = text
            T["luck_game"] = (f"{cap(theirs(team))} results are ahead of their chances" if luck > 0 else
                              f"{cap(the(team))} are better than their record") + ":" + text.split(":", 1)[1]
            T["lines"].append(dict(k="luck", text=text, w=25 + 2 * abs(luck)))
            weight = max(weight, 25 + 2 * abs(luck))
        last10 = res[-10:]
        T["last10"] = record([x["res"] for x in last10]) if last10 else None
        xf10, xa10 = sum(x["xf"] or 0 for x in last10), sum(x["xa"] or 0 for x in last10)
        T["xg10"] = r(xf10 / (xf10 + xa10), 3) if xf10 + xa10 else None
        T["card"] = dict(team=team, rec=f"{t['w']}-{t['l']}-{t['otl']}", last10=T["last10"], xg10=T["xg10"],
                         streak=T.get("streak", {}).get("text"), luck=T["luck"], luck_text=T.get("luck_text"),
                         xg_pct=t["xg_pct"], weight=r(weight, 1))
        P["team"][team] = T
    # hot and cold names and goalie form per team (for the Teams page)
    for team, T in P["team"].items():
        hot = sorted((S for S in P["skater"].values() if S["team"] == team and S["form"].get("state") == "hot"), key=lambda S: -S["form"]["z"])
        cold = sorted((S for S in P["skater"].values() if S["team"] == team and S["form"].get("state") == "cold"
                       and S["rate"]["ppg"] >= 0.45), key=lambda S: S["form"]["z"])
        if hot:
            T["lines"].append(dict(k="hot", text=f"Running hot: {', '.join(_who(S) for S in hot[:3])}.", w=20))
        if cold:
            T["lines"].append(dict(k="cold", text=f"Running cold: {', '.join(_who(S) for S in cold[:3])}.", w=18))
        for G in P["goalie"].values():
            if G["team"] == team and G.get("state"):
                T["lines"].append(dict(k="goalie", text=G["text"], w=22))
        T["lines"].sort(key=lambda x: -x["w"])


def _who(S):
    f = S["form"]
    return f"{S['name']} ({f['pts']} points in {f['n']}, {num(f['xpts'])} expected)"


def _rank(d, high=True):
    v = {k: x for k, x in d.items() if x is not None}
    order = sorted(v, key=lambda k: -v[k] if high else v[k])
    return {k: i + 1 for i, k in enumerate(order)}


# ------------------------------------------------------------------ tonight: storylines and players to watch

def _ptg(cur, prev):
    """Player-team-game rows for two seasons (regular and playoffs) with the home team, for former-team lookups."""
    out = []
    for d in (prev, cur):
        g = d["games"][["game_id", "home"]]
        out.append(d["pg"][["player_id", "team", "opp", "date", "game_id", "pts", "g", "a"]].merge(g, on="game_id", how="left"))
        gg = d["gg"][["player_id", "team", "date", "game_id"]].merge(d["games"][["game_id", "home", "away"]], on="game_id", how="left")
        gg["opp"] = np.where(gg.team == gg.home, gg.away, gg.home)
        out.append(gg[["player_id", "team", "opp", "date", "game_id", "home"]].assign(pts=0, g=0, a=0))
    return pd.concat(out, ignore_index=True).sort_values("date")


def _former(pid, opp, home, bio, ptg, names, cur_season):
    """A storyline when a player faces a team he used to play for."""
    if not bio:
        return None
    stints = [(s, t, gp) for s, t, gp in bio.get("nhl_teams") or [] if t == opp]
    if not stints:
        return None
    gp_with = sum(gp for _, _, gp in stints)
    last_s = max(s for s, _, _ in stints)
    recent = str(last_s) >= str(int(cur_season[:4]) - 1) + cur_season[:4]
    if gp_with < 20 and not (recent and gp_with >= 5):
        return None
    mine = ptg[ptg.player_id == pid]
    with_opp = mine[mine.team == opp]
    name = names.get(pid)
    city = METRO.get(opp, (NICK.get(opp, opp),))[0]
    if recent and len(with_opp):
        left = with_opp.date.max()
        since = mine[(mine.date > left) & (mine.team != opp)]
        faced = since[since.opp == opp]
        visited = faced[faced.home == opp]
        if faced.empty:
            text = f"{name} faces {the(opp)} for the first time since leaving them ({pl(gp_with, 'game')} in their colours)."
            if home == opp:
                text = f"{name} is back in {city} for the first time since leaving {the(opp)} ({pl(gp_with, 'game')} with them)."
            return dict(k="former", text=text, w=48 if gp_with >= 100 else 40, chip=f"First game vs old team")
        if home == opp and visited.empty:
            return dict(k="former", text=f"{name} plays in {city} for the first time since leaving {the(opp)} "
                                         f"({pl(gp_with, 'game')} with them).", w=42, chip="First trip back")
        return dict(k="former", text=f"{name} faces his old team: {pl(gp_with, 'game')} with {the(opp)}, most recently in "
                                     f"{_season_label(last_s)}.", w=18, chip="Former team")
    if gp_with >= 150:
        return dict(k="former", text=f"{name} faces {the(opp)}, where he played {gp_with:,} games.", w=14, chip="Former team")
    return None


def _season_label(s):
    s = str(s)
    return f"{s[:4]}-{s[6:]}"


def _vs_history(pid, opp, ptg, name):
    """Strong recent record against tonight's opponent (two seasons of data, flagged as a small sample)."""
    mine = ptg[(ptg.player_id == pid)]
    vs = mine[mine.opp == opp]
    n, pts = len(vs), int(vs.pts.sum())
    allp = mine.pts.sum() / max(len(mine), 1)
    if n >= 4 and pts >= 6 and pts / n >= max(1.5 * allp, 1.0):
        return dict(k="vs", text=f"{name} has {pts} points in {n} games against {the(opp)} since the start of last season. "
                                 f"A small sample, and not something the model uses.", w=16, chip=f"{pts} pts in {n} vs {opp}")
    return None


def game_stories(P, slate_games, props, lu, sched, cur, prev, names, profiles, standings, game_index, bios, today, season):
    """{game_id: {storylines: [...], watch: {team: [...]}}} plus the slate's headlines."""
    today_s = str(today)
    games = cur["games"]
    ptg = _ptg(cur, prev)
    st = {t["team"]: t for t in standings}
    by_game = {}
    played = games[["date", "home", "away", "game_id", "home_score", "away_score", "decided_in", "venue"]]
    future = [g for g in sched if g["date"] > today_s]
    prev_po = prev["games"][prev["games"].game_type == "playoffs"]
    prev_reg = prev["games"][prev["games"].game_type == "regular"]
    div_table = {}
    for t, row in st.items():
        div_table.setdefault(DIVISION.get(t), []).append(row)
    div_pos = {}
    for d, rows in div_table.items():
        for i, row in enumerate(sorted(rows, key=lambda x: (-x["pts"], x["gp"], -(x["gf"] - x["ga"])))):
            div_pos[row["team"]] = i + 1
    props_by = {}
    for p in props:
        props_by.setdefault((p["game"], p["team"]), []).append(p)

    def schedule_lines(team, opp, home_team):
        out = []
        mine = played[(played.home == team) | (played.away == team)].sort_values("date")
        last = mine.iloc[-1] if len(mine) else None
        rest = (today - dt.date.fromisoformat(last.date)).days - 1 if last is not None else None
        orest_g = played[(played.home == opp) | (played.away == opp)].sort_values("date")
        orest = (today - dt.date.fromisoformat(orest_g.iloc[-1].date)).days - 1 if len(orest_g) else None
        if rest == 0:
            lh = last.home == team
            gf, ga = (last.home_score, last.away_score) if lh else (last.away_score, last.home_score)
            res = "win" if gf > ga else "loss"
            where = "at home" if lh else f"in {METRO.get(last.home, (last.home,))[0]}"
            ot = " in overtime" if last.decided_in == "OT" else " in a shootout" if last.decided_in == "SO" else ""
            out.append(dict(team=team, k="b2b", w=46, priced=True,
                            text=f"{cap(the(team))} are on the second night of a back-to-back after a {gf}-{ga} {res}{ot} {where} last night.",
                            effect=f"Priced: the model trims {team}'s scoring 2.5% and gives {opp} 2.5% more. Tired teams got 47.4% "
                                   f"of the expected goals in 2025-26."))
        elif rest is not None and orest is not None and rest >= 2 and orest == 0:
            out.append(dict(team=team, k="rest", w=30, priced=False,
                            text=f"Rest edge: {the(team)} have had {pl(rest, 'day')} off; {the(opp)} played last night.",
                            effect="Only the back-to-back half of this is priced; extra rest beyond one day isn't."))
        three = mine[(mine.date >= str(today - dt.timedelta(days=3)))]
        if len(three) >= 2 and rest != 0:
            out.append(dict(team=team, k="sched", w=18, priced=False,
                            text=f"Third game in four nights for {the(team)}.",
                            effect="Not priced; only the second night of a back-to-back is."))
        # road trips and home stands: consecutive games on one side of the ledger
        side = [x.home == team for x in mine.itertuples()]
        here = home_team == team
        run_back = next((i for i, v in enumerate(side[::-1]) if v != here), len(side))
        ahead = 0
        for g in [g for g in future if team in (g["away"], g["home"])]:
            if (g["home"] == team) != here:
                break
            ahead += 1
        if not here:
            n, tot = run_back + 1, run_back + 1 + ahead
            if tot >= 3:
                text = (f"{cap(the(team))} close a {nw(tot)}-game road trip." if ahead == 0 else
                        f"Game {nw(n)} of a {nw(tot)}-game road trip for {the(team)}.")
                if run_back >= 1:
                    trip = mine.iloc[-run_back:]
                    rs = []
                    for x in trip.itertuples():
                        gf, ga = (x.away_score, x.home_score)
                        rs.append("W" if gf > ga else ("OTL" if x.decided_in != "REG" else "L"))
                    text += f" They're {record(rs)} on it so far."
                out.append(dict(team=team, k="trip", w=16 + 3 * n, priced=False, text=text,
                                effect="Not priced; the model treats every road game the same."))
        else:
            if run_back == 0 and len(side) >= 3:
                away_run = next((i for i, v in enumerate(side[::-1]) if v), len(side))
                if away_run >= 3:
                    out.append(dict(team=team, k="home", w=24, priced=False,
                                    text=f"{cap(the(team))} are home after a {nw(away_run)}-game road trip.",
                                    effect="Not priced."))
            n, tot = run_back + 1, run_back + 1 + ahead
            if tot >= 4 and run_back >= 1:
                out.append(dict(team=team, k="stand", w=12 + 2 * n, priced=False,
                                text=f"Game {nw(n)} of a {nw(tot)}-game home stand for {the(team)}.", effect="Not priced."))
        return out

    def series_lines(a, h):
        out = []
        yday = str(today - dt.timedelta(days=1))
        meets = played[((played.home == a) & (played.away == h)) | ((played.home == h) & (played.away == a))].sort_values("date")
        if len(meets):
            last = meets.iloc[-1]
            win = last.home if last.home_score > last.away_score else last.away
            score = f"{max(last.home_score, last.away_score)}-{min(last.home_score, last.away_score)}"
            ot = " in overtime" if last.decided_in == "OT" else " in a shootout" if last.decided_in == "SO" else ""
            gi = next((x for x in game_index if x["id"] == int(last.game_id)), None)
            deserved = ""
            if gi and gi.get("dtw_home") is not None:
                dw = gi["dtw_home"] if win == last.home else 1 - gi["dtw_home"]
                deserved = (f" and deserved it ({round(100 * dw)}% of replays from the shots)" if dw >= 0.55 else
                            f", though {the(last.home if win == last.away else last.away)} deserved it more "
                            f"({round(100 * (1 - dw))}% of replays)" if dw < 0.45 else ", in a coin flip on the chances")
            if last.date == yday:
                out.append(dict(team=None, k="rematch", w=58, priced=False,
                                text=f"Rematch of last night: {the(win)} won {score}{ot}{deserved}.",
                                effect="Not priced beyond the back-to-back."))
            else:
                n = len(meets)
                d = dt.date.fromisoformat(last.date)
                out.append(dict(team=None, k="series", w=22, priced=False,
                                text=f"{cap(ordinalw(n + 1))} meeting this season. "
                                     f"Last time, on {d:%b} {d.day}, {the(win)} won {score}{ot}{deserved}.",
                                effect="Not priced; one game says little."))
        po = prev_po[((prev_po.home == a) & (prev_po.away == h)) | ((prev_po.home == h) & (prev_po.away == a))]
        if len(po):
            wins = {}
            for x in po.itertuples():
                w = x.home if x.home_score > x.away_score else x.away
                wins[w] = wins.get(w, 0) + 1
            win = max(wins, key=wins.get)
            lose = a if win == h else h
            rd = int(str(po.game_id.iloc[0])[-3])
            out.append(dict(team=None, k="playoff", w=52, priced=False,
                            text=f"Rematch of last spring's {ROUND.get(rd, 'playoff')} series, which {the(win)} won in "
                                 f"{nw(len(po))} ({wins[win]}-{wins.get(lose, 0)}).",
                            effect="Not priced; rivalry and memory don't show up in the chances."))
        reg = prev_reg[((prev_reg.home == a) & (prev_reg.away == h)) | ((prev_reg.home == h) & (prev_reg.away == a))]
        if len(reg) >= 2 and not len(meets):
            wa = sum((x.home == a and x.home_score > x.away_score) or (x.away == a and x.away_score > x.home_score) for x in reg.itertuples())
            if wa != len(reg) - wa:
                lead, n_w = (a, wa) if wa > len(reg) - wa else (h, len(reg) - wa)
                out.append(dict(team=None, k="series", w=10, priced=False,
                                text=f"First meeting this season. {cap(the(lead))} won {nw(n_w)} of {nw(len(reg))} last season.",
                                effect="Not priced."))
        if DIVISION.get(a) == DIVISION.get(h) and a in st and h in st:
            div = DIVISION[a]
            ta, th = st[a], st[h]
            gap = ta["pts"] - th["pts"]
            ahead = a if gap > 0 else h
            gtxt = ("level on points" if gap == 0 else f"{the(ahead)} {pl(abs(gap), 'point')} ahead")
            w = 18 if P.get("gp_med", 0) < 20 else 34
            out.append(dict(team=None, k="division", w=w, priced=False,
                            text=f"Division game: {a} sits {ordinalw(div_pos[a])} in the {div} and {h} {ordinalw(div_pos[h])}, {gtxt}.",
                            effect="Not priced; standings don't change the chances."))
        return out

    def injury_lines(team, opp):
        out = []
        outs = [(i, v) for i, v in lu.get("inj", {}).items() if v["team"] == team and v["out"]]
        def imp(i):
            S = P["skater"].get(i)
            if not S:
                return 0
            pv = S.get("prev") or {}
            return max(S["rate"]["ppg"], pv.get("pts", 0) / pv["gp"] if pv.get("gp", 0) >= 20 else 0)
        for i, v in sorted(outs, key=lambda t: -imp(t[0]))[:2]:
            S = P["skater"].get(i)
            G = P["goalie"].get(i)
            if S and imp(i) >= 0.45:
                kind = f" ({v['kind'].lower()})" if v.get("kind") and v["kind"].lower() not in ("undisclosed", "not specified") else ""
                back = ""
                if v.get("back"):
                    d = dt.date.fromisoformat(v["back"][:10])
                    if d > today:
                        back = f" ESPN's estimated return: {d:%b} {d.day}."
                ss, pv = S["season"], S.get("prev") or {}
                if ss["gp"] >= 10 or pv.get("gp", 0) < 20:
                    tail = f" He has {pl(ss['pts'], 'point')} in {pl(ss['gp'], 'game')} this season." if ss["gp"] else ""
                else:
                    tail = f" He had {pl(pv['pts'], 'point')} in {pl(pv['gp'], 'game')} last season."
                status = STATUS.get(v["status"].lower(), v["status"].lower())
                out.append(dict(team=team, k="injury", w=36 + 20 * min(imp(i), 1.2), priced=True,
                                text=f"{cap(the(team))} are without {S['name']}{kind}, {status}.{tail}{back}",
                                effect="Priced: he's out of the lineup and the team rating.", pid=i))
            elif G and G["starts"] >= 3:
                out.append(dict(team=team, k="injury", w=40, priced=True,
                                text=f"{cap(the(team))} are without goalie {G['name']}, {STATUS.get(v['status'].lower(), v['status'].lower())}.",
                                effect="Priced through tonight's projected goalie.", pid=i))
        for x in lu.get("returning", []):
            if x["team"] != team:
                continue
            ppg = imp(x["id"])
            if ppg < 0.35 and "Just joined" not in x["note"]:
                continue
            note, k = x["note"], "back"
            if note.startswith("Just joined from"):
                text, k = f"{x['name']} could debut for {the(team)} after joining from {the(note.split()[-1])}.", "new"
            elif note.startswith("Day-to-day"):
                text = f"{x['name']} is day-to-day and could return for {the(team)}."
            elif "cleared" in note:
                text = f"{x['name']} could be back for {the(team)}: ESPN has cleared him from its injury report."
            else:
                text = f"{x['name']} could be back for {the(team)}: he's off the out list and {note.split(': ', 1)[-1]}."
            out.append(dict(team=team, k=k, w=30 + 20 * min(ppg, 1.2), priced=True, text=text,
                            effect="Priced as playing, and every price assumes he dresses. Check the lineup.", pid=x["id"]))
        return out

    def goalie_lines(g, side):
        out = []
        team = g[side]
        opp = g["home" if side == "away" else "away"]
        gid, src = g.get(side + "_goalie"), g.get(side + "_goalie_src")
        G = P["goalie"].get(gid)
        if not G:
            return out
        opt = next((o for o in g.get(side + "_goalies", []) if o["id"] == gid), None)
        f = opt["factor"] if opt else 1.0
        eff = (f"Priced: the model has {opp} scoring {round(100 * abs(1 - f))}% {'fewer' if f < 1 else 'more'} goals than against "
               f"an average goalie." if abs(1 - f) >= 0.03 else "Priced: the model rates him close to an average goalie.")
        tag = "" if src == "espn" else " (projected)"
        others = [x for x in P["goalie"].values() if x["team"] == team and x["id"] != gid and x["starts"] >= 1]
        top = max(others, key=lambda x: x["starts"], default=None)
        if top and G["team_starts"] >= 4 and top["starts"] >= 0.6 * G["team_starts"] and G["starts"] < 0.4 * G["team_starts"]:
            hurt = lu.get("inj", {}).get(top["id"])
            text = (f"{G['name']}{tag} starts for {the(team)} with {top['name']} ({top['starts']} of {G['team_starts']} starts) "
                    f"{STATUS.get(hurt['status'].lower(), hurt['status'].lower())}." if hurt else
                    f"Backup in: {G['name']}{tag} starts for {the(team)} over {top['name']}, who has "
                    f"{top['starts']} of {G['team_starts']} starts.")
            out.append(dict(team=team, k="goalie", w=44, priced=True, text=text,
                            effect=eff, pid=gid))
        elif G.get("state"):
            out.append(dict(team=team, k="goalie", w=40, priced=True, text=G["text"].replace(G["name"], G["name"] + tag, 1),
                            effect=eff + " Recent form only counts through his whole season, which the model shrinks hard; goalie "
                                         "seasons barely repeat.", pid=gid))
        return out

    def special_lines(a, h):
        out = []
        for t, o in ((a, h), (h, a)):
            T, O = P["team"].get(t, {}), P["team"].get(o, {})
            pr, kr = T.get("pp_rank"), O.get("pk_rank")
            if pr and kr and pr <= 6 and kr >= 26:
                pen = O.get("pen_rank")
                extra = ("" if not pen or pen > 8 else f", and {the(o)} take the most penalties in the league" if pen == 1 else
                         f", and {the(o)} take the {ordinalw(pen)}-most penalties")
                out.append(dict(team=t, k="special", w=30, priced=True,
                                text=f"Power play against penalty kill: {t}'s power play ({ordinalw(pr)} in chances) meets {o}'s kill "
                                     f"({ordinalw(kr)} in chances allowed){extra}.",
                                effect="Partly priced: power-play chances are in each team's rating and in each player's role; the "
                                       "number of penalties isn't projected."))
        return out

    def market_lines(g):
        m = g.get("market") or {}
        out = []
        if m.get("p_home") is not None and m.get("model_p_home") is not None:
            d = m["model_p_home"] - m["p_home"]
            if abs(d) >= 0.06:
                t = g["home"] if d > 0 else g["away"]
                mp = m["model_p_home"] if d > 0 else 1 - m["model_p_home"]
                kp = m["p_home"] if d > 0 else 1 - m["p_home"]
                out.append(dict(team=t, k="market", w=26, priced=True,
                                text=f"The model is higher on {the(t)} than DraftKings is: {round(100 * mp)}% to win against the "
                                     f"market's {round(100 * kp)}%.",
                                effect="The model's win numbers are still being graded against the market on the Trust page. "
                                       "Read a gap as a question, not a pick."))
        if m.get("implied_total") is not None and g.get("total") is not None:
            d = g["total"] - m["implied_total"]
            if abs(d) >= 0.5:
                out.append(dict(team=None, k="market", w=14, priced=True,
                                text=f"The model sees {'more' if d > 0 else 'fewer'} goals than the market: {num(g['total'])} against "
                                     f"about {num(m['implied_total'])}.",
                                effect="Totals have never beaten the market or a league average in testing. Context only."))
        return out

    def player_items(g):
        """Per-player storylines and chips: milestones, former team, hometown, history against tonight's opponent."""
        items = {}
        home = g["home"]
        for p in [p for p in props if p["game"] == g["id"]]:
            pid, team = p["id"], p["team"]
            opp = p["opp"]
            S = P["skater"].get(pid)
            name = p["name"]
            bio = bios.get(pid)
            got = []
            if S:
                for m in S["milestones"]:
                    if (m["stat"] == "gp" and m["need"] == 1) or (m["stat"] in ("g", "a") and m["need"] == 1) or \
                            (m["stat"] == "pts" and m["need"] <= 2):
                        if m["stat"] == "gp":
                            text = f"{name} plays his {ordinal(m['target'])} NHL game."
                        else:
                            text = f"{name} is {m['text']}."
                        size = (10 if m["target"] >= 300 else 0) + (10 if m["target"] >= 500 else 0) + (12 if m["target"] >= 1000 else 0)
                        got.append(dict(k="milestone", text=text, w=30 + size + (6 if m["stat"] != "gp" else 0),
                                        chip=f"Milestone: {m['text'] if m['stat'] != 'gp' else ordinal(m['target']) + ' game'}"))
                    elif m["stat"] == "first_g" and p.get("lineup") == "last":
                        w = 21 if p.get("pos") == "F" and p["p_goal"] >= 0.15 else 8
                        got.append(dict(k="milestone", text=f"{name} is {m['text'][0].lower() + m['text'][1:]}.", w=w,
                                        chip="First NHL goal watch"))
            fm = _former(pid, opp, home, bio, ptg, names, season)
            if fm:
                got.append(fm)
            ht = hometown_team(bio)
            if ht and ht == home and team != home:
                got.append(dict(k="hometown", text=f"{name} plays near home: he was born in {born_in(bio)}.", w=24, chip="Homecoming"))
            vs = _vs_history(pid, opp, ptg, name)
            if vs:
                got.append(vs)
            if got:
                items[pid] = got
        # goalies starting tonight: milestones and former teams
        for side in ("away", "home"):
            gid = g.get(side + "_goalie")
            G = P["goalie"].get(gid)
            if not G:
                continue
            team, opp = g[side], g["home" if side == "away" else "away"]
            got = []
            for m in G.get("milestones", []):
                if m["stat"] == "gp" and m["need"] == 1:
                    got.append(dict(k="milestone", text=f"{G['name']} would play his {ordinal(m['target'])} NHL game.", w=44,
                                    chip=f"{ordinal(m['target'])} game"))
                elif m["stat"] == "w" and m["need"] == 1:
                    got.append(dict(k="milestone", text=f"{G['name']} is one win from {m['target']:,} career wins.", w=46,
                                    chip=f"One win from {m['target']}"))
            fm = _former(gid, opp, home, bios.get(gid), ptg, names, season)
            if fm:
                got.append(fm)
            ht = hometown_team(bios.get(gid))
            if ht and ht == home and team != home:
                got.append(dict(k="hometown", text=f"{G['name']} plays near home: he was born in {born_in(bios.get(gid))}.", w=24,
                                chip="Homecoming"))
            if got:
                items[gid] = got
        return items

    headlines = []
    for g in slate_games:
        a, h = g["away"], g["home"]
        lines = []
        for t, o in ((a, h), (h, a)):
            T = P["team"].get(t, {})
            if T.get("streak"):
                lines.append(dict(team=t, k="streak", w=28 + 4 * T["streak"]["n"], priced=False, text=T["streak"]["text"],
                                  effect="Not priced as a streak: the model rates teams on a season of chances, so a run counts "
                                         "only as much as the chances behind it."))
            if T.get("luck_text") and abs(T.get("luck", 0)) >= 5:
                lines.append(dict(team=t, k="luck", w=20 + 1.5 * abs(T["luck"]), priced=True, text=T["luck_game"],
                                  effect=f"The model goes by chances, so it already rates {t} {'below' if T['luck'] > 0 else 'above'} "
                                         f"what the record says."))
            lines += schedule_lines(t, o, h)
            lines += injury_lines(t, o)
            lines += goalie_lines(g, "away" if t == a else "home")
        lines += series_lines(a, h)
        lines += special_lines(a, h)
        lines += market_lines(g)
        items = player_items(g)
        homes = {}
        for pid, got in items.items():
            team = next((p["team"] for p in props if p["id"] == pid and p["game"] == g["id"]), None)
            if team is None:
                team = a if g.get("away_goalie") == pid else h
            for x in got:
                if x["k"] == "hometown":
                    homes.setdefault(team, []).append((names.get(pid), bios.get(pid, {}).get("birth_city")))
                    continue
                if x["w"] >= 20:
                    lines.append(dict(team=team, k=x["k"], w=x["w"], priced=False, text=x["text"], pid=pid,
                                      effect=("Not priced; nobody has shown milestones move scoring." if x["k"] == "milestone" else
                                              "Not priced; there's no reliable evidence revenge games change output." if x["k"] == "former" else
                                              "Not priced; family in the stands isn't in the data." if x["k"] == "hometown" else
                                              "Not priced.")))
        for t, who in homes.items():
            if len(who) == 1:
                text = f"{who[0][0]} plays near home: he was born in {who[0][1]}."
            else:
                by_city = {}
                for n, c in who:
                    by_city.setdefault(c, []).append(n)
                parts = [f"{' and '.join(ns) if len(ns) <= 2 else ', '.join(ns[:-1]) + ' and ' + ns[-1]} ({c})" for c, ns in by_city.items()]
                text = f"Homecoming for {nw(len(who))} {NICK.get(t, t)}: " + "; ".join(parts) + "."
            lines.append(dict(team=t, k="hometown", w=22 + 2 * len(who), priced=False, text=text,
                              effect="Not priced; family in the stands isn't in the data."))
        # hottest and coldest names in tonight's lineups
        for t in (a, h):
            pool = [P["skater"][p["id"]] for p in props_by.get((g["id"], t), []) if p["id"] in P["skater"]]
            hot = sorted((S for S in pool if S["form"].get("state") == "hot"), key=lambda S: -S["form"]["z"])
            cold = sorted((S for S in pool if S["form"].get("state") == "cold" and S["rate"]["ppg"] >= 0.6), key=lambda S: S["form"]["z"])
            if hot and hot[0]["form"]["z"] >= 2.0:
                S = hot[0]
                lines.append(dict(team=t, k="hot", w=24 + 3 * S["form"]["z"], priced=False, pid=S["id"],
                                  text=f"{S['name']} is rolling: {S['form']['text']}",
                                  effect="The model only moves on a streak through his chances, shrunk hard toward his longer record."))
            if cold:
                S = cold[0]
                lines.append(dict(team=t, k="cold", w=22 + 2 * abs(S["form"]["z"]), priced=False, pid=S["id"],
                                  text=f"{S['name']} is in a rut: {S['form']['text']}",
                                  effect="The model prices his chances, not the slump."))
        lines.sort(key=lambda x: -x["w"])
        seen, keep = set(), []
        for x in lines:
            key = (x["k"], x.get("team"), x.get("pid"))
            if key in seen:
                continue
            seen.add(key)
            if x.get("effect"):   # the page tags each line "In the model" or not, so the effect drops its own label
                e = re.sub(r"^(Not priced|Priced|Partly priced)( as playing)?[:;,.]?\s*", lambda m: "As playing: " if m.group(2) else "", x["effect"])
                x = dict(x, effect=cap(e) if e else None)
            keep.append({k: (r(v, 1) if k == "w" else v) for k, v in x.items()})
        keep = keep[:9]
        watch = {t: _watch(P, props_by.get((g["id"], t), []), items, lu) for t in (a, h)}
        by_game[g["id"]] = dict(storylines=keep, watch=watch)
        kinds = set()
        for x in keep:
            if len(kinds) == 2:
                break
            if x["k"] not in kinds:
                kinds.add(x["k"])
                headlines.append(dict(game=g["id"], away=a, home=h, **x))
    headlines.sort(key=lambda x: -x["w"])
    return by_game, headlines[:8]


def ordinalw(n):
    words = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth",
             10: "tenth"}
    return words.get(int(n), ordinal(n))


def _watch(P, rows, items, lu):
    """Three players per team: the model's likeliest producers, pushed up by the stories around them."""
    cands = []
    for p in rows:
        if p.get("lineup") not in ("last", "returning", "recent"):
            continue
        S = P["skater"].get(p["id"])
        chips, bonus = [], 0.0
        why = None
        if S:
            f = S["form"]
            if f.get("state") == "hot":
                lab = {"earned": "Hot, and earned", "bounces": "Hot, on bounces", "partly": "Hot"}[f["verdict"]]
                chips.append(dict(k="hot", t=f"{lab}: {f['pts']} pts in {f['n']}"))
                bonus += 0.06 + 0.04 * min(f["z"], 3) + (0.04 if f["verdict"] == "earned" else 0)
                why = why or f["text"]
            elif f.get("state") == "cold" and f["verdict"] == "due":
                chips.append(dict(k="due", t=f"Due: {f['pts']} pts in {f['n']} on {num(f['xpts'])} expected"))
                bonus += 0.06
                why = why or f["text"]
            for s in f["streaks"]:
                if s["k"] in ("points", "goals"):
                    chips.append(dict(k="streak", t=s["text"]))
                    bonus += 0.03 + 0.01 * s["n"]
                elif s.get("due"):
                    chips.append(dict(k="due", t=s["text"]))
                    bonus += 0.04
            for fl in S["flags"]:
                chips.append(dict(k=fl["k"], t=fl["label"]))
                bonus += {"breakout": 0.06, "due": 0.05, "cooling": 0.0}[fl["k"]]
                if fl["k"] != "cooling":
                    why = why or fl["text"]
        for x in items.get(p["id"], []):
            chips.append(dict(k=x["k"], t=x.get("chip") or x["text"]))
            bonus += dict(milestone=0.2 if x["w"] >= 30 else 0.03, former=0.06 + 0.002 * x["w"], hometown=0.05, vs=0.04).get(x["k"], 0.03)
            if x["k"] in ("milestone", "former", "hometown"):
                why = x["text"] if (why is None or x["w"] >= 40) else why
        if p.get("lineup") == "returning":
            chips.append(dict(k="back", t=p.get("lineup_note") or "Returning"))
            bonus += 0.03
        base = p["p_goal"] + 0.4 * p["p_2pts"]
        cands.append(dict(id=p["id"], name=p["name"], pos=p.get("pos"), p_goal=p["p_goal"], p_1pt=p.get("p_1pt"),
                          p_2pts=p["p_2pts"], chips=chips, why=why, score=base + bonus))
    cands.sort(key=lambda c: -c["score"])
    out = []
    for c in cands[:3]:
        S = P["skater"].get(c["id"])
        role = (S or {}).get("role") or {}
        pp1 = (role.get("pp") or 0) >= 0.55
        if S and not c["why"]:
            ss = S["season"]
            bits = [f"{mmss(role['toi'])} a night" if role.get("toi") else None,
                    f"on the ice for {round(100 * role['pp'])}% of his team's power-play chances" if pp1 else None]
            lead = cap(", ".join(b for b in bits if b)) + ". " if any(bits) else ""
            c["why"] = f"{lead}{ss['pts']} points in {ss['gp']} games, with {num(ss['ixg'] or 0)} expected goals on his own shots."
        if not c["chips"]:
            c["chips"] = [dict(k="top", t="Top power play" if pp1 else "Big minutes" if (role.get("toi") or 0) >= 19 else "Model pick")]
        c["line"] = f"Model: {round(100 * c['p_goal'])}% to score, {round(100 * c['p_1pt'])}% for a point."
        c.pop("score")
        c["chips"] = c["chips"][:4]
        c["p_goal"], c["p_1pt"], c["p_2pts"] = r(c["p_goal"], 3), r(c["p_1pt"], 3), r(c["p_2pts"], 3)
        out.append(c)
    return out
