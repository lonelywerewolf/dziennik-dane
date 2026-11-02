"""Eksport do formatu bazy panelu (Dziennik Portfela).

Tworzy data/export/:
  prices/{YYYY-MM-DD}.json  – dokument dla kolekcji prices: {date, fx, q:{TICKER:{close,ccy,chg}}, src}
  feed/{YYYY-MM-DD}.json    – pozycje w formacie feed panelu (ostatnie 7 dni)
  holders/{TICKER}.json     – transakcje insiderów USA w formacie holders panelu
  recs/{TICKER}.json        – rekomendacje dla spółek z watchlisty w formacie recs panelu
  gpw_last.json             – ostatnie zamknięcia WSZYSTKICH spółek GPW (do warunków dla obserwowanych)
  manifest.json             – sumy kontrolne plików, żeby zadania kopiowały tylko zmiany
"""
import datetime as dt, hashlib, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)
E = lambda *p: os.path.join(ROOT, "data", "export", *p)


def jload(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    s = json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
    if old != s:
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
    return hashlib.sha1(s.encode()).hexdigest()[:12]


CFG = jload(os.path.join(ROOT, "config", "watchlist.json"), {"companies": []})
COMP = CFG["companies"]
START = "2025-11-01"


def read_hist(key):
    p = D("history", key + ".csv")
    if not os.path.exists(p):
        return {}
    out = {}
    for line in open(p, encoding="utf-8").read().splitlines()[1:]:
        c = line.split(",")
        if len(c) >= 2 and c[1] not in ("", "None"):
            out[c[0]] = (float(c[1]), float(c[2]) if len(c) > 2 and c[2] not in ("", "None") else None)
    return out


def prices(manifest):
    fx = jload(D("fx.json"), {"USD": {}, "EUR": {}})
    keys = [c["ticker"] for c in COMP] + list(CFG.get("gpw_benchmarks", {})) + list(CFG.get("us_benchmarks", {}))
    hist = {k: read_hist(k) for k in keys}
    ccy = {c["ticker"]: c.get("ccy", "PLN") for c in COMP}
    # dni sesyjne GPW (archiwum) ∪ dni sesyjne USA
    days = sorted({d for h in hist.values() for d in h if d >= START})
    last = {}
    prev_close = {}
    fx_last = {}
    for d in days:
        for cur in ("USD", "EUR"):
            # kurs NBP z tego dnia lub ostatni wcześniejszy
            v = fx.get(cur, {}).get(d)
            if v:
                fx_last[cur] = v
            elif cur not in fx_last:
                earlier = [x for x in fx.get(cur, {}) if x <= d]
                if earlier:
                    fx_last[cur] = fx[cur][max(earlier)]
        q = {}
        for k in keys:
            h = hist[k].get(d)
            if h is None:
                continue
            close, chg = h
            if chg is None and k in prev_close and prev_close[k]:
                chg = round((close / prev_close[k] - 1) * 100, 2)
            e = {"close": close, "ccy": ccy.get(k, "PLN" if k.startswith("^") and k not in CFG.get("us_benchmarks", {}) else "USD" if k in CFG.get("us_benchmarks", {}) else "PLN")}
            if k.startswith("^"):
                e["index"] = True
            if chg is not None:
                e["chg"] = chg
            q[k] = e
            prev_close[k] = close
        doc = {"date": d, "fx": {"USDPLN": fx_last.get("USD"), "EURPLN": fx_last.get("EUR")}, "q": q,
               "src": ["https://www.gpw.pl/archiwum-notowan", "https://www.nasdaq.com", "https://api.nbp.pl"], "via": "github-zbieracz"}
        manifest["prices"][d] = jsave(E("prices", d + ".json"), doc)


def feed(manifest):
    cut = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    for f in sorted(os.listdir(D("feed"))) if os.path.isdir(D("feed")) else []:
        day = f[:10]
        if day < cut:
            continue
        src = jload(D("feed", f), {"items": []})
        items = []
        for i in src["items"]:
            items.append({"id": i["id"], "time": i.get("time"), "ticker": i.get("ticker"), "kind": "espi" if i.get("kind") == "espi" else ("skrot" if i.get("kind") == "skrot" else "news"),
                          "title": (i.get("company") + ": " if i.get("company") else "") + i["title"], "text": "", "source": {"bossa": "bossa.pl (PAP/ESPI)", "strefainwestorow": "strefainwestorow.pl (PAP)"}.get(i.get("src"), i.get("src")),
                          "url": i.get("url")})
        manifest["feed"][day] = jsave(E("feed", day + ".json"), {"date": day, "auto": items, "via": "github-zbieracz"})


def holders(manifest):
    data = jload(D("insiders_us.json"), {"items": []})
    by = {}
    for i in data["items"]:
        t = i["ticker"]
        typ = i.get("type", "")
        action = "kupno" if typ.startswith("P") else "sprzedaż" if typ.startswith("S") else "inne"
        by.setdefault(t, []).append({"date": (i.get("tradeDate") or i.get("filed", ""))[:10], "kind": "insider", "who": f"{i.get('who')} ({i.get('role')})", "action": action,
                                     "shares": i.get("qty"), "value": i.get("value"), "text": f"{typ}, cena {i.get('price')}, po transakcji {i.get('owned')} akcji ({i.get('deltaOwn')})",
                                     "url": i.get("url") or i.get("src")})
    for t, items in by.items():
        items.sort(key=lambda x: x["date"], reverse=True)
        manifest["holders"][t] = jsave(E("holders", t + ".json"), {"ticker": t, "auto": items[:150], "via": "github-zbieracz"})


def recs(manifest):
    data = jload(D("recs.json"), {"items": []})
    by = {}
    for i in data["items"]:
        if not i.get("ticker"):
            continue
        try:
            target = float(i["target"]) if i.get("target") else None
        except ValueError:
            target = None
        by.setdefault(i["ticker"], []).append({"date": i["date"], "house": i["house"], "rating": i["rating"], "target": target, "currency": "PLN",
                                               "url": i.get("report") or "https://strefainwestorow.pl/rekomendacje", "source": "strefainwestorow.pl"})
    for t, items in by.items():
        manifest["recs"][t] = jsave(E("recs", t + ".json"), {"ticker": t, "auto": items, "via": "github-zbieracz"})


def gpw_last(manifest):
    folder = D("gpw")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json")) if os.path.isdir(folder) else []
    for f in reversed(files):
        day = jload(os.path.join(folder, f), {})
        if day.get("stocks"):
            doc = {"date": day["date"], "fields": ["close", "chgPct", "turnoverK"], "stocks": day["stocks"], "src": "https://www.gpw.pl/archiwum-notowan"}
            manifest["gpw_last"] = jsave(E("gpw_last.json"), doc)
            break


if __name__ == "__main__":
    m = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "prices": {}, "feed": {}, "holders": {}, "recs": {}}
    for fn in (prices, feed, holders, recs, gpw_last):
        try:
            fn(m)
        except Exception as e:
            m.setdefault("errors", []).append(f"{fn.__name__}: {e!r}")
    jsave(E("manifest.json"), m)
    print(json.dumps({k: (len(v) if isinstance(v, dict) else v) for k, v in m.items()}, ensure_ascii=False))
