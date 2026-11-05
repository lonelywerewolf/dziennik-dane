"""Zbieracz danych dla Dziennika Portfela.

Uruchamiany przez GitHub Actions co 15 min. Bez AI – zwykłe pobieranie stron.
Wyniki w data/: feed (ESPI + PAP + wiadomości), kursy, historia, kursy NBP,
rekomendacje, transakcje insiderów USA (SEC Form 4), alerty warunków i status.
"""
import csv, datetime as dt, hashlib, html, io, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error, http.cookiejar
from zoneinfo import ZoneInfo
import email.utils

WAW = ZoneInfo("Europe/Warsaw")
NOW = dt.datetime.now(WAW)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
STATUS = {"runAt": NOW.isoformat(timespec="seconds"), "sources": {}}

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(url, ua=UA, data=None, headers=None, timeout=30):
    h = {"User-Agent": ua, "Accept-Language": "pl,en;q=0.8", "Accept": "text/html,application/xhtml+xml,application/json,text/csv,*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
    os.replace(tmp, path)


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


CFG = jload(os.path.join(ROOT, "config", "watchlist.json"), {"companies": []})
COMP = CFG["companies"]
EXTRA_COMP = jload(os.path.join(ROOT, "config", "extra.json"), {"companies": []}).get("companies", [])


def match_ticker(*texts):
    blob = " ".join(t for t in texts if t).upper()
    for c in COMP + EXTRA_COMP:
        if any(re.search(x, blob, re.I) for x in c.get("exclude", [])):
            continue
        for k in c.get("match", []):
            if re.search(r"(?<![A-Z0-9])" + re.escape(k.upper()) + r"(?![A-Z0-9])", blob):
                return c["ticker"]
    return None


# ---------------- feed (per dzień) ----------------
FEED = {}


def feed_day(day):
    if day not in FEED:
        FEED[day] = jload(D("feed", day + ".json"), {"date": day, "items": []})
        FEED[day]["_ids"] = {i["id"] for i in FEED[day]["items"]}
    return FEED[day]


def add_item(it):
    f = feed_day(it["date"])
    if it["id"] in f["_ids"]:
        return False
    f["_ids"].add(it["id"])
    f["items"].append(it)
    return True


def known(item_id, day):
    return item_id in feed_day(day)["_ids"]


def save_feeds():
    for day, f in FEED.items():
        items = sorted(f["items"], key=lambda i: (i.get("time") or "", i["id"]), reverse=True)
        jsave(D("feed", day + ".json"), {"date": day, "count": len(items), "items": items})


# ---------------- bossa: ESPI + depesze PAP (pełna paginacja) ----------------
PL_MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12}


def bossa():
    st = {"pages": 0, "new": 0}
    stop_before = (NOW - dt.timedelta(days=4)).date()
    newest = oldest = None
    for page in range(0, 60):
        url = "https://bossa.pl/analizy/komunikaty" + (f"?page=%2C%2C%2C{page}" if page else "")
        s = get(url)
        st["pages"] += 1
        parts = re.split(r'<h2 class="b30-news-entry-date-header">([^<]+)</h2>', s)
        if len(parts) < 3:
            break
        hit_known = 0
        total = 0
        for k in range(1, len(parts), 2):
            m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", parts[k])
            if not m:
                continue
            day = dt.date(int(m.group(3)), PL_MONTHS.get(m.group(2).lower(), 1), int(m.group(1)))
            for e in re.finditer(r'id="message-(\d+)".*?<span class="time">(\d\d:\d\d)</span>.*?<span class="b30-papmessage-entry-title-prefix"[^>]*data-type="(\w+)"[^>]*>(.*?)</span>\s*<h4[^>]*>(.*?)</h4>', parts[k + 1], re.S):
                mid, hm, typ, prefix, title = e.group(1), e.group(2), e.group(3), text(e.group(4)), text(e.group(5))
                total += 1
                ts = dt.datetime.combine(day, dt.time(int(hm[:2]), int(hm[3:]))).replace(tzinfo=WAW)
                newest = max(newest or ts, ts)
                oldest = min(oldest or ts, ts)
                iid = f"bossa-{typ}-{mid}"
                if known(iid, day.isoformat()):
                    hit_known += 1
                    continue
                if add_item({"id": iid, "date": day.isoformat(), "time": hm, "ts": ts.isoformat(), "src": "bossa", "kind": "espi" if typ == "espi" else "pap",
                             "company": prefix or None, "title": title, "ticker": match_ticker(prefix, title),
                             "url": f"https://bossa.pl/analizy/komunikaty#message-{mid}"}):
                    st["new"] += 1
        # stop: cała strona już znana albo starsza niż horyzont
        if total and hit_known == total and page > 0:
            st["complete"] = True
            break
        if oldest and oldest.date() < stop_before:
            st["complete"] = True
            break
        time.sleep(0.6)
    st.update(newest=newest and newest.isoformat(), oldestSeen=oldest and oldest.isoformat())
    st.setdefault("complete", False)
    return st


