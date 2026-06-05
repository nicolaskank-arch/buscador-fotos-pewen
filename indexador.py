"""Orquestador: lista fotos del Drive + scrapea el sitio, las procesa y guarda en SQLite.

Uso:
    python indexador.py              # incremental (mantiene thumbs ya generados)
    python indexador.py --rebuild    # tira la DB y empieza de cero
    python indexador.py --solo-drive # salta el scraper del sitio
    python indexador.py --solo-web   # salta el sync del drive

Variables de entorno opcionales:
    DRIVE_FOLDER_URL    override de la URL de la carpeta del Drive
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import drive_sync, web_scraper
from src.analyzer import hash_id, procesar
from src.config import DB_PATH, DRIVE_FOLDER_URL, THUMBS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS fotos (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,            -- 'drive' | 'web'
    name        TEXT,
    categoria   TEXT,
    alt         TEXT,
    url_original TEXT,
    url_view    TEXT,
    url_download TEXT,
    thumb_path  TEXT,
    r INTEGER, g INTEGER, b INTEGER,
    h REAL, s REAL, v REAL,
    tono        TEXT,
    width       INTEGER,
    height      INTEGER,
    indexed_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_tono ON fotos(tono);
CREATE INDEX IF NOT EXISTS idx_source ON fotos(source);
CREATE INDEX IF NOT EXISTS idx_categoria ON fotos(categoria);

CREATE VIRTUAL TABLE IF NOT EXISTS fotos_fts USING fts5(
    id UNINDEXED,
    name, alt, categoria,
    content='', tokenize='unicode61'
);
"""


def init_db(rebuild: bool = False) -> sqlite3.Connection:
    if rebuild and DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def upsert_foto(conn: sqlite3.Connection, row: dict) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    conn.execute(
        f"INSERT OR REPLACE INTO fotos ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    conn.execute("DELETE FROM fotos_fts WHERE id = ?", (row["id"],))
    conn.execute(
        "INSERT INTO fotos_fts (id, name, alt, categoria) VALUES (?, ?, ?, ?)",
        (row["id"], row.get("name") or "", row.get("alt") or "", row.get("categoria") or ""),
    )


def ya_procesado(conn: sqlite3.Connection, foto_id: str) -> bool:
    cur = conn.execute("SELECT thumb_path FROM fotos WHERE id = ?", (foto_id,))
    row = cur.fetchone()
    if not row:
        return False
    thumb_relpath = row[0]
    if not thumb_relpath:
        return False
    return (DB_PATH.parent / thumb_relpath).exists()


def _procesar_una(it: dict, source: str, fuente_url_key: str) -> dict | None:
    """Worker thread-safe: descarga, analiza y devuelve la row lista para insertar.

    No toca la DB — eso queda para el main thread (SQLite + threads no se llevan bien).
    """
    clave = it.get(fuente_url_key) or it.get("id") or it.get("url") or ""
    if not clave:
        return None
    foto_id = hash_id(source, clave)
    download_src = it.get("url_thumb_drive") or it.get("url_download") or it.get("url")
    if not download_src:
        return None

    meta = procesar(download_src, foto_id)
    if meta is None:
        return None

    return {
        "id": foto_id,
        "source": source,
        "name": it.get("name") or it.get("alt") or "",
        "categoria": it.get("categoria") or it.get("carpeta") or "",
        "alt": it.get("alt") or "",
        "url_original": it.get("url") or it.get("url_view") or "",
        "url_view": it.get("url_view") or it.get("url") or "",
        "url_download": it.get("url_download") or it.get("url") or "",
        "indexed_at": time.time(),
        **meta,
    }


def procesar_lista(conn: sqlite3.Connection, items: list[dict], source: str, fuente_url_key: str,
                   max_workers: int = 8) -> tuple[int, int]:
    pendientes = []
    saltadas = 0
    for it in items:
        clave = it.get(fuente_url_key) or it.get("id") or it.get("url") or ""
        if not clave:
            continue
        foto_id = hash_id(source, clave)
        if ya_procesado(conn, foto_id):
            saltadas += 1
            continue
        pendientes.append(it)

    if not pendientes:
        return 0, saltadas

    nuevas = 0
    errores = 0
    total = len(pendientes)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_procesar_una, it, source, fuente_url_key): it for it in pendientes}
        for f in as_completed(futures):
            try:
                row = f.result()
            except Exception as e:
                errores += 1
                print(f"  ! worker excepción: {e}", file=sys.stderr)
                continue
            if row is None:
                errores += 1
                continue
            upsert_foto(conn, row)
            nuevas += 1

            if nuevas % 25 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = nuevas / max(elapsed, 0.1)
                eta = (total - nuevas) / max(rate, 0.1)
                print(f"  · {nuevas}/{total} · {rate:.1f}/s · ETA {eta/60:.1f} min · errores={errores}")

    conn.commit()
    print(f"  · final: {nuevas} nuevas, {saltadas} reutilizadas, {errores} errores")
    return nuevas, saltadas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="borrar y rehacer la DB")
    ap.add_argument("--solo-drive", action="store_true")
    ap.add_argument("--solo-web", action="store_true")
    args = ap.parse_args()

    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    conn = init_db(rebuild=args.rebuild)

    if not args.solo_web:
        print("=== Google Drive ===")
        folder = os.environ.get("DRIVE_FOLDER_URL") or DRIVE_FOLDER_URL
        try:
            drive_items = drive_sync.listar_carpeta(folder)
        except Exception as e:
            print(f"[drive] falló: {e}", file=sys.stderr)
            drive_items = []
        print(f"  {len(drive_items)} imágenes listadas")
        if drive_items:
            n, s = procesar_lista(conn, drive_items, source="drive", fuente_url_key="id")
            print(f"  → {n} nuevas, {s} reutilizadas")

    if not args.solo_drive:
        print("\n=== pewenpisos.com.ar ===")
        web_items = web_scraper.scrapear_sitio()
        print(f"  {len(web_items)} imágenes únicas en el sitio")
        if web_items:
            n, s = procesar_lista(conn, web_items, source="web", fuente_url_key="url")
            print(f"  → {n} nuevas, {s} reutilizadas")

    with closing(conn.execute("SELECT source, COUNT(*) FROM fotos GROUP BY source")) as cur:
        print("\n=== Total en DB ===")
        for src, n in cur.fetchall():
            print(f"  {src}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
