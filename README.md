# dziennik-dane

Automatic market-data collector for the **Dziennik Portfela** panel. It runs on GitHub Actions every 15 minutes on weekdays (about 6:00–22:45 Polish time) and once a day at weekends. It uses no AI: it simply downloads public pages.

## Sources
| What | Source |
|---|---|
| ESPI/EBI filings and PAP dispatches (full pagination) | bossa.pl/analizy/komunikaty |
| PAP news with exact times, "Skrót wiadomości" | strefainwestorow.pl/wiadomosci |
| Broker recommendations (target prices, PDF reports) | strefainwestorow.pl/rekomendacje |
| Latest ESPI (cross-check) | gpw.pl/komunikaty |
| Closes, change, turnover of every GPW stock + indices (WIG, WIG20, mWIG40, sWIG80, sector indices) | official GPW quotes archive |
| US prices: history and live | Nasdaq API |
| Insider transactions in the US (SEC Form 4) | openinsider.com |
| USD/PLN, EUR/PLN rates (table A) | api.nbp.pl |

## Files
- `config/watchlist.json` – tracked companies and indices; `config/conditions.json` – price conditions
- `data/feed/YYYY-MM-DD.json`, `data/quotes.json`, `data/history/*.csv`, `data/gpw/*.json`, `data/fx.json`, `data/recs.json`, `data/insiders_us.json`
- `data/status.json` – log of every run (what was fetched, coverage, errors)
- `data/export/` – files already in the panel format; scheduled tasks copy to the panel only what changed (`manifest.json`)