# ---------------- strefainwestorow: wiadomości PAP (pełna paginacja) ----------------
def strefa():
    st = {"pages": 0, "new": 0}
    horizon = NOW - dt.timedelta(days=4)
    newest = oldest = None
    for page in range(0, 25):
        s = get("https://strefainwestorow.pl/wiadomosci" + (f"?page={page}" if page else ""))
        st["pages"] += 1
        found = 0
        known_n = 0
        for a in re.finditer(r'<a[^>]+href="(/wiadomosci/(\d{8})/[^"#?]+)"[^>]*>(.*?)</a>', s, re.S):
            path, ymd, inner = a.group(1), a.group(2), a.group(3)
            title = text(inner)
            if len(title) < 8:
                continue
            tail = s[a.end(): a.end() + 4000]
            tm = re.search(r'<time\s+datetime="([^"]+)"', tail)
            if not tm:
                continue
            ts = dt.datetime.strptime(tm.group(1), "%Y-%m-%dT%H:%M:%S%z").astimezone(WAW)
            found += 1
            newest = max(newest or ts, ts)
            oldest = min(oldest or ts, ts)
            iid = "strefa-" + hashlib.sha1(path.encode()).hexdigest()[:12]
            day = ts.date().isoformat()
            if known(iid, day):
                known_n += 1
                continue
            kind = "skrot" if title.lower().startswith("skrót wiadomości") else "news"
            if add_item({"id": iid, "date": day, "time": ts.strftime("%H:%M"), "ts": ts.isoformat(), "src": "strefainwestorow", "kind": kind,
                         "title": title, "ticker": match_ticker(title), "url": "https://strefainwestorow.pl" + path}):
                st["new"] += 1
        if not found:
            break
        if known_n >= found * 0.8 and page > 0:
            st["complete"] = True
            break
        if oldest and oldest < horizon:
            st["complete"] = True
            break
        time.sleep(0.6)
    st.update(newest=newest and newest.isoformat(), oldestSeen=oldest and oldest.isoformat())
    st.setdefault("complete", False)
    return st


# ---------------- rekomendacje ----------------
def _num(v):
    if v is None:
        return None
    v = re.sub(r"[^0-9,.\-]", "", str(v)).replace(",", ".")
    try:
        return str(float(v)) if v not in ("", ".", "-") else None
    except ValueError:
        return None


def _recs_page(url):
    s = get(url)
    tb = s[s.find("<tbody"): s.find("</tbody>")]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
        if len(cells) < 8:
            continue
        g = lambda i: text(cells[i][1])
        raw = lambda i: (re.search(r'raw="([^"]*)"', cells[i][0]) or [None, None])[1] or _num(g(i))
        tsm = re.search(r'timestamp="(\d+)"', cells[7][0])
        if tsm:
            date = dt.datetime.fromtimestamp(int(tsm.group(1)), WAW).date().isoformat()
        else:
            m = re.search(r"(\d\d)-(\d\d)-(\d{4})", g(7))
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else g(7)
        rep = re.search(r'href="([^"]+)"', cells[8][1]) if len(cells) > 8 else None
        isin = re.search(r"/notowania/spolki/([A-Z]{2}[A-Z0-9]{10})", cells[0][1])
        comp = g(0)
        code = re.search(r"\(([A-Z0-9]{2,6})\)\s*$", comp)
        out.append({"date": date, "company": comp, "code": code and code.group(1), "name": re.sub(r"\s*\([^)]*\)\s*$", "", comp),
                    "isin": isin and isin.group(1), "rating": g(1), "price": raw(2), "target": raw(3), "upside": raw(4), "priceAtPub": raw(5), "house": g(6),
                    "report": rep and urllib.parse.urljoin("https://strefainwestorow.pl", html.unescape(rep.group(1))), "ticker": match_ticker(comp)})
    return out


