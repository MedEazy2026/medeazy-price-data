"""Build the daily price summary that the Shopify theme reads (shop metafield medeazy.prices).

Run by the "MedEazy daily price summary refresh" scheduled task:
    python3 build_price_summary.py FOLDER CHANGED_DATE
FOLDER holds the live theme's assets/pricing-*.json files. Writes prices_summary.json.

Per treatment: price range per dose (min/max/avg/gap, the 3 cheapest pharmacies), and
"dc": every pharmacy with a discount offer, cheapest first, for the discount codes page.
"""
import json, sys, re, datetime

REG = [
  dict(key="mounjaro", name="Mounjaro", full="Mounjaro", ingr="tirzepatide", handle="mounjaro-price-comparison", file="pricing-mounjaro.json", headline=True, soon=False,
       cols=[("2_5mg","2.5mg"),("5mg","5mg"),("7_5mg","7.5mg"),("10mg","10mg"),("12_5mg","12.5mg"),("15mg","15mg")]),
  dict(key="wegovy", name="Wegovy", full="Wegovy injection", ingr="semaglutide", handle="wegovy-pricing", file="pricing-wegovy.json", headline=True, soon=False,
       cols=[("0_25mg","0.25mg"),("0_5mg","0.5mg"),("1mg","1mg"),("1_7mg","1.7mg"),("2_4mg","2.4mg"),("7_2mg","7.2mg")]),
  dict(key="wegovy-pill", name="Wegovy pill", full="Wegovy pill", ingr="oral semaglutide", handle="wegovy-pill-pricing", file="pricing-wegovy-pill.json", headline=True, soon=False,
       cols=[("1_5mg","1.5mg"),("4mg","4mg"),("9mg","9mg"),("25mg","25mg")]),
  dict(key="orlistat", name="Orlistat", full="Orlistat", ingr="orlistat", handle="orlistat-pricing", file="pricing-orlistat.json", headline=False, soon=False,
       cols=[("Orlistat120mg","Orlistat 120mg"),("Xenical120mg","Xenical 120mg"),("Alli60mg","Alli 60mg")]),
  dict(key="foundayo", name="Foundayo", full="Foundayo", ingr="orforglipron", handle="foundayo-price-comparison", file=None, headline=False, soon=True,
       cols=[("0_8mg","0.8mg"),("2_5mg","2.5mg"),("5_5mg","5.5mg"),("9mg","9mg"),("14_5mg","14.5mg"),("17_2mg","17.2mg")]),
]


def num(v):
    if v is None: return None
    try: n = float(re.sub(r"[£,\s]", "", str(v)))
    except ValueError: return None
    return n if n > 0 and n == n and n != float("inf") else None


def gbp(n):
    if n is None: return "—"
    return "£%d" % round(n) if round(n * 100) % 100 == 0 else "£%.2f" % n


def gbp0(n):
    if n is None: return "—"
    return "£{:,}".format(int(round(n)))


def norm(s): return str(s).lower().replace(" ", "")


def is_code(text):
    """'EAZY40' or 'EAZY40 and EAZY15' is a code; 'Click the pharmacy name...' is offer text."""
    parts = [x.strip() for x in re.split(r"\s+(?:and|or|&|/)\s+|\s*,\s*", text) if x.strip()]
    return bool(parts) and all(re.fullmatch(r"[A-Za-z0-9_-]{2,20}", x) for x in parts)


def build(folder, changed):
    out = {"updated": datetime.date.today().isoformat(), "changed": changed, "order": [], "t": {}}
    allnames = set(); g_lo = []; g_hi = []; g_n = 0; g_codes = 0
    for t in REG:
        rows = []
        if t["file"] and not t["soon"]:
            raw = json.load(open(f"{folder}/{t['file']}"))
            for r in raw:
                if not r or not r.get("Pharmacy"): continue
                d = str(r.get("Discount") or "").strip()
                d = "" if d == "-" else d
                rows.append({"name": str(r["Pharmacy"]).strip(), "disc": bool(d), "code": d,
                             "detail": str(r.get("DiscountTooltip") or "").strip(),
                             "url": str(r.get("url") or "").strip(),
                             "p": [num(r.get(k)) for k, _ in t["cols"]]})
        tt = {"name": t["name"], "full": t["full"], "ingr": t["ingr"], "handle": t["handle"], "soon": t["soon"],
              "n": str(len(rows)), "codes": str(sum(1 for r in rows if r["disc"])),
              "c0": norm(t["cols"][0][1]), "cols": [lab for _, lab in t["cols"]], "a": {}, "c": {}}
        lows = []; highs = []
        for i, (k, lab) in enumerate(t["cols"]):
            lst = sorted([(r["p"][i], r["name"]) for r in rows if r["p"][i] is not None], key=lambda x: x[0])
            ent = {"label": lab, "n": str(len(lst))}
            if lst:
                mn, mx = lst[0][0], lst[-1][0]; avg = sum(x[0] for x in lst) / len(lst)
                lows.append(mn); highs.append(mx)
                ent.update({"min": gbp(mn), "max": gbp(mx), "avg": gbp0(avg), "gap": gbp0(mx - mn),
                            "min_v": round(mn, 2), "max_v": round(mx, 2), "avg_v": round(avg),
                            "top": [x[1] for x in lst[:3]], "topp": [gbp(x[0]) for x in lst[:3]]})
            else:
                ent.update({"min": "—", "max": "—", "avg": "—", "gap": "—", "top": [], "topp": []})
            tt["c"][norm(lab)] = ent
            if norm(k) != norm(lab): tt["a"][norm(k)] = norm(lab)
        tt["lo"] = gbp(min(lows)) if lows else ("Soon" if t["soon"] else "—")
        tt["hi"] = gbp(max(highs)) if highs else ("Soon" if t["soon"] else "—")
        tt["lo_v"] = round(min(lows), 2) if lows else None
        tt["hi_v"] = round(max(highs), 2) if highs else None
        # Discount offers, cheapest starting dose first: p = pharmacy, k = code (blank when the offer
        # is text rather than a code), d = what it gives, u = link, f = price of the first dose after the offer
        dc = []
        for r in rows:
            if not r["disc"]: continue
            first = next((v for v in r["p"] if v is not None), None)
            code = r["code"] if is_code(r["code"]) else ""
            detail = r["detail"] or ("" if code else r["code"])
            dc.append({"p": r["name"], "k": code, "d": detail[:160], "u": r["url"], "f": gbp(first), "fv": first or 9999})
        dc.sort(key=lambda x: (x["fv"], x["p"].lower()))
        for x in dc: x.pop("fv")
        tt["dc"] = dc
        out["t"][t["key"]] = tt; out["order"].append(t["key"])
        if t["headline"] and not t["soon"] and rows:
            for r in rows: allnames.add(r["name"].lower())
            if lows: g_lo.append(min(lows))
            if highs: g_hi.append(max(highs))
            g_n += len(rows); g_codes += int(tt["codes"])
    out["pharmacies"] = str(len(allnames))
    out["g"] = {"lo": gbp(min(g_lo)) if g_lo else "—", "hi": gbp(max(g_hi)) if g_hi else "—", "n": str(g_n), "codes": str(g_codes)}
    return out


if __name__ == "__main__":
    s = build(sys.argv[1], sys.argv[2])
    txt = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
    open("prices_summary.json", "w").write(txt)
    print(len(txt), "chars")
