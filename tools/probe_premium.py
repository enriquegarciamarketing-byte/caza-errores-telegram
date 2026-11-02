"""Diagnóstico: cómo trae Chollometro el cupón y las condiciones de un chollo (no publica)."""
import json
import re
import feeds

for feed in ["https://www.chollometro.com/rss/hot", "https://www.chollometro.com/rss/nuevos"]:
    _s, raw = feeds._get(feed)
    entries = feeds.parse_rss(raw.decode("utf-8", "replace"))
    picks = [e for e in entries if feeds.conditional_price(e["title"]) or "2052619" in e["link"]][:4]
    for e in picks:
        print("\n=====", e["title"], e["link"])
        _s, body = feeds._get(e["link"])
        page = body.decode("utf-8", "replace")
        for key in ("voucherCode", "voucher", "couponCode", "code\"", "discountCode", "paymentMethod", "shipping"):
            for m in list(re.finditer(re.escape(key), page))[:3]:
                print(f"  [{key}] …{page[max(0, m.start()-120):m.start()+200]!r}")
        for m in re.finditer(r'"(voucherCode|price|nextBestPrice|shippingPrice|startDate|endDate)":("[^"]*"|[\d.]+|null)', page):
            print("   ", m.group(0))
            
        desc = re.search(r'"description":"(.{0,900})', page)
        print("  descripcion:", desc.group(1)[:900] if desc else None)
