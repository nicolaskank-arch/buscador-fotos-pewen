"""Scrapea las categorías de pewenpisos.com.ar + cada página de producto.

El sitio usa lazy-load: las URLs reales están en data-src / data-lazy-src / srcset.
Filtramos placeholders, logos, promos bancarias y limitamos a <main>.

Flujo:
  1. Para cada categoría (/pisos-flotantes-clasicos/, etc.):
     - Scrapeo las imágenes que están directamente en la grid.
     - Extraigo todos los links a /producto/X/ y los visito en paralelo.
     - Cada página de producto suele tener 3-5 fotos del mismo material.
  2. Dedup global por URL final (sin el sufijo -WxH de WordPress).
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import HTTP_HEADERS, REQUEST_TIMEOUT, SITE_BASE, SITE_CATEGORIES

LAZY_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-bg", "data-srcset", "data-lazy-srcset")
EXCLUDE_PATTERNS = (
    "logo", "icon", "favicon", "placeholder",
    "whatsapp", "instagram", "facebook", "wp-includes",
    "promo", "promocion", "hipotecario", "estrellas", "naranja-",
    "mipyme", "bnaconecta", "pymenacion", "agronacion", "payway",
    "mercadopago", "banco-", "tarjeta-", "cuotas-",
)
MIN_DIM = 200
MAIN_SELECTORS = ("main", "#content", "article")
PRODUCT_LINK_RE = re.compile(r"/producto/[a-z0-9\-]+/?$", re.I)
WORKERS_PRODUCTOS = 16


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
    m = re.search(r"-(\d{2,4})x(\d{2,4})\.(jpg|jpeg|png|webp)", url, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _normalizar_url_imagen(url: str) -> str:
    url = re.sub(r"-(\d{2,4})x(\d{2,4})(\.(jpg|jpeg|png|webp))", r"\3", url, flags=re.I)
    url = re.sub(r"(?<!:)//+", "/", url)
    return url


def _primera_url_srcset(srcset: str) -> str | None:
    if not srcset:
        return None
    candidatos = [c.strip().split()[0] for c in srcset.split(",") if c.strip()]
    return candidatos[-1] if candidatos else None


def _slug_a_nombre(path: str) -> str:
    s = path.strip("/").replace("-", " ")
    return s[:1].upper() + s[1:] if s else ""


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"[scraper] error {url}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"[scraper] {url} -> HTTP {r.status_code}", file=sys.stderr)
        return None
    return BeautifulSoup(r.text, "lxml")


def _raiz_main(soup: BeautifulSoup):
    for sel in MAIN_SELECTORS:
        raiz = soup.select_one(sel)
        if raiz:
            return raiz
    return soup


def _imgs_de_soup(raiz, page_url: str, categoria: str) -> dict[str, dict]:
    """Extrae el dict {url_normalizada: row} de un fragmento HTML."""
    encontradas: dict[str, dict] = {}
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
            full = urljoin(page_url, raw.strip())
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
                "src_page": page_url,
            }

    return encontradas


def _links_producto(raiz, base_url: str) -> list[str]:
    urls = set()
    for a in raiz.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base_url, href)
        if _es_pewen(full) and PRODUCT_LINK_RE.search(urlparse(full).path):
            urls.add(full.split("?")[0].split("#")[0])
    return sorted(urls)


def scrapear_pagina_producto(url: str, categoria: str) -> dict[str, dict]:
    soup = _fetch_soup(url)
    if soup is None:
        return {}
    return _imgs_de_soup(_raiz_main(soup), url, categoria)


def scrapear_categoria(path: str) -> dict[str, dict]:
    """Scrapea la grid + todas las páginas de producto linkeadas desde ahí."""
    url = urljoin(SITE_BASE, path)
    soup = _fetch_soup(url)
    if soup is None:
        return {}
    raiz = _raiz_main(soup)
    categoria = _slug_a_nombre(path)

    encontradas = _imgs_de_soup(raiz, url, categoria)
    productos = _links_producto(raiz, url)
    print(f"[scraper] {path} -> {len(encontradas)} en grid, {len(productos)} productos")

    if productos:
        with ThreadPoolExecutor(max_workers=WORKERS_PRODUCTOS) as ex:
            futures = {ex.submit(scrapear_pagina_producto, p, categoria): p for p in productos}
            for f in as_completed(futures):
                try:
                    extras = f.result()
                except Exception as e:
                    print(f"[scraper] producto fail: {e}", file=sys.stderr)
                    continue
                for k, v in extras.items():
                    if k not in encontradas:
                        encontradas[k] = v

    return encontradas


def scrapear_sitio(categorias: list[str] = None) -> list[dict]:
    categorias = categorias or SITE_CATEGORIES
    todas: dict[str, dict] = {}
    for c in categorias:
        items = scrapear_categoria(c)
        print(f"[scraper] {c} -> {len(items)} imágenes totales")
        for url, row in items.items():
            if url in todas:
                if row["categoria"] not in todas[url]["categoria"]:
                    todas[url]["categoria"] += f" / {row['categoria']}"
            else:
                todas[url] = row
    return list(todas.values())


if __name__ == "__main__":
    import sys
    cats = [sys.argv[1]] if len(sys.argv) > 1 else None
    items = scrapear_sitio(cats)
    print(f"\nTotal único: {len(items)} imágenes")
    for it in items[:8]:
        print(f"  · [{it['categoria']}] {it['url']}  alt={it['alt'][:40]!r}")
