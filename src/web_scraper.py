"""Scrapea las categorías de pewenpisos.com.ar y extrae todas las imágenes de productos.

El sitio usa lazy-load: las URLs reales están en data-src / data-lazy-src / srcset,
no en src. Filtramos placeholders SVG y logos/íconos chicos.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import HTTP_HEADERS, REQUEST_TIMEOUT, SITE_BASE, SITE_CATEGORIES

LAZY_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-bg", "data-srcset", "data-lazy-srcset")
EXCLUDE_PATTERNS = (
    "logo", "icon", "favicon", "placeholder",
    "whatsapp", "instagram", "facebook", "wp-includes",
    # promos bancarias / sliders del WP — no son productos
    "promo", "promocion", "hipotecario", "estrellas", "naranja-",
    "mipyme", "bnaconecta", "pymenacion", "agronacion", "payway",
    "mercadopago", "banco-", "tarjeta-", "cuotas-",
)
MIN_DIM = 200
MAIN_SELECTORS = ("main", "#content", "article")


def _es_pewen(url: str) -> bool:
    try:
        host = urlparse(url).netloc
    except Exception:
        return False
    return host.endswith("pewenpisos.com.ar")


def _es_imagen(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return lower.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _es_excluida(url: str) -> bool:
    low = url.lower()
    if any(p in low for p in EXCLUDE_PATTERNS):
        return True
    if low.startswith("data:"):
        return True
    return False


def _extraer_dims_wp(url: str) -> tuple[int | None, int | None]:
    """WordPress sufija las imágenes redimensionadas con -WxH.jpg. Extraemos eso."""
    m = re.search(r"-(\d{2,4})x(\d{2,4})\.(jpg|jpeg|png|webp)", url, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _normalizar_url_imagen(url: str) -> str:
    """Saca el sufijo -WxH para quedarnos con la versión original (más grande)
    y colapsa // duplicados del path."""
    url = re.sub(r"-(\d{2,4})x(\d{2,4})(\.(jpg|jpeg|png|webp))", r"\3", url, flags=re.I)
    url = re.sub(r"(?<!:)//+", "/", url)
    return url


def _primera_url_srcset(srcset: str) -> str | None:
    if not srcset:
        return None
    candidatos = [c.strip().split()[0] for c in srcset.split(",") if c.strip()]
    return candidatos[-1] if candidatos else None  # último suele ser el más grande


def scrapear_categoria(path: str) -> list[dict]:
    """Devuelve lista de dicts con keys: url, alt, title, categoria, src_page."""
    url = urljoin(SITE_BASE, path)
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"[scraper] {url} -> HTTP {r.status_code}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"[scraper] error {url}: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, "lxml")
    categoria = _slug_a_nombre(path)
    encontradas: dict[str, dict] = {}

    raiz = None
    for sel in MAIN_SELECTORS:
        raiz = soup.select_one(sel)
        if raiz:
            break
    if raiz is None:
        raiz = soup

    for img in raiz.find_all("img"):
        candidatos = []

        for attr in ("src", *LAZY_ATTRS):
            v = img.get(attr)
            if not v:
                continue
            if attr.endswith("srcset"):
                primera = _primera_url_srcset(v)
                if primera:
                    candidatos.append(primera)
            else:
                candidatos.append(v)

        srcset = img.get("srcset")
        if srcset:
            primera = _primera_url_srcset(srcset)
            if primera:
                candidatos.append(primera)

        for raw in candidatos:
            full = urljoin(url, raw.strip())
            if not _es_imagen(full):
                continue
            if not _es_pewen(full):
                continue
            if _es_excluida(full):
                continue

            w, h = _extraer_dims_wp(full)
            if w and h and (w < MIN_DIM or h < MIN_DIM):
                continue

            url_norm = _normalizar_url_imagen(full)
            if url_norm in encontradas:
                continue

            alt = (img.get("alt") or "").strip()
            title = (img.get("title") or "").strip()
            encontradas[url_norm] = {
                "url": url_norm,
                "alt": alt,
                "title": title,
                "categoria": categoria,
                "src_page": url,
            }

    return list(encontradas.values())


def _slug_a_nombre(path: str) -> str:
    s = path.strip("/").replace("-", " ")
    return s[:1].upper() + s[1:] if s else ""


def scrapear_sitio(categorias: list[str] = None) -> list[dict]:
    categorias = categorias or SITE_CATEGORIES
    todas: dict[str, dict] = {}
    for c in categorias:
        items = scrapear_categoria(c)
        print(f"[scraper] {c} -> {len(items)} imágenes")
        for it in items:
            if it["url"] in todas:
                if it["categoria"] not in todas[it["url"]]["categoria"]:
                    todas[it["url"]]["categoria"] += f" / {it['categoria']}"
            else:
                todas[it["url"]] = it
    return list(todas.values())


if __name__ == "__main__":
    items = scrapear_sitio()
    print(f"\nTotal único: {len(items)} imágenes")
    for it in items[:5]:
        print(f"  · [{it['categoria']}] {it['url']}  alt={it['alt'][:40]!r}")