def recs():
    """Rekomendacje DM: najnowsze + pełna lista z 12 miesięcy (strefainwestorow). Historia rośnie w data/recs.json."""
    path = D("recs.json")
    data = jload(path, {"items": []})
    have = {(i["date"], i["company"], i["house"], i["rating"]): i for i in data["items"]}
    new, seen, errs = 0, 0, []
    for url in ("https://strefainwestorow.pl/rekomendacje", "https://strefainwestorow.pl/rekomendacje/lista-rekomendacji/wszystkie"):
        try:
            rows = _recs_page(url)
        except Exception as e:
            errs.append(f"{url}: {e!r}")
            continue
        seen += len(rows)
        for it in rows:
            key = (it["date"], it["company"], it["house"], it["rating"])
            if key in have:
                old = have[key]
                for k in ("code", "name", "isin", "report"):
                    if it.get(k) and not old.get(k):
                        old[k] = it[k]
                old["ticker"] = it["ticker"] or old.get("ticker")
                continue
            have[key] = it
            data["items"].append(it)
            new += 1
    data["items"].sort(key=lambda i: i["date"], reverse=True)
    data["items"] = data["items"][:8000]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    return {"new": new, "seen": seen, "total": len(data["items"]), "oldest": data["items"][-1]["date"] if data["items"] else None,
            "newest": data["items"][0]["date"] if data["items"] else None, **({"errors": errs} if errs else {})}


# ---------------- pełne teksty kluczowych artykułów (dla raportów) ----------------
ART_RE = re.compile(r"Skrót wiadomości|DZIEŃ NA |TYDZIEŃ NA |Przegląd prasy|Tygodnik PIE|Notowania ciągłe - podsumowanie", re.I)


def _article_text(page):
    for pat in (r'<div[^>]+class="[^"]*field--name-body[^"]*"[^>]*>(.*?)</div>\s*</div>', r'<div[^>]+class="[^"]*field-name-body[^"]*"[^>]*>(.*?)</div>\s*</div>',
                r"<article[^>]*>(.*?)</article>"):
        m = re.search(pat, page, re.S)
        if m and len(text(m.group(1))) > 300:
            body = m.group(1)
            break
    else:
        return None
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
    body = re.sub(r"</(p|div|li|h\d)>|<br\s*/?>", "\n", body)
    out = "\n".join(l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "", body)).splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def articles():
    """Zapisuje pełną treść podsumowań PAP (Skrót wiadomości, DZIEŃ NA…, Przegląd prasy) i wiadomości PAP o śledzonych
    spółkach do data/articles/{dzień}/{id}.txt – raporty nie muszą ich pobierać przez WebFetch."""
    done, fail = 0, []
    for day in [(NOW - dt.timedelta(days=k)).date().isoformat() for k in (0, 1)]:
        for it in feed_day(day)["items"]:
            url = it.get("url") or ""
            if "strefainwestorow.pl/wiadomosci/" not in url:
                continue
            if not (ART_RE.search(it.get("title", "")) or it.get("ticker")):
                continue
            path = D("articles", day, re.sub(r"[^A-Za-z0-9_-]", "_", it["id"])[:80] + ".txt")
            if os.path.exists(path):
                continue
            if done >= 25 or len(fail) >= 8:
                break
            try:
                t = _article_text(get(url))
            except Exception as e:
                fail.append(f"{it['id']}: {e!r}"[:120])
                continue
            if not t:
                fail.append(f"{it['id']}: brak treści")
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{it.get('title')}\n{it.get('time')} · {url}\n\n{t}\n")
            done += 1
    return {"saved": done, **({"errors": fail[:5], "failed": len(fail)} if fail else {})}


# ---------------- GPW (kontrolnie) ----------------
def gpw():
    s = get("https://www.gpw.pl/komunikaty", headers={"Accept": "text/html", "Referer": "https://www.gpw.pl/"})
    try:
        sp = D("_samples", "gpw_komunikaty.html")
        if not os.path.exists(sp) or time.time() - os.path.getmtime(sp) > 86400:
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            i = s.find("komunikat")
            open(sp, "w", encoding="utf-8").write(s[:60000])
    except Exception:
        pass
    times = re.findall(r"(\d\d-\d\d-\d{4} \d\d:\d\d:\d\d)", s)
    return {"ok": True, "items": len(times), "newest": times[0] if times else None, "oldestSeen": times[-1] if times else None}


