import os, json, time, urllib.request, urllib.error
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
os.makedirs("debug", exist_ok=True)
SRC = {
 "gpw_arch_akcje.html": "https://www.gpw.pl/archiwum-notowan?fetch=0&type=10&instrument=&date=30-10-2026&show_x=Poka%C5%BC+wyniki",
 "gpw_arch_indeksy.html": "https://www.gpw.pl/archiwum-notowan?fetch=0&type=1&instrument=&date=30-10-2026&show_x=Poka%C5%BC+wyniki",
 "gpw_arch_xls.xls": "https://www.gpw.pl/archiwum-notowan?fetch=1&type=10&instrument=&date=30-10-2026",
 "nasdaq_nvda_hist.json": "https://api.nasdaq.com/api/quote/NVDA/historical?assetclass=stocks&fromdate=2026-10-01&todate=2026-11-02&limit=50",
 "nasdaq_comp_hist.json": "https://api.nasdaq.com/api/quote/COMP/historical?assetclass=index&fromdate=2026-10-01&todate=2026-11-02&limit=50",
 "nasdaq_nvda_info.json": "https://api.nasdaq.com/api/quote/NVDA/info?assetclass=stocks",
 "openinsider_nvda.html": "http://openinsider.com/screener?s=NVDA&fd=365&cnt=100",
}
rep = {}
for n, u in SRC.items():
    h = {"User-Agent": UA, "Accept": "application/json, text/html, */*", "Accept-Language": "pl,en;q=0.8"}
    if "nasdaq" in u: h.update({"Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=30) as r:
            b = r.read(); open("debug/" + n, "wb").write(b); rep[n] = {"status": r.status, "bytes": len(b)}
    except urllib.error.HTTPError as e: rep[n] = {"status": e.code}
    except Exception as e: rep[n] = {"error": repr(e)[:200]}
    time.sleep(1)
json.dump(rep, open("debug/_report2.json", "w"), indent=1); print(rep)
