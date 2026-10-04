---
license: cc-by-4.0
language:
- en
pretty_name: UK Weight Loss Medicine Prices (MedEazy)
tags:
- healthcare
- pharmacy
- prices
- uk
- mounjaro
- tirzepatide
- wegovy
- semaglutide
- orlistat
- glp-1
size_categories:
- 1K<n<10K
configs:
- config_name: latest
  data_files: medeazy-prices-latest.csv
- config_name: history
  data_files: medeazy-prices-history.csv
- config_name: monthly_index
  data_files: medeazy-monthly-index.csv
---

# UK Weight Loss Medicine Prices (MedEazy)

Private prices for prescription weight loss medicines at UK online pharmacies,
collected by [MedEazy](https://medeazy.co.uk), an independent UK price comparison
service. Every pharmacy is checked against the General Pharmaceutical Council
(GPhC) register before it is listed.

Covers Mounjaro (tirzepatide), Wegovy injection and Wegovy pill (semaglutide)
and Orlistat (including Xenical and Alli), by dose, across 70+ pharmacies.
Tracking began on 4 October 2026 and the files update automatically every hour.

- **Always-current copy:** https://data.medeazy.co.uk
- **Methodology and live figures:** https://medeazy.co.uk/pages/data
- **Source code for the tracker:** https://github.com/MedEazy2026/medeazy-price-data

## Files

| File | What it holds |
|---|---|
| `medeazy-prices-latest.csv` | Every current price by pharmacy, treatment and dose, with the date it took effect |
| `medeazy-prices-history.csv` | Every price change, new listing and removal since tracking began, timestamped |
| `medeazy-monthly-index.csv` | Lowest, median and highest price per product and dose, by month |

### `medeazy-prices-latest.csv`

| Column | Meaning |
|---|---|
| treatment | Mounjaro, Wegovy injection, Wegovy pill, Orlistat |
| active_ingredient | e.g. tirzepatide, semaglutide |
| form | weekly injection, daily tablet, capsule |
| product | Product name (e.g. Xenical 120mg for Orlistat) |
| dose | e.g. 2.5mg |
| pharmacy | Pharmacy name as listed on MedEazy |
| gphc_number | GPhC registration number |
| pharmacy_website | Pharmacy website domain |
| price_gbp | Monthly price in GBP |
| price_since | Date this price was first seen |
| discount_code | Discount code offered, if any |
| discount_detail | What the code gives |

### `medeazy-prices-history.csv`

One row per event: `listed`, `price_change` or `removed`, with old and new price,
change in GBP and percent, and the UTC time it was detected.

### `medeazy-monthly-index.csv`

Per month, product and dose: number of pharmacies, lowest, median and highest
price, the gap between lowest and highest, and days tracked. `complete_month`
is `no` for the month in progress.

## What a price means

The private price for a monthly supply of each dose, as shown on MedEazy.
Where a pharmacy offers a discount code, the price is the price after that code,
and the code is listed alongside it. Prices usually include consultation,
prescription and standard delivery; some pharmacies add fees. Always check the
pharmacy's own site before ordering.

## Licence and credit

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You may reuse the data,
including commercially, as long as you credit:

> Source: MedEazy (medeazy.co.uk/data)

Online, please link the credit to https://medeazy.co.uk/pages/data.

## Limitations

- Covers pharmacies listed on MedEazy only, not every UK pharmacy.
- Prices are advertised prices; a pharmacy may charge differently at checkout.
- This is price information only. It is not medical advice, and these are
  prescription-only medicines (except Alli 60mg) that need a clinical assessment.
