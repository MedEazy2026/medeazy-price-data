#!/usr/bin/env python3
"""
MedEazy price tracker.

Reads the pricing JSON files (assets/pricing-*.json) from the LIVE Shopify
theme, compares them with the last check, appends every change to a
permanent ledger (data/ledger.csv), and rebuilds the public files in docs/:

  docs/medeazy-prices-latest.csv    today's price for every listing
  docs/medeazy-prices-history.csv   every price change since tracking began
  docs/medeazy-monthly-index.csv    lowest / median / highest per product & dose, by month
  docs/summary.json                 headline numbers for the /data page

The ledger is the single source of truth: every other file is rebuilt from
it on each run, so nothing else needs backing up.

Usage
  python scripts/update_prices.py                 # fetch from Shopify (needs env vars, see README)
  python scripts/update_prices.py --from-dir DIR  # use local pricing-*.json files instead (testing)

Standard library only - no pip installs needed.
"""

import argparse
import csv
import glob
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
LEDGER = os.path.join(DATA, "ledger.csv")
STATE = os.path.join(DATA, "current.json")
PENDING = os.path.join(DATA, "pending.json")

API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-07")

# Fields in the pricing files that are NOT prices. Every other field is
# treated as a price column, so a new dose added to a file is picked up
# automatically.
META_FIELDS = {
    "Pharmacy", "url", "GPHC", "GPHCLink", "TrustPilot", "TPlink",
    "DiscountType", "Discount", "DiscountTooltip",
}

# Nice names per pricing file. A new file (e.g. pricing-foundayo.json) is
# picked up automatically; add a line here to give it proper labels.
TREATMENTS = {
    "mounjaro":    {"treatment": "Mounjaro",        "ingredient": "tirzepatide",       "form": "weekly injection"},
    "wegovy":      {"treatment": "Wegovy injection", "ingredient": "semaglutide",       "form": "weekly injection"},
    "wegovy-pill": {"treatment": "Wegovy pill",     "ingredient": "oral semaglutide",  "form": "daily tablet"},
    "orlistat":    {"treatment": "Orlistat",        "ingredient": "orlistat",          "form": "capsule"},
    "foundayo":    {"treatment": "Foundayo",        "ingredient": "orforglipron",      "form": "daily tablet"},
    "saxenda":     {"treatment": "Saxenda",         "ingredient": "liraglutide",       "form": "daily injection"},
}

# Safety net for hand edits: if a file suddenly loses more than this share
# of its listings, assume a mistake and stop rather than log mass removals.
MAX_DROP_SHARE = 0.30

# Price moves bigger than this (%) look like typos, so they are held back and
# only recorded if they are still on the site HOLD_HOURS later.
BIG_MOVE_PCT = 40
HOLD_HOURS = 3

LEDGER_COLS = [
    "detected_at_utc", "date_uk", "event", "treatment", "product", "dose",
    "pharmacy", "gphc_number", "old_price_gbp", "new_price_gbp",
    "change_gbp", "change_pct", "discount_code",
]


# --------------------------------------------------------------- fetching

