"""Mezclador de fórmulas: pasa una receta a gramos, ml y pomos.

Una fórmula son N tonos en proporción de *partes* (ej. 2 partes de 7.3 + 1 parte
de 8.1), un total en gramos de tintura y una proporción tintura:oxidante. El
mezclador convierte todo a gramos/ml, lo traduce a unidades de stock y avisa si
falta mercadería antes de aplicar.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import stock
from .catalogo import etiqueta as _etiqueta
from .catalogo import producto as get_producto

# Proporción tintura:oxidante → ml de oxidante por gramo de tintura
PROPORCIONES = {
    "1:1": 1.0,
    "1:1.5": 1.5,
    "1:2": 2.0,
    "1:2.5": 2.5,
    "1:3": 3.0,
}
PROPORCION_DEFAULT = "1:1.5"

# Guía orientativa de volumen según cuánto se quiere aclarar. La palabra final
# siempre la tiene la tabla del fabricante.
GUIA_OXIDANTE = [
    (0, "10 vol", "Tono sobre tono, oscurecer o dar reflejo sin aclarar"),
    (1, "20 vol", "Cobertura de canas y hasta 1-2 tonos de aclaración"),
    (2, "30 vol", "2-3 tonos de aclaración"),
    (3, "40 vol", "3-4 tonos o super aclarantes"),
]


class FormulaInvalida(ValueError):
    """La receta no se puede calcular (sin componentes, partes en cero, etc.)."""


@dataclass(frozen=True)
class Componente:
    producto_id: int
    partes: float = 1.0


@dataclass
class ItemMezcla:
    producto_id: int
    etiqueta: str
    partes: float
    gramos: float
    unidades: float          # pomos que hay que abrir (fraccionario)
    contenido: float
    unidad: str
    disponible: float = 0.0  # unidades no vencidas en stock
    faltante: float = 0.0    # unidades que no se pueden cubrir

    @property
    def alcanza(self) -> bool:
        return self.faltante <= 1e-9


@dataclass
class Mezcla:
    items: list[ItemMezcla] = field(default_factory=list)
    gramos_tintura: float = 0.0
    proporcion: str = PROPORCION_DEFAULT
    oxidante: ItemMezcla | None = None
    oxidante_ml: float = 0.0

    @property
    def total(self) -> float:
        """Gramos totales de mezcla lista (tintura + oxidante, 1 ml ≈ 1 g)."""
        return round(self.gramos_tintura + self.oxidante_ml, 2)

    @property
    def alcanza(self) -> bool:
        faltan = [i for i in self.items if not i.alcanza]
        if self.oxidante and not self.oxidante.alcanza:
            faltan.append(self.oxidante)
        return not faltan

    @property
    def faltantes(self) -> list[ItemMezcla]:
        salida = [i for i in self.items if not i.alcanza]
        if self.oxidante and not self.oxidante.alcanza:
            salida.append(self.oxidante)
        return salida


def sugerir_oxidante(tonos_a_aclarar: int) -> tuple[str, str]:
    """Volumen orientativo según los tonos de aclaración buscados."""
    elegido = GUIA_OXIDANTE[0]
    for minimo, volumen, detalle in GUIA_OXIDANTE:
        if tonos_a_aclarar >= minimo:
            elegido = (minimo, volumen, detalle)
    return elegido[1], elegido[2]


def calcular(
    conn: sqlite3.Connection,
    componentes: list[Componente],
    gramos_tintura: float,
    proporcion: str = PROPORCION_DEFAULT,
    oxidante_id: int | None = None,
    ref: date | None = None,
) -> Mezcla:
    """Arma la mezcla y la contrasta contra el stock disponible."""
    if not componentes:
        raise FormulaInvalida("La fórmula necesita al menos un tono")
    if gramos_tintura <= 0:
        raise FormulaInvalida("Los gramos de tintura tienen que ser mayores a 0")
    if proporcion not in PROPORCIONES:
        raise FormulaInvalida(f"Proporción desconocida: {proporcion}")

    total_partes = sum(c.partes for c in componentes)
    if total_partes <= 0:
        raise FormulaInvalida("Las partes de la fórmula suman 0")

    mezcla = Mezcla(gramos_tintura=round(gramos_tintura, 2), proporcion=proporcion)
    for comp in componentes:
        if comp.partes <= 0:
            continue
        prod = get_producto(conn, comp.producto_id)
        if prod is None:
            raise FormulaInvalida(f"No existe el producto {comp.producto_id}")
        gramos = round(gramos_tintura * comp.partes / total_partes, 2)
        mezcla.items.append(
            _item(conn, prod, comp.partes, gramos, ref)
        )

    mezcla.oxidante_ml = round(gramos_tintura * PROPORCIONES[proporcion], 2)
    if oxidante_id:
        oxi = get_producto(conn, oxidante_id)
        if oxi is None:
            raise FormulaInvalida(f"No existe el oxidante {oxidante_id}")
        mezcla.oxidante = _item(conn, oxi, 0.0, mezcla.oxidante_ml, ref)
    return mezcla


def _item(conn, prod, partes, cantidad, ref) -> ItemMezcla:
    contenido = prod["contenido"] or 1.0
    unidades = round(cantidad / contenido, 4)
    disp = stock.disponible(conn, prod["id"], ref)
    return ItemMezcla(
        producto_id=prod["id"],
        etiqueta=_etiqueta(prod),
        partes=partes,
        gramos=cantidad,
        unidades=unidades,
        contenido=contenido,
        unidad=prod["unidad"],
        disponible=disp,
        faltante=round(max(unidades - disp, 0.0), 4),
    )


def guardar_formula(
    conn: sqlite3.Connection,
    nombre: str,
    mezcla: Mezcla,
    cliente: str = "",
    notas: str = "",
) -> int:
    """Persiste la receta para poder repetirla."""
    cur = conn.execute(
        """INSERT INTO formulas (nombre, cliente, oxidante_id, proporcion, gramos, notas)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            nombre.strip() or "Sin nombre",
            cliente.strip(),
            mezcla.oxidante.producto_id if mezcla.oxidante else None,
            PROPORCIONES[mezcla.proporcion],
            mezcla.gramos_tintura,
            notas.strip(),
        ),
    )
    formula_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO formula_items (formula_id, producto_id, partes) VALUES (?, ?, ?)",
        [(formula_id, i.producto_id, i.partes) for i in mezcla.items],
    )
    conn.commit()
    return formula_id


