"""Conexión y esquema de la base de tinturas.

Todo el stock se guarda en **unidades** (pomos, botellas). Cada producto sabe
cuánto contiene una unidad (`contenido`, en g para tintura y ml para oxidante),
así el mezclador puede pasar de gramos a pomos y viceversa sin ambigüedad.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "tinturas.db"

# Tipos de producto
TINTURA = "tintura"
OXIDANTE = "oxidante"
DECOLORANTE = "decolorante"
TRATAMIENTO = "tratamiento"
TIPOS = (TINTURA, OXIDANTE, DECOLORANTE, TRATAMIENTO)

# Tipos de movimiento
INGRESO = "ingreso"
CONSUMO = "consumo"
AJUSTE = "ajuste"
DESCARTE = "descarte"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS marcas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS productos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    marca_id      INTEGER NOT NULL REFERENCES marcas(id) ON DELETE CASCADE,
    tipo          TEXT NOT NULL,
    linea         TEXT NOT NULL DEFAULT '',
    codigo        TEXT NOT NULL,            -- '7.3', '20 vol', ...
    nombre        TEXT NOT NULL DEFAULT '', -- 'Rubio Dorado'
    contenido     REAL NOT NULL DEFAULT 60, -- g (tintura) o ml (oxidante) por unidad
    unidad        TEXT NOT NULL DEFAULT 'g',
    stock_minimo  REAL NOT NULL DEFAULT 0,  -- en unidades
    activo        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (marca_id, tipo, linea, codigo, contenido)
);

CREATE TABLE IF NOT EXISTS lotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    lote          TEXT NOT NULL DEFAULT '',
    vencimiento   TEXT,                     -- ISO 'YYYY-MM-DD'; NULL = sin dato
    cantidad      REAL NOT NULL DEFAULT 0,  -- unidades disponibles hoy
    cantidad_ini  REAL NOT NULL DEFAULT 0,
    costo_unit    REAL,
    ubicacion     TEXT NOT NULL DEFAULT '',
    creado        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_lotes_producto ON lotes(producto_id);
CREATE INDEX IF NOT EXISTS ix_lotes_venc ON lotes(vencimiento);

CREATE TABLE IF NOT EXISTS movimientos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    lote_id       INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
    tipo          TEXT NOT NULL,
    cantidad      REAL NOT NULL,            -- unidades; negativo = sale del stock
    motivo        TEXT NOT NULL DEFAULT '',
    referencia    TEXT NOT NULL DEFAULT '',
    fecha         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_mov_fecha ON movimientos(fecha);
CREATE INDEX IF NOT EXISTS ix_mov_producto ON movimientos(producto_id);

CREATE TABLE IF NOT EXISTS formulas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre        TEXT NOT NULL,
    cliente       TEXT NOT NULL DEFAULT '',
    oxidante_id   INTEGER REFERENCES productos(id) ON DELETE SET NULL,
    proporcion    REAL NOT NULL DEFAULT 1.5, -- ml de oxidante por g de tintura
    gramos        REAL NOT NULL DEFAULT 60,  -- gramos de tintura de la fórmula
    notas         TEXT NOT NULL DEFAULT '',
    creada        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS formula_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id    INTEGER NOT NULL REFERENCES formulas(id) ON DELETE CASCADE,
    producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    partes        REAL NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_fitems_formula ON formula_items(formula_id);

CREATE TABLE IF NOT EXISTS aplicaciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id    INTEGER NOT NULL REFERENCES formulas(id) ON DELETE CASCADE,
    fecha         TEXT NOT NULL DEFAULT (datetime('now')),
    gramos        REAL NOT NULL DEFAULT 0,
    notas         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS verificaciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL DEFAULT (datetime('now')),
    usuario       TEXT NOT NULL DEFAULT '',
    notas         TEXT NOT NULL DEFAULT '',
    estado        TEXT NOT NULL DEFAULT 'abierta',  -- abierta | cerrada
    cerrada       TEXT
);

CREATE TABLE IF NOT EXISTS verificacion_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    verificacion_id  INTEGER NOT NULL REFERENCES verificaciones(id) ON DELETE CASCADE,
    lote_id          INTEGER NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
    esperado         REAL NOT NULL DEFAULT 0,
    contado          REAL,                  -- NULL = todavía no se contó
    UNIQUE (verificacion_id, lote_id)
);
"""


def conectar(path: str | Path | None = None) -> sqlite3.Connection:
    """Abre la base (la crea si no existe) con el esquema ya aplicado."""
    destino = str(path or DB_PATH)
    conn = sqlite3.connect(destino, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    inicializar(conn)
    return conn


def inicializar(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