def http_json(url, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        sys.exit(f"Shopify request failed ({e.code}): {body}")


def shopify_token(store):
    """A fixed Admin API token, or one minted from a Dev Dashboard app's
    client ID and secret (client credentials grant)."""
    token = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if token:
        return token
    cid = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not (cid and secret):
        sys.exit("Set SHOPIFY_ADMIN_TOKEN, or SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET.")
    res = http_json(
        f"https://{store}/admin/oauth/access_token",
        {"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"},
    )
    if "access_token" not in res:
        sys.exit(f"Could not get a Shopify token: {res}")
    return res["access_token"]


def fetch_from_shopify():
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store:
        sys.exit("Set SHOPIFY_STORE, e.g. your-store.myshopify.com")
    store = store.replace("https://", "").strip("/")
    token = shopify_token(store)
    query = """
    query {
      themes(first: 1, roles: [MAIN]) {
        nodes {
          name
          files(first: 50, filenames: ["assets/pricing-*.json"]) {
            nodes { filename body { ... on OnlineStoreThemeFileBodyText { content } } }
          }
        }
      }
    }"""
    res = http_json(
        f"https://{store}/admin/api/{API_VERSION}/graphql.json",
        {"query": query},
        {"X-Shopify-Access-Token": token},
    )
    if res.get("errors"):
        sys.exit(f"Shopify returned errors: {res['errors']}")
    themes = res["data"]["themes"]["nodes"]
    if not themes:
        sys.exit("No published theme found.")
    print(f"Reading live theme: {themes[0]['name']}")
    files = {}
    for node in themes[0]["files"]["nodes"]:
        name = os.path.basename(node["filename"])
        files[name] = (node.get("body") or {}).get("content", "")
    return files


def fetch_from_dir(path):
    files = {}
    for f in sorted(glob.glob(os.path.join(path, "pricing-*.json"))):
        with open(f, encoding="utf-8") as fh:
            files[os.path.basename(f)] = fh.read()
    return files


# ----------------------------------------------------------- normalising

def to_price(v):
    s = str(v).strip().replace("£", "").replace(",", "")
    if not s or s == "-":
        return None
    try:
        p = round(float(s), 2)
    except ValueError:
        return None
    return p if p > 0 else None


def split_variant(slug, key):
    """'10mg' -> ('Mounjaro', '10mg'); '2_5mg' -> '2.5mg';
    'Xenical120mg' -> product 'Xenical', dose '120mg'."""
    m = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*(\d[\d_.]*\s*(?:mg|mcg|g|ml)?.*)$", key)
    if m:
        product, dose = m.group(1).strip(), m.group(2)
    else:
        product, dose = None, key
    dose = re.sub(r"(?<=\d)_(?=\d)", ".", dose).replace("_", " ").strip()
    return product, dose


def clean_site(row):
    """Pharmacy's own domain, without affiliate links or tracking."""
    for field in ("TPlink", "url"):
        u = (row.get(field) or "").strip()
        if not u:
            continue
        p = urllib.parse.urlparse(u if "//" in u else "https://" + u)
        host = p.netloc.lower()
        if field == "TPlink":
            m = re.search(r"/review/(?:www\.)?([^/?#]+)", p.path)
            if m:
                return m.group(1).lower()
            continue
        if "awin1.com" in host:
            q = urllib.parse.parse_qs(p.query).get("ued")
            if q:
                host = urllib.parse.urlparse(q[0]).netloc.lower()
            else:
                continue
        if host.endswith(".myshopify.com"):
            continue
        return host.removeprefix("www.")
    return ""


def name_key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def canonical_names(files):
    """'Medicine Market place' and 'Medicine Market Place' are one pharmacy:
    use whichever spelling appears most often across all files."""
    seen = defaultdict(lambda: defaultdict(int))
    for content in files.values():
        try:
            for row in json.loads(content):
                n = str(row.get("Pharmacy", "")).strip()
                if n:
                    seen[name_key(n)][n] += 1
        except Exception:
            pass
    return {k: max(v.items(), key=lambda kv: (kv[1], kv[0]))[0] for k, v in seen.items()}


def parse_files(files):
    """Returns {key: listing} plus per-file listing counts.
    key = slug|pharmacy|price column (stable while you edit prices)."""
    listings, counts, problems = {}, {}, []
    canon = canonical_names(files)
    for fname, content in files.items():
        slug = fname.removeprefix("pricing-").removesuffix(".json")
        info = TREATMENTS.get(slug, {
            "treatment": slug.replace("-", " ").title(), "ingredient": "", "form": ""})
        try:
            rows = json.loads(content)
            assert isinstance(rows, list)
        except Exception as e:  # broken JSON from a hand edit
            problems.append(f"{fname} could not be read ({e})")
            continue
        n = 0
        for row in rows:
            pharmacy = str(row.get("Pharmacy", "")).strip()
            if not pharmacy:
                continue
            pharmacy = canon.get(name_key(pharmacy), pharmacy)
            code = str(row.get("Discount", "")).strip()
            code = "" if code in ("-", "") else code
            for col, val in row.items():
                if col in META_FIELDS:
                    continue
                price = to_price(val)
                if price is None:
                    continue
                product, dose = split_variant(slug, col)
                listings[f"{slug}|{pharmacy}|{col}"] = {
                    "treatment": info["treatment"],
                    "active_ingredient": info["ingredient"],
                    "form": info["form"],
                    "product": product or info["treatment"],
                    "dose": dose,
                    "pharmacy": pharmacy,
                    "gphc_number": str(row.get("GPHC", "")).strip(),
                    "pharmacy_website": clean_site(row),
                    "price_gbp": price,
                    "discount_code": code,
                    "discount_detail": str(row.get("DiscountTooltip", "")).strip(),
                }
                n += 1
        counts[slug] = n
    return listings, counts, problems


# --------------------------------------------------------------- ledger

def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append_ledger(events):
    new = not os.path.exists(LEDGER)
    os.makedirs(DATA, exist_ok=True)
    with open(LEDGER, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS)
        if new:
            w.writeheader()
        w.writerows(events)


def money(x):
    return "" if x is None else f"{x:.2f}"


def diff(prev, cur, now_utc):
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    day = now_utc.astimezone(UK).date().isoformat()
    events = []
    for key in sorted(set(prev) | set(cur)):
        a, b = prev.get(key), cur.get(key)
        old = a["price_gbp"] if a else None
        newp = b["price_gbp"] if b else None
        if a and b and old == newp:
            continue
        ref = b or a
        if a is None:
            event = "listed"
        elif b is None:
            event = "removed"
        else:
            event = "price_change"
        change = (newp - old) if (old is not None and newp is not None) else None
        events.append({
            "detected_at_utc": stamp, "date_uk": day, "event": event,
            "treatment": ref["treatment"], "product": ref["product"], "dose": ref["dose"],
            "pharmacy": ref["pharmacy"], "gphc_number": ref["gphc_number"],
            "old_price_gbp": money(old), "new_price_gbp": money(newp),
            "change_gbp": money(change),
            "change_pct": f"{change / old * 100:.1f}" if change is not None and old else "",
            "discount_code": ref.get("discount_code", ""),
            "_key": key,
        })
    return events


# --------------------------------------------------------------- outputs

def write_csv(path, cols, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def ledger_key(e):
    return f"{e['treatment']}|{e['product']}|{e['dose']}|{e['pharmacy']}"


def price_since(ledger):
    """Date each listing's current price started."""
    since = {}
    for e in ledger:
        since[ledger_key(e)] = e["date_uk"]
    return since


def monthly_index(ledger, today):
    """Replays the ledger day by day. For each month and product/dose:
    month-end lowest, median and highest, plus the average daily median."""
    if not ledger:
        return []
    by_day = defaultdict(list)
    for e in ledger:
        by_day[e["date_uk"]].append(e)
    start = date.fromisoformat(min(by_day))
    state, daily = {}, defaultdict(lambda: defaultdict(list))
    d = start
    while d <= today:
        for e in by_day.get(d.isoformat(), []):
            k = ledger_key(e)
            if e["event"] == "removed":
                state.pop(k, None)
            else:
                state[k] = (e, float(e["new_price_gbp"]))
        month = d.strftime("%Y-%m")
        groups = defaultdict(list)
        for e, p in state.values():
            groups[(e["treatment"], e["product"], e["dose"])].append(p)
        for g, prices in groups.items():
            daily[month][g].append(sorted(prices))
        d += timedelta(days=1)

    def dose_num(dose):
        m = re.match(r"[\d.]+", dose)
        return float(m.group()) if m else 0

    rows = []
    for month in sorted(daily):
        for g in sorted(daily[month], key=lambda g: (g[0], g[1], dose_num(g[2]))):
            days = daily[month][g]
            last = days[-1]
            rows.append({
                "month": month,
                "complete_month": "no" if month == today.strftime("%Y-%m") else "yes",
                "treatment": g[0], "product": g[1], "dose": g[2],
                "pharmacies_listed": len(last),
                "lowest_price_gbp": money(last[0]),
                "median_price_gbp": money(statistics.median(last)),
                "highest_price_gbp": money(last[-1]),
                "price_gap_gbp": money(last[-1] - last[0]),
                "avg_daily_median_gbp": money(statistics.mean(statistics.median(x) for x in days)),
                "days_tracked": len(days),
            })
    return rows


def build_outputs(listings, ledger, now_utc):
    os.makedirs(DOCS, exist_ok=True)
    today = now_utc.astimezone(UK).date()
    since = price_since(ledger)

    def dose_num(dose):
        m = re.match(r"[\d.]+", dose)
        return float(m.group()) if m else 0

    latest = []
    for l in sorted(listings.values(),
                    key=lambda l: (l["treatment"], l["product"], dose_num(l["dose"]), l["price_gbp"], l["pharmacy"])):
        row = dict(l)
        row["price_gbp"] = money(l["price_gbp"])
        row["price_since"] = since.get(f"{l['treatment']}|{l['product']}|{l['dose']}|{l['pharmacy']}", "")
        latest.append(row)
    write_csv(os.path.join(DOCS, "medeazy-prices-latest.csv"),
              ["treatment", "active_ingredient", "form", "product", "dose", "pharmacy",
               "gphc_number", "pharmacy_website", "price_gbp", "price_since",
               "discount_code", "discount_detail"], latest)

    write_csv(os.path.join(DOCS, "medeazy-prices-history.csv"), LEDGER_COLS, ledger)

    index = monthly_index(ledger, today)
    write_csv(os.path.join(DOCS, "medeazy-monthly-index.csv"),
              ["month", "complete_month", "treatment", "product", "dose", "pharmacies_listed",
               "lowest_price_gbp", "median_price_gbp", "highest_price_gbp", "price_gap_gbp",
               "avg_daily_median_gbp", "days_tracked"], index)

    # Headline numbers for the /data page.
    groups = defaultdict(list)
    for l in listings.values():
        groups[(l["treatment"], l["product"], l["dose"])].append(l["price_gbp"])
    doses = []
    for (t, p, d), prices in groups.items():
        doses.append({"treatment": t, "product": p, "dose": d, "pharmacies": len(prices),
                      "lowest": min(prices), "median": round(statistics.median(prices), 2),
                      "highest": max(prices), "gap": round(max(prices) - min(prices), 2)})
    doses.sort(key=lambda x: (x["treatment"], x["product"], dose_num(x["dose"])))
    biggest = max(doses, key=lambda x: x["gap"]) if doses else None
    first = ledger[0]["date_uk"] if ledger else today.isoformat()
    changes = [e for e in ledger if e["event"] == "price_change"]
    summary = {
        "source": "MedEazy (medeazy.co.uk/data)",
        "licence": "CC BY 4.0",
        "last_checked_date": today.isoformat(),
        "tracking_since": first,
        "pharmacies_tracked": len({l["pharmacy"] for l in listings.values()}),
        "listings": len(listings),
        "price_changes_recorded": len(changes),
        "biggest_gap": biggest,
        "lowest_by_treatment": {
            t: min(l["price_gbp"] for l in listings.values() if l["treatment"] == t)
            for t in sorted({l["treatment"] for l in listings.values()})
        },
        "doses": doses,
    }
    tmp = os.path.join(DOCS, "summary.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    os.replace(tmp, os.path.join(DOCS, "summary.json"))
    return summary


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", help="read pricing-*.json from this folder instead of Shopify")
    args = ap.parse_args()

    # MEDEAZY_NOW lets tests pretend it's another day.
    now = os.environ.get("MEDEAZY_NOW")
    now_utc = (datetime.fromisoformat(now).astimezone(timezone.utc) if now
               else datetime.now(timezone.utc)).replace(microsecond=0)

    files = fetch_from_dir(args.from_dir) if args.from_dir else fetch_from_shopify()
    if not files:
        sys.exit("No pricing-*.json files found - nothing recorded.")
    listings, counts, problems = parse_files(files)

    prev = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            prev = json.load(fh)

    # Safety checks - stop without recording anything if an edit looks broken.
    prev_counts = defaultdict(int)
    for k in prev:
        prev_counts[k.split("|", 1)[0]] += 1
    for slug, before in prev_counts.items():
        after = counts.get(slug, 0)
        if before and after < before * (1 - MAX_DROP_SHARE):
            problems.append(f"pricing-{slug}.json went from {before} to {after} prices")
    if problems:
        print("STOPPED - nothing recorded, because:")
        for p in problems:
            print("  -", p)
        print("Fix the file in the theme; the next run will pick it up. "
              "If the drop is genuine, run the workflow once with 'allow_big_change'.")
        if os.environ.get("MEDEAZY_ALLOW_BIG_CHANGE") != "1" or any("could not be read" in p for p in problems):
            sys.exit(1)
        print("allow_big_change set - continuing.")

    events = diff(prev, listings, now_utc)

    # Hold suspicious moves (likely typos) until they've been live for
    # HOLD_HOURS. Fixed in time -> never reaches the public history.
    pending = {}
    if os.path.exists(PENDING):
        with open(PENDING, encoding="utf-8") as fh:
            pending = json.load(fh)
    new_pending, kept, held = {}, [], []
    for e in events:
        k = e["_key"]
        if e["event"] == "price_change" and abs(float(e["change_pct"])) > BIG_MOVE_PCT:
            p = pending.get(k)
            if p and p["price"] == listings[k]["price_gbp"]:
                first = datetime.fromisoformat(p["first_seen"])
                if now_utc - first >= timedelta(hours=HOLD_HOURS):
                    # Still there - genuine. Record it at the time it first appeared.
                    e["detected_at_utc"] = first.strftime("%Y-%m-%dT%H:%M:%SZ")
                    e["date_uk"] = first.astimezone(UK).date().isoformat()
                    kept.append(e)
                    continue
                new_pending[k] = p
            else:
                new_pending[k] = {"price": listings[k]["price_gbp"],
                                  "first_seen": now_utc.isoformat()}
            held.append(e)
            listings[k] = prev[k]           # keep the old price until confirmed
        else:
            kept.append(e)
    events = kept
    os.makedirs(DATA, exist_ok=True)
    with open(PENDING, "w", encoding="utf-8") as fh:
        json.dump(new_pending, fh, indent=1, sort_keys=True)
    for e in held:
        print(f"HOLDING: {e['pharmacy']} {e['product']} {e['dose']} {e['old_price_gbp']} -> "
              f"{e['new_price_gbp']} ({e['change_pct']}%). Recorded only if still live in "
              f"{HOLD_HOURS}h - fix it in the theme if it's a typo.")

    if events:
        for e in events:
            e.pop("_key", None)
        append_ledger(events)
    if events or held:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(listings, fh, indent=1, sort_keys=True)

    ledger = read_ledger()
    summary = build_outputs(listings, ledger, now_utc)

    kinds = defaultdict(int)
    for e in events:
        kinds[e["event"]] += 1
    print(f"{summary['listings']} prices from {summary['pharmacies_tracked']} pharmacies. "
          f"This run: {dict(kinds) or 'no changes'}.")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file and (events or held):
        with open(summary_file, "a", encoding="utf-8") as fh:
            for e in held:
                fh.write(f"> **Held for {HOLD_HOURS}h (possible typo):** {e['pharmacy']} {e['product']} "
                         f"{e['dose']} {e['old_price_gbp']} → {e['new_price_gbp']} ({e['change_pct']}%)\n\n")
            fh.write(f"### {len(events)} change(s) recorded\n\n")
            for e in events[:50]:
                fh.write(f"- {e['event']}: {e['pharmacy']} {e['product']} {e['dose']} "
                         f"{e['old_price_gbp'] or '–'} → {e['new_price_gbp'] or '–'}\n")


if __name__ == "__main__":
    main()
