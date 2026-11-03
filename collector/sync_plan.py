"""Plan synchronizacji data/export -> baza panelu (dla zadań Claude).

Krok 1:  python3 collector/sync_plan.py STAN.json
         STAN.json = plik z `ArtifactData get meta/sync` (out_dir). Brak pliku = pierwsza synchronizacja.
         Wypisuje JSON {"check": [...]} – dokumenty, dla których trzeba poznać wersję
         (ArtifactData get z out_dir; wersja jest w odpowiedzi).
Krok 2:  python3 collector/sync_plan.py STAN.json --final [kolekcja/id=wersja ...] [--missing kolekcja/id ...]
         Tworzy /tmp/dziennik-sync/batch_N.json (gotowe listy `writes` dla ArtifactData batch)
         i wypisuje ich treść. Ostatni wpis ostatniej paczki zapisuje meta/sync.
"""
import datetime as dt, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "data", "export")
OUT = "/tmp/dziennik-sync"
COLL = {"prices": "prices", "feed": "feed", "holders": "holders", "recs": "recs", "recsall": "recsall", "events": "events"}
MERGE = {"feed", "holders", "recs"}          # pola 'auto' dopisywane przez update, własne pozycje zadań zostają


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def docs():
    m = load(os.path.join(EXP, "manifest.json"), {})
    out = {}
    for kind, coll in COLL.items():
        for k, h in (m.get(kind) or {}).items():
            out[f"{coll}/{k}"] = (h, os.path.join(EXP, kind, k + ".json"))
    if m.get("gpw_last"):
        out["meta/gpwlast"] = (m["gpw_last"], os.path.join(EXP, "gpw_last.json"))
    return out


def plan(state):
    old = state.get("hashes", {})
    recent = (dt.date.today() - dt.timedelta(days=6)).isoformat()
    changed, check = [], []
    for key, (h, path) in sorted(docs().items()):
        if old.get(key) == h:
            continue
        coll, did = key.split("/", 1)
        changed.append(key)
        # wersję trzeba znać, gdy dokument może już istnieć
        if key in old or coll in MERGE or coll == "events" or key.startswith("meta/") or (coll == "prices" and did >= recent):
            check.append(key)
    return changed, check


def main():
    state_path = sys.argv[1]
    state = load(state_path, {})
    changed, check = plan(state)
    if "--final" not in sys.argv:
        pc = sorted(k.split("/", 1)[1] for k in check if k.startswith("prices/"))
        other = [k for k in check if not k.startswith("prices/")] + (["meta/sync"] if state else [])
        print(json.dumps({"changed": len(changed), "check": other, "pricesCheck": len(pc), "pricesFrom": pc[0] if pc else None,
                          "hint": "Wersje prices: JEDNO ArtifactData query collection prices, query {where:[[\"date\",\">=\",pricesFrom]], limit:1000}, out_dir /tmp/db – lista pokazuje wersje. Dokumentów spoza listy użyj jako --missing."}, ensure_ascii=False))
        return
    args = sys.argv[sys.argv.index("--final") + 1:]
    versions, missing, mode = {}, set(), "v"
    for a in args:
        if a == "--missing":
            mode = "m"
            continue
        if mode == "v" and "=" in a:
            k, v = a.rsplit("=", 1)
            versions[k] = int(v)
        elif mode == "m":
            missing.add(a)
    allk = docs()
    writes = []
    for key in changed:
        coll, did = key.split("/", 1)
        h, path = allk[key]
        w = {"collection": coll, "doc_id": did, "file_path": path}
        if key in versions:
            w["op"] = "update" if coll in MERGE else "set"
            w["if_version"] = versions[key]
        elif key in missing or key not in check:
            w["op"] = "set"
        else:
            sys.exit(f"Brak wersji dla {key}: podaj {key}=WERSJA albo --missing {key}")
        writes.append(w)
    new_state = {"hashes": {**state.get("hashes", {}), **{k: allk[k][0] for k in changed}}, "syncedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    os.makedirs(OUT, exist_ok=True)
    sp = os.path.join(OUT, "meta_sync.json")
    json.dump(new_state, open(sp, "w"))
    sw = {"op": "set", "collection": "meta", "doc_id": "sync", "file_path": sp}
    if "meta/sync" in versions:
        sw["if_version"] = versions["meta/sync"]
    batches, cur, size = [], [], 0
    for w in writes:
        s = os.path.getsize(w["file_path"])
        if cur and (len(cur) >= 40 or size + s > 700_000):
            batches.append(cur)
            cur, size = [], 0
        cur.append(w)
        size += s
    cur.append(sw)
    batches.append(cur)
    for f in os.listdir(OUT):
        if f.startswith("batch_"):
            os.remove(os.path.join(OUT, f))
    for i, b in enumerate(batches, 1):
        p = os.path.join(OUT, f"batch_{i}.json")
        json.dump(b, open(p, "w"), ensure_ascii=False)
        print(f"### {p} ({len(b)} zapisów)")
        print(json.dumps(b, ensure_ascii=False))


if __name__ == "__main__":
    main()
