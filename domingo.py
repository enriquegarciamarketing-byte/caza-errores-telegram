"""Recordatorio de cada domingo (26/11/2026): en cada canal, una imagen con la línea gráfica de las tarjetas y un
copy que recuerda los otros dos canales, para empujar el funnel Caza Errores → Caza Chollos → WhatsApp."""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import marco_canal as mc

DARK, GREY, BORDER = (26, 26, 26), (120, 120, 120), (232, 230, 226)
WHATSAPP = "https://whatsapp.com/channel/0029VbE063mEwEk5M7m9Xe17"
OUT = Path(__file__).resolve().parent / "output" / "domingo"

FICHAS = {
    "caza_errores": ("Caza Errores", "t.me/caza_errores", "telegram",
                     "Errores de precio que duran minutos", "Activa las notificaciones"),
    "cazachollos": ("Caza Chollos", "t.me/cazachollos_com", "telegram",
                    "Chollos todo el día y el top 5 cada noche", "Lo que necesitas, más barato"),
    "whatsapp": ("Caza Chollos en WhatsApp", "Canal de WhatsApp", "whatsapp_completo",
                 "Lo mejor del día sin saturarte el móvil", "Perfecto para la familia"),
}
OTROS = {"caza_errores": ["cazachollos", "whatsapp"], "cazachollos": ["caza_errores", "whatsapp"],
         "whatsapp": ["caza_errores", "cazachollos"]}
TITULAR = {
    "caza_errores": ("Aquí cazamos errores", "pero la familia es más grande"),
    "cazachollos": ("Aquí cazamos chollos", "pero hay más donde elegir"),
    "whatsapp": ("Aquí te llega lo mejor", "y en Telegram aún hay más"),
}


def imagen(canal: str, out: Path) -> Path:
    S, W, H = 2, 1000, 1000
    u = S * 1.0
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    f = mc._font
    mx = 64 * u

    # Etiqueta «CADA DOMINGO» y titular
    kick = "CADA DOMINGO · REPASO DE CANALES"
    fk = f(round(19 * u), b"ExtraBold")
    kw = d.textlength(kick, font=fk) + 40 * u
    d.rounded_rectangle((mx, 40 * u, mx + kw, 82 * u), 21 * u, outline=mc.NARANJA, width=round(2.5 * u))
    d.text((mx + kw / 2, 61.5 * u), kick, font=fk, fill=mc.NARANJA, anchor="mm")
    l1, l2 = TITULAR[canal]
    d.text((mx, 150 * u), l1, font=f(round(64 * u), b"Black"), fill=DARK, anchor="ls")
    d.text((mx, 226 * u), l2, font=f(round(64 * u), b"Black"), fill=mc.NARANJA, anchor="ls")
    d.text((mx, 278 * u), "Estos son los otros canales de la casa 👇".replace(" 👇", ""),
           font=f(round(26 * u), b"Medium"), fill=GREY, anchor="ls")

    # Fichas de los otros dos canales
    alto, gap, y = 230 * u, 34 * u, 320 * u
    sombra = Image.new("L", im.size, 0)
    sd = ImageDraw.Draw(sombra)
    for i in range(2):
        yy = y + i * (alto + gap)
        sd.rounded_rectangle((mx, yy + 8 * u, W * S - mx, yy + alto + 8 * u), 30 * u, fill=40)
    im.paste((90, 90, 90), (0, 0), sombra.filter(ImageFilter.GaussianBlur(14 * u)))
    d = ImageDraw.Draw(im)
    for i, otro in enumerate(OTROS[canal]):
        nombre, enlace, logo, linea1, linea2 = FICHAS[otro]
        yy = y + i * (alto + gap)
        x1 = W * S - mx
        d.rounded_rectangle((mx, yy, x1, yy + alto), 30 * u, fill="white", outline=BORDER, width=round(2 * u))
        # Icono: círculo con el degradado de la marca y el logo en blanco
        r = 62 * u
        cx, cy = mx + 40 * u + r, yy + alto / 2
        circ = mc._degradado(round(2 * r), round(2 * r))
        mk = Image.new("L", circ.size, 0)
        ImageDraw.Draw(mk).ellipse((0, 0, circ.width - 1, circ.height - 1), fill=255)
        im.paste(circ, (round(cx - r), round(cy - r)), mk)
        g = mc._glifo(logo, round((60 if logo.endswith("_completo") else 50) * u))
        im.paste((255, 255, 255), (round(cx - g.width / 2 + (0 if logo.endswith("_completo") else -3 * u)),
                                   round(cy - g.height / 2)), g)
        tx = cx + r + 36 * u
        d.text((tx, yy + 66 * u), nombre, font=f(round(40 * u), b"ExtraBold"), fill=DARK, anchor="ls")
        d.text((tx, yy + 108 * u), enlace, font=f(round(27 * u), b"Bold"), fill=mc.NARANJA, anchor="ls")
        d.text((tx, yy + 158 * u), linea1, font=f(round(25 * u), b"SemiBold"), fill=(70, 70, 70), anchor="ls")
        d.text((tx, yy + 194 * u), linea2, font=f(round(23 * u), b"Medium"), fill=GREY, anchor="ls")
        # Flecha
        ax, ay = x1 - 56 * u, cy
        d.ellipse((ax - 26 * u, ay - 26 * u, ax + 26 * u, ay + 26 * u), fill=(245, 243, 239))
        d.line((ax - 10 * u, ay, ax + 10 * u, ay), fill=mc.NARANJA, width=round(5 * u))
        d.line((ax + 1 * u, ay - 10 * u, ax + 11 * u, ay), fill=mc.NARANJA, width=round(5 * u))
        d.line((ax + 1 * u, ay + 10 * u, ax + 11 * u, ay), fill=mc.NARANJA, width=round(5 * u))

    # Pie
    d.text((W * S / 2, 912 * u), "Tres canales, la misma forma de pagar menos",
           font=f(round(24 * u), b"Bold"), fill=GREY, anchor="mm")
    im = im.resize((W, H), Image.LANCZOS)
    return mc.guardar(mc.enmarcar_canal(im, canal), out, quality=95)


