"""Diagnóstico: estructura del chollo en la página de Chollometro (no publica)."""
import html, json, re
import feeds

_s, raw = feeds._get("https://www.chollometro.com/rss/hot")
entries = feeds.parse_rss(raw.decode("utf-8", "replace"))
picks = [e for e in entries if re.search(r"cup[oó]n|paypal|c[oó]digo", e["title"], re.I)][:3]
for e in picks:
    tid = re.search(r"(\d{5,})/?$", e["link"]).group(1)
    _s, body = feeds._get(e["link"])
    page = body.decode("utf-8", "replace")
    print("\n=====", e["title"][:90], tid, "rss price", e["price"])
    for m in list(re.finditer(r'\\?"threadId\\?":\\?"?' + tid, page))[:2]:
        print("  threadId ctx:", page[m.start()-200:m.start()+1500].replace("\\\\", "\\")[:1700])
    m = re.search(r'"voucherCode":"([^"]*)"', page.replace('\\"', '"'))
    print("  voucher:", m.group(1) if m else None)
    for kw in ("PayPal", "paypal", "Paypal"):
        for mm in list(re.finditer(kw, page))[:3]:
            print(f"  [{kw}]", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page[mm.start()-250:mm.start()+250]))))
