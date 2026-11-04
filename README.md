# Caza Errores — ofertas en Telegram

## Modo revisión de Amazon Afiliados (04/11/2026)

Amazon rechazó la cuenta aprobada temporalmente por uso de su marca (capturas de la ficha en X). Mientras se revisa, `config.json` → `amazon_channel.revision_mode` deja el canal, el resumen y la web en lo que permiten las normas sin la Creators API:

- `"estricto"` (activo): sin precios, sin tachados, sin porcentajes, sin «mínimo histórico», sin estrellas y sin fotos de Amazon. Cabecera sin «Amazon» (CHOLLO DEL DÍA / CHOLLAZO / ERROR DE PRECIO), aviso de oferta limitada, enlace «VER OFERTA» y `#Publicidad`. Tarjeta con el logo del canal. Sin collage en el resumen. La web no publica cifras.
- `"descuento"`: igual, pero con el % frente al precio más bajo de los últimos 30 días (nunca el PVP) y la foto.
- `""`: formato normal, cuando la cuenta esté aprobada y haya Creators API.

Limpieza del canal: Actions → «Limpiar posts antiguos @cazachollos_com» → escribe `LIMPIAR`. Cambia cada post antiguo del bot a «Oferta finalizada» (tarjeta neutra, sin precios, sin botón) y lo marca como terminado en la memoria.

## Canal normal @cazachollos_com (solo Amazon, `canal_nube.py`)

Corre en GitHub Actions (`scan-generic.yml`), sin depender de ningún ordenador. Solo publica Amazon.es; Chollometro y el resto de tiendas ya no entran.

Amazon devuelve captcha a las lecturas desde GitHub, así que los datos salen de Jimmyleaks, que sigue el precio de Amazon.es producto a producto. Reglas:

- **Producto exacto**: el ASIN sale del botón de compra de Jimmyleaks (`/p/ID/` redirige a `amazon.es/dp/ASIN`) y se publica `https://www.amazon.es/dp/ASIN?tag=cazadores_errores-21`. Nunca una búsqueda por EAN, que era lo que hacía que el precio no cuadrara.
- **Precio reciente**: visto en Amazon hace menos de 60 minutos, igual en el listado y en la ficha, y releído justo antes de enviar. Si cambia, no sale. El post dice a qué hora se vio.
- **Descuento honesto**: frente al precio más bajo de los 30 días anteriores a la bajada (el criterio de la ley europea). Nunca el PVP tachado. Mínimo -18 % en móviles, aspiradoras, cafeteras y electrodomésticos, -20 % en muebles, TV, informática y consolas, y -30 % en el resto de categorías top. Si el producto está en su precio más bajo de siempre, basta -10 % en esas categorías.
- **Lo que interesa**: prioriza lo que más compra la gente online (móviles, aspiradoras, cafeteras, electrodomésticos, muebles, TV y sonido, informática, consolas…) según `amazon_channel.interest`. Lo de poco interés (tornillería, papelería, consumibles, ropa interior, fundas…) nunca sale; el resto solo si es un error de precio (-65 % y desde 20 €). Se publica primero lo de más interés, descuento y ahorro.
- **Calidad**: con stock, 10 € o más, 4,0 estrellas y 10 opiniones, al menos 30 días de historial y bajada de menos de 14 días. 48 listados de Jimmyleaks: 2 fijos y, por turnos, 13 categorías y 33 marcas que la gente busca (Roborock, Cecotec, DeLonghi, Xiaomi, Samsung, Apple, Philips…).
- **Seguimiento**: los posts de las últimas 48 h se revisan; si sube el precio o se agota, el post se marca «⛔ YA NO ESTÁ A ESTE PRECIO».
- Hasta 10 posts por hora y 70 al día, de 08:00 a 23:50. Como GitHub retrasa las tareas muy frecuentes, cada ejecución busca durante unos 35 minutos: una pasada cada 2 minutos, o al minuto si quedaron chollos aprobados por publicar. Los listados de categorías y marcas se recorren por turnos (12 por pasada). Si lleva 40 minutos sin publicar, entra en modo sin silencios: admite la mejor rebaja real de las categorías top desde -15 % (estrella) o -18 % (resto), siempre frente al mínimo de 30 días. A las 23:59 se cierra el día con el resumen de los 10 mejores que siguen activos; después no sale nada hasta las 08:00. Cada post enseña además el descuento frente a su precio habitual de 90 días cuando es bastante mayor. Ajustes en `config.json` → `amazon_channel`. Memoria en `state/canal_nube.json`.

Pruebas desde Actions → «Canal normal @cazachollos_com» → Run workflow: `dry_run` (no envía nada) o `test_private` sin `dry_run` (hasta 3 ejemplos a tu chat, nunca al canal).

### Post manual (`publicar-manual.yml`)

Para publicar a mano un chollo concreto en @cazachollos_com: Actions → «Post manual @cazachollos_com» → Run workflow, con `datos` en JSON y `privado` marcado para probar en tu chat (desmárcalo para el canal). Campos: `url` (amazon.es/dp/…, link.amazon, amzn.eu) o `asin`, `title`, `price`, `reference` (el «precio más bajo de los últimos 30 días» que muestra Amazon), `image` (ruta en `images/manual/` o URL), `seen_at` (hora vista, HH:MM), `lines` (líneas extra) y opcionales `habitual`, `rating`, `reviews`, `historical_low`. Si el precio de referencia no es mayor que el actual o el enlace no es del producto, no se publica.

