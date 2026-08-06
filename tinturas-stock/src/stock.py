"""Stock por lote, con vencimientos y consumo FEFO.

FEFO = *first expired, first out*: siempre se gasta primero el lote que vence
antes. Los lotes ya vencidos quedan fuera de la asignación (hay que descartarlos
o forzarlos explícitamente), así el sistema no propone usar mercadería vencida.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from .db import AJUSTE, CONSUMO, DESCARTE, INGRESO

DIAS_CRITICO = 30
DIAS_AVISO = 90

# Estados de vencimiento, de peor a mejor
VENCIDO = "vencido"
CRITICO = "critico"
AVISO = "aviso"
OK = "ok"
SIN_FECHA = "sin_fecha"

_ORDEN_ESTADO = {VENCIDO: 0, CRITICO: 1, AVISO: 2, OK: 3, SIN_FECHA: 4}


class StockInsuficiente(Exception):
    """No hay unidades disponibles (no vencidas) para cubrir lo pedido."""

    def __init__(self, producto_id: int, pedido: float, disponible: float):
        self.producto_id = producto_id
        self.pedido = pedido
        self.disponible = disponible
        super().__init__(
            f"Producto {producto_id}: se piden {pedido:g} u. y hay {disponible:g} u. disponibles"
        )


@dataclass(frozen=True)
class Asignacion:
    """Cuántas unidades salen de cada lote para cubrir un consumo."""

    lote_id: int
    lote: str
    vencimiento: str | None
    unidades: float


def _hoy(ref: date | None = None) -> date:
    return ref or date.today()


def _parse(fecha: str | None) -> date | None:
    if not fecha:
        return None
    try:
        return datetime.strptime(fecha[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def estado_vencimiento(
    vencimiento: str | None,
    ref: date | None = None,
    dias_critico: int = DIAS_CRITICO,
    dias_aviso: int = DIAS_AVISO,
) -> tuple[str, int | None]:
    """Devuelve (estado, días restantes). Días negativos = ya venció."""
    venc = _parse(vencimiento)
    if venc is None:
        return SIN_FECHA, None
    dias = (venc - _hoy(ref)).days
    if dias < 0:
        return VENCIDO, dias
    if dias <= dias_critico:
        return CRITICO, dias
    if dias <= dias_aviso:
        return AVISO, dias
    return OK, dias


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #

def lotes(
    conn: sqlite3.Connection,
    producto_id: int | None = None,
    con_stock: bool = True,
) -> list[sqlite3.Row]:
    sql = """SELECT l.*, p.codigo, p.nombre AS producto, p.tipo, p.contenido, p.unidad,
                    m.nombre AS marca
               FROM lotes l
               JOIN productos p ON p.id = l.producto_id
               JOIN marcas m ON m.id = p.marca_id
              WHERE 1 = 1"""
    args: list = []
    if producto_id is not None:
        sql += " AND l.producto_id = ?"
        args.append(producto_id)
    if con_stock:
        sql += " AND l.cantidad > 0"
    sql += " ORDER BY l.vencimiento IS NULL, l.vencimiento, l.id"
    return conn.execute(sql, args).fetchall()


def disponible(
    conn: sqlite3.Connection,
    producto_id: int,
    ref: date | None = None,
    incluir_vencidos: bool = False,
) -> float:
    """Unidades utilizables de un producto."""
    total = 0.0
    for lote in lotes(conn, producto_id):
        if not incluir_vencidos and estado_vencimiento(lote["vencimiento"], ref)[0] == VENCIDO:
            continue
        total += lote["cantidad"]
    return total


def resumen(conn: sqlite3.Connection, ref: date | None = None) -> list[dict]:
    """Una fila por producto con stock, próximo vencimiento y alertas."""
    filas = []
    productos = conn.execute(
        """SELECT p.*, m.nombre AS marca
             FROM productos p JOIN marcas m ON m.id = p.marca_id
            WHERE p.activo = 1
            ORDER BY m.nombre, p.tipo, LENGTH(p.codigo), p.codigo"""
    ).fetchall()
    for p in productos:
        del_producto = lotes(conn, p["id"])
        util = 0.0
        vencido = 0.0
        proximo = None
        peor = SIN_FECHA
        for lote in del_producto:
            estado, _ = estado_vencimiento(lote["vencimiento"], ref)
            if estado == VENCIDO:
                vencido += lote["cantidad"]
            else:
                util += lote["cantidad"]
                if lote["vencimiento"] and (proximo is None or lote["vencimiento"] < proximo):
                    proximo = lote["vencimiento"]
            if _ORDEN_ESTADO[estado] < _ORDEN_ESTADO[peor]:
                peor = estado
        filas.append(
            {
                "producto_id": p["id"],
                "marca": p["marca"],
                "tipo": p["tipo"],
                "codigo": p["codigo"],
                "nombre": p["nombre"],
                "unidades": util,
                "vencidas": vencido,
                "contenido_total": util * p["contenido"],
                "unidad": p["unidad"],
                "stock_minimo": p["stock_minimo"],
                "bajo_minimo": util < p["stock_minimo"],
                "proximo_vencimiento": proximo,
                "estado": peor if del_producto else SIN_FECHA,
            }
        )
    return filas


def alertas(conn: sqlite3.Connection, ref: date | None = None) -> dict[str, list]:
    """Lotes vencidos / por vencer y productos por debajo del mínimo."""
    vencidos, criticos, avisos = [], [], []
    for lote in lotes(conn):
        estado, dias = estado_vencimiento(lote["vencimiento"], ref)
        item = dict(lote)
        item["dias"] = dias
        if estado == VENCIDO:
            vencidos.append(item)
        elif estado == CRITICO:
            criticos.append(item)
        elif estado == AVISO:
            avisos.append(item)
    faltantes = [f for f in resumen(conn, ref) if f["bajo_minimo"] and f["stock_minimo"] > 0]
    return {"vencidos": vencidos, "criticos": criticos, "avisos": avisos, "bajo_minimo": faltantes}


# --------------------------------------------------------------------------- #
# Movimientos
# --------------------------------------------------------------------------- #

def ingresar(
    conn: sqlite3.Connection,
    producto_id: int,
    unidades: float,
    vencimiento: str | None = None,
    lote: str = "",
    costo_unit: float | None = None,
    ubicacion: str = "",
    motivo: str = "Compra",
) -> int:
    """Da de alta un lote nuevo y registra el ingreso. Devuelve el lote_id."""
    if unidades <= 0:
        raise ValueError("El ingreso tiene que ser mayor a 0")
    cur = conn.execute(
        """INSERT INTO lotes
               (producto_id, lote, vencimiento, cantidad, cantidad_ini, costo_unit, ubicacion)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (producto_id, lote.strip(), vencimiento or None, unidades, unidades, costo_unit,
         ubicacion.strip()),
    )
    lote_id = int(cur.lastrowid)
    _movimiento(conn, producto_id, lote_id, INGRESO, unidades, motivo)
    conn.commit()
    return lote_id


