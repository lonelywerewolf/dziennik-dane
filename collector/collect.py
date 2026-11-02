"""Zbieracz danych dla Dziennika Portfela.

Uruchamiany przez GitHub Actions co 15 min. Bez AI – zwykłe pobieranie stron.
Wyniki w data/: feed (ESPI + PAP + wiadomości), kursy, historia, kursy NBP,
rekomendacje, transakcje insiderów USA (SEC Form 4), alerty warunków i status.
"""
import csv, datetime as dt, hashlib, html, io, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error, http.cookiejar
from zoneinfo import ZoneInfo

WAW = ZoneInfo("Europe/Warsaw")
NOW = dt.datetime.now(WAW)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEC_UA = "DziennikPortfela lonelywerewolf@users.noreply.github.com"
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


def match_ticker(*texts):
    blob = " ".join(t for t in texts if t).upper()
    for c in COMP:
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
def recs():
    s = get("https://strefainwestorow.pl/rekomendacje")
    tb = s[s.find("<tbody"): s.find("</tbody>")]
    path = D("recs.json")
    data = jload(path, {"items": []})
    have = {(i["date"], i["company"], i["house"], i["rating"]) for i in data["items"]}
    new = 0
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
        if len(cells) < 8:
            continue
        g = lambda i: text(cells[i][1])
        raw = lambda i: (re.search(r'raw="([^"]*)"', cells[i][0]) or [None, None])[1]
        tsm = re.search(r'timestamp="(\d+)"', cells[7][0])
        date = dt.datetime.fromtimestamp(int(tsm.group(1)), WAW).date().isoformat() if tsm else g(7)
        rep = re.search(r'href="([^"]+)"', cells[8][1]) if len(cells) > 8 else None
        it = {"date": date, "company": g(0), "rating": g(1), "price": raw(2), "target": raw(3), "upside": raw(4), "priceAtPub": raw(5), "house": g(6),
              "report": rep and urllib.parse.urljoin("https://strefainwestorow.pl", html.unescape(rep.group(1))), "ticker": match_ticker(g(0))}
        key = (it["date"], it["company"], it["house"], it["rating"])
        if key in have:
            continue
        have.add(key)
        data["items"].append(it)
        new += 1
    data["items"].sort(key=lambda i: i["date"], reverse=True)
    data["items"] = data["items"][:1500]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    return {"new": new, "newest": data["items"][0]["date"] if data["items"] else None}


# ---------------- GPW (kontrolnie) ----------------
def gpw():
    s = get("https://www.gpw.pl/komunikaty", headers={"Accept": "text/html", "Referer": "https://www.gpw.pl/"})
    times = re.findall(r"(\d\d-\d\d-\d{4} \d\d:\d\d:\d\d)", s)
    return {"ok": True, "items": len(times), "newest": times[0] if times else None, "oldestSeen": times[-1] if times else None}


