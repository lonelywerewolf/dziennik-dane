"""Panel → konfiguracja zbieracza (uruchamia zadanie odświeżania).

Użycie: python3 collector/sync_config.py /tmp/db/watchlist /tmp/db/ideas
 - /tmp/db/watchlist: dokumenty z panelu (ArtifactData list watchlist z out_dir) – Twój portfel
 - /tmp/db/ideas:     dokumenty z panelu (ArtifactData list ideas z out_dir) – tezy i obserwowane
Panel jest źródłem prawdy: config/watchlist.json = spółki z panelu, config/extra.json = obserwowane spoza portfela,
config/conditions.json = warunki cenowe z tez. Istniejące ustawienia spółek (gpw, isin, match, exclude) zostają.
Wypisuje JSON {changed, added, removed, missingIsin}; przy changed=true zadanie robi commit + push.
"""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
J = lambda p, d: json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d
CFG = lambda n: os.path.join(ROOT, "config", n)

gl = J(os.path.join(ROOT, "data", "export", "gpw_last.json"), {}).get("stocks", {})
cal = J(os.path.join(ROOT, "data", "calendar.json"), {"gpw": []}).get("gpw", [])
MARKET_CCY = {"GPW": "PLN", "NewConnect": "PLN", "USA": "USD", "Euronext": "EUR"}


def docs(folder):
    return [d.get("data", d) for d in (J(f, {}) for f in sorted(glob.glob(os.path.join(folder, "*.json"))))] if folder and os.path.isdir(folder) else []


def build(t, name, market, prev):
    if prev:
        return prev
    hit = next((e for e in cal if e.get("ticker") == t or e.get("gpwName") == t), None)
    gname = t if t in gl else (hit or {}).get("gpwName")
    if market in ("GPW", "NewConnect") or (market is None and gname in gl):
        nm = (name or (hit or {}).get("name") or gname or t)
        e = {"ticker": t, "name": nm, "market": market or "GPW", "ccy": "PLN",
             "match": sorted({x for x in [gname, nm.upper().replace(" S.A.", "").replace(" SA", "").strip()] if x and len(x) > 2})}
        if gname:
            e["gpw"] = gname
        if (hit or {}).get("isin"):
            e["isin"] = hit["isin"]
        return e
    return {"ticker": t, "name": name or t, "market": market or "USA", "ccy": MARKET_CCY.get(market or "USA", "USD"), "insiders": (market or "USA") == "USA",
            "match": [x for x in {(name or "").upper().split(" (")[0].replace(" INC", "").replace(" CORP", "").strip()} if len(x) > 2]}


wl_cfg = J(CFG("watchlist.json"), {"companies": []})
ex_cfg = J(CFG("extra.json"), {"companies": []})
known = {c["ticker"]: c for c in wl_cfg["companies"] + ex_cfg.get("companies", [])}

panel_wl = docs(sys.argv[1] if len(sys.argv) > 1 else None)
panel_ideas = docs(sys.argv[2] if len(sys.argv) > 2 else None)
added, removed = [], []

new_wl = []
for w in panel_wl:
    t = (w.get("ticker") or "").upper()
    if not t:
        continue
    e = build(t, w.get("name"), w.get("market"), known.get(t))
    e = dict(e)
    e["market"] = w.get("market") or e.get("market")
    if t not in {c["ticker"] for c in wl_cfg["companies"]}:
        added.append(t)
    new_wl.append(e)
if panel_wl:
    removed += sorted({c["ticker"] for c in wl_cfg["companies"]} - {c["ticker"] for c in new_wl})
own = {c["ticker"] for c in new_wl} if panel_wl else {c["ticker"] for c in wl_cfg["companies"]}

new_ex, conds = [], []
for i in panel_ideas:
    t = (i.get("ticker") or "").upper().strip()
    if not t:
        continue
    for c in i.get("conditions", []):
        if c.get("kind") == "price":
            conds.append({"ticker": t, "gpwName": (i.get("gpwName") or t).upper(), "op": c.get("op"), "value": c.get("value"), "ccy": c.get("ccy")})
    if t in own or any(x["ticker"] == t for x in new_ex):
        continue
    e = build(t, i.get("name"), i.get("market"), known.get(t))
    if t not in {c["ticker"] for c in ex_cfg.get("companies", [])}:
        added.append(t)
    new_ex.append(e)
removed += sorted({c["ticker"] for c in ex_cfg.get("companies", [])} - {c["ticker"] for c in new_ex} - own)

changed = False
outs = [("extra.json", {"_opis": ex_cfg.get("_opis", "Obserwowane spoza portfela (z panelu)."), "companies": sorted(new_ex, key=lambda x: x["ticker"])}),
        ("conditions.json", {"_opis": "Warunki cenowe z tez w panelu (synchronizowane automatycznie).", "items": conds})]
if panel_wl:
    outs.insert(0, ("watchlist.json", {**{k: v for k, v in wl_cfg.items() if k != "companies"}, "companies": new_wl}))
for name, obj in outs:
    if J(CFG(name), None) != obj:
        json.dump(obj, open(CFG(name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        changed = True
missing = [e["ticker"] for e in new_wl + new_ex if e.get("market") in ("GPW", "NewConnect") and not e.get("isin")]
print(json.dumps({"changed": changed, "added": added, "removed": removed, "conditions": len(conds), "missingIsin": missing,
                  "hint": "missingIsin: znajdź ISIN (WebSearch 'strefainwestorow <nazwa> wyniki-finansowe' – ISIN w adresie /notowania/spolki/<ISIN>/), dopisz pole isin w config/watchlist.json lub config/extra.json. Potem commit + push."}, ensure_ascii=False))
