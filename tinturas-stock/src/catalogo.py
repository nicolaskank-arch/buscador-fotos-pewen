"""Catálogo de marcas y productos.

El seed de tonos es un punto de partida con la numeración internacional que usan
tanto Yellow como Color Master (primer dígito = altura de tono, decimales =
reflejo). No pretende ser la carta completa de cada marca: desde la pestaña
Catálogo se agregan, editan y desactivan tonos.
"""
from __future__ import annotations

import sqlite3

from .db import DECOLORANTE, OXIDANTE, TINTURA

MARCAS = ("Yellow", "Color Master")

# Presentación por marca: (contenido de un pomo, unidad)
PRESENTACION = {
    "Yellow": (100.0, "g"),
    "Color Master": (60.0, "g"),
}

# (código, nombre). Numeración internacional: altura.reflejo
TONOS_SEED = [
    # Naturales
    ("1.0", "Negro"),
    ("3.0", "Castaño Oscuro"),
    ("4.0", "Castaño"),
    ("5.0", "Castaño Claro"),
    ("6.0", "Rubio Oscuro"),
    ("7.0", "Rubio"),
    ("8.0", "Rubio Claro"),
    ("9.0", "Rubio Muy Claro"),
    ("10.0", "Rubio Extra Claro"),
    # Cenizas (.1)
    ("5.1", "Castaño Claro Ceniza"),
    ("6.1", "Rubio Oscuro Ceniza"),
    ("7.1", "Rubio Ceniza"),
    ("8.1", "Rubio Claro Ceniza"),
    ("9.1", "Rubio Muy Claro Ceniza"),
    ("10.1", "Rubio Extra Claro Ceniza"),
    # Irisados (.2)
    ("6.2", "Rubio Oscuro Irisado"),
    ("7.2", "Rubio Irisado"),
    ("8.2", "Rubio Claro Irisado"),
    # Dorados (.3)
    ("6.3", "Rubio Oscuro Dorado"),
    ("7.3", "Rubio Dorado"),
    ("8.3", "Rubio Claro Dorado"),
    ("9.3", "Rubio Muy Claro Dorado"),
    # Cobrizos (.4)
    ("6.4", "Rubio Oscuro Cobrizo"),
    ("7.4", "Rubio Cobrizo"),
    ("8.4", "Rubio Claro Cobrizo"),
    # Caobas (.5)
    ("5.5", "Castaño Claro Caoba"),
    ("6.5", "Rubio Oscuro Caoba"),
    ("7.5", "Rubio Caoba"),
    # Rojos (.6)
    ("6.6", "Rubio Oscuro Rojo"),
    ("7.6", "Rubio Rojo"),
    ("6.66", "Rubio Oscuro Rojo Intenso"),
    # Super aclarantes
    ("11.0", "Super Aclarante Natural"),
    ("11.1", "Super Aclarante Ceniza"),
    ("11.3", "Super Aclarante Dorado"),
    # Correctores / mixtones
    ("0.1", "Corrector Azul Ceniza"),
    ("0.3", "Corrector Amarillo Dorado"),
    ("0.6", "Corrector Rojo"),
    ("0.66", "Corrector Rojo Intenso"),
]

# (código, contenido ml)
OXIDANTES_SEED = [("10 vol", 900.0), ("20 vol", 900.0), ("30 vol", 900.0), ("40 vol", 900.0)]

VOLUMEN_A_PORCENTAJE = {"10 vol": "3%", "20 vol": "6%", "30 vol": "9%", "40 vol": "12%"}


def sembrar(conn: sqlite3.Connection) -> int:
    """Carga marcas, tonos, oxidantes y decolorante base. Idempotente."""
    creados = 0
    for marca in MARCAS:
        conn.execute("INSERT OR IGNORE INTO marcas (nombre) VALUES (?)", (marca,))
        marca_id = conn.execute("SELECT id FROM marcas WHERE nombre = ?", (marca,)).fetchone()["id"]
        contenido, unidad = PRESENTACION[marca]

        for codigo, nombre in TONOS_SEED:
            creados += _upsert_producto(
                conn, marca_id, TINTURA, "Coloración", codigo, nombre, contenido, unidad
            )
        for codigo, ml in OXIDANTES_SEED:
            creados += _upsert_producto(
                conn, marca_id, OXIDANTE, "Oxidante", codigo,
                f"Emulsión oxidante {VOLUMEN_A_PORCENTAJE[codigo]}", ml, "ml",
            )
        creados += _upsert_producto(
            conn, marca_id, DECOLORANTE, "Decoloración", "Polvo", "Polvo decolorante", 500.0, "g"
        )
    conn.commit()
    return creados


def _upsert_producto(conn, marca_id, tipo, linea, codigo, nombre, contenido, unidad) -> int:
    cur = conn.execute(
        """INSERT OR IGNORE INTO productos
               (marca_id, tipo, linea, codigo, nombre, contenido, unidad)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (marca_id, tipo, linea, codigo, nombre, contenido, unidad),
    )
    return cur.rowcount


def marcas(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM marcas ORDER BY nombre").fetchall()


def productos(
    conn: sqlite3.Connection,
    tipo: str | None = None,
    marca_id: int | None = None,
    solo_activos: bool = True,
) -> list[sqlite3.Row]:
    sql = """SELECT p.*, m.nombre AS marca
               FROM productos p JOIN marcas m ON m.id = p.marca_id
              WHERE 1 = 1"""
    args: list = []
    if tipo:
        sql += " AND p.tipo = ?"
        args.append(tipo)
    if marca_id:
        sql += " AND p.marca_id = ?"
        args.append(marca_id)
    if solo_activos:
        sql += " AND p.activo = 1"
    sql += " ORDER BY m.nombre, p.tipo, LENGTH(p.codigo), p.codigo"
    return conn.execute(sql, args).fetchall()


def producto(conn: sqlite3.Connection, producto_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT p.*, m.nombre AS marca
             FROM productos p JOIN marcas m ON m.id = p.marca_id
            WHERE p.id = ?""",
        (producto_id,),
    ).fetchone()


def etiqueta(row: sqlite3.Row) -> str:
    """Texto corto para selects: 'Yellow 7.3 · Rubio Dorado (100 g)'."""
    nombre = f" · {row['nombre']}" if row["nombre"] else ""
    return f"{row['marca']} {row['codigo']}{nombre} ({row['contenido']:g} {row['unidad']})"


def crear_producto(
    conn: sqlite3.Connection,
    marca_id: int,
    tipo: str,
    codigo: str,
    nombre: str = "",
    linea: str = "",
    contenido: float = 60.0,
    unidad: str = "g",
    stock_minimo: float = 0.0,
) -> int:
    cur = conn.execute(
        """INSERT INTO productos
               (marca_id, tipo, linea, codigo, nombre, contenido, unidad, stock_minimo)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (marca_id, tipo, linea, codigo.strip(), nombre.strip(), contenido, unidad, stock_minimo),
    )
    conn.commit()
    return int(cur.lastrowid)


def actualizar_producto(conn: sqlite3.Connection, producto_id: int, **campos) -> None:
    permitidos = {"nombre", "linea", "contenido", "unidad", "stock_minimo", "activo", "codigo"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    sets = ", ".join(f"{k} = ?" for k in campos)
    conn.execute(f"UPDATE productos SET {sets} WHERE id = ?", [*campos.values(), producto_id])
    conn.commit()
