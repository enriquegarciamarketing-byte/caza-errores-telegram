# Cazadores de Errores de Precio — Telegram

Publicador de ofertas revisadas para `@caza_errores`. GitHub Actions genera una tarjeta de precio con la foto que se aporte, conserva el enlace corto de afiliado y publica la imagen con su pie en Telegram. Solo procesa ofertas con `status: "approved"`.

## Qué queda automatizado

- Crea la tarjeta en el formato de referencia: precio normal, precio actual, ahorro y porcentaje.
- Exige al menos tres anuncios comparables revisados de Wallapop, calcula la media de sus precios anunciados y estima ROI después de las comisiones y el envío que se indiquen.
- Envía foto y pie con el enlace afiliado corto (`link.amazon` o `amzn.to`), el aviso de afiliación y que precio/stock pueden cambiar.
- Rechaza datos sin revisar, precios con más de 20 minutos, anuncios comparables sin enlaces Wallapop válidos, ofertas duplicadas o imágenes que falten.

## Qué requiere revisión manual

Este repositorio **no rastrea Amazon ni busca anuncios en Wallapop**. Wallapop indica en sus términos que no se pueden usar robots ni extraer datos sistemáticamente sin autorización expresa por escrito, y que las herramientas externas tipo bot requieren autorización. Por eso, hasta tener un acceso oficial autorizado, añade manualmente los comparables y sus precios a `offers.json`; el bot promedia esos datos y no inicia sesión ni raspa el sitio.

Los anuncios de Wallapop muestran precios pedidos, no importes de ventas cerradas. Usa productos exactos siempre que puedas. Si introduces productos parecidos, el post y la tarjeta los identificarán como similares. El ROI es una estimación bruta antes de impuestos basada en la media y en las comisiones/envío indicados; no garantiza que se venda a ese precio.

La detección de errores de precio en Amazon también necesita una fuente histórica cuyo uso y publicación estén autorizados. El proyecto no consulta ni extrae las páginas de Amazon. Verifica además que tu canal está aprobado por Amazon Afiliados y que el contenido y uso del enlace cumplen las condiciones de tu cuenta. Amazon restringe ciertos usos de enlaces especiales para compras destinadas a reventa.

## Configuración

1. El bot de Telegram debe ser administrador de `@caza_errores` con permiso para publicar mensajes.
2. En GitHub, abre **Settings → Secrets and variables → Actions** y añade:
   - `TELEGRAM_BOT_TOKEN`: token de BotFather de este bot.
   - `TELEGRAM_CHAT_ID`: `@caza_errores`.
3. En **Settings → Actions → General**, permite que los workflows escriban en el repositorio para registrar los IDs publicados.
4. Usa **Actions → Publicar ofertas aprobadas → Run workflow** para lanzarlo manualmente. También se inicia al cambiar `offers.json`.

No pongas el token en `offers.json`, en el código ni en un commit. Guárdalo solo como secreto de GitHub.

## Preparar una publicación

1. Coloca una foto de producto con licencia/permiso de uso en `images/`, por ejemplo `images/ram-ddr4.jpg`. No descargues fotos de Amazon para republicarlas sin permiso.
2. Añade un elemento a `offers.json` siguiendo este ejemplo. Los precios de Wallapop se recopilan y comprueban manualmente; reemplaza los datos ficticios y cambia `draft` a `approved` solo tras verificar producto, variante, estado, vendedor, precio y comparables. Sin tres anuncios comparables revisados, el bot no publica.

```json
[
  {
    "id": "B0XXXXXXXX-20261028-1200",
    "status": "draft",
    "asin": "B0XXXXXXXX",
    "title": "Nombre exacto del producto y variante",
    "affiliate_url": "https://link.amazon/TU-ENLACE-CORTO",
    "image_path": "ram-ddr4.jpg",
    "current_price_eur": 64.20,
    "reference_price_eur": 173.51,
    "reference_period_days": 90,
    "reference_source": "Proveedor histórico autorizado",
    "reference_source_url": "https://proveedor.example/producto",
    "checked_at": "2026-10-28T12:00:00+02:00",
    "approved_by": "tu nombre",
    "wallapop_comparables": [
      {"title": "Anuncio del mismo producto, capacidad y estado", "match": "exacto", "price_eur": 129.00, "url": "https://es.wallapop.com/item/anuncio-1"},
      {"title": "Anuncio del mismo producto, capacidad y estado", "match": "exacto", "price_eur": 139.00, "url": "https://es.wallapop.com/item/anuncio-2"},
      {"title": "Anuncio de producto comparable", "match": "similar", "price_eur": 149.00, "url": "https://es.wallapop.com/item/anuncio-3"}
    ],
    "resale_fees_eur": 10.00,
    "resale_shipping_eur": 0.00
  }
]
```

`asin` debe ser el ASIN real de 10 caracteres; en `affiliate_url` pega exactamente el enlace corto que genera tu cuenta. Confirma que abre la ficha de la variante correcta y conserva tu etiqueta de afiliado. La imagen debe estar en `images/`; `image_path` lleva solo su nombre.

Incluye al menos tres anuncios Wallapop. `match` acepta `exacto` o `similar`; si uno o más son similares, el resultado se etiquetará como media de anuncios similares. El ROI usa: `(media Wallapop − precio Amazon − comisiones − envío) / precio Amazon × 100`. Introduce `0` si una comisión/envío no aplica.

## Coste y límites

Telegram Bot API y GitHub Actions pueden funcionar sin coste dentro de las cuotas de GitHub. La acción solo publica ofertas aprobadas; no hay una fuente gratuita autorizada configurada para descubrir errores de precio. Un feed automático requerirá una API/proveedor compatible y permiso para publicar sus datos.

Referencias: [Términos de Wallapop](https://about.wallapop.com/condiciones-de-uso/), [políticas de Amazon Afiliados España](https://afiliados.amazon.es/help/operating/policies), [licencia de uso de contenido y API de Amazon](https://afiliados.amazon.es/help/operating/license), [Telegram Bot API](https://core.telegram.org/bots/api).
