"""Verificación de stock: conteo físico contra lo que dice el sistema.

Flujo: se abre una verificación (saca una foto de lo que el sistema cree que
hay), se cargan los conteos reales pomo por pomo, y al cerrarla se generan los
ajustes. Mientras está abierta no se toca el stock, así se puede contar en
varias tandas sin bloquear el trabajo del salón.
"""
from __future__ import annotations

import sqlite3

from . import stock

ABIERTA = "abierta"
CERRADA = "cerrada"


class VerificacionCerrada(Exception):
    """No se puede modificar una verificación ya cerrada."""


def abrir(conn: sqlite3.Connection, usuario: str = "", notas: str = "") -> int:
    """Crea la verificación y congela el esperado de cada lote con stock."""
    cur = conn.execute(
        "INSERT INTO verificaciones (usuario, notas) VALUES (?, ?)",
        (usuario.strip(), notas.strip()),
    )
    verificacion_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO verificacion_items (verificacion_id, lote_id, esperado) VALUES (?, ?, ?)",
        [(verificacion_id, lote["id"], lote["cantidad"]) for lote in stock.lotes(conn)],
    )
    conn.commit()
    return verificacion_id


def abierta(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM verificaciones WHERE estado = ? ORDER BY id DESC LIMIT 1", (ABIERTA,)
    ).fetchone()


def listar(conn: sqlite3.Connection, limite: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM verificaciones ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()


def _estado(conn: sqlite3.Connection, verificacion_id: int) -> str:
    fila = conn.execute(
        "SELECT estado FROM verificaciones WHERE id = ?", (verificacion_id,)
    ).fetchone()
    if fila is None:
        raise ValueError(f"No existe la verificación {verificacion_id}")
    return fila["estado"]


def contar(conn: sqlite3.Connection, verificacion_id: int, lote_id: int, contado: float) -> None:
    """Registra el conteo físico de un lote."""
    if _estado(conn, verificacion_id) == CERRADA:
        raise VerificacionCerrada(f"La verificación {verificacion_id} ya está cerrada")
    if contado < 0:
        raise ValueError("La cantidad contada no puede ser negativa")
    actualizado = conn.execute(
        "UPDATE verificacion_items SET contado = ? WHERE verificacion_id = ? AND lote_id = ?",
        (contado, verificacion_id, lote_id),
    ).rowcount
    if not actualizado:
        # Lote que apareció después de abrir la verificación (o que estaba en 0).
        esperado = conn.execute(
            "SELECT cantidad FROM lotes WHERE id = ?", (lote_id,)
        ).fetchone()
        if esperado is None:
            raise ValueError(f"No existe el lote {lote_id}")
        conn.execute(
            """INSERT INTO verificacion_items (verificacion_id, lote_id, esperado, contado)
               VALUES (?, ?, ?, ?)""",
            (verificacion_id, lote_id, esperado["cantidad"], contado),
        )
    conn.commit()


def detalle(conn: sqlite3.Connection, verificacion_id: int) -> list[dict]:
    """Filas del conteo con la diferencia calculada."""
    filas = conn.execute(
        """SELECT vi.*, l.lote, l.vencimiento, l.ubicacion, p.codigo, p.nombre AS producto,
                  p.tipo, p.unidad, m.nombre AS marca
             FROM verificacion_items vi
             JOIN lotes l ON l.id = vi.lote_id
             JOIN productos p ON p.id = l.producto_id
             JOIN marcas m ON m.id = p.marca_id
            WHERE vi.verificacion_id = ?
            ORDER BY m.nombre, p.tipo, LENGTH(p.codigo), p.codigo, l.vencimiento""",
        (verificacion_id,),
    ).fetchall()
    salida = []
    for f in filas:
        item = dict(f)
        item["diferencia"] = (
            None if f["contado"] is None else round(f["contado"] - f["esperado"], 6)
        )
        item["estado_venc"] = stock.estado_vencimiento(f["vencimiento"])[0]
        salida.append(item)
    return salida


def resumen(conn: sqlite3.Connection, verificacion_id: int) -> dict:
    filas = detalle(conn, verificacion_id)
    contados = [f for f in filas if f["contado"] is not None]
    diferencias = [f for f in contados if f["diferencia"]]
    return {
        "total": len(filas),
        "contados": len(contados),
        "pendientes": len(filas) - len(contados),
        "con_diferencia": len(diferencias),
        "faltantes": sum(-f["diferencia"] for f in diferencias if f["diferencia"] < 0),
        "sobrantes": sum(f["diferencia"] for f in diferencias if f["diferencia"] > 0),
        "diferencias": diferencias,
    }


def cerrar(
    conn: sqlite3.Connection, verificacion_id: int, aplicar_ajustes: bool = True
) -> list[tuple[int, float]]:
    """Cierra la verificación y ajusta el stock a lo contado.

    Los lotes que quedaron sin contar no se tocan: contar parcial no puede
    borrar stock que nadie revisó.
    """
    if _estado(conn, verificacion_id) == CERRADA:
        raise VerificacionCerrada(f"La verificación {verificacion_id} ya está cerrada")
    ajustes: list[tuple[int, float]] = []
    if aplicar_ajustes:
        for fila in detalle(conn, verificacion_id):
            if fila["contado"] is None or not fila["diferencia"]:
                continue
            diferencia = stock.ajustar(
                conn,
                fila["lote_id"],
                fila["contado"],
                motivo="Verificación de stock",
                referencia=f"verificacion:{verificacion_id}",
            )
            if diferencia:
                ajustes.append((fila["lote_id"], diferencia))
    conn.execute(
        "UPDATE verificaciones SET estado = ?, cerrada = datetime('now') WHERE id = ?",
        (CERRADA, verificacion_id),
    )
    conn.commit()
    return ajustes
