"""Etiqueta de sección de cada post del premium (23/11/2026, Enrique): debajo de #ErrorDePrecio / #Chollo,
un #Moda, #Reacondicionado, #Tecnología… para que la gente sepa de un vistazo qué es.
Se decide por el tipo de canal (warehouse → #Reacondicionado) y por las palabras del título (primero el arranque,
que dice qué es el producto; si no, el título entero)."""
from __future__ import annotations

import re
import unicodedata

# Orden = prioridad (Bebé antes que Alimentación: «yogur desde 6 meses» es de bebé).
SECCIONES = [
    ("#Bebé", ["bebe", "bebes", "pañal", "panales", "toallitas", "biberon", "chupete", "carrito", "cuna",
               "desde 6 meses", "desde 4 meses", "infantil", "silla de coche"]),
    ("#Gaming", ["ps5", "ps4", "playstation", "xbox", "nintendo", "switch", "videojuego", "consola", "gaming",
                 "mando inalambrico", "steam deck"]),
    ("#Tecnología", ["movil", "smartphone", "iphone", "samsung galaxy", "xiaomi redmi", "tablet", "ipad", "portatil",
                     "ordenador", "monitor", "auriculares", "cascos", "airpods", "altavoz", "smartwatch", "reloj inteligente",
                     "camara", "gopro", "insta360", "televisor", "smart tv", "tv", "ssd", "disco duro", "pendrive",
                     "tarjeta microsd", "raton", "teclado", "router", "powerbank", "bateria externa", "cargador",
                     "proyector", "kindle", "echo", "fire tv", "chromecast", "impresora", "dron", "drone"]),
    ("#Hogar", ["aspirador", "aspiradora", "robot aspirador", "fregasuelos", "cafetera", "freidora", "microondas",
                "lavadora", "secadora", "lavavajillas", "nevera", "frigorifico", "horno", "batidora", "robot de cocina",
                "sofa", "colchon", "almohada", "edredon", "sabanas", "toalla", "sarten", "olla", "bateria de cocina",
                "lampara", "silla", "mesa", "estanteria", "purificador", "ventilador", "calefactor", "radiador",
                "deshumidificador", "humidificador", "plancha de vapor", "vaporeta", "detergente", "suavizante",
                "lavavajillas", "papel higienico", "bombilla"]),
    ("#Belleza", ["champu", "acondicionador", "gel de ducha", "crema", "serum", "perfume", "colonia", "eau de",
                  "maquillaje", "desodorante", "cepillo de dientes", "cepillo electrico", "afeitadora", "depiladora",
                  "secador", "plancha de pelo", "rizador", "cuchillas", "protector solar", "neutrogena", "nivea"]),
    ("#Moda", ["camiseta", "pantalon", "vaqueros", "jeans", "zapatillas", "zapatos", "botas", "sandalias",
               "chaqueta", "abrigo", "cazadora", "sudadera", "jersey", "vestido", "falda", "bolso", "cartera",
               "cinturon", "gorra", "calcetines", "sujetador", "bañador", "reloj", "gafas de sol", "mochila", "chandal",
               "polo", "camisa", "leggings", "parka", "plumifero"]),
    ("#Deporte", ["bicicleta", "mancuernas", "pesas", "esterilla", "running", "fitness", "patinete", "cinta de correr",
                  "proteina", "creatina", "raqueta", "balon", "padel"]),
    ("#Juguetes", ["lego", "juguete", "muñeca", "puzzle", "playmobil", "peluche", "hot wheels", "nerf", "juego de mesa"]),
    ("#Bricolaje", ["taladro", "atornillador", "herramienta", "sierra", "amoladora", "lijadora", "caja de herramientas",
                    "brocas", "compresor", "hidrolimpiadora", "cortacesped"]),
    ("#Mascotas", ["perro", "perros", "gato", "gatos", "pienso", "arena para gatos", "mascota"]),
    ("#Motor", ["coche", "neumatico", "dashcam", "moto", "casco de moto", "aceite de motor"]),
    ("#Alimentación", ["chocolate", "bombones", "cafe en grano", "cafe molido", "capsulas", "aceite de oliva", "aceite",
                       "cerveza", "vino", "galletas", "jerky", "snack", "patatas fritas", "leche", "refresco", "monster",
                       "red bull", "coca-cola", "agua mineral", "yogur", "cereales", "atun", "nestle", "colacao"]),
]
POR_CANAL = {"warehouse": "#Reacondicionado", "ropa": "#Moda"}
DEFECTO = {"basicos": "#DelDíaADía"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _busca(texto: str) -> str | None:
    folded = _fold(texto)
    for etiqueta, palabras in SECCIONES:
        if any(re.search(rf"(?<![\w]){re.escape(_fold(p))}(?![\w])", folded) for p in palabras):
            return etiqueta
    return None


def seccion(titulo: str, tipo: str = "general") -> str | None:
    if tipo in POR_CANAL:
        return POR_CANAL[tipo]
    if _busca_en(titulo, "#Bebé"):  # «yogur desde 6 meses» es de bebé aunque arranque por yogur
        return "#Bebé"
    arranque = " ".join((titulo or "").split()[:4])
    return _busca(arranque) or _busca(titulo) or DEFECTO.get(tipo)


def _busca_en(texto: str, etiqueta: str) -> bool:
    folded = _fold(texto)
    palabras = dict(SECCIONES).get(etiqueta) or []
    return any(re.search(rf"(?<![\w]){re.escape(_fold(p))}(?![\w])", folded) for p in palabras)
