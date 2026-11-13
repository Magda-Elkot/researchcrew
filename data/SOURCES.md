# Sample data sources

Born-digital PDFs indexed by docs-mcp (`uv run ingest data/pdfs`). Topics: DECISIONS #27.
The `doc_id` is the file name without `.pdf`.

| doc_id | Topic | Lang | Pages | Publisher / title | Source URL | Licence |
|---|---|---|---|---|---|---|
| `who-emro-annual-report-2024-2025-en` | Public health | en | 96 | WHO EMRO, *The work of WHO in the Eastern Mediterranean Region: Annual report of the Regional Director 2024/2025* (EM/RC72/2) | https://applications.emro.who.int/docs/9789292747329-eng.pdf | CC BY-NC-SA 3.0 IGO |
| `who-emro-annual-report-2024-2025-ar` | Public health | ar | 96 | WHO EMRO, same report in Arabic (أعمال منظمة الصحة العالمية في إقليم شرق المتوسط: التقرير السنوي للمديرة الإقليمية 2024/2025) | https://applications.emro.who.int/docs/9789292747343-ara.pdf | CC BY-NC-SA 3.0 IGO |
| `irena-renewable-energy-arab-region-2016-en` | Renewable energy | en | 24 | IRENA and League of Arab States, *Renewable Energy in the Arab Region: Overview of developments* (2016) | https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2016/IRENA_Arab_Region_Overview_2016.pdf | IRENA: free use with attribution |
| `irena-renewable-energy-markets-gcc-2023-en` | Renewable energy | en | 152 | IRENA, *Renewable energy markets: GCC 2023* | https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2023/Dec/IRENA_Rnewable_energy_markets_GCC_2023.pdf | IRENA: free use with attribution |
| `unesco-ethics-of-ai-recommendation-flyer-en` | AI ethics | en | 2 | UNESCO, flyer on the *Recommendation on the Ethics of Artificial Intelligence* | https://www.unesco.nl/sites/default/files/inline-files/Rec%20on%20Ethics%20of%20AI%20-%20Flyer%20-%20UNESCO%20HQ.pdf | **No licence stated in the file.** Kept locally, not committed (`.gitignore`) until confirmed; the shareable demo container removes it at startup (`DEMO_EXCLUDE_DOC_IDS`). |

Attribution: © World Health Organization 2025; © IRENA 2016, 2023; © UNESCO. Text is used unmodified
apart from extraction and normalisation (NFKC, Arabic lam-alef fix) for search.

## Checked and rejected

| File | Why |
|---|---|
| WHO EMRO *Regional health overview 2019* (Arabic, https://applications.emro.who.int/docs/9789292740542-ara.pdf) | Broken font mapping: Arabic letter pairs come out swapped ("يف" 2207× vs "في" 2×, "عىل", "بني"). Rejected automatically by `extract.py` (`swapped_pairs_suspected`). |

## Still to add (manual download needed)

These sites block scripted downloads, so they need a browser download into `data/pdfs/`,
followed by `uv run ingest data/pdfs` again (re-ingest is idempotent):

| Suggested file name | What | Where |
|---|---|---|
| `unesco-ethics-of-ai-recommendation-en.pdf` | UNESCO Recommendation on the Ethics of AI (full text, 2021/2022), CC BY-SA 3.0 IGO | https://unesdoc.unesco.org/ark:/48223/pf0000381137 |
| `unesco-ethics-of-ai-recommendation-ar.pdf` | Same, Arabic edition | https://unesdoc.unesco.org/ark:/48223/pf0000381137_ara |
| an Arabic renewable-energy report, e.g. ESCWA | Arabic coverage for the energy topic | https://digitallibrary.un.org (ESCWA energy reports, `-AR.pdf`) |

Run `uv run python -c "from pathlib import Path; from mcp_servers.docs_mcp.extract import extract_pdf; d = extract_pdf(Path('data/pdfs/<file>.pdf')); print(d.language, d.arabic, d.lam_alef_fixes)"`
on any new Arabic PDF first (SPEC: check ≥ 2 Arabic PDFs for broken letters).