# ---------------- kursy i historia: Yahoo Finance (publiczny endpoint wykresów) ----------------
def yahoo_chart(sym, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d"
    j = json.loads(get(url, headers={"Accept": "application/json"}))
    r = j["chart"]["result"][0]
    ts = r.get("timestamp") or []
    closes = r["indicators"]["quote"][0].get("close") or []
    rows = [(dt.datetime.fromtimestamp(t, ZoneInfo(r["meta"].get("exchangeTimezoneName") or "UTC")).date().isoformat(), c) for t, c in zip(ts, closes) if c is not None]
    return r["meta"], rows


def quotes():
    syms = {c["ticker"]: c.get("yahoo") for c in COMP if c.get("yahoo")}
    syms.update(CFG.get("benchmarks", {}))
    st = {"history": 0, "latest": 0, "errors": [], "symbols": {}}
    hist_dir = D("history")
    os.makedirs(hist_dir, exist_ok=True)
    latest = jload(D("quotes.json"), {"q": {}})
    for key, cands in syms.items():
        cands = cands if isinstance(cands, list) else [cands]
        path = os.path.join(hist_dir, key + ".csv")
        full = (not os.path.exists(path)) or NOW.hour >= 22
        err = None
        for sym in cands:
            try:
                meta, rows = yahoo_chart(sym, "2y" if full else "5d")
                if not rows:
                    raise ValueError("brak danych")
                if full:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("date,close\n" + "".join(f"{d},{round(c, 4)}\n" for d, c in rows))
                    st["history"] += 1
                else:
                    old = dict(l.strip().split(",") for l in open(path, encoding="utf-8").read().splitlines()[1:] if l.strip())
                    for d, c in rows:
                        old[d] = str(round(c, 4))
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("date,close\n" + "".join(f"{d},{v}\n" for d, v in sorted(old.items())))
                d_last, c_last = rows[-1]
                q = {"date": d_last, "close": round(c_last, 4), "ccy": meta.get("currency"), "symbol": sym,
                     "src": f"https://finance.yahoo.com/quote/{sym}"}
                if len(rows) > 1:
                    q["prevClose"] = round(rows[-2][1], 4)
                    q["chg"] = round((c_last / rows[-2][1] - 1) * 100, 2)
                rmp = meta.get("regularMarketPrice")
                if rmp:
                    q["live"] = rmp
                    q["liveAt"] = dt.datetime.fromtimestamp(meta.get("regularMarketTime", 0), WAW).isoformat(timespec="minutes")
                latest["q"][key] = q
                st["latest"] += 1
                st["symbols"][key] = sym
                err = None
                break
            except Exception as e:
                err = f"{key}/{sym}: {e!r}"[:200]
        if err:
            st["errors"].append(err)
        time.sleep(0.4)
    latest["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(D("quotes.json"), latest)
    st["ok"] = st["latest"] > 0
    return st


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


# ---------------- SEC Form 4 (insiderzy USA) ----------------
def sec():
    st = {"new": 0, "errors": []}
    path = D("insiders_us.json")
    data = jload(path, {"items": []})
    have = {i["id"] for i in data["items"]}
    for c in COMP:
        if c.get("market") != "USA" or not c.get("sec"):
            continue
        try:
            s = get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c['sec']}&type=4&dateb=&owner=include&count=40&output=atom",
                    ua=SEC_UA, headers={"Accept": "application/atom+xml"})
            for e in re.findall(r"<entry>(.*?)</entry>", s, re.S):
                g = lambda t: (re.search(rf"<{t}[^>]*>(.*?)</{t}>", e, re.S) or [None, ""])[1]
                link = (re.search(r'<link[^>]+href="([^"]+)"', e) or [None, ""])[1]
                iid = (re.search(r"accession-number>([^<]+)<", e) or [None, link])[1]
                if iid in have:
                    continue
                have.add(iid)
                data["items"].append({"id": iid, "ticker": c["ticker"], "date": g("filing-date") or g("updated")[:10], "title": text(g("title")), "summary": text(g("summary"))[:300], "url": link})
                st["new"] += 1
        except Exception as e:
            st["errors"].append(f"{c['ticker']}: {e!r}"[:200])
        time.sleep(0.3)
    data["items"].sort(key=lambda i: i["date"], reverse=True)
    data["items"] = data["items"][:2000]
    data["updatedAt"] = NOW.isoformat(timespec="seconds")
    jsave(path, data)
    st["ok"] = not st["errors"]
    return st


# ---------------- warunki (strefy wejścia, progi) ----------------
def conditions():
    cond = jload(os.path.join(ROOT, "config", "conditions.json"), {"items": []})
    q = jload(D("quotes.json"), {"q": {}})["q"]
    out = []
    for c in cond.get("items", []):
        t = c.get("ticker")
        px = q.get(t, {}).get("close")
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
    jobs = [("bossa", bossa), ("strefa", strefa), ("recs", recs), ("gpw", gpw), ("quotes", quotes), ("nbp", nbp), ("sec", sec), ("conditions", conditions)]
    for name, fn in jobs:
        if not only or name in only:
            run(name, fn)
    save_feeds()
    prev = jload(D("status.json"), {"runs": []})
    runs = [STATUS] + prev.get("runs", [])[:95]
    jsave(D("status.json"), {"last": STATUS, "runs": runs})
