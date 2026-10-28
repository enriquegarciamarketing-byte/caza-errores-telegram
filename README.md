# Caza Errores — ofertas en Telegram

Hay dos automatizaciones separadas. El canal premium (reventa) sigue en `scan-deals.yml` y no cambia de reglas. El canal público normal es otra: `Canal normal @cazachollos_com`.

## Canal normal (@cazachollos_com)

Workflow: `.github/workflows/scan-generic.yml`. Visible en Actions como **Canal normal @cazachollos_com**. Grupo de concurrencia `telegram-generic` (el premium sigue en `telegram-scanner`). Memoria propia en `state/generic.json`. No usa el secreto `TELEGRAM_CHAT_ID`: el destino está en `config.json`, clave `generic.chat_id` (`@cazachollos_com`). El bot es el mismo (`TELEGRAM_BOT_TOKEN`).

Cada pasada comprueba con `getChatMember` que el bot puede publicar. Si no puede, lo dice en el log (`NO PUEDE PUBLICAR: …`) y termina sin tumbar la ejecución. La prueba `test_private` sigue pudiendo mandar ejemplos al administrador.

**Cadencia recomendada: cada 15 minutos.** El workflow ya lleva un cron a los minutos 07, 22, 37 y 52. Un bucle externo puede dispararlo por la API con la misma cadencia; tiene que mandar `dry_run: false` porque el valor por defecto del disparo manual es la simulación:

```bash
curl -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/enriquegarciamarketing-byte/caza-errores-telegram/actions/workflows/scan-generic.yml/dispatches \
  -d '{"ref":"main","inputs":{"dry_run":false}}'
```

Si el cron y el bucle coinciden, el cupo impide el segundo post. Para dejar solo el bucle, quita el bloque `schedule` del workflow.

Qué publica: chollos variados de todas las categorías y tiendas (el RSS caliente de Chollometro primero, luego los nuevos, y las listas de Amazon que ya usa el repo). No es el canal de reventa: no hay ROI ni tarjeta de Wallapop. Se descartan caducados, sin precio, duplicados, temperatura baja y enlaces que no se puedan dejar limpios.

Ritmo, en `config.json` → `generic`:

| Ajuste | Valor |
| --- | --- |
| Temperatura mínima | 80° |
| Precio mínimo | 3 € |
| Descuento mínimo en las listas de Amazon | 20 % (y no se fía de un descuento mayor del 95 %) |
| Máximo por hora | 4 |
| Máximo al día | 40 |
| Máximo por pasada | 1 |
| Separación mínima | 15 minutos |
| Silencio | 01:00–08:00 Europe/Madrid |
| No repetir el mismo chollo | 14 días |
| Fichas abiertas por pasada | 8 |

Amazon sale siempre con `tag=cazadores_errores-21` (enlaces cortos resueltos, tags ajenos fuera, ASIN comprobado). El resto de tiendas lleva a la ficha directa, sin parámetros de afiliado ajenos. Si `store_affiliates` tiene una plantilla con `{url}` para esa tienda, se aplica encima del enlace ya limpio. Si el enlace no se puede limpiar, el chollo no se publica.

El texto sigue el estilo del canal (gancho, título, tienda, botón «Ver en …») con este bloque de precio. El PVP va tachado. Si no hay un precio anterior fiable, solo se muestra AHORA.

Con PVP:

```
🔥 <b>BAJÓN DE PRECIO</b>

<b>LG OLED 55 pulgadas</b>
📂 Electrónica

❌ PVP MediaMarkt: <s>1.149,50 €</s>
💰 AHORA: 223,71 €
📉 −81 % sobre PVP
🤑 Te ahorras: 925,79 €

🔗 <b><a href="https://www.mediamarkt.es/es/product/lg-oled-55">Ver en MediaMarkt</a></b>
```

Sin PVP fiable:

```
🔥 <b>CHOLLO CALIENTE</b>

<b>ASUS TUF Gaming M4 Air</b>
📂 Electrónica

💰 AHORA: 34,03 €

🔗 <b><a href="https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21">Ver en Amazon</a></b>
```

Entradas manuales: `dry_run` (no publica; es el valor por defecto) y `test_private` (2 o 3 ejemplos solo al chat del administrador, sin guardar memoria). Para que `test_private` envíe de verdad, desmarca `dry_run`.

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

- `TELEGRAM_BOT_TOKEN`: token del bot, guardado solo como secreto. Lo usan los dos canales.
- `TELEGRAM_CHAT_ID`: `@caza_errores`. Solo el canal premium. El canal normal publica en `@cazachollos_com`, definido en `config.json`.

El bot necesita permiso para publicar en el canal. GitHub Actions registra los IDs publicados para evitar duplicados. Las notificaciones en el móvil dependen de que Telegram tenga activadas las notificaciones del canal.

## Coste y límites

Telegram Bot API y GitHub Actions pueden funcionar dentro de las cuotas gratuitas. El flujo actual publica ofertas aprobadas; la búsqueda y verificación de precios son manuales. No automatiza la extracción de Amazon ni de Wallapop. Cumple las condiciones de tu cuenta de Afiliados de Amazon y usa imágenes con permiso.

Referencias: [políticas de Amazon Afiliados España](https://afiliados.amazon.es/help/operating/policies), [términos de Wallapop](https://about.wallapop.com/condiciones-de-uso/), [Telegram Bot API](https://core.telegram.org/bots/api).