## Web escaparate (GitHub Pages, `docs/`)

Web pública con los chollos del canal normal: https://enriquegarciamarketing-byte.github.io/caza-errores-telegram/

- Cada vez que se guarda la memoria del canal (`tools/guardar_memoria.sh`), `web_export.py` rehace `docs/chollos.json` con lo publicado en las últimas 48 h (las que el bot vigila): título, precio, precio de referencia, hora y si ya no está a ese precio.
- `docs/index.html` lee ese JSON directamente de GitHub (raw), así que se actualiza sola sin volver a desplegar Pages. Refresca cada 5 minutos.
- Mismo enlace de afiliado que el canal, aviso de Afiliado de Amazon en el pie y sin fotos de Amazon (solo se podrán poner cuando los datos vengan de la Creators API).
- Sirve como sitio web para registrar en Amazon Afiliados junto al canal de Telegram y X.

## Cascada premium → canal normal (02/11/2026)

Lo que el premium descarta **porque no da para revender** (sin margen en Wallapop, fuera de las categorías de reventa, ahorro o importe pequeños, rebaja menor que la del premium) baja al canal normal, que lo revisa con **todas** sus reglas: relee la ficha, descuento real frente al mínimo de 30 días, interés, foto, precio visto hace menos de una hora y segunda lectura antes de enviar.

- Solo Amazon.es visto en Jimmyleaks. Nada de Chollometro ni de otras tiendas.
- Nunca baja lo que el premium ha publicado ni lo que espera tu OK.
- Nunca baja lo descartado por datos dudosos (precio que no cuadra, datos viejos, sin stock, tallas, descuento sospechoso, media inflada…): hay una lista blanca de motivos en `cascada.py`.
- El premium sube la lista en cada pasada a la rama `cascada` (un solo commit que se sobrescribe; main no se ensucia). El canal normal la lee en cada pasada y tiene `cascade_max_details` fichas extra solo para eso, sin quitar sitio a sus listados.
- Los posts que salen así quedan marcados en `state/canal_nube.json` con `"origen": "premium"`.
- Pruebas: el premium en `dry_run` sube la lista a la rama `cascada-prueba`; el canal normal en `test_private` la lee y te manda primero esos ejemplos. El canal real solo lee `cascada`.
- Interruptor: `config.json` → `cascada.enabled` (y `amazon_channel.cascade_enabled`).

## Escáner automático (scan-deals.yml)

**Fiabilidad (31/10/2026).** Amazon: el descuento se calcula frente al precio más bajo de los 30 días anteriores a la bajada (o la Amazon UE más barata), nunca frente a la media de 90 días ni el PVP; el enlace va al producto exacto (`/dp/ASIN` sacado del botón de compra de Jimmyleaks), nunca a una búsqueda por EAN; el precio se ve hace menos de 60 minutos y se relee justo antes de publicar. Otras tiendas: el enlace sale sin afiliados ajenos (si no se puede limpiar, no se publica) y el precio tiene que aparecer en la propia página de la tienda (`resale.external_require_verified`). Los posts de las últimas 48 h se revisan y, si suben o se agotan, se marcan «⛔ YA NO ESTÁ A ESTE PRECIO».

**Errores de precio y frecuencia (02/11/2026).** GitHub arranca la tarea más o menos una vez por hora aunque esté programada cada 10 minutos, así que cada ejecución programada hace pasadas seguidas durante 40 minutos, una cada 2,5 minutos, las 24 horas. En cada pasada lee mínimos de hoy, actualizados y bajadas de la última hora (`?order=-drop`), y por turnos 5 de los 21 listados de `rotating_sources` (hogar, grandes electrodomésticos, salud, informática…). Chollometro se mira cada 4 pasadas y cada ficha se abre como mucho una vez cada 6 h.

- Un **error de precio** (-70 % o más frente a la referencia honesta) entra aunque no sea de una categoría premium ni llegue a 25 € (una Conga a 23 € que vale 370 €), si es de marca, tiene al menos 15 opiniones y 3,8 estrellas y normalmente vale 60 € o más (`error_min_reference_eur`, `error_min_reviews`, `error_min_rating`).
- Hasta -92 % sale solo. De -92 % a -98 % te llega por privado con la tarjeta y sale en cuanto respondes **OK** a ese mensaje (caduca en 1 h; justo antes de publicar se relee la ficha). Por encima de -98 % se descarta como dato roto (`error_auto_max_discount`, `error_max_discount`, `error_ask_hours`).
- **Tiendas que no dejan leer su página** desde GitHub (AliExpress, Zalando, Privalia…): ya no se tiran ni salen solas. Te llegan por privado y salen con tu **OK** (caduca en 3 h, `resale.external_ask_admin`, `resale.external_ask_hours`). Lo que espera tu OK no gasta cupo de gangas.

Pruebas: Actions → «Escanear chollos automáticamente» → Run workflow con `dry_run` y, si quieres ver varias pasadas, `minutes` (por ejemplo 6).

Cada pasada, `scanner.py`:

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
