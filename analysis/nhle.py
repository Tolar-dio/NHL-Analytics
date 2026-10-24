"""NHL equivalency (NHLe): how a point in another league translates to the NHL, from players' own career paths.

For every skater who played 15+ regular-season games in league A one season and 20+ in league B the next, the
pair says how his scoring rate changed between the two leagues. A league's direct factor to the NHL is
    sum(w * NHL points per game) / sum(w * league points per game),  w = harmonic mean of the two game counts.
Leagues that rarely feed the NHL directly (USHL, Swedish and Finnish juniors, the MHL) are translated through the
league they usually feed (USHL -> NCAA -> NHL), when both legs have enough pairs.

Careers come from the NHL.com bios of this season's players and from the first two rounds of every draft since 2005
(scripts/fetch_external.py), so players who never stuck in the NHL count too. Caveats, said wherever the numbers are
shown: only players who moved count, so the factors describe prospects good enough to move; players improve with age,
which flatters the next season; small leagues are noisy (n is published).

Writes data/derived/nhle.json:
    {"leagues": {"SHL": {"factor": 0.57, "n": 64, "via": null}, ...}, "aliases": {...}, "pairs": N}

    python analysis/nhle.py
"""
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_A, MIN_B, MIN_N, MIN_LEG = 15, 20, 12, 15

# NHL.com's league labels vary by season and source; fold them into one name per league
ALIASES = {
    "Sweden": "SHL", "SEL": "SHL", "SHL": "SHL",
    "Finland": "Liiga", "SM-liiga": "Liiga", "Liiga": "Liiga",
    "Swiss": "NL", "Swiss-A": "NL", "Switzerland": "NL", "NLA": "NL", "NL": "NL",
    "Czechia": "Czechia", "Czech": "Czechia", "Czech Rep.": "Czechia", "ELH": "Czechia", "Czech Extraliga": "Czechia",
    "Germany": "DEL", "DEL": "DEL",
    "Slovakia": "Slovakia", "Austria": "ICEHL", "ICEHL": "ICEHL", "EBEL": "ICEHL",
    "HockeyAllsvenskan": "Allsvenskan", "Allsvenskan": "Allsvenskan", "Sweden-2": "Allsvenskan",
    "Mestis": "Mestis", "Finland-2": "Mestis",
    "KHL": "KHL", "VHL": "VHL", "MHL": "MHL", "Russia-Jr.": "MHL", "Russia": "KHL",
    "NCAA": "NCAA", "H-East": "NCAA", "Hockey East": "NCAA", "WCHA": "NCAA", "NCHC": "NCAA", "ECAC": "NCAA", "CCHA": "NCAA",
    "Big Ten": "NCAA", "BIG10": "NCAA", "Big 10": "NCAA", "Atlantic Hockey": "NCAA", "AHA": "NCAA", "CHA": "NCAA", "Atlantic": "NCAA",
    "OHL": "OHL", "WHL": "WHL", "QMJHL": "QMJHL", "LHJMQ": "QMJHL",
    "USHL": "USHL", "NTDP": "NTDP", "USDP": "NTDP", "USNTDP": "NTDP",
    "J20 SuperElit": "J20 Nationell", "J20 Nationell": "J20 Nationell", "Swe-Jr.": "J20 Nationell", "SuperElit": "J20 Nationell",
    "U20 SM-liiga": "U20 SM-sarja", "U20 SM-sarja": "U20 SM-sarja", "Fin-Jr.": "U20 SM-sarja",
    "AHL": "AHL", "ECHL": "ECHL", "NHL": "NHL",
    "BCHL": "BCHL", "AJHL": "AJHL", "OJHL": "OJHL", "NAHL": "NAHL", "CCHL": "CCHL", "SJHL": "SJHL", "MJHL": "MJHL",
}
# shown in a player's path as tournaments, never translated
INTERNATIONAL = {
    "WJC-20": "World Juniors", "WJC-18": "U18 Worlds", "WC": "World Championship", "OG": "Olympics", "Olympics": "Olympics",
    "4 Nations": "4 Nations Face-Off", "WCup": "World Cup", "Hlinka Gretzky Cup": "Hlinka Gretzky Cup",
    "Ivan Hlinka Memorial": "Hlinka Gretzky Cup", "WHC-17": "U17 World Challenge", "WJAC-19": "World Junior A Challenge",
    "EHT": "Euro Hockey Tour", "Memorial Cup": "Memorial Cup", "Champions HL": "Champions Hockey League",
    "WJC-A": "World Juniors", "WC-A": "World Championship", "WJ18-A": "U18 Worlds", "YOG": "Youth Olympics",
    "OGQ": "Olympic qualifying", "Spengler Cup": "Spengler Cup",
}