# ---------------- GPW: oficjalne archiwum notowań (zamknięcia, zmiana, obrót) ----------------
def plnum(x):
    x = html.unescape(x).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None


def gpw_day(day, typ):
    url = f"https://www.gpw.pl/archiwum-notowan?fetch=0&type={typ}&instrument=&date={day.strftime('%d-%m-%Y')}&show_x=Poka%C5%BC+wyniki"
    s = get(url, headers={"Referer": "https://www.gpw.pl/archiwum-notowan"})
    tb = s[s.find('<table class="table footable"'):]
    tb = tb[: tb.find("</table>")]
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", tb, re.S):
        c = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(c) >= 7:
            # nazwa, waluta, otwarcie, max, min, zamknięcie, zmiana %, obrót (tys.)
            out[c[0]] = [plnum(c[5]), plnum(c[6]), plnum(c[7]) if len(c) > 7 else None]
    return out


def gpw_archive():
    st = {"days": 0, "errors": []}
    folder = D("gpw")
    os.makedirs(folder, exist_ok=True)
    have = {f[:10] for f in os.listdir(folder)}
    today = NOW.date()
    days = []
    d = dt.date(2025, 11, 1)
    while d <= today:
        if d.weekday() < 5 and d.isoformat() not in have and not (d == today and NOW.hour * 60 + NOW.minute < 17 * 60 + 15):
            days.append(d)
        d += dt.timedelta(days=1)
    # najpierw dzisiaj/ostatnie, potem uzupełnianie historii (maks. 40 dni na przebieg)
    days = sorted(days, reverse=True)[:40]
    for d in days:
        try:
            stocks = gpw_day(d, 10)
            time.sleep(0.8)
            idx = gpw_day(d, 1) if stocks else {}
            if stocks:
                jsave(os.path.join(folder, d.isoformat() + ".json"), {"date": d.isoformat(), "fields": ["close", "chgPct", "turnoverK"], "stocks": stocks, "indices": idx})
                st["days"] += 1
            else:
                # dzień bez sesji (święto) – zapisz pusty znacznik, żeby nie pytać ponownie
                if d < today:
                    jsave(os.path.join(folder, d.isoformat() + ".json"), {"date": d.isoformat(), "noSession": True, "stocks": {}, "indices": {}})
        except Exception as e:
            st["errors"].append(f"{d}: {e!r}"[:200])
        time.sleep(0.8)
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
    st["latest"] = files[-1][:10] if files else None
    st["stored"] = len(files)
    st["ok"] = not st["errors"]
    return st


# ---------------- USA: Nasdaq API (historia + kurs bieżący) ----------------
NASDAQ_H = {"Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/", "Accept": "application/json"}


def usd(x):
    return plnum(str(x).replace("$", "").replace(",", ""))


