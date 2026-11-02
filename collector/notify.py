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
           text="✅ <b>Dziennik Portfela</b>: powiadomienia działają.\nBędę pisać tylko w ważnych sprawach: komunikaty ESPI Twoich i obserwowanych spółek, istotne wiadomości (wyniki, emisje, wezwania, dywidendy, rekomendacje), nowe raporty analityczne, spełnione warunki z Twoich tez i zakupy akcji przez insiderów w USA.")
    chat = st["chat_id"]
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
            if it.get("kind") == "espi" or KEYWORDS.search(it.get("title", "")):
                own = "🔴" if any(c["ticker"] == t for c in COMP) else "👀"
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
    for it in jload(D("recs.json"), {"items": []})["items"][:100]:
        key = "rec-" + "|".join(str(it.get(k)) for k in ("date", "company", "house", "rating"))
        if it.get("ticker") in TRACKED and key not in sent:
            sent.add(key)
            if not first:
                msgs.append(f"🏦 <b>{esc(it['ticker'])}</b> · rekomendacja: {esc(it['rating'])}, cena docelowa {esc(it.get('target'))} zł ({esc(it['house'])}, {esc(it['date'])})\n{esc(it.get('report') or '')}")

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
    return {"ok": True, "sent": min(len(msgs), 16), "first": first}
