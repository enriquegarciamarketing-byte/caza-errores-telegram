# Caza Errores — ofertas en Telegram

## Canal normal @cazachollos_com (solo Amazon, `canal_amazon.py`)

Desde el 31/10/2026 el canal publica **solo Amazon.es** y lo ejecuta el Mac de Enrique, porque Amazon devuelve captcha a las lecturas desde los servidores de GitHub. El workflow antiguo (`scan-generic.yml`, Chollometro y otras tiendas) está pausado.

Reglas que no se saltan:

- Los chollos se buscan en la propia Amazon (listados con filtro de descuento de `amazon_channel.discovery_urls`).
- El precio publicado es el de la ficha del producto, leído **dos veces**: al elegirlo y justo antes de enviarlo. Si cambia, no sale.
- El descuento se calcula frente al **"Precio más bajo reciente"** que muestra Amazon (mínimo de los 30 días anteriores, obligatorio en la UE). Sin ese dato no hay rebaja verificable y no se publica. Nunca se usa el PVP.
- Mínimo 40 % de descuento, precio de 8 € o más, vendido o enviado por Amazon, 4,0 estrellas y 30 opiniones, con stock y sin precio exclusivo Prime. Se ajusta en `config.json` → `amazon_channel`.
- Enlace directo al producto: `https://www.amazon.es/dp/ASIN?tag=cazadores_errores-21`.
- Cada pasada vuelve a mirar los posts de las últimas 48 h y, si el precio sube o se agota, añade al post «⛔ YA NO ESTÁ A ESTE PRECIO».
- Máximo 3 posts por hora y 30 al día, en silencio de 01:00 a 08:00. Si Amazon pide captcha, la pasada se para sin publicar.

En el Mac:

```bash
curl -fsSL https://raw.githubusercontent.com/enriquegarciamarketing-byte/caza-errores-telegram/main/mac/instalar.sh | bash
```

Instala en `~/CazaChollos`, pide el token del bot (se guarda en `.env`, fuera de git), hace una prueba sin enviar y otra que manda hasta 3 chollos solo a tu chat privado. No publica en el canal hasta ejecutar `bash ~/CazaChollos/mac/activar.sh`. Para parar: `bash ~/CazaChollos/mac/pausar.sh`. Registro en `~/CazaChollos/state/canal_amazon.log`.

Pruebas a mano: `--dry-run` (no envía nada), `--test-private` (solo a tu chat), `--ignore-limits` (salta cupos y horario).

## Escáner automático (scan-deals.yml)

Cada 10 minutos, las 24 horas, `scanner.py`:

1. Lee las listas públicas de Jimmyleaks (mínimos de hoy, actualizados, mayor bajada).
2. Abre la ficha de cada candidato nuevo y toma la media real de 90 días, el mínimo histórico y el EAN. La bajada frente al PVP no cuenta; solo cuenta frente a la media.
3. Clasifica: ERROR DE PRECIO (70 % o más bajo la media, a cualquier hora), MÍNIMO HISTÓRICO o GANGA (40 % o más, valoración 4,0 con 30 opiniones, precio de 12 € o más; máximo 8 al día, separadas 40 min y nunca de 0:00 a 8:00).
4. Publica la tarjeta con un enlace de búsqueda por EAN en Amazon.es que lleva la etiqueta de afiliado.
5. Avisa por privado al administrador. Si responde a un aviso con su enlace corto de SiteStripe, el bot lo cambia en el post. Sin EAN, espera a ese enlace antes de publicar.

Controles antes de publicar sin revisión: precio del listado igual al de la ficha, datos de menos de 3 horas, media de 90 días coherente con el PVP, descuento no absurdo (máximo 92 %) y EAN presente.

Productos con tallas (ropa, calzado, bolsas por tamaños): Jimmyleaks a veces mezcla la media de una talla con el precio de otra. Sin Creators API se descartan. Con ella (`amazon_api.py`), el bot comprueba en vivo que la talla con historial está a ese precio, lista todas las tallas del mismo color que también lo están y enlaza al producto exacto. Para activarla, añade en GitHub Secrets `AMAZON_CREATORS_CLIENT_ID` y `AMAZON_CREATORS_CLIENT_SECRET` (Amazon exige 10 ventas válidas en 30 días). Con la API activa, también se verifica en vivo el precio de los productos sin tallas.

