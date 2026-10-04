"""Turn assets/pricing-*.json into ready-to-render price tables.

Each table is pre-sorted cheapest first, with prices already formatted, so the
Liquid section only has to loop. Output shape (one object per treatment) is
what the hourly job would write to the shop metafield medeazy.price_table_<slug>.
"""
import json, re, statistics, sys, glob, os

TREATMENTS = {
    "mounjaro":    {"name": "Mounjaro", "ingredient": "tirzepatide", "form": "weekly injection", "unit": "per month (4 pens)", "weeks": 4},
    "wegovy":      {"name": "Wegovy", "ingredient": "semaglutide", "form": "weekly injection", "unit": "per month (4 pens)", "weeks": 4},
    "wegovy-pill": {"name": "Wegovy pill", "ingredient": "oral semaglutide", "form": "daily tablet", "unit": "per month", "weeks": 0},
    "orlistat":    {"name": "Orlistat", "ingredient": "orlistat", "form": "capsules", "unit": "per pack", "weeks": 0},
}
META = {"Pharmacy", "url", "GPHC", "GPHCLink", "TrustPilot", "TPlink", "DiscountType", "Discount", "DiscountTooltip"}


def num(v):
    try:
        return float(str(v).replace("£", "").replace(",", "").strip())
    except ValueError:
        return None


def money(v):
    s = f"{v:,.2f}"
    return "£" + (s[:-3] if s.endswith(".00") else s)


def split_codes(text):
    """'EAZY40 and EAZY15' -> two codes; 'Click the pharmacy name...' -> no code (it's offer text)."""
    parts = [x.strip() for x in re.split(r"\s+(?:and|or|&|/)\s+|\s*,\s*", text) if x.strip()]
    if parts and all(re.fullmatch(r"[A-Za-z0-9_-]{2,20}", x) for x in parts):
        return parts
    return []


def dose_label(key):
    k = key.replace("_", ".")
    m = re.match(r"^([A-Za-z]+)([\d.]+mg)$", k)
    return f"{m.group(1)} {m.group(2)}" if m else k


def build(slug, rows, updated):
    info = TREATMENTS.get(slug, {"name": slug.title(), "ingredient": "", "form": "", "unit": "", "weeks": 0})
    dose_keys = [k for k in rows[0] if k not in META]
    doses = []
    for key in dose_keys:
        offers = []
        for r in rows:
            p = num(r.get(key))
            if not p or p <= 0:
                continue
            code = (r.get("Discount") or "").strip()
            code = "" if code in ("-", "") else code
            tp = num(r.get("TrustPilot"))
            offers.append({"pharmacy": r["Pharmacy"].strip(), "price": p, "url": r.get("url", ""),
                           "gphc": r.get("GPHC", ""), "gphc_url": r.get("GPHCLink", ""),
                           "rating": tp, "rating_url": r.get("TPlink", ""),
                           "code": code, "code_detail": (r.get("DiscountTooltip") or "").strip()})
        if not offers:
            continue
        offers.sort(key=lambda o: (o["price"], o["pharmacy"].lower()))
        prices = [o["price"] for o in offers]
        lo, hi, med = prices[0], prices[-1], statistics.median(prices)
        span = (hi - lo) or 1
        out = []
        for i, o in enumerate(offers, 1):
            r = o["rating"]
            out.append({
                "rank": i, "pharmacy": o["pharmacy"], "price": money(o["price"]), "price_num": f"{o['price']:.2f}",
                "per_week": money(o["price"] / info["weeks"]) if info["weeks"] else "",
                "above_low": "" if o["price"] == lo else "+" + money(o["price"] - lo),
                "bar": round(4 + 96 * (o["price"] - lo) / span),
                "rating": f"{r:.1f}" if r else "", "rating_band": ("high" if r and r >= 4.5 else "mid" if r and r >= 4 else "low") if r else "none",
                "rating_url": o["rating_url"], "url": o["url"], "gphc": o["gphc"], "gphc_url": o["gphc_url"],
                "code": o["code"], "codes": split_codes(o["code"]), "code_detail": o["code_detail"] or ("" if split_codes(o["code"]) else o["code"]),
            })
        doses.append({
            "id": f"{slug}-{dose_label(key).lower().replace(' ', '-').replace('.', '-')}",
            "label": dose_label(key), "count": len(out),
            "low": money(lo), "median": money(med), "high": money(hi),
            "low_num": f"{lo:.2f}", "high_num": f"{hi:.2f}",
            "gap": money(hi - lo), "gap_year": money((hi - lo) * 12) if info["weeks"] or slug == "wegovy-pill" else "",
            "codes": sum(1 for o in out if o["code"]),
            "offers": out,
        })
    return {"slug": slug, "name": info["name"], "ingredient": info["ingredient"], "form": info["form"],
            "unit": info["unit"], "updated": updated, "pharmacies": len(rows), "doses": doses}


if __name__ == "__main__":
    src, dst, updated = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(dst, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src, "pricing-*.json"))):
        slug = os.path.basename(f)[8:-5]
        t = build(slug, json.load(open(f)), updated)
        json.dump(t, open(os.path.join(dst, f"{slug}.json"), "w"), ensure_ascii=False, separators=(",", ":"))
        print(slug, len(t["doses"]), "doses", os.path.getsize(os.path.join(dst, f"{slug}.json")), "bytes")