def plan_fefo(
    conn: sqlite3.Connection,
    producto_id: int,
    unidades: float,
    ref: date | None = None,
    incluir_vencidos: bool = False,
) -> tuple[list[Asignacion], float]:
    """Simula el consumo sin tocar la base.

    Devuelve (asignaciones, faltante). `faltante` > 0 significa que el stock no
    alcanza; sirve para avisar antes de aplicar una fórmula.
    """
    pendiente = round(unidades, 6)
    asignaciones: list[Asignacion] = []
    for lote in lotes(conn, producto_id):
        if pendiente <= 0:
            break
        if not incluir_vencidos and estado_vencimiento(lote["vencimiento"], ref)[0] == VENCIDO:
            continue
        toma = min(lote["cantidad"], pendiente)
        if toma <= 0:
            continue
        asignaciones.append(
            Asignacion(lote["id"], lote["lote"], lote["vencimiento"], round(toma, 6))
        )
        pendiente = round(pendiente - toma, 6)
    return asignaciones, max(pendiente, 0.0)


def consumir(
    conn: sqlite3.Connection,
    producto_id: int,
    unidades: float,
    motivo: str = "",
    referencia: str = "",
    ref: date | None = None,
    incluir_vencidos: bool = False,
) -> list[Asignacion]:
    """Descuenta unidades por FEFO. Falla si no alcanza (no deja stock negativo)."""
    if unidades <= 0:
        raise ValueError("El consumo tiene que ser mayor a 0")
    asignaciones, faltante = plan_fefo(conn, producto_id, unidades, ref, incluir_vencidos)
    if faltante > 1e-9:
        raise StockInsuficiente(producto_id, unidades, unidades - faltante)
    for a in asignaciones:
        conn.execute(
            "UPDATE lotes SET cantidad = cantidad - ? WHERE id = ?", (a.unidades, a.lote_id)
        )
        _movimiento(conn, producto_id, a.lote_id, CONSUMO, -a.unidades, motivo, referencia)
    conn.commit()
    return asignaciones


