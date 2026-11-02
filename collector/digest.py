"""Uporządkowany materiał do raportu dziennego + wskaźniki do kryteriów oceny.

data/digest/YYYY-MM-DD.json – pozycje z okna pogrupowane tematycznie, bez duplikatów bossa/strefa,
                              z flagami słów kluczowych. Raport dzienny czyta to zamiast surowej listy.
data/scores/{TICKER}.json    – kryteria liczbowe (B1–B7 i wycena) policzone z data/fundamentals + kursów.
"""
import datetime as dt, json, os, re, statistics
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)


def jload(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


CFG = jload(os.path.join(ROOT, "config", "watchlist.json"), {"companies": []})
EXTRA = jload(os.path.join(ROOT, "config", "extra.json"), {"companies": []}).get("companies", [])
OWN = {c["ticker"] for c in CFG["companies"]}
WATCH = {c["ticker"] for c in EXTRA} - OWN

CATS = [
    ("podsumowania", r"^(Skrót wiadomości|Dzień na |Tydzień na |Tydzień w kraju|Przegląd prasy|Kalendarium|Notowania ciągłe|WIG20 na |WIG20 na otwarciu|Poranny|Popołudniowy)"),
    ("wyniki", r"wynik|raport (kwartaln|półroczn|roczn|okresow)|szacunkow|przychod|EBITDA|zysk netto|strat[ay] netto|marż"),
    ("rekomendacje", r"rekomendac|cen[aęy] docelow|podnosi cenę|obniża cenę|kupuj|sprzedaj|trzymaj|akumuluj|przeważ|niedoważ"),
    ("korporacyjne", r"emisj|ABB|wezwani|przejęc|przejmie|fuzj|połączeni|dywidend|skup akcji|skup własnych|umow|kontrakt|zamówieni|przetarg|prezes|zarząd|rada nadzorcz|walne|WZA|NWZ|akcjonariusz|art\. 69|art\. 19|transakcj|nabyci|zbyci|upadł|restruktur|układ|zawiesz|wyklucz|debiut|IPO"),
    ("makro_pl", r"inflacj|CPI|PKB|RPP|NBP|stop[ay] procentow|bezroboci|PMI|produkcj|sprzedaż detaliczn|wynagrodze|zatrudnieni|budżet|deficyt|dług publiczn|obligacj|SPW|złot|EUR/PLN|USD/PLN|GUS|MF |Ministerstw|KPO|SAFE|rząd|Sejm|ustaw"),
    ("swiat_rynki", r"Fed|EBC|ECB|Wall Street|S&P|Nasdaq|Dow|DAX|USA|Chin|Niemc|stref[ay] euro|ropa|Brent|WTI|gaz|złoto|miedź|dolar|jen|bitcoin|cła|taryf|Trump|ISM|payrolls|NFP"),
    ("energetyka_surowce", r"energ|prąd|OZE|wiatr|fotowolt|węgl|paliw|Orlen|PGE|Tauron|Enea|KGHM|JSW|gazow"),
    ("nieruchomosci", r"mieszka|deweloper|nieruchomo|kredyt(y|ów) hipote|budownictw"),
    ("fundusze_drobne", r"OFE|PTE|TFI|FIZ|jednost(ek|ki) uczestnictwa|wartości aktywów netto|jednostki rozrachunkowej|Fundusz Inwestycyjny Zamknięty"),
]
FLAGS = {"emisja": r"emisj|ABB", "wezwanie": r"wezwani", "dywidenda": r"dywidend", "wyniki": r"wynik|szacunkow", "prognoza": r"prognoz|guidance|korekt",
         "umowa": r"umow|kontrakt|zamówieni", "zarząd": r"prezes|zarząd|rezygnac|odwoła", "insider": r"art\. 19|transakcj.*(osob|członk)|nabyci.*akcji", "akcjonariat": r"art\. 69|znaczn|akcjonariusz"}


def norm(t):
    return re.sub(r"[^a-ząćęłńóśźż0-9 ]", "", t.lower())[:120]


def build_digest(day):
    items = jload(D("feed", day + ".json"), {"items": []})["items"]
    out = {k: [] for k, _ in CATS}
    out.update({"twoje_spolki": [], "obserwowane": [], "pozostale": []})
    seen = []
    dup = 0
    for it in sorted(items, key=lambda i: (i.get("src") != "strefainwestorow", i.get("time") or "")):   # strefa (z linkiem) wygrywa
        n = norm(it.get("title", ""))
        if any(SequenceMatcher(None, n, s).ratio() > 0.9 for s in seen[-400:]):
            dup += 1
            continue
        seen.append(n)
        title = (it.get("company") + ": " if it.get("company") else "") + it.get("title", "")
        e = {"time": it.get("time"), "kind": it.get("kind"), "ticker": it.get("ticker"), "title": title, "url": it.get("url"), "src": it.get("src"),
             "flags": [f for f, rx in FLAGS.items() if re.search(rx, title, re.I)]}
        if it.get("ticker") in OWN:
            out["twoje_spolki"].append(e)
            continue
        if it.get("ticker") in WATCH:
            out["obserwowane"].append(e)
            continue
        for k, rx in CATS:
            if re.search(rx, title, re.I):
                out[k].append(e)
                break
        else:
            out["pozostale"].append(e)
    for k in out:
        out[k].sort(key=lambda e: e.get("time") or "", reverse=True)
    counts = {k: len(v) for k, v in out.items()}
    jsave(D("digest", day + ".json"), {"date": day, "counts": counts, "duplicatesRemoved": dup, "total": len(items),
                                     "note": "Kolejność ważności: twoje_spolki, obserwowane, podsumowania (Skrót PAP = szkielet dnia), wyniki, korporacyjne, rekomendacje, makro_pl, swiat_rynki, energetyka_surowce, nieruchomosci, pozostale; fundusze_drobne zwykle pomijaj.",
                                     "groups": out})
    return counts


# ---------------- kryteria liczbowe ----------------
def cagr(a, b, years):
    try:
        return (b / a) ** (1 / years) - 1 if a and b and a > 0 and b > 0 else None
    except Exception:
        return None


def pct(x):
    return None if x is None else round(x * 100, 1)


def avg_cpi():
    s = jload(D("macro.json"), {"series": {}}).get("series", {}).get("cpi_pl_yoy", {}).get("points", [])
    v = [p[1] for p in s[-24:] if p[1] is not None]
    return sum(v) / len(v) / 100 if v else None


def score_pl(t, f, price, turnover):
    years = [p for p in f.get("periods", []) if not p.get("ytd") and p.get("revenue")]
    years = years[:5]                    # najnowsze pierwsze
    if len(years) < 2:
        return None
    r = {"ticker": t, "unit": f.get("unit"), "src": f.get("src"), "years": [p["period"] for p in years]}
    n = min(3, len(years) - 1)
    nominal = cagr(years[n]["revenue"], years[0]["revenue"], n)
    cpi = avg_cpi()
    r["B1_revenueCagr"] = {"years": n, "nominal": pct(nominal), "real": pct(nominal - cpi) if nominal is not None and cpi is not None else None, "cpiAvg": pct(cpi), "pass": (nominal - cpi) >= 0.05 if nominal is not None and cpi is not None else None}
    margins = [p["ebit"] / p["revenue"] for p in years if p.get("ebit") is not None and p.get("revenue")]
    r["B2_ebitMargin"] = {"byYear": [pct(m) for m in margins], "stdev_pp": pct(statistics.pstdev(margins)) if len(margins) > 1 else None,
                          "trend": "rośnie" if len(margins) > 1 and margins[0] > margins[-1] else "spada" if len(margins) > 1 and margins[0] < margins[-1] else None}
    if len(years) >= 2 and years[1].get("ebit") and years[1]["ebit"] > 0 and years[0].get("ebit") is not None:
        rg = years[0]["revenue"] / years[1]["revenue"] - 1
        eg = years[0]["ebit"] / years[1]["ebit"] - 1
        r["B3_operatingLeverage"] = {"revenueGrowth": pct(rg), "ebitGrowth": pct(eg), "pass": eg > rg if rg > 0 else None}
    eq = [(p["assets"] - p["liabilities"]) for p in years if p.get("assets") and p.get("liabilities") is not None]
    if years[0].get("ebit") is not None and years[0].get("assets") and years[0].get("stLiabilities") is not None:
        ic = years[0]["assets"] - years[0]["stLiabilities"] - (years[0].get("cash") or 0)
        roic = years[0]["ebit"] * 0.81 / ic if ic > 0 else None
        r["B4_roicApprox"] = {"value": pct(roic), "method": "EBIT×(1−19%) / (aktywa − zobowiązania krótkoterminowe − gotówka); przybliżenie", "pass": roic > 0.11 if roic is not None else None}
    cfo = sum(p.get("cfo") or 0 for p in years[:3])
    ni = sum(p.get("netIncome") or 0 for p in years[:3])
    r["B5_cashConversion"] = {"cfo3y": cfo, "netIncome3y": ni, "ratio": pct(cfo / ni) if ni > 0 else None, "pass": (cfo / ni) >= 0.8 if ni > 0 else None}
    r["B6_debt"] = {"liabilitiesToEquity": round(years[0]["liabilities"] / eq[0], 2) if eq and eq[0] > 0 else None, "cash": years[0].get("cash"),
                    "note": "Dług netto/EBITDA wymaga zadłużenia odsetkowego – sprawdź w raporcie (strefa nie podaje); tu tylko zobowiązania/kapitał własny."}
    r["B7_dilution"] = {"value": None, "note": "brak liczby akcji w źródle – sprawdź (stockanalysis: Buyback Yield / Dilution)"}
    ytd = next((p for p in f.get("periods", []) if p.get("ytd")), None)
    if ytd:
        r["ytd"] = {"period": ytd["period"], "revenue": ytd.get("revenue"), "ebit": ytd.get("ebit"), "netIncome": ytd.get("netIncome")}
    r["ratios"] = f.get("ratios", {})
    r["liquidity"] = turnover
    r["price"] = price
    return r


def scores():
    gpw_files = sorted(f for f in os.listdir(D("gpw")) if f.endswith(".json")) if os.path.isdir(D("gpw")) else []
    last60 = [jload(D("gpw", f), {}) for f in gpw_files[-60:]]
    last60 = [d for d in last60 if d.get("stocks")]
    out = {}
    for c in CFG["companies"] + EXTRA:
        f = jload(D("fundamentals", c["ticker"] + ".json"), None)
        if not f:
            continue
        turnover = None
        name = c.get("gpw")
        if name and last60:
            vals = [d["stocks"].get(name, [None, None, None])[2] for d in last60]
            vals = [v for v in vals if v is not None]
            if vals:
                turnover = {"avg60k": round(sum(vals) / len(vals), 1), "sessions": len(vals), "unit": "tys. zł/dzień",
                            "filterA": "OK" if sum(vals) / len(vals) >= 200 else "ostrzeżenie" if sum(vals) / len(vals) >= 150 else "odrzuć"}
        if c.get("market") in ("GPW", "NewConnect"):
            s = score_pl(c["ticker"], f, None, turnover)
            if s:
                jsave(D("scores", c["ticker"] + ".json"), s)
                out[c["ticker"]] = True
    return out


if __name__ == "__main__":
    today = dt.date.today()
    for d in (today - dt.timedelta(days=1), today):
        if os.path.exists(D("feed", d.isoformat() + ".json")):
            print(d, build_digest(d.isoformat()))
    print("scores", scores())
