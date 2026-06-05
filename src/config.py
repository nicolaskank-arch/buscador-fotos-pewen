from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/11fqLMp8nndRy1sAEWAZmRYHDoYdgazjn"

SITE_BASE = "https://pewenpisos.com.ar"

SITE_CATEGORIES = [
    "/pisos-flotantes-clasicos/",
    "/pisos-flotantes-alta-gama/",
    "/pisos-flotantes-water-resistant/",
    "/pisos-vinilicos-2/",
    "/pisos-de-porcelanato/",
    "/porcelanato-cemento/",
    "/porcelanato-marmol/",
    "/porcelanato-madera/",
    "/deck/",
    "/prefinished/",
    "/homogeneos/",
    "/tecnicos/",
    "/accesorios/",
    "/revestimientodepared/",
    "/revestimiento-interior-eps/",
    "/revestimiento-exterior-wpc/",
    "/piedrafina/",
    "/revestimiento-madera/",
    "/trabajos/",
]

DB_PATH = ROOT / "fotos.db"
THUMBS_DIR = ROOT / "thumbs"
CACHE_DIR = ROOT / "cache"

THUMB_SIZE = 400
THUMB_QUALITY = 82

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PewenBuscadorBot/1.0; +https://pewenpisos.com.ar)"
}

REQUEST_TIMEOUT = 20