Ajustes en `config.json`. Memoria en `state/scanner.json` e informe de la última pasada en `state/last_run.log`.

## Publicación manual (offers.json)

El publicador crea una tarjeta minimalista con foto del producto, etiqueta de clasificación, precio actual y descuento. Usa una paleta propia inspirada en naranja y azul oscuro; no incorpora el logotipo de Amazon. El canal recibe la imagen, el enlace corto de afiliado y la información de la oferta.

## Clasificación de publicaciones

- **ERROR DE PRECIO**: descuento verificado de 70 % o más frente al precio medio de los últimos 90 días.
- **GANGA**: descuento verificado de 40 % a 69,9 %.
- **MÍNIMO HISTÓRICO**: precio identificado manualmente como mínimo histórico por la fuente indicada. Puede publicarse aunque el descuento sea inferior al 40 %.
- **OPORTUNIDAD DE REVENTA**: oferta desde el 40 % con ROI positivo estimado a partir de al menos tres comparables revisados de Wallapop y costes explícitos.
- Una oferta de 70 % o más conserva siempre la etiqueta principal **ERROR DE PRECIO**; si hay comparables, la tarjeta añade la estimación de reventa. Si faltan, no inventa ROI.

Toda oferta debe estar aprobada en `offers.json`, tener una comprobación reciente del precio (máximo 20 minutos), enlace afiliado, imagen y una referencia histórica de 90 días. Los precios se revisan manualmente; este flujo gratuito no rastrea Amazon ni Wallapop por su cuenta. No uses el precio tachado como sustituto del historial.

## Preparación y aprobación

1. Añade una foto que tengas permiso para utilizar en `images/`.
2. Usa una fuente histórica que hayas revisado y registra su URL y fecha.
3. Marca `historical_low: true` solo cuando la fuente confirme el mínimo.
4. Cambia `status` de `draft` a `approved` solo tras comprobar producto, variante, stock y precio.
5. Al guardar `offers.json`, GitHub Actions publica las ofertas aprobadas que cumplen la regla de clasificación.

Ejemplo de ganga:

```json
[
  {
    "id": "B0XXXXXXXX-20261028-1200",
    "status": "draft",
    "asin": "B0XXXXXXXX",
    "title": "Nombre exacto del producto y variante",
    "affiliate_url": "https://link.amazon/TU-ENLACE-CORTO",
    "image_path": "producto.jpg",
    "current_price_eur": 59.99,
    "reference_price_eur": 99.99,
    "reference_period_days": 90,
    "reference_source": "PrecioReal o Keepa (revisado manualmente)",
    "reference_source_url": "https://proveedor.example/producto",
    "checked_at": "2026-10-28T12:00:00+02:00",
    "approved_by": "tu nombre",
    "historical_low": false
  }
]
```

Para marcar mínimo histórico, cambia `historical_low` a `true` tras confirmarlo en la fuente. Para añadir estimación de reventa, incluye al menos tres anuncios Wallapop con `title`, `match` (`exacto` o `similar`), `price_eur` y URL, y añade `resale_fees_eur` y `resale_shipping_eur`. El ROI es orientativo: los anuncios reflejan precios pedidos, no ventas cerradas.

## Configuración

En **Settings → Secrets and variables → Actions** define:

- `TELEGRAM_BOT_TOKEN`: token del bot, guardado solo como secreto.
- `TELEGRAM_CHAT_ID`: `@caza_errores`.

El bot necesita permiso para publicar en el canal. GitHub Actions registra los IDs publicados para evitar duplicados. Las notificaciones en el móvil dependen de que Telegram tenga activadas las notificaciones del canal.

## Coste y límites

Telegram Bot API y GitHub Actions pueden funcionar dentro de las cuotas gratuitas. El flujo actual publica ofertas aprobadas; la búsqueda y verificación de precios son manuales. No automatiza la extracción de Amazon ni de Wallapop. Cumple las condiciones de tu cuenta de Afiliados de Amazon y usa imágenes con permiso.

Referencias: [políticas de Amazon Afiliados España](https://afiliados.amazon.es/help/operating/policies), [términos de Wallapop](https://about.wallapop.com/condiciones-de-uso/), [Telegram Bot API](https://core.telegram.org/bots/api).
