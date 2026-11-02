"""Sonda: pobiera surowe próbki źródeł, żeby dopasować parsery. Wynik w debug/."""
import os, time, json, urllib.request, urllib.error, ssl
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEC_UA = "DziennikPortfela/1.0 (github.com/lonelywerewolf)"
os.makedirs("debug", exist_ok=True)
T = int(time.time())
SRC = {
 "gpw_komunikaty.html": "https://www.gpw.pl/komunikaty",
 "bossa_komunikaty.html": "https://bossa.pl/analizy/komunikaty",
 "bossa_komunikaty_p1.html": "https://bossa.pl/analizy/komunikaty?page=%2C%2C%2C1",
 "strefa_wiadomosci.html": "https://strefainwestorow.pl/wiadomosci",
 "strefa_wiadomosci_p1.html": "https://strefainwestorow.pl/wiadomosci?page=1",
 "strefa_rekomendacje.html": "https://strefainwestorow.pl/rekomendacje",
 "stooq_xtb.csv": "https://stooq.pl/q/d/l/?s=xtb&i=d",
 "stooq_nvda.csv": "https://stooq.pl/q/d/l/?s=nvda.us&i=d",
 "stooq_wig.csv": "https://stooq.pl/q/d/l/?s=wig&i=d",
 "stooq_ndq.csv": "https://stooq.pl/q/d/l/?s=^ndq&i=d",
 "nbp_usd.json": "https://api.nbp.pl/api/exchangerates/rates/a/usd/last/5/?format=json",
 "sec_nvda_form4.xml": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=NVDA&type=4&dateb=&owner=include&count=40&output=atom",
 "biznesradar_espi_p2.html": "https://www.biznesradar.pl/temat/76,espi-ebi,2",
}
report = {}
for name, url in SRC.items():
    ua = SEC_UA if "sec.gov" in url else UA
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "pl,en;q=0.8"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            report[name] = {"url": url, "status": r.status, "bytes": len(body), "sec": round(time.time()-t0, 1)}
            open(os.path.join("debug", name), "wb").write(body)
    except urllib.error.HTTPError as e:
        report[name] = {"url": url, "status": e.code, "error": str(e)}
    except Exception as e:
        report[name] = {"url": url, "error": repr(e)}
json.dump(report, open("debug/_report.json", "w"), indent=1)
print(json.dumps(report, indent=1))