def canon(lg):
    return ALIASES.get(lg)


def load_careers(season):
    """{player_id: {"pos", "name", "career": [...], "draft": {...}, "birth_date"}} from bios plus draft careers."""
    out = {}
    paths = [os.path.join(ROOT, "data", "external", "draft", "careers.jsonl")]
    bdir = os.path.join(ROOT, "data", "external", "bios")
    if os.path.isdir(bdir):
        paths += [os.path.join(bdir, s, "bios.jsonl") for s in sorted(os.listdir(bdir))]
    for p in paths:      # later files (newer bios) win
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    k, v = json.loads(line)
                    if v.get("career"):
                        out[int(k)] = v
    return out


def league_seasons(career, gt=2):
    """{(season, league): [gp, pts, g]} for one player, multi-team seasons summed, untranslatable leagues skipped."""
    acc = defaultdict(lambda: [0, 0, 0])
    for r in career:
        lg = canon(r.get("lg"))
        if r.get("gt") != gt or not lg or not r.get("gp"):
            continue
        a = acc[(r["s"], lg)]
        a[0] += r.get("gp") or 0
        a[1] += r.get("p") or 0
        a[2] += r.get("g") or 0
    return acc


def build(season=None):
    C = load_careers(season)
    pairs = defaultdict(lambda: [0.0, 0.0, 0])          # (A, B) -> [sum w*ppg_A, sum w*ppg_B, n]
    for pid, v in C.items():
        if v.get("pos") == "G":
            continue
        ls = league_seasons(v["career"])
        by_season = defaultdict(list)
        for (s, lg), (gp, p, g) in ls.items():
            by_season[s].append((lg, gp, p))
        for s, rows in by_season.items():
            nxt = by_season.get(s + 10001) or []
            for la, ga, pa in rows:
                if ga < MIN_A:
                    continue
                for lb, gb, pb in nxt:
                    if gb < MIN_B or lb == la:
                        continue
                    w = 2 * ga * gb / (ga + gb)
                    q = pairs[(la, lb)]
                    q[0] += w * pa / ga
                    q[1] += w * pb / gb
                    q[2] += 1
    direct = {a: dict(factor=round(q[1] / q[0], 3), n=q[2], via=None)
              for (a, b), q in pairs.items() if b == "NHL" and q[2] >= MIN_N and q[0] > 0}
    out = dict(direct)
    # one-step chains for leagues without enough direct pairs: A -> M -> NHL, picking the best-supported path
    leagues = {a for a, _ in pairs} | {b for _, b in pairs}
    for a in leagues:
        if a == "NHL" or (a in direct and direct[a]["n"] >= 30):
            continue
        best = None
        for m, dm in direct.items():
            q = pairs.get((a, m))
            if m == a or not q or q[2] < MIN_LEG or dm["n"] < 30:
                continue
            n = min(q[2], dm["n"])
            if not best or n > best[1]:
                best = (round(q[1] / q[0] * dm["factor"], 3), n, m, q[2])
        if best and (a not in direct or best[1] > direct[a]["n"]):
            out[a] = dict(factor=best[0], n=best[3], via=best[2])
    res = dict(leagues=dict(sorted(out.items(), key=lambda kv: -kv[1]["factor"])), aliases=ALIASES, international=INTERNATIONAL,
               pairs=int(sum(q[2] for q in pairs.values())), players=len(C),
               method="consecutive seasons, 15+ GP then 20+ GP, harmonic-mean weights; chains through one league when direct pairs are few")
    path = os.path.join(ROOT, "data", "derived", "nhle.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    return res


def load():
    path = os.path.join(ROOT, "data", "derived", "nhle.json")
    return json.load(open(path)) if os.path.exists(path) else build()


if __name__ == "__main__":
    r = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{r['players']} careers, {r['pairs']} league-to-league pairs")
    for lg, v in r["leagues"].items():
        print(f"  {lg:16s} {v['factor']:.3f}  n={v['n']:4d}  {('via ' + v['via']) if v['via'] else ''}")