def aplicar(
    conn: sqlite3.Connection,
    mezcla: Mezcla,
    formula_id: int | None = None,
    referencia: str = "",
    notas: str = "",
    ref: date | None = None,
) -> list[stock.Asignacion]:
    """Descuenta del stock lo que consume la mezcla (FEFO).

    Se valida todo antes de tocar nada: si falta un solo componente no se
    descuenta ninguno, así no queda una fórmula aplicada a medias.
    """
    if not mezcla.alcanza:
        primero = mezcla.faltantes[0]
        raise stock.StockInsuficiente(primero.producto_id, primero.unidades, primero.disponible)

    motivo = "Mezcla aplicada"
    asignaciones: list[stock.Asignacion] = []
    objetivos = list(mezcla.items) + ([mezcla.oxidante] if mezcla.oxidante else [])
    for item in objetivos:
        asignaciones += stock.consumir(
            conn, item.producto_id, item.unidades, motivo, referencia, ref
        )
    if formula_id:
        conn.execute(
            "INSERT INTO aplicaciones (formula_id, gramos, notas) VALUES (?, ?, ?)",
            (formula_id, mezcla.gramos_tintura, notas.strip()),
        )
        conn.commit()
    return asignaciones


def formulas(conn: sqlite3.Connection, limite: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.*, (SELECT COUNT(*) FROM aplicaciones a WHERE a.formula_id = f.id) AS usos
             FROM formulas f ORDER BY f.creada DESC, f.id DESC LIMIT ?""",
        (limite,),
    ).fetchall()


def items_de(conn: sqlite3.Connection, formula_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT fi.*, p.codigo, p.nombre, p.contenido, p.unidad, m.nombre AS marca
             FROM formula_items fi
             JOIN productos p ON p.id = fi.producto_id
             JOIN marcas m ON m.id = p.marca_id
            WHERE fi.formula_id = ?""",
        (formula_id,),
    ).fetchall()