# ---------------------------------------------------------------- copies y publicación

COPY = {
    "caza_errores": ("🔁 <b>Repaso de domingo cazadores</b>\n\n"
                     "Aquí van los errores que duran minutos, pero entre semana también salen chollos muy buenos 👇\n\n"
                     "🛒 t.me/cazachollos_com\n"
                     f"📲 {WHATSAPP.removeprefix('https://')}"),
    "cazachollos": ("☕ <b>Domingo de repaso</b>\n\n"
                    "Si queréis ir un paso por delante, los errores de precio salen en un canal aparte y vuelan en "
                    "minutos ⚡\n\n"
                    "👉 t.me/caza_errores\n\n"
                    "Y para quien no tenga Telegram, también estamos en WhatsApp 📲\n"
                    f"👉 {WHATSAPP.removeprefix('https://')}"),
    "whatsapp": ("👋 *Repaso de domingo*\n\n"
                 "En Telegram tenéis aún más chollos y un canal solo de errores de precio 👇\n\n"
                 "🛒 t.me/cazachollos_com\n"
                 "⚡ t.me/caza_errores"),
}
BOTONES = {
    "caza_errores": [[{"text": "🛒 Únete a Caza Chollos", "url": "https://t.me/cazachollos_com"}],
                     [{"text": "📲 Únete a WhatsApp", "url": WHATSAPP}]],
    "cazachollos": [[{"text": "⚡ Únete a Caza Errores", "url": "https://t.me/caza_errores"}],
                    [{"text": "📲 Únete a WhatsApp", "url": WHATSAPP}]],
}
CHATS = {"caza_errores": os.environ.get("PREMIUM_CHAT_ID", "").strip() or "-1004494143183",
         "cazachollos": "@cazachollos_com"}
NOMBRES = {"caza_errores": "Caza Errores", "cazachollos": "Caza Chollos", "whatsapp": "WhatsApp"}


def publicar(privado: bool, solo: str | None = None) -> int:
    from scanner import Telegram
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"].strip())
    admin = (os.environ.get("ADMIN_CHAT_ID") or "").strip()
    if privado and not admin:
        print("Falta ADMIN_CHAT_ID", file=sys.stderr)
        return 2
    estado = 0
    for canal in ("caza_errores", "cazachollos", "whatsapp"):
        if solo and canal != solo:
            continue
        foto = imagen(canal, OUT / f"domingo_{canal}.jpg")
        try:
            if canal == "whatsapp" and not privado:
                import whatsapp as wa
                token = (os.environ.get("WHAPI_TOKEN") or "").strip()
                if not token:
                    print("WhatsApp: sin WHAPI_TOKEN, no publico")
                    continue
                to = wa.target(token, None, datetime.now(), wa.DEFAULT_INVITE, False)
                wa.send_image(token, to, foto, COPY[canal])
                print("WhatsApp: repaso del domingo publicado")
                continue
            texto = COPY[canal]
            if canal == "whatsapp":  # vista previa en Telegram del post de WhatsApp
                texto = re.sub(r"\*(.+?)\*", r"<b>\1</b>", texto)
            if privado:
                texto = f"🧪 <b>PRUEBA · así saldría en {NOMBRES[canal]}</b>\n\n" + texto
            extra = {"reply_markup": {"inline_keyboard": BOTONES[canal]}} if canal in BOTONES else {}
            msg = tg.send_photo(admin if privado else CHATS[canal], foto, texto, extra)
            print(f"{NOMBRES[canal]}: enviado {'a tu chat privado' if privado else 'al canal'} "
                  f"(mensaje {msg.get('message_id')})")
        except Exception as exc:  # un canal que falla no tumba a los demás
            print(f"{NOMBRES[canal]}: no he podido publicar ({exc})", file=sys.stderr)
            estado = 1
    return estado


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Repaso de canales de cada domingo")
    ap.add_argument("--privado", action="store_true", help="las tres versiones a tu chat privado, nunca al canal")
    ap.add_argument("--canal", choices=["caza_errores", "cazachollos", "whatsapp"], help="solo este canal")
    ap.add_argument("--imagenes", help="solo generar las imágenes en esta carpeta")
    a = ap.parse_args()
    if a.imagenes:
        for c in ("caza_errores", "cazachollos", "whatsapp"):
            print(imagen(c, Path(a.imagenes) / f"domingo_{c}.jpg"))
        raise SystemExit(0)
    raise SystemExit(publicar(a.privado, a.canal))
