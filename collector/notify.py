"""Powiadomienia Telegram – tylko ważne rzeczy dla portfela i obserwowanych spółek.

Token bota: sekret TELEGRAM_TOKEN w GitHub Actions (nigdy w plikach).
chat_id ustalany automatycznie z pierwszej wiadomości wysłanej do bota.
"""
import datetime as dt, json, os, re, urllib.parse, urllib.request
from collect import jload, jsave, D, ROOT, NOW, COMP

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
EXTRA = jload(os.path.join(ROOT, "config", "extra.json"), {"companies": []}).get("companies", [])
TRACKED = {c["ticker"]: c for c in COMP + EXTRA}
KEYWORDS = re.compile(r"wynik|prognoz|emisj|ABB|wezwani|przejęc|przejmie|dywidend|umow|kontrakt|zamówien|rekomendac|cena docelow|prezes|rezygnac|odwoł|upadł|restruktur|skup akcji|"
                      r"skup własnych|akcjonariusz|znaczn|zawiesz|korekt|guidance|odpis|pozew|kar[ay] |UOKiK|KNF", re.I)
API = "https://api.telegram.org/bot{}/{}"
# transakcje osób pełniących obowiązki zarządcze (art. 19 MAR) i znaczni akcjonariusze
INSIDER = re.compile(r"art\.? ?19|(?-i:\bMAR\b)|osob[ayę] (pełniąc|blisko związan)|obowiązki zarządcze|powiadomieni\w* o transakcj|transakcj\w* (na|akcjami|nabyci|zbyci)|nabyci\w* akcji|zbyci\w* akcji|członk\w* (zarządu|rady)", re.I)
BUY = re.compile(r"nabyci|kupn|zakup", re.I)
SELL = re.compile(r"zbyci|sprzeda", re.I)


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(API.format(TOKEN, method), data=data), timeout=20) as r:
        return json.loads(r.read().decode())


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run():
    if not TOKEN:
        return {"ok": True, "skipped": "brak TELEGRAM_TOKEN"}
    st_path = D("telegram.json")
    st = jload(st_path, {})
    if not st.get("chat_id"):
        upd = tg("getUpdates")
        chats = [u["message"]["chat"]["id"] for u in upd.get("result", []) if u.get("message", {}).get("chat")]
        if not chats:
            return {"ok": False, "error": "Brak wiadomości do bota – wyślij mu dowolną wiadomość w Telegramie."}
        st["chat_id"] = chats[-1]
        jsave(st_path, st)
        tg("sendMessage", chat_id=st["chat_id"], parse_mode="HTML",
           text="✅ <b>Dziennik Portfela</b>: powiadomienia działają.\nBędę pisać tylko w ważnych sprawach: komunikaty ESPI Twoich i obserwowanych spółek, istotne wiadomości (wyniki, emisje, wezwania, dywidendy, rekomendacje), nowe raporty analityczne, spełnione warunki z Twoich tez i transakcje insiderów (zarząd, rada nadzorcza) w Twoich i obserwowanych spółkach z GPW oraz zakupy insiderów w USA.")
    chat = st["chat_id"]
    try:
        cmd_changes = commands(chat)
    except Exception as e:
        cmd_changes = [f"błąd poleceń: {e!r}"[:120]]
    sent_path = D("notified.json")
    first = not os.path.exists(sent_path)
    sent = set(jload(sent_path, {"ids": []})["ids"])
    msgs = []
    horizon = (NOW - dt.timedelta(hours=6)).isoformat()

    # 1) komunikaty i wiadomości
    for day in {NOW.date().isoformat(), (NOW.date() - dt.timedelta(days=1)).isoformat()}:
        for it in jload(D("feed", day + ".json"), {"items": []})["items"]:
            t = it.get("ticker")
            if not t or t not in TRACKED or it["id"] in sent:
                continue
            sent.add(it["id"])
            if first or (it.get("ts") or "") < horizon:
                continue
            title = it.get("title", "")
            own = "🔴" if any(c["ticker"] == t for c in COMP) else "👀"
            if INSIDER.search(title):
                side = "🟢 insider KUPUJE" if BUY.search(title) else "🔻 insider SPRZEDAJE" if SELL.search(title) else "👤 transakcja insidera (kupno/sprzedaż – w treści komunikatu)"
                msgs.append(f"{side} · <b>{esc(t)}</b> {esc(it.get('time'))}\n{esc((it.get('company') + ': ') if it.get('company') else '')}{esc(title)}\n{esc(it.get('url'))}")
                continue
            if it.get("kind") == "espi" or KEYWORDS.search(title):
                kind = "ESPI" if it.get("kind") == "espi" else "PAP"
                msgs.append(f"{own} <b>{esc(t)}</b> · {kind} {esc(it.get('time'))}\n{esc((it.get('company') + ': ') if it.get('company') else '')}{esc(it['title'])}\n{esc(it.get('url'))}")

    # 2) raporty PWPA i rekomendacje
    for it in jload(D("pwpa.json"), {"items": []})["items"][:80]:
        key = "pwpa-" + it["file"]
        if it["ticker"] in TRACKED and key not in sent:
            sent.add(key)
            if not first:
                tgt = f", cena docelowa ~{it['targetGuess']:g} zł" if it.get("targetGuess") else ""
                msgs.append(f"📑 <b>{esc(it['ticker'])}</b> · raport GPW PWPA ({esc(it.get('type'))}{tgt})\n{esc(it.get('house'))}\n{esc(it['url'])}")
    recs_all = jload(D("recs.json"), {"items": []})["items"]
    rec_cut = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    for it in recs_all[:150]:
        key = "rec-" + "|".join(str(it.get(k)) for k in ("date", "company", "house", "rating"))
        if it.get("ticker") in TRACKED and key not in sent:
            sent.add(key)
            if not first and it.get("date", "") >= rec_cut:   # stare rekomendacje z uzupełniania historii – bez alertu
                prev = next((p for p in recs_all if p.get("company") == it.get("company") and p.get("house") == it.get("house") and p.get("date", "") < it["date"]), None)
                ch = ""
                if prev:
                    try:
                        d = (float(it["target"]) / float(prev["target"]) - 1) * 100
                        ch = f"\nPoprzednio ({esc(prev['date'])}): {esc(prev['rating'])}, {esc(prev.get('target'))} zł → zmiana ceny docelowej {d:+.1f}%"
                    except Exception:
                        ch = f"\nPoprzednio ({esc(prev['date'])}): {esc(prev['rating'])}, {esc(prev.get('target'))} zł"
                msgs.append(f"🏦 <b>{esc(it['ticker'])}</b> · rekomendacja: {esc(it['rating'])}, cena docelowa {esc(it.get('target'))} zł ({esc(it['house'])}, {esc(it['date'])}){ch}\n{esc(it.get('report') or '')}")

    # 3) zakupy insiderów w USA
    for it in jload(D("insiders_us.json"), {"items": []})["items"][:200]:
        key = "ins-" + it["id"]
        if key in sent:
            continue
        sent.add(key)
        if not first and str(it.get("type", "")).startswith("P"):
            msgs.append(f"🟢 <b>{esc(it['ticker'])}</b> · insider KUPUJE: {esc(it['who'])} ({esc(it['role'])}), {esc(it['qty'])} akcji po {esc(it['price'])}, wartość {esc(it['value'])}\n{esc(it.get('url') or '')}")

    # 4) warunki cenowe z tez (przejście: niespełniony → spełniony)
    prev = jload(D("conditions_prev.json"), {})
    now_state = {}
    for c in jload(D("conditions_status.json"), {"items": []})["items"]:
        k = f"{c.get('ticker')}|{c.get('op')}|{c.get('value')}"
        now_state[k] = c["met"]
        if c["met"] and prev.get(k) is False:
            msgs.append(f"🎯 <b>{esc(c['ticker'])}</b> · warunek z Twojej tezy spełniony: kurs {'≤' if c['op'] == 'below' else '≥'} {c['value']} (teraz {c['price']})")
    jsave(D("conditions_prev.json"), now_state)

    # 5) awaria zbieracza (3 kolejne przebiegi z błędem bossa)
    runs = jload(D("status.json"), {"runs": []}).get("runs", [])[:3]
    if len(runs) == 3 and all(not r.get("sources", {}).get("bossa", {}).get("ok", True) for r in runs) and "alarm-" + NOW.date().isoformat() not in sent:
        sent.add("alarm-" + NOW.date().isoformat())
        msgs.append("⚠️ Zbieracz: 3 przebiegi z rzędu bez danych z bossa.pl. Raporty przejdą na tryb awaryjny.")

    for m in msgs[:15]:
        tg("sendMessage", chat_id=chat, text=m, parse_mode="HTML", disable_web_page_preview="true")
    if len(msgs) > 15:
        tg("sendMessage", chat_id=chat, text=f"… i jeszcze {len(msgs) - 15} powiadomień – szczegóły w panelu.")
    jsave(sent_path, {"ids": sorted(sent)[-30000:]})
    return {"ok": True, "sent": min(len(msgs), 16), "first": first, "commands": cmd_changes}


