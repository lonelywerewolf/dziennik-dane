"""Przenosi tezy/obserwowane z panelu (kolekcja ideas) do konfiguracji zbieracza.

Użycie (zadanie Claude): ArtifactData list collection "ideas" z out_dir /tmp/db  →
  python3 collector/ideas_to_config.py /tmp/db/ideas
Aktualizuje config/extra.json (spółki spoza portfela do śledzenia) i config/conditions.json (warunki cenowe).
Wypisuje, czy coś się zmieniło (wtedy zadanie robi commit + push).
"""
import json, os, re, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
J = lambda p, d: json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d

wl = J(os.path.join(ROOT, "config", "watchlist.json"), {"companies": []})
own = {c["ticker"] for c in wl["companies"]}
cal = J(os.path.join(ROOT, "data", "calendar.json"), {"gpw": []}).get("gpw", [])
gl = J(os.path.join(ROOT, "data", "export", "gpw_last.json"), {}).get("stocks", {})
old_extra = J(os.path.join(ROOT, "config", "extra.json"), {"companies": []})
known = {c["ticker"]: c for c in old_extra.get("companies", [])}

ideas = [J(f, {}) for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json")))]
extra, conds = [], []
for i in ideas:
    t = (i.get("ticker") or "").upper().strip()
    if not t:
        continue
    gpw_name = (i.get("gpwName") or t).upper()
    for c in i.get("conditions", []):
        if c.get("kind") == "price":
            conds.append({"ticker": t, "gpwName": gpw_name, "op": c.get("op"), "value": c.get("value"), "ccy": c.get("ccy")})
    if t in own:
        continue
    prev = known.get(t, {})
    hit = next((e for e in cal if e.get("ticker") == t or e.get("gpwName") == gpw_name), None)
    us = bool(re.fullmatch(r"[A-Z]{1,5}", t)) and gpw_name not in gl and not hit
    e = {"ticker": t, "name": i.get("name") or prev.get("name") or t, "market": prev.get("market") or ("USA" if us else "GPW"),
         "gpw": None if us else (gpw_name if gpw_name in gl else (hit or {}).get("gpwName") or prev.get("gpw")),
         "isin": prev.get("isin") or (hit or {}).get("isin"),
         "match": prev.get("match") or [x for x in {(i.get("name") or "").upper().split(" S.A")[0].strip(), gpw_name} if x and len(x) > 2]}
    e = {k: v for k, v in e.items() if v not in (None, [], "")}
    extra.append(e)

new_extra = {"_opis": old_extra.get("_opis", ""), "companies": sorted(extra, key=lambda x: x["ticker"])}
new_cond = {"_opis": "Warunki cenowe z tez w panelu (synchronizowane przez zadania).", "items": conds}
changed = False
for name, obj in (("extra.json", new_extra), ("conditions.json", new_cond)):
    p = os.path.join(ROOT, "config", name)
    if J(p, None) != obj:
        json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        changed = True
missing_isin = [e["ticker"] for e in extra if e.get("market") == "GPW" and not e.get("isin")]
print(json.dumps({"changed": changed, "extra": [e["ticker"] for e in extra], "conditions": len(conds),
                  "missingIsin": missing_isin, "hint": "Dla spółek z missingIsin znajdź ISIN (WebSearch 'strefainwestorow <nazwa> wyniki-finansowe' – ISIN jest w adresie) i dopisz do config/extra.json, potem commit + push."}, ensure_ascii=False))
