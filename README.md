# MedEazy price data

Keeps a permanent record of every price change on medeazy.co.uk and publishes
three CSV files, updated automatically.

**Your day-to-day doesn't change.** Keep editing `assets/pricing-*.json` in the
theme code as normal. Every hour this checks your live theme, records anything
that changed, and republishes the files.

| File | What it holds |
|---|---|
| `medeazy-prices-latest.csv` | Every current price, with the date it took effect |
| `medeazy-prices-history.csv` | Every price change, new listing and removal since tracking began |
| `medeazy-monthly-index.csv` | Lowest, median and highest price per product and dose, by month |
| `summary.json` | Headline numbers the /data page can display |

Once set up, they live at `https://data.medeazy.co.uk/<file name>`.

---

## How it's connected

| Piece | Where |
|---|---|
| Shopify access | Dev Dashboard app **MedEazy price tracker** (scope `read_themes` only), installed on `d3edyn-tk.myshopify.com` |
| Secrets | This repo → **Settings → Secrets and variables → Actions**: `SHOPIFY_STORE`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` |
| Hosting | GitHub Pages from `main` / `docs`, custom domain `data.medeazy.co.uk` |
| DNS | GoDaddy: CNAME `data` → `medeazy2026.github.io` |

If the Shopify client secret is ever rotated in the Dev Dashboard, update the
`SHOPIFY_CLIENT_SECRET` secret here to match.

To run a check by hand: **Actions → Update price data → Run workflow**. The
very first run is the baseline: every current price is recorded as "listed".

---

## What happens automatically

- **Every hour** your live theme's pricing files are read and compared with
  the last check. Changes are added to `data/ledger.csv`, the permanent
  record, and all published files are rebuilt from it.
- **New treatments are picked up on their own.** Add
  `assets/pricing-foundayo.json` in the same format and it appears in the data.
  So do new doses or new pharmacies added to a file.
- **Theme copies don't matter.** It always reads whichever theme is published.

## Safety nets for hand edits

- **Broken file** (e.g. a missing comma): the run stops and records nothing.
  GitHub emails you that the run failed. Fix the file; the next hourly run
  carries on.
- **Lots of prices vanish at once** (over 30% of a file): treated as an
  accident, so the run stops. If you really did remove them, go to **Actions →
  Update price data → Run workflow** and tick *allow big change*.
- **A price jumps or drops more than 40%** (e.g. 2999 typed for 299): held for
  3 hours instead of published. Fixed within that time, it never appears in
  the public history. Still there after 3 hours, it is recorded with the time
  it first appeared. Held prices are listed on the run's summary page.

Pharmacy names that differ only in capitals or spacing ("Medicine Market place"
and "Medicine Market Place") are treated as the same pharmacy.

## Settings you might change

At the top of `scripts/update_prices.py`:

- `MAX_DROP_SHARE = 0.30`: how big a sudden loss of listings stops a run
- `BIG_MOVE_PCT = 40` and `HOLD_HOURS = 3`: the typo hold
- `TREATMENTS`: display names, active ingredients and forms per pricing file

The schedule is the `cron` line in `.github/workflows/update-prices.yml`.
GitHub may start scheduled runs a few minutes late at busy times.

## Testing without Shopify

    python scripts/update_prices.py --from-dir path/to/folder/with/pricing-files

Python 3.10+ only; no extra packages needed.
