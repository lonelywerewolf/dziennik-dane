import os, json, time, urllib.request, urllib.error
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
os.makedirs("debug", exist_ok=True)
NQ = {"Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/", "Accept": "application/json"}
SRC = {
 "strefa_spolki.html": ("https://strefainwestorow.pl/notowania/spolki", {}),
 "strefa_snt_wyniki.html": ("https://strefainwestorow.pl/notowania/spolki/PLSNKTK00019/wyniki-finansowe", {}),
 "strefa_snt_kwartalne.html": ("https://strefainwestorow.pl/notowania/spolki/PLSNKTK00019/wyniki-finansowe?okres=kwartalne", {}),
 "strefa_kalendarz.html": ("https://strefainwestorow.pl/dane/raporty/lista-publikacji-raportow-okresowych", {}),
 "strefa_dywidendy.html": ("https://strefainwestorow.pl/dane/dywidendy", {}),
 "nasdaq_fin_nvda.json": ("https://api.nasdaq.com/api/company/NVDA/financials?frequency=2", NQ),
 "nasdaq_earn_date_nvda.json": ("https://api.nasdaq.com/api/analyst/NVDA/earnings-date", NQ),
 "nasdaq_earn_cal.json": ("https://api.nasdaq.com/api/calendar/earnings?date=2026-11-19", NQ),
 "gpw_pwpa.html": ("https://www.gpw.pl/gpwpa", {}),
 "gpw_pwpa_raporty.html": ("https://www.gpw.pl/raporty-analityczne", {}),
 "knf_short.html": ("https://www.knf.gov.pl/dla_rynku/Rejestry_i_Ewidencje/Krotka_sprzedaz", {}),
 "eurostat_hicp_pl.json": ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr?geo=PL&coicop=CP00&lastTimePeriod=6", {}),
 "fred_cpi.csv": ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", {}),
 "fred_pl10y.csv": ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=IRLTLT01PLM156N", {}),
 "nbp_stopy.html": ("https://nbp.pl/polityka-pieniezna/decyzje-rpp/podstawowe-stopy-procentowe-nbp/", {}),
}
rep = {}
for n, (u, extra) in SRC.items():
    h = {"User-Agent": UA, "Accept": "text/html,application/json,*/*", "Accept-Language": "pl,en;q=0.8"}; h.update(extra)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=30) as r:
            b = r.read(); open("debug/" + n, "wb").write(b); rep[n] = {"status": r.status, "bytes": len(b), "url": r.geturl()}
    except urllib.error.HTTPError as e: rep[n] = {"status": e.code}
    except Exception as e: rep[n] = {"error": repr(e)[:150]}
    time.sleep(1)
json.dump(rep, open("debug/_report3.json", "w"), indent=1); print(json.dumps(rep, indent=1))
