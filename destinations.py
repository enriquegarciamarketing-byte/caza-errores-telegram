"""Foto del destino para las tarjetas de viaje. Commons si está en la lista; si no, Wikipedia."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import wallapop

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "output" / "destinations"
USER_AGENT = "CazaChollosBot/1.0 (https://t.me/cazachollos_com)"
# Ciudades por encima de países: «Roma, Italia» enseña el Coliseo, no un mapa.
CITY = 2
COUNTRY = 1

# (claves en español, título de Wikipedia, archivo de Commons ya comprobado o "")
_PLACES = [
    (("nueva york",), "Nueva York", "Statue_of_Liberty,_NY.jpg", CITY),
    (("paris", "disneyland paris"), "Torre Eiffel", "Tour_Eiffel_Wikimedia_Commons.jpg", CITY),
    (("egipto", "el cairo", "giza", "piramides"), "Pirámides de Guiza", "All_Gizah_Pyramids.jpg", CITY),
    (("roma", "coliseo"), "Coliseo", "Colosseum_in_Rome,_Italy_-_April_2007.jpg", CITY),
    (("barcelona",), "Templo Expiatorio de la Sagrada Familia", "Sagrada_Familia_01.jpg", CITY),
    (("londres",), "Big Ben", "Elizabeth_Tower,_June_2022.jpg", CITY),
    (("praga",), "Puente de Carlos", "Charles_Bridge_in_Prague.jpg", CITY),
    (("atenas",), "Acrópolis de Atenas", "Acropolis_of_Athens.jpg", CITY),
    (("estambul",), "Santa Sofía", "Hagia_Sophia_Mars_2013.jpg", CITY),
    (("santorini", "oia"), "Santorini", "Santorini_Oia.jpg", CITY),
    (("mykonos",), "Miconos", "Mykonos_windmills.jpg", CITY),
    (("marrakech", "marruecos"), "Marrakech", "Koutoubia_Mosque.jpg", CITY),
    (("mallorca", "palma de mallorca"), "Palma de Mallorca", "Cathedral_of_Palma_de_Mallorca.jpg", CITY),
    (("rio de janeiro", "rio"), "Cristo Redentor", "Christ_the_Redeemer_-_Cristo_Redentor.jpg", CITY),
    (("machu picchu", "cusco", "peru"), "Machu Picchu", "Machu_Picchu,_Peru.jpg", CITY),
    (("taj mahal", "agra"), "Taj Mahal", "Taj_Mahal_(Edited).jpeg", CITY),
    (("sidney", "sydney"), "Ópera de Sídney", "Sydney_Opera_House_-_Dec_2008.jpg", CITY),
    (("granada", "alhambra"), "Alhambra", "Alhambra_Granada.jpg", CITY),
    (("madrid",), "Puerta de Alcalá", "Puerta_de_Alcalá,_Madrid.jpg", CITY),
    (("milan", "milano"), "Milán", "Piazza_del_Duomo_Milano.jpg", CITY),
    (("venecia",), "Venecia", "Canal_Grande_Chiesa_della_Salute_e_Dogana_dal_ponte_dell_Accademia.jpg", CITY),
    (("lisboa", "belem"), "Torre de Belém", "Belem_Tower.jpg", CITY),
    (("berlin",), "Puerta de Brandeburgo", "Brandenburg_Gate.jpg", CITY),
    (("tenerife", "teide"), "Teide", "Teide_Tenerife.jpg", CITY),
    (("florencia",), "Catedral de Santa María del Fiore", "Florence_Cathedral.jpg", CITY),
    (("amsterdam",), "Ámsterdam", "Amsterdam_Canal.jpg", CITY),
    (("petra", "jordania"), "Petra", "Al_Khazneh.jpg", CITY),
    (("chichen itza", "cancun", "riviera maya", "tulum"), "Chichén Itzá", "Chichen_Itza_3.jpg", CITY),
    (("angkor", "camboya"), "Angkor Wat", "Angkor_Wat.jpg", CITY),
    (("ciudad del cabo", "sudafrica"), "Ciudad del Cabo", "Table_Mountain_Cape_Town.jpg", CITY),
    (("sevilla",), "Catedral de Sevilla", "Sevilla_Cathedral_-_Southeast.jpg", CITY),
    (("edimburgo", "escocia"), "Castillo de Edimburgo", "Edinburgh_Castle.jpg", CITY),
    (("copenhague", "dinamarca"), "Nyhavn", "Nyhavn.jpg", CITY),
    (("suiza", "matterhorn", "zermatt"), "Alpes suizos", "Matterhorn.jpg", COUNTRY),
    (("las vegas",), "Las Vegas", "Las_Vegas_Strip.jpg", CITY),
    (("san francisco",), "Puente Golden Gate", "Golden_Gate_Bridge.jpg", CITY),
    (("iguazu", "cataratas"), "Cataratas del Iguazú", "Iguazu_Falls.jpg", CITY),
    (("bangkok", "tailandia"), "Gran Palacio de Bangkok", "Grand_Palace_Bangkok.jpg", CITY),
    (("tokio", "japon", "fuji", "kioto"), "Monte Fuji", "Mount_Fuji.jpg", CITY),
    (("pekin", "china", "muralla"), "Gran Muralla China", "Great_Wall_of_China.jpg", CITY),
    (("baviera", "munich", "munich"), "Castillo de Neuschwanstein", "Neuschwanstein_Castle.jpg", CITY),
    (("grecia",), "Acrópolis de Atenas", "Acropolis_of_Athens.jpg", COUNTRY),
    (("capadocia", "turquia"), "Capadocia", "Cappadocia.jpg", CITY),
    (("tunez", "djerba"), "Túnez", "Amphitheatre_of_El_Jem.jpg", COUNTRY),
    (("lanzarote",), "Timanfaya", "Timanfaya.jpg", CITY),
    (("bilbao",), "Museo Guggenheim Bilbao", "Guggenheim_Bilbao.jpg", CITY),
    (("valencia",), "Ciudad de las Artes y las Ciencias", "City_of_Arts_and_Sciences.jpg", CITY),
    (("pisa",), "Torre de Pisa", "Leaning_Tower_of_Pisa.jpg", CITY),
    (("budapest",), "Parlamento de Budapest", "Hungarian_Parliament_Building_from_across_the_Danube.jpg", CITY),
    (("viena",), "Palacio de Schönbrunn", "Schonbrunn.jpg", CITY),
    (("cracovia", "polonia"), "Castillo de Wawel", "Wawel_Castle.jpg", CITY),
    (("bruselas",), "Atomium", "Atomium.jpg", CITY),
    (("dublin", "irlanda"), "Dublín", "", COUNTRY),
    (("rusia", "moscu", "san petersburgo"), "Catedral de San Basilio", "Saint_Basil's_Cathedral.jpg", CITY),
    (("los angeles", "hollywood"), "Hollywood", "Hollywood_Sign.jpg", CITY),
    (("miami", "orlando"), "Miami", "Miami_skyline.jpg", CITY),
    (("singapur",), "Marina Bay Sands", "Marina_Bay_Sands.jpg", CITY),
    (("bali", "indonesia"), "Tanah Lot", "Tanah_Lot.jpg", CITY),
    (("vietnam", "halong", "ha long"), "Bahía de Ha Long", "Ha_Long_Bay.jpg", CITY),
    (("maldivas",), "Maldivas", "Maldives.jpg", COUNTRY),
    (("isla de pascua",), "Moái", "Moai.jpg", CITY),
    (("punta cana", "republica dominicana"), "Punta Cana", "Punta_Cana_beach.jpg", CITY),
    (("habana", "cuba", "varadero"), "El Capitolio", "El_Capitolio.jpg", CITY),
    (("buenos aires", "argentina"), "Buenos Aires", "Obelisco_de_Buenos_Aires.jpg", CITY),
    (("patagonia", "torres del paine", "chile"), "Torres del Paine", "Torres_del_Paine.jpg", CITY),
    (("cordoba",), "Mezquita-catedral de Córdoba", "Mezquita_de_Cordoba.jpg", CITY),
    (("santiago de compostela", "galicia"), "Catedral de Santiago de Compostela", "Santiago_de_Compostela_Cathedral.jpg", CITY),
    (("oporto", "porto"), "Oporto", "Porto_Ribeira.jpg", CITY),
    (("colonia",), "Catedral de Colonia", "Cologne_Cathedral.jpg", CITY),
    (("noruega", "fiordos"), "Geirangerfjord", "Geirangerfjord.jpg", COUNTRY),
    (("islandia",), "Islandia", "Hallgrimskirkja.jpg", COUNTRY),
    (("croacia", "dubrovnik"), "Lagos de Plitvice", "Plitvice_Lakes.jpg", COUNTRY),
    (("eslovenia", "bled"), "Lago Bled", "Lake_Bled.jpg", CITY),
    (("finlandia", "helsinki"), "Catedral de Helsinki", "Helsinki_Cathedral.jpg", CITY),
    (("chefchaouen",), "Chefchaouen", "Chefchaouen.jpg", CITY),
    (("jerusalen", "israel"), "Cúpula de la Roca", "Dome_of_the_Rock.jpg", CITY),
    (("amalfi", "positano", "costa amalfitana"), "Costa Amalfitana", "Positano.jpg", CITY),
    (("lago de como", "lago como"), "Lago de Como", "Lake_Como.jpg", CITY),
    (("cinque terre",), "Cinque Terre", "Cinque_Terre.jpg", CITY),
    (("nueva zelanda",), "Nueva Zelanda", "", COUNTRY),
    (("hong kong",), "Hong Kong", "Hong_Kong_Island_Skyline_2009.jpg", CITY),
    (("seul", "corea"), "Seúl", "", CITY),
    (("india",), "Taj Mahal", "Taj_Mahal_(Edited).jpeg", COUNTRY),
    (("mexico",), "Ciudad de México", "", COUNTRY),
    (("italia",), "Italia", "Colosseum_in_Rome,_Italy_-_April_2007.jpg", COUNTRY),
    (("francia",), "París", "Tour_Eiffel_Wikimedia_Commons.jpg", COUNTRY),
    (("reino unido", "inglaterra"), "Londres", "Elizabeth_Tower,_June_2022.jpg", COUNTRY),
    (("alemania",), "Berlín", "Brandenburg_Gate.jpg", COUNTRY),
    (("portugal",), "Lisboa", "Belem_Tower.jpg", COUNTRY),
    (("grecia",), "Grecia", "Acropolis_of_Athens.jpg", COUNTRY),
    (("canarias",), "Teide", "Teide_Tenerife.jpg", COUNTRY),
]


def _fold(value: str) -> str:
    return wallapop.fold_text(value or "")


def _slug(label: str) -> str:
    folded = _fold(label)
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "destino"


def match_destination(title: str) -> dict | None:
    """Destino más específico nombrado en el título, o None."""
    text = _fold(title)
    best = None
    best_score = -1
    for keys, wiki, filename, rank in _PLACES:
        for key in keys:
            if wallapop.keyword_in(text, key):
                score = rank * 1000 + len(key)
                if score > best_score:
                    best_score = score
                    best = {"label": key, "wiki": wiki, "file": filename, "slug": _slug(key)}
    return best


def commons_url(filename: str, width: int = 1600) -> str:
    quoted = urllib.parse.quote(filename)
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quoted}?width={width}"


def _get(url: str, timeout: int = 25) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            kind = (response.headers.get("content-type") or "").lower()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if "text/html" in kind or data[:1] == b"<":
        return None
    if len(data) < 2000:
        return None
    return data


def _wikipedia_image(title: str) -> bytes | None:
    api = "https://es.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))
    request = urllib.request.Request(api, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, UnicodeError):
        return None
    thumb = (payload.get("thumbnail") or {}).get("source") or ""
    original = (payload.get("originalimage") or {}).get("source") or ""
    source = re.sub(r"/\d+px-", "/1600px-", thumb) if thumb else original
    if not source:
        return None
    return _get(source)


def destination_image(title: str, cache_dir: Path | None = None) -> Path | None:
    """Ruta cacheada de la foto del destino, o None si no hay destino o la descarga falla."""
    place = match_destination(title)
    if not place:
        return None
    folder = cache_dir or CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{place['slug']}.jpg"
    if path.exists() and path.stat().st_size > 2000:
        return path
    data = _get(commons_url(place["file"])) if place.get("file") else None
    if data is None:
        data = _wikipedia_image(place["wiki"])
    if not data:
        return None
    path.write_bytes(data)
    return path
