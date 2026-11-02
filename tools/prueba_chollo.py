"""Prueba privada de un chollo de Chollometro: te llega a tu chat como PRUEBA, nunca al canal."""
import json
import os
import re
import sys

import feeds
import scanner

tid = sys.argv[1]
cfg = scanner.load_json(scanner.CONFIG_PATH, {})
state = scanner.load_json(scanner.STATE_PATH, {})
_s, raw = feeds._get(f"https://www.chollometro.com/share-deal/{tid}")
page = raw.decode("utf-8", "replace")
anchor = page.find(f'"threadId":"{tid}"')
win = page[max(0, anchor - 6000):anchor + 6000]
rel = min(anchor, 6000)


def nearest(pattern):
    best = None
    for m in re.finditer(pattern, win):
        d = abs(m.start() - rel)
        if best is None or d < best[0]:
            best = (d, m.group(1))
    return best[1] if best else None


title = json.loads('"' + nearest(r'"title":"((?:[^"\\]|\\.)*)"') + '"')
price = float(nearest(r'"price":(\d+(?:\.\d+)?)'))
image = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
entry = {"title": title, "price": price, "image": image.group(1) if image else "",
         "link": f"https://www.chollometro.com/ofertas/{tid}", "temperature": 999}
print("Chollo:", title, price)
cand = feeds._from_feed(entry, cfg, [], page)
if not cand:
    print("No he podido sacar la tienda del chollo")
    sys.exit(1)
print({k: cand.get(k) for k in ("store_label", "direct_url", "coupons", "coupon_text", "paypal", "from_spain", "was")})
if cand.get("was") and cand["was"] > cand["price"]:
    cand.update(reference_price=cand["was"], avg90=cand["was"],
                discount=(cand["was"] - cand["price"]) / cand["was"] * 100,
                ref_text="frente al precio anterior en la tienda")
else:
    cand.update(reference_price=cand["price"], avg90=cand["price"], discount=0)
token = os.environ["TELEGRAM_BOT_TOKEN"]
tg = scanner.Telegram(token)
ok = scanner.attach_wallapop(None, cfg, state, cand, True)
if not ok:
    print("Sin datos de reventa: la prueba sale sin el bloque de reventa")
    scanner.attach_wallapop = lambda *a, **k: True
sent = scanner.publish(tg, cfg, state, cand, "@caza_errores", False, test_private=True)
print("Enviado a tu chat" if sent else "No enviado")