# ---------------- polecenia z Telegrama (tylko z czatu właściciela) ----------------
HELP = ("Polecenia:\n/dodaj TICKER [nazwa] – śledź spółkę (komunikaty, kursy, wyniki, powiadomienia)\n/usun TICKER – przestań śledzić (spółki z portfela zostają)\n"
        "/warunek TICKER < 8,20 (albo >) – powiadom, gdy kurs przekroczy próg\n/warunki – lista progów, /usunwarunek TICKER\n/lista – śledzone spółki")


def _cfg(name, default):
    return jload(os.path.join(ROOT, "config", name), default)


def _save_cfg(name, obj):
    with open(os.path.join(ROOT, "config", name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _resolve(t, name):
    """Ustal rynek i dane spółki: GPW (archiwum notowań, kalendarz) albo USA (Nasdaq)."""
    gl = jload(D("export", "gpw_last.json"), {}).get("stocks", {})
    cal = jload(D("calendar.json"), {"gpw": []}).get("gpw", [])
    hit = next((e for e in cal if e.get("ticker") == t or e.get("gpwName") == t), None)
    gname = t if t in gl else (hit or {}).get("gpwName")
    if gname and gname in gl:
        e = {"ticker": t, "name": name or (hit or {}).get("name") or gname, "market": "GPW", "ccy": "PLN", "gpw": gname,
             "match": sorted({x for x in [gname, (name or (hit or {}).get("name") or "").upper().replace(" SA", "").replace(" S.A.", "").strip()] if x and len(x) > 2})}
        if (hit or {}).get("isin"):
            e["isin"] = hit["isin"]
        return e, f"GPW · {gname} · kurs {gl[gname][0]} zł" + ("" if e.get("isin") else " (ISIN uzupełnię przy najbliższym kalendarzu raportów)")
    try:
        from collect import get, NASDAQ_H
        info = json.loads(get(f"https://api.nasdaq.com/api/quote/{t}/info?assetclass=stocks", headers=NASDAQ_H)).get("data")
        if info and info.get("primaryData", {}).get("lastSalePrice"):
            return ({"ticker": t, "name": name or info.get("companyName") or t, "market": "USA", "ccy": "USD", "insiders": True,
                     "match": [x for x in {(info.get("companyName") or "").split(" Common")[0].split(",")[0].upper()} if len(x) > 2]},
                    f"USA · {info.get('companyName')} · {info['primaryData']['lastSalePrice']}")
    except Exception:
        pass
    return None, "Nie znalazłem takiej spółki ani w notowaniach GPW (podaj nazwę z notowań, np. COGNOR), ani na Nasdaq/NYSE (ticker, np. AMD)."


def commands(chat):
    st_path = D("telegram.json")
    st = jload(st_path, {})
    upd = tg("getUpdates", offset=st.get("offset", 0), timeout=0).get("result", [])
    changed = []
    for u in upd:
        st["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("chat", {}).get("id") != chat or not m.get("text", "").startswith("/"):
            continue
        parts = m["text"].strip().split()
        cmd, args = parts[0].split("@")[0].lower(), parts[1:]
        own = {c["ticker"] for c in COMP}
        extra = _cfg("extra.json", {"companies": []})
        cond = _cfg("conditions.json", {"items": []})
        reply = HELP
        if cmd == "/dodaj" and args:
            t = args[0].upper()
            if t in own or any(c["ticker"] == t for c in extra["companies"]):
                reply = f"{t} jest już śledzona."
            else:
                e, info = _resolve(t, " ".join(args[1:]) or None)
                if e:
                    extra["companies"].append(e)
                    _save_cfg("extra.json", extra)
                    changed.append(t)
                    reply = f"✅ Dodano {t}: {info}.\nOd następnego przebiegu: komunikaty, kursy, wyniki finansowe, raporty i powiadomienia."
                else:
                    reply = "❌ " + info
        elif cmd == "/usun" and args:
            t = args[0].upper()
            n = len(extra["companies"])
            extra["companies"] = [c for c in extra["companies"] if c["ticker"] != t]
            if len(extra["companies"]) < n:
                _save_cfg("extra.json", extra)
                changed.append("-" + t)
                reply = f"Usunięto {t} ze śledzonych."
            else:
                reply = f"{t} " + ("jest w portfelu – usuń ją w panelu." if t in own else "nie była śledzona.")
        elif cmd == "/warunek" and len(args) >= 3 and args[1] in ("<", ">", "<=", ">="):
            t = args[0].upper()
            try:
                v = float(args[2].replace(",", "."))
                cond["items"].append({"ticker": t, "gpwName": t, "op": "below" if args[1].startswith("<") else "above", "value": v})
                _save_cfg("conditions.json", cond)
                changed.append("warunek " + t)
                reply = f"🎯 Zapisano: powiadomię, gdy kurs {t} {'≤' if args[1].startswith('<') else '≥'} {v}."
            except ValueError:
                reply = "Podaj liczbę, np. /warunek COGNOR < 8,20"
        elif cmd == "/usunwarunek" and args:
            t = args[0].upper()
            cond["items"] = [c for c in cond["items"] if c.get("ticker") != t]
            _save_cfg("conditions.json", cond)
            changed.append("-warunek " + t)
            reply = f"Usunięto progi dla {t}."
        elif cmd == "/warunki":
            reply = "\n".join(f"{c['ticker']} {'≤' if c['op'] == 'below' else '≥'} {c['value']}" for c in cond["items"]) or "Brak progów."
        elif cmd == "/lista":
            reply = "Portfel: " + ", ".join(sorted(own)) + "\nObserwowane: " + (", ".join(c["ticker"] for c in extra["companies"]) or "brak")
        tg("sendMessage", chat_id=chat, text=reply)
    jsave(st_path, st)
    return changed