def ajustar(
    conn: sqlite3.Connection,
    lote_id: int,
    cantidad_real: float,
    motivo: str = "Ajuste manual",
    referencia: str = "",
) -> float:
    """Fija la cantidad de un lote al valor contado. Devuelve la diferencia."""
    if cantidad_real < 0:
        raise ValueError("La cantidad contada no puede ser negativa")
    fila = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if fila is None:
        raise ValueError(f"No existe el lote {lote_id}")
    diferencia = round(cantidad_real - fila["cantidad"], 6)
    if diferencia == 0:
        return 0.0
    conn.execute("UPDATE lotes SET cantidad = ? WHERE id = ?", (cantidad_real, lote_id))
    _movimiento(conn, fila["producto_id"], lote_id, AJUSTE, diferencia, motivo, referencia)
    conn.commit()
    return diferencia


def descartar(
    conn: sqlite3.Connection, lote_id: int, motivo: str = "Vencido", referencia: str = ""
) -> float:
    """Saca todo el remanente de un lote (vencido, roto, etc.)."""
    fila = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    if fila is None:
        raise ValueError(f"No existe el lote {lote_id}")
    cantidad = fila["cantidad"]
    if cantidad <= 0:
        return 0.0
    conn.execute("UPDATE lotes SET cantidad = 0 WHERE id = ?", (lote_id,))
    _movimiento(conn, fila["producto_id"], lote_id, DESCARTE, -cantidad, motivo, referencia)
    conn.commit()
    return cantidad


def descartar_vencidos(conn: sqlite3.Connection, ref: date | None = None) -> list[tuple[int, float]]:
    """Descarta de una todos los lotes vencidos con stock. Devuelve (lote_id, unidades)."""
    salidas = []
    for lote in lotes(conn):
        if estado_vencimiento(lote["vencimiento"], ref)[0] == VENCIDO:
            cantidad = descartar(conn, lote["id"], motivo="Vencido")
            if cantidad:
                salidas.append((lote["id"], cantidad))
    return salidas


def movimientos(
    conn: sqlite3.Connection, limite: int = 200, producto_id: int | None = None
) -> list[sqlite3.Row]:
    sql = """SELECT mv.*, p.codigo, p.tipo, m.nombre AS marca, l.lote, l.vencimiento
               FROM movimientos mv
               JOIN productos p ON p.id = mv.producto_id
               JOIN marcas m ON m.id = p.marca_id
               LEFT JOIN lotes l ON l.id = mv.lote_id
              WHERE 1 = 1"""
    args: list = []
    if producto_id is not None:
        sql += " AND mv.producto_id = ?"
        args.append(producto_id)
    sql += " ORDER BY mv.fecha DESC, mv.id DESC LIMIT ?"
    args.append(limite)
    return conn.execute(sql, args).fetchall()


def _movimiento(conn, producto_id, lote_id, tipo, cantidad, motivo="", referencia=""):
    conn.execute(
        """INSERT INTO movimientos (producto_id, lote_id, tipo, cantidad, motivo, referencia)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (producto_id, lote_id, tipo, cantidad, motivo, referencia),
    )
