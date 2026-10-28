"""Etiqueta de afiliado en todos los enlaces de Amazon que salen del canal."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

SHORT_HOSTS = {
    "link.amazon", "www.link.amazon",
    "amzn.to", "www.amzn.to",
    "amzn.eu", "www.amzn.eu",
    "amzlinks.in", "www.amzlinks.in",
}
# Saltos habituales de un enlace corto antes de llegar a Amazon.es.
REDIRECT_SUFFIXES = (
    "amazon.es", "amazon.com", "amazon.de", "amazon.fr", "amazon.it",
    "amazon.co.uk", "amazon-adsystem.com",
)
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)
USER_AGENT = "CazaErroresBot/1.0 (+https://t.me/caza_errores)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")


def is_amazon_es(url: str) -> bool:
    host = _host(url)
    return host == "amazon.es" or host.endswith(".amazon.es")


def is_short_link(url: str) -> bool:
    return _host(url) in SHORT_HOSTS


def _redirect_host_ok(url: str) -> bool:
    host = _host(url)
    if host in SHORT_HOSTS:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in REDIRECT_SUFFIXES)


def tag_values(url: str) -> list[str]:
    query = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    return [value for key, value in query if key.lower() == "tag"]


def extract_asin(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url or "")
    match = ASIN_RE.search(parts.path or "")
    if match:
        return match.group(1).upper()
    for key, values in urllib.parse.parse_qs(parts.query).items():
        if key.lower() == "asin" and values and re.fullmatch(r"[A-Z0-9]{10}", values[0].upper()):
            return values[0].upper()
    return None


def force_tag(url: str, tag: str) -> str:
    """Deja un solo parámetro tag, el del canal, y conserva el resto de la consulta."""
    parts = urllib.parse.urlsplit(url.strip())
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() != "tag"]
    query.append(("tag", tag))
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path,
                                    urllib.parse.urlencode(query), parts.fragment))


def fallback_link(tag: str, asin: str | None = None, gtin: str | None = None) -> str | None:
    if asin and re.fullmatch(r"[A-Z0-9]{10}", asin.upper()):
        return f"https://www.amazon.es/dp/{asin.upper()}?tag={urllib.parse.quote(tag)}"
    if gtin and re.fullmatch(r"\d{8,14}", gtin):
        return f"https://www.amazon.es/s?k={urllib.parse.quote(gtin)}&tag={urllib.parse.quote(tag)}"
    return None


def resolve_redirects(url: str, limit: int = 8) -> str:
    """Sigue la cadena HTTP de un enlace corto. No sale de Amazon ni de los acortadores conocidos."""
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(limit):
        if not _redirect_host_ok(current):
            break
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with opener.open(request, timeout=15) as response:
                return response.geturl() or current
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            if not location:
                return current
            current = urllib.parse.urljoin(current, location)
            continue
    return current


def prepare_amazon_link(url: str | None, tag: str, *, asin: str | None = None, gtin: str | None = None,
                        resolve=None) -> tuple[str | None, list[str]]:
    """Devuelve un enlace publicable con la etiqueta del canal, y avisos para el administrador.

    Un amazon.es se reescribe siempre. Un enlace corto se abre; si el destino no lleva
    la etiqueta, o el ASIN no es el del producto, no se usa y se sustituye por /dp/ o por el EAN.
    """
    raw = (url or "").strip()
    warnings: list[str] = []
    if not raw or not tag:
        return fallback_link(tag, asin, gtin) if tag else None, warnings
    if is_short_link(raw):
        return _prepare_short(raw, tag, asin=asin, gtin=gtin, resolve=resolve or resolve_redirects)
    if is_amazon_es(raw):
        return force_tag(raw, tag), warnings
    return raw, warnings


def _prepare_short(url: str, tag: str, *, asin: str | None, gtin: str | None, resolve) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    try:
        final = resolve(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        warnings.append(f"No he podido abrir el enlace corto ({exc}). Publico un enlace con tu etiqueta.")
        return fallback_link(tag, asin, gtin), warnings
    got = extract_asin(final)
    expected = asin.upper() if asin and re.fullmatch(r"[A-Z0-9]{10}", asin.upper()) else None
    if expected and got and got != expected:
        warnings.append(f"El enlace corto resuelve al ASIN {got}, no a {expected}. No lo uso.")
        return fallback_link(tag, expected, gtin), warnings
    tags = tag_values(final)
    if tag not in tags:
        warnings.append("El enlace corto no termina con tu etiqueta de afiliado. Publico el enlace directo.")
        return fallback_link(tag, expected or got, gtin), warnings
    if is_amazon_es(final):
        return force_tag(final, tag), warnings
    if got:
        return fallback_link(tag, got, gtin), warnings
    warnings.append("El enlace corto no acaba en Amazon.es. Publico el enlace directo.")
    return fallback_link(tag, expected, gtin), warnings