def nasdaq():
    st = {"history": 0, "live": 0, "errors": []}
    folder = D("history")
    os.makedirs(folder, exist_ok=True)
    live = jload(D("us_live.json"), {"q": {}})
    items = [(c["ticker"], c["ticker"], "stocks") for c in COMP + EXTRA_COMP if c.get("market") == "USA"] + [(k, v.split(":")[0], (v.split(":") + ["index"])[1]) for k, v in CFG.get("us_benchmarks", {}).items()]
    for key, sym, cls in items:
        path = os.path.join(folder, key + ".csv")
        try:
            old = {}
            if os.path.exists(path):
                old = dict(l.split(",") for l in open(path, encoding="utf-8").read().splitlines()[1:] if "," in l)
            frm = "2025-10-25" if not old else (NOW.date() - dt.timedelta(days=10)).isoformat()
            j = json.loads(get(f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass={cls}&fromdate={frm}&todate={NOW.date()}&limit=9999", headers=NASDAQ_H))
            for r in (j.get("data") or {}).get("tradesTable", {}).get("rows", []) or []:
                m, d_, y = r["date"].split("/")
                v = usd(r["close"])
                if v:
                    old[f"{y}-{m}-{d_}"] = str(v)
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,close\n" + "".join(f"{k},{v}\n" for k, v in sorted(old.items())))
            if cls in ("index", "etf"):
                # historia indeksów w Nasdaq aktualizuje się z opóźnieniem – dopisz zamknięcie z notowania bieżącego, gdy sesja w USA zamknięta
                try:
                    info = json.loads(get(f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass={cls}", headers=NASDAQ_H))["data"]["primaryData"]
                    ts = str(info.get("lastTradeTimestamp") or "")
                    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", ts)
                    px = usd(info.get("lastSalePrice"))
                    ny = NOW.astimezone(ZoneInfo("America/New_York"))
                    closed = ny.hour >= 17 or ny.hour < 9 or ny.weekday() >= 5
                    if m and px and closed:
                        d0 = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat()
                        if d0 not in old:
                            old[d0] = str(px)
                            with open(path, "w", encoding="utf-8") as f:
                                f.write("date,close\n" + "".join(f"{k},{v}\n" for k, v in sorted(old.items())))
                            st.setdefault("indexFromLive", []).append(f"{key} {d0}")
                    live["q"][key] = {"price": px, "chgPct": plnum(str(info.get("percentageChange", "")).replace("%", "").replace("+", "")), "at": ts,
                                      "src": f"https://www.nasdaq.com/market-activity/index/{sym.lower()}"}
                except Exception as e:
                    st["errors"].append(f"{key} info: {e!r}"[:200])
                if len(old) == 0:
                    st["errors"].append(f"{key}: pusta historia")
            st["history"] += 1
            time.sleep(0.5)
            if cls == "stocks":
                info = json.loads(get(f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass=stocks", headers=NASDAQ_H))["data"]["primaryData"]
                live["q"][key] = {"price": usd(info.get("lastSalePrice")), "chgPct": plnum(str(info.get("percentageChange", "")).replace("%", "").replace("+", "")),
                                  "at": info.get("lastTradeTimestamp"), "src": f"https://www.nasdaq.com/market-activity/stocks/{sym.lower()}"}
                st["live"] += 1
        except Exception as e:
            st["errors"].append(f"{key}: {e!r}"[:200])
        time.sleep(0.5)
    live["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(D("us_live.json"), live)
    st["ok"] = not st["errors"]
    return st


# ---------------- wiadomości o spółkach z USA (RSS) ----------------
def us_news():
    """Nagłówki o spółkach z USA (watchlista + obserwowane) z kanałów RSS Nasdaq i Yahoo Finance → data/us_news.json."""
    path = D("us_news.json")
    data = jload(path, {"items": []})
    have = {i["id"] for i in data["items"]}
    st = {"new": 0, "sources": {}, "errors": []}
    tick = [c["ticker"] for c in COMP + EXTRA_COMP if c.get("market") == "USA"]
    for t in tick:
        for name, url in (("nasdaq", f"https://www.nasdaq.com/feed/rssoutbound?symbol={t}"),):   # Yahoo: 429 z adresów GitHuba
            try:
                x = get(url, headers={"Accept": "application/rss+xml,application/xml,text/xml"}, timeout=20)
            except Exception as e:
                st["errors"].append(f"{name} {t}: {e!r}"[:120])
                continue
            n = 0
            for it in re.findall(r"<item>(.*?)</item>", x, re.S):
                g = lambda tag: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1])).strip()
                link, title, pub = g("link"), g("title"), g("pubDate")
                if not link or not title:
                    continue
                iid = hashlib.sha1(link.encode()).hexdigest()[:12]
                if iid in have:
                    continue
                try:
                    when = email.utils.parsedate_to_datetime(pub).astimezone(WAW).isoformat(timespec="minutes")
                except Exception:
                    when = NOW.isoformat(timespec="minutes")
                have.add(iid)
                data["items"].append({"id": iid, "ticker": t, "time": when, "title": title, "url": link, "src": name,
                                      "summary": re.sub(r"<[^>]+>", "", g("description"))[:400]})
                n += 1
            st["sources"][name] = st["sources"].get(name, 0) + n
            st["new"] += n
            time.sleep(0.4)
    data["items"].sort(key=lambda i: i["time"], reverse=True)
    data["items"] = data["items"][:2000]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    st["ok"] = bool(st["sources"]) or not tick
    st["errors"] = st["errors"][:6]
    return st


# ---------------- zbiorcze kursy: quotes.json + historia spółek GPW ----------------
def build_quotes():
    folder = D("gpw")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json")) if os.path.isdir(folder) else []
    gmap = {c["ticker"]: c["gpw"] for c in COMP + EXTRA_COMP if c.get("gpw")}
    gidx = CFG.get("gpw_benchmarks", {})
    series = {k: {} for k in list(gmap) + list(gidx)}
    for f in files:
        day = jload(os.path.join(folder, f), {})
        if day.get("noSession"):
            continue
        for k, name in gmap.items():
            v = day.get("stocks", {}).get(name)
            if v and v[0]:
                series[k][day["date"]] = v
        for k, name in gidx.items():
            v = day.get("indices", {}).get(name)
            if v and v[0]:
                series[k][day["date"]] = v
    os.makedirs(D("history"), exist_ok=True)
    q = {}
    for k, ser in series.items():
        if not ser:
            continue
        with open(D("history", k + ".csv"), "w", encoding="utf-8") as f:
            f.write("date,close,chgPct,turnoverK\n" + "".join(f"{d},{v[0]},{v[1]},{v[2]}\n" for d, v in sorted(ser.items())))
        d_last = max(ser)
        v = ser[d_last]
        q[k] = {"date": d_last, "close": v[0], "chg": v[1], "turnoverK": v[2], "ccy": "PLN" if not k.startswith("^") else None, "src": "https://www.gpw.pl/archiwum-notowan"}
    live = jload(D("us_live.json"), {"q": {}})["q"]
    for c in COMP + EXTRA_COMP:
        if c.get("market") != "USA":
            continue
        path = D("history", c["ticker"] + ".csv")
        if not os.path.exists(path):
            continue
        rows = [l.split(",") for l in open(path, encoding="utf-8").read().splitlines()[1:] if "," in l]
        if not rows:
            continue
        d_last, close = rows[-1][0], float(rows[-1][1])
        e = {"date": d_last, "close": close, "ccy": "USD", "src": f"https://www.nasdaq.com/market-activity/stocks/{c['ticker'].lower()}"}
        if len(rows) > 1:
            e["chg"] = round((close / float(rows[-2][1]) - 1) * 100, 2)
        if live.get(c["ticker"]):
            e["live"] = live[c["ticker"]]
        q[c["ticker"]] = e
    for k in CFG.get("us_benchmarks", {}):
        path = D("history", k + ".csv")
        if os.path.exists(path):
            rows = [l.split(",") for l in open(path, encoding="utf-8").read().splitlines()[1:] if "," in l]
            if rows:
                q[k] = {"date": rows[-1][0], "close": float(rows[-1][1]), "src": "https://www.nasdaq.com"}
    jsave(D("quotes.json"), {"updatedAt": NOW.isoformat(timespec="seconds"), "q": q})
    return {"ok": bool(q), "tickers": len(q)}


# ---------------- NBP ----------------
def nbp():
    path = D("fx.json")
    fx = jload(path, {"USD": {}, "EUR": {}})
    for cur in ("USD", "EUR"):
        start = dt.date(2025, 11, 1) if not fx[cur] else NOW.date() - dt.timedelta(days=10)
        while start <= NOW.date():
            end = min(start + dt.timedelta(days=90), NOW.date())
            try:
                j = json.loads(get(f"https://api.nbp.pl/api/exchangerates/rates/a/{cur.lower()}/{start}/{end}/?format=json", headers={"Accept": "application/json"}))
                for r in j["rates"]:
                    fx[cur][r["effectiveDate"]] = r["mid"]
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            start = end + dt.timedelta(days=1)
        fx[cur] = dict(sorted(fx[cur].items()))
    fx["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, fx)
    return {"ok": True, "USD": list(fx["USD"].items())[-1], "EUR": list(fx["EUR"].items())[-1]}


# ---------------- insiderzy USA: openinsider.com (zbiorczo z SEC Form 4) ----------------
def insiders():
    st = {"new": 0, "errors": []}
    path = D("insiders_us.json")
    data = jload(path, {"items": []})
    have = {i["id"] for i in data["items"]}
    for c in COMP + EXTRA_COMP:
        if c.get("market") != "USA" or not c.get("insiders"):
            continue
        try:
            s = get(f"http://openinsider.com/screener?s={c['ticker']}&fd=730&cnt=200")
            tb = s[s.find('class="tinytable"'):]
            tb = tb[tb.find("<tbody>"): tb.find("</tbody>")]
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                if len(cells) < 12:
                    continue
                link = (re.search(r'href="(http[^"]+sec\.gov[^"]+)"', cells[1]) or [None, None])[1]
                filed, trade = text(cells[1]), text(cells[2])
                who, role, typ = text(cells[4]), text(cells[5]), text(cells[6])
                iid = hashlib.sha1(f"{link}|{who}|{trade}|{typ}|{text(cells[8])}".encode()).hexdigest()[:14]
                if iid in have:
                    continue
                have.add(iid)
                data["items"].append({"id": iid, "ticker": c["ticker"], "filed": filed, "tradeDate": trade, "who": who, "role": role, "type": typ,
                                      "price": text(cells[7]), "qty": text(cells[8]), "owned": text(cells[9]), "deltaOwn": text(cells[10]), "value": text(cells[11]),
                                      "url": link, "src": f"http://openinsider.com/screener?s={c['ticker']}"})
                st["new"] += 1
        except Exception as e:
            st["errors"].append(f"{c['ticker']}: {e!r}"[:200])
        time.sleep(1)
    data["items"].sort(key=lambda i: i["filed"], reverse=True)
    data["items"] = data["items"][:3000]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    st["ok"] = not st["errors"]
    return st


# ---------------- warunki (strefy wejścia, progi) ----------------
def conditions():
    cond = jload(os.path.join(ROOT, "config", "conditions.json"), {"items": []})
    q = jload(D("quotes.json"), {"q": {}})["q"]
    folder = D("gpw")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json")) if os.path.isdir(folder) else []
    gl = {}
    for f in reversed(files):
        gl = jload(os.path.join(folder, f), {}).get("stocks", {})
        if gl:
            break
    out = []
    for c in cond.get("items", []):
        t = c.get("ticker")
        px = q.get(t, {}).get("close")
        if px is None and gl.get((c.get("gpwName") or t or "").upper()):
            px = gl[(c.get("gpwName") or t).upper()][0]
        if px is None:
            continue
        ok = None
        if c.get("op") == "below":
            ok = px <= float(c["value"])
        elif c.get("op") == "above":
            ok = px >= float(c["value"])
        if ok is not None:
            out.append({**c, "price": px, "met": ok, "checkedAt": NOW.isoformat(timespec="seconds")})
    jsave(D("conditions_status.json"), {"updatedAt": NOW.isoformat(timespec="seconds"), "items": out})
    return {"checked": len(out), "met": sum(1 for o in out if o["met"])}


def run(name, fn):
    t0 = time.time()
    try:
        r = fn()
    except Exception as e:
        r = {"ok": False, "error": repr(e)[:300]}
    r.setdefault("ok", True)
    r["sec"] = round(time.time() - t0, 1)
    STATUS["sources"][name] = r
    print(name, json.dumps(r, ensure_ascii=False)[:400])


if __name__ == "__main__":
    only = set(sys.argv[1:])
    jobs = [("bossa", bossa), ("strefa", strefa), ("articles", articles), ("recs", recs), ("gpw", gpw), ("gpw_archive", gpw_archive), ("nasdaq", nasdaq), ("us_news", us_news), ("quotes", build_quotes), ("nbp", nbp), ("insiders", insiders), ("conditions", conditions)]
    try:
        import extra
        jobs += [("fundamentals", extra.fundamentals), ("calendar", extra.calendar), ("pwpa", extra.pwpa), ("macro", extra.macro)]
    except Exception as e:
        STATUS["sources"]["extra_import"] = {"ok": False, "error": repr(e)[:200]}
    for name, fn in jobs:
        if not only or name in only:
            run(name, fn)
    save_feeds()
    try:
        import notify
        run("telegram", notify.run)
    except Exception as e:
        STATUS["sources"]["telegram"] = {"ok": False, "error": repr(e)[:200]}
    prev = jload(D("status.json"), {"runs": []})
    runs = [STATUS] + prev.get("runs", [])[:39]
    jsave(D("status.json"), {"last": STATUS, "runs": runs})
