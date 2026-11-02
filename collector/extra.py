"""Moduły dzienne zbieracza: fundamenty, kalendarze, raporty PWPA, makro.

Uruchamiane raz dziennie (rano) albo gdy pliku brakuje. Bez AI.
"""
import datetime as dt, html, io, json, os, re, time, urllib.parse, urllib.request
from collect import get, jload, jsave, text, plnum, usd, NOW, D, CFG, COMP, ROOT, WAW, NASDAQ_H

EXTRA = jload(os.path.join(ROOT, "config", "extra.json"), {"companies": []})   # spółki spoza portfela (obserwowane, kandydaci)
ALL = COMP + [c for c in EXTRA.get("companies", []) if c.get("ticker") not in {x["ticker"] for x in COMP}]


def due(path, hours=20):
    return not os.path.exists(path) or (time.time() - os.path.getmtime(path)) > hours * 3600


# ---------- 1. Fundamenty ----------
def strefa_table(s):
    tb = s[s.find('<table class="table d-none d-lg-table table-results-desktop'):]
    tb = tb[: tb.find("</table>")]
    heads = [text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", tb, re.S)][1:]
    rows = {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
        c = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(c) > 1:
            rows[c[0]] = [plnum(x) if x not in ("", "-") else None for x in c[1:]]
    return heads, rows


KEYMAP = {"Przychody ze sprzedaży": "revenue", "Zysk (strata) ze sprzedaży": "salesProfit", "Zysk operacyjny (EBIT)": "ebit", "Zysk netto": "netIncome",
          "Aktywa ogółem": "assets", "Aktywa obrotowe": "currentAssets", "Zobowiązania ogółem": "liabilities", "Zobowiązania długoterminowe": "ltLiabilities",
          "Zobowiązania krótkoterminowe": "stLiabilities", "A. Przepływy pieniężne z działalności operacyjnej": "cfo", "B. Przepływy pieniężne z działalności inwestycyjnej": "cfi",
          "C. Przepływy pieniężne z działalności finansowej": "cff", "Środki pieniężne na koniec okresu": "cash"}


def fundamentals():
    st = {"pl": 0, "us": 0, "errors": []}
    for c in ALL:
        path = D("fundamentals", c["ticker"] + ".json")
        if not due(path, 24 * 6):          # raz na ~6 dni (wyniki kwartalne)
            continue
        try:
            if c.get("market") in ("GPW", "NewConnect") and c.get("isin"):
                base = f"https://strefainwestorow.pl/notowania/spolki/{c['isin']}"
                heads, rows = strefa_table(get(base + "/wyniki-finansowe"))
                periods = []
                for i, h in enumerate(heads):
                    p = {"period": h, "ytd": "*" in h}
                    for pl_name, key in KEYMAP.items():
                        v = rows.get(pl_name)
                        if v and i < len(v):
                            p[key] = v[i]
                    periods.append(p)
                time.sleep(1)
                ratios = {}
                try:
                    rs = get(base + "/wskazniki-finansowe")
                    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", rs, re.S):
                        cc = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
                        if len(cc) >= 2 and len(cc[0]) < 60:
                            ratios[cc[0]] = cc[1]
                except Exception as e:
                    st["errors"].append(f"{c['ticker']} wskaźniki: {e!r}"[:120])
                jsave(path, {"ticker": c["ticker"], "unit": "tys. PLN", "periods": periods, "ratios": ratios, "src": base + "/wyniki-finansowe", "updatedAt": NOW.isoformat(timespec="seconds")})
                st["pl"] += 1
            elif c.get("market") == "USA":
                out = {"ticker": c["ticker"], "unit": "tys. USD", "src": f"https://www.nasdaq.com/market-activity/stocks/{c['ticker'].lower()}/financials", "updatedAt": NOW.isoformat(timespec="seconds")}
                for freq, name in ((2, "quarterly"), (1, "annual")):
                    j = json.loads(get(f"https://api.nasdaq.com/api/company/{c['ticker']}/financials?frequency={freq}", headers=NASDAQ_H)).get("data")
                    if not j:
                        out["note"] = "Nasdaq nie publikuje sprawozdań dla tego ADR (spółka zagraniczna, raporty 20-F/6-K) – dane z raportów spółki."
                        break
                    tables = {}
                    for tname in ("incomeStatementTable", "balanceSheetTable", "cashFlowTable"):
                        t = j.get(tname) or {}
                        hd = t.get("headers") or {}
                        cols = [hd[k] for k in sorted(hd) if k != "value1"]
                        tables[tname] = {"periods": cols, "rows": {r["value1"]: [usd(r[k]) for k in sorted(r) if k != "value1"] for r in (t.get("rows") or [])}}
                    out[name] = tables
                    time.sleep(0.6)
                jsave(path, out)
                st["us"] += 1
        except Exception as e:
            st["errors"].append(f"{c['ticker']}: {e!r}"[:160])
        time.sleep(1)
    st["ok"] = not st["errors"]
    return st


# ---------- 2. Kalendarz ----------
def calendar():
    st = {"errors": []}
    path = D("calendar.json")
    cal = jload(path, {"gpw": [], "us": []})
    if due(path, 12):
        try:
            s = get("https://strefainwestorow.pl/dane/raporty/lista-publikacji-raportow-okresowych")
            tb = s[s.find("<tbody"): s.find("</tbody>")]
            items = []
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
                cells = re.findall(r"<td([^>]*)>(.*?)</td>", r, re.S)
                if len(cells) < 5:
                    continue
                isin = (re.search(r"/notowania/spolki/([A-Z0-9]{12})", cells[1][1]) or [None, None])[1]
                ts = re.search(r'timestamp="(\d+)"', cells[3][0])
                date = dt.datetime.fromtimestamp(int(ts.group(1)), WAW).date().isoformat() if ts else None
                items.append({"gpwName": text(cells[0][1]), "ticker": text(cells[1][1]), "isin": isin, "name": text(cells[2][1]), "date": date, "report": text(cells[4][1])})
            cal["gpw"] = items
            cal["gpwSrc"] = "https://strefainwestorow.pl/dane/raporty/lista-publikacji-raportow-okresowych"
            st["gpw"] = len(items)
        except Exception as e:
            st["errors"].append(f"gpw: {e!r}"[:160])
        us = []
        for c in ALL:
            if c.get("market") != "USA":
                continue
            try:
                j = json.loads(get(f"https://api.nasdaq.com/api/analyst/{c['ticker']}/earnings-date", headers=NASDAQ_H))["data"]
                txt = j.get("reportText") or ""
                m = re.search(r"on\s+(\d{1,2})/(\d{1,2})/(\d{4})", txt)
                if m:
                    us.append({"ticker": c["ticker"], "date": f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", "when": "po sesji" if "after" in txt else "przed sesją" if "before" in txt else "",
                               "estimated": "expected" in txt, "consensusEps": ((re.search(r"consensus EPS forecast for the quarter is \$([\d.\-]+)", txt) or [None, ""])[1] or "").rstrip(".") or None, "text": txt,
                               "src": f"https://www.nasdaq.com/market-activity/stocks/{c['ticker'].lower()}/earnings"})
            except Exception as e:
                st["errors"].append(f"{c['ticker']}: {e!r}"[:120])
            time.sleep(0.6)
        cal["us"] = us
        st["us"] = len(us)
        cal["updatedAt"] = NOW.isoformat(timespec="seconds")
        jsave(path, cal)
    st["ok"] = not st["errors"]
    return st


# ---------- 4. Raporty PWPA (gpw.pl) ----------
def pwpa():
    st = {"new": 0, "texts": 0, "errors": []}
    path = D("pwpa.json")
    data = jload(path, {"items": []})
    have = {i["file"] for i in data["items"]}
    s = get("https://www.gpw.pl/gpwpa")
    want = {c["ticker"] for c in ALL} | {c.get("pwpa") for c in ALL if c.get("pwpa")}
    TYPES = {"ra": "raport analityczny", "aw": "aktualizacja wyceny", "pw": "prognoza wyników", "rk": "komentarz"}
    for r in re.findall(r"<tr>(.*?)</tr>", s, re.S):
        c = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        href = re.search(r'href="(/pub/pwpa/[^"]+\.pdf)"', r)
        if len(c) < 6 or not href:
            continue
        f = href.group(1).rsplit("/", 1)[1]
        if f in have:
            continue
        code = (re.search(r"_([a-z]{2})\.pdf$", f) or [None, ""])[1]
        it = {"date": text(c[0]), "ticker": text(c[1]), "company": text(c[2]), "file": f, "url": "https://www.gpw.pl" + urllib.parse.quote(href.group(1)),
              "type": text(c[4]) or TYPES.get(code, ""), "house": text(c[5])}
        data["items"].append(it)
        have.add(f)
        st["new"] += 1
    # tekst PDF dla spółek z portfela i obserwowanych
    try:
        from pypdf import PdfReader
        for it in data["items"]:
            if it["ticker"] not in want or it.get("textFile"):
                continue
            try:
                req = urllib.request.Request(it["url"], headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                                                 "Accept": "application/pdf,*/*", "Referer": "https://www.gpw.pl/gpwpa"})
                b = urllib.request.urlopen(req, timeout=60).read()
                pdf = PdfReader(io.BytesIO(b))
                txt = "\n".join((p.extract_text() or "") for p in pdf.pages[:6])
                tf = D("pwpa_text", it["file"].replace(".pdf", ".txt"))
                os.makedirs(os.path.dirname(tf), exist_ok=True)
                open(tf, "w", encoding="utf-8").write(txt[:20000])
                it["textFile"] = os.path.relpath(tf, ROOT)
                m = re.search(r"[Cc]ena docelowa[^\d]{0,40}([\d\s]+[,.]\d+|\d+)", txt)
                if m:
                    it["targetGuess"] = plnum(m.group(1))
                st["texts"] += 1
                time.sleep(1)
            except Exception as e:
                st["errors"].append(f"{it['file']}: {e!r}"[:140])
    except ImportError:
        st["errors"].append("brak pypdf")
    data["items"].sort(key=lambda i: i["date"], reverse=True)
    data["items"] = data["items"][:3000]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    st["ok"] = not st["errors"]
    return st


# ---------- 5. Makro (Eurostat) ----------
EUROSTAT = {
    "cpi_pl_yoy": ("prc_hicp_manr", "geo=PL&coicop=CP00", "Inflacja HICP Polska r/r, %"),
    "cpi_ea_yoy": ("prc_hicp_manr", "geo=EA&coicop=CP00", "Inflacja HICP strefa euro r/r, %"),
    "core_pl_yoy": ("prc_hicp_manr", "geo=PL&coicop=TOT_X_NRG_FOOD", "Inflacja bazowa (bez energii i żywności) Polska r/r, %"),
    "unemp_pl": ("une_rt_m", "geo=PL&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT", "Stopa bezrobocia Polska (Eurostat, SA), %"),
    "gdp_pl_qoq": ("namq_10_gdp", "geo=PL&unit=CLV_PCH_PRE&s_adj=SCA&na_item=B1GQ", "PKB Polska k/k (SA), %"),
    "gdp_pl_yoy": ("namq_10_gdp", "geo=PL&unit=CLV_PCH_SM&s_adj=SCA&na_item=B1GQ", "PKB Polska r/r (SA), %"),
    "yield10_pl": ("irt_lt_mcby_m", "geo=PL&int_rt=MCBY", "Rentowność 10-letnich obligacji PL (Maastricht), %"),
    "retail_pl_yoy": ("sts_trtu_m", "geo=PL&indic_bt=VOL_SLS&nace_r2=G47&s_adj=CA&unit=PCH_SM", "Sprzedaż detaliczna PL r/r (wolumen), %"),
    "industry_pl_yoy": ("sts_inpr_m", "geo=PL&indic_bt=PRD&nace_r2=B-D&s_adj=CA&unit=PCH_SM", "Produkcja przemysłowa PL r/r, %"),
    "constr_pl_yoy": ("sts_copr_m", "geo=PL&indic_bt=PRD&nace_r2=F&s_adj=CA&unit=PCH_SM", "Produkcja budowlana PL r/r, %"),
}


def macro():
    path = D("macro.json")
    if not due(path, 20):
        return {"ok": True, "skipped": True}
    st = {"series": 0, "errors": []}
    out = jload(path, {"series": {}})
    for key, (ds, q, label) in EUROSTAT.items():
        try:
            j = json.loads(get(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{ds}?{q}&lastTimePeriod=24", headers={"Accept": "application/json"}))
            idx = j["dimension"]["time"]["category"]["index"]
            vals = j.get("value", {})
            pts = sorted((t, vals.get(str(i))) for t, i in idx.items())
            pts = [(t, v) for t, v in pts if v is not None]
            out["series"][key] = {"label": label, "points": pts, "src": f"https://ec.europa.eu/eurostat/databrowser/view/{ds}/default/table"}
            st["series"] += 1
        except Exception as e:
            st["errors"].append(f"{key}: {e!r}"[:140])
        time.sleep(0.5)
    out["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, out)
    st["ok"] = st["series"] > 0
    return st
