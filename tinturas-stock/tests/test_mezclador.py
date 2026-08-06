from datetime import date, timedelta

import pytest

from src import catalogo, mezclador, stock
from src.db import OXIDANTE, TINTURA, conectar
from src.mezclador import Componente


@pytest.fixture()
def conn(tmp_path):
    c = conectar(tmp_path / "test.db")
    catalogo.sembrar(c)
    yield c
    c.close()


def iso(dias: int) -> str:
    return (date.today() + timedelta(days=dias)).isoformat()


def buscar(conn, codigo, tipo=TINTURA, marca="Yellow"):
    for p in catalogo.productos(conn, tipo=tipo):
        if p["codigo"] == codigo and p["marca"] == marca:
            return p["id"]
    raise AssertionError(f"No se encontró {marca} {codigo}")


def test_un_solo_tono(conn):
    tono = buscar(conn, "7.3")
    m = mezclador.calcular(conn, [Componente(tono)], gramos_tintura=100, proporcion="1:1.5")

    assert len(m.items) == 1
    assert m.items[0].gramos == 100
    assert m.items[0].unidades == 1.0  # pomo Yellow de 100 g
    assert m.oxidante_ml == 150
    assert m.total == 250


def test_reparto_por_partes(conn):
    a, b = buscar(conn, "7.3"), buscar(conn, "8.1")
    m = mezclador.calcular(conn, [Componente(a, 2), Componente(b, 1)], gramos_tintura=90)

    assert m.items[0].gramos == 60
    assert m.items[1].gramos == 30
    assert sum(i.gramos for i in m.items) == m.gramos_tintura


def test_partes_fraccionarias(conn):
    a, b = buscar(conn, "7.3"), buscar(conn, "0.6")
    m = mezclador.calcular(conn, [Componente(a, 1), Componente(b, 0.5)], gramos_tintura=60)

    assert m.items[0].gramos == 40
    assert m.items[1].gramos == 20


def test_proporciones(conn):
    tono = buscar(conn, "7.3")
    assert mezclador.calcular(conn, [Componente(tono)], 60, "1:1").oxidante_ml == 60
    assert mezclador.calcular(conn, [Componente(tono)], 60, "1:2").oxidante_ml == 120
    assert mezclador.calcular(conn, [Componente(tono)], 60, "1:3").oxidante_ml == 180


def test_pomo_de_60g_de_color_master(conn):
    tono = buscar(conn, "7.3", marca="Color Master")
    m = mezclador.calcular(conn, [Componente(tono)], gramos_tintura=90)
    assert m.items[0].unidades == 1.5


def test_oxidante_se_convierte_a_botellas(conn):
    tono = buscar(conn, "7.3")
    oxi = buscar(conn, "20 vol", tipo=OXIDANTE)
    m = mezclador.calcular(conn, [Componente(tono)], 100, "1:1.5", oxidante_id=oxi)

    assert m.oxidante is not None
    assert m.oxidante.gramos == 150
    assert m.oxidante.unidades == pytest.approx(150 / 900, rel=1e-3)


def test_formula_vacia_o_invalida(conn):
    tono = buscar(conn, "7.3")
    with pytest.raises(mezclador.FormulaInvalida):
        mezclador.calcular(conn, [], 60)
    with pytest.raises(mezclador.FormulaInvalida):
        mezclador.calcular(conn, [Componente(tono)], 0)
    with pytest.raises(mezclador.FormulaInvalida):
        mezclador.calcular(conn, [Componente(tono)], 60, "1:9")
    with pytest.raises(mezclador.FormulaInvalida):
        mezclador.calcular(conn, [Componente(tono, 0)], 60)


def test_marca_faltantes_contra_el_stock(conn):
    tono = buscar(conn, "7.3")
    stock.ingresar(conn, tono, 0.5, vencimiento=iso(200))

    m = mezclador.calcular(conn, [Componente(tono)], 100)

    assert not m.alcanza
    assert m.items[0].faltante == 0.5
    assert [i.producto_id for i in m.faltantes] == [tono]


def test_stock_vencido_no_cuenta_como_disponible(conn):
    tono = buscar(conn, "7.3")
    stock.ingresar(conn, tono, 10, vencimiento=iso(-1))
    m = mezclador.calcular(conn, [Componente(tono)], 100)
    assert not m.alcanza


def test_aplicar_descuenta_tintura_y_oxidante(conn):
    tono = buscar(conn, "7.3")
    oxi = buscar(conn, "20 vol", tipo=OXIDANTE)
    stock.ingresar(conn, tono, 2, vencimiento=iso(200))
    stock.ingresar(conn, oxi, 1, vencimiento=iso(200))

    m = mezclador.calcular(conn, [Componente(tono)], 100, "1:1.5", oxidante_id=oxi)
    mezclador.aplicar(conn, m, referencia="ficha-1")

    assert stock.disponible(conn, tono) == 1
    assert stock.disponible(conn, oxi) == pytest.approx(1 - 150 / 900, rel=1e-3)


def test_aplicar_sin_stock_no_descuenta_nada(conn):
    a, b = buscar(conn, "7.3"), buscar(conn, "8.1")
    stock.ingresar(conn, a, 5, vencimiento=iso(200))  # de a sobra, de b no hay nada

    m = mezclador.calcular(conn, [Componente(a), Componente(b)], 100)
    with pytest.raises(stock.StockInsuficiente):
        mezclador.aplicar(conn, m)

    assert stock.disponible(conn, a) == 5


def test_guardar_y_releer_formula(conn):
    a, b = buscar(conn, "7.3"), buscar(conn, "8.1")
    m = mezclador.calcular(conn, [Componente(a, 2), Componente(b, 1)], 90, "1:2")

    fid = mezclador.guardar_formula(conn, "Base clienta X", m, cliente="X")

    guardada = mezclador.formulas(conn)[0]
    assert guardada["id"] == fid
    assert guardada["proporcion"] == 2.0
    assert sorted(i["partes"] for i in mezclador.items_de(conn, fid)) == [1, 2]


def test_aplicacion_queda_registrada(conn):
    tono = buscar(conn, "7.3")
    stock.ingresar(conn, tono, 3, vencimiento=iso(200))
    m = mezclador.calcular(conn, [Componente(tono)], 100)
    fid = mezclador.guardar_formula(conn, "Retoque raíz", m)

    mezclador.aplicar(conn, m, formula_id=fid)

    assert mezclador.formulas(conn)[0]["usos"] == 1


@pytest.mark.parametrize(
    "tonos, volumen", [(0, "10 vol"), (1, "20 vol"), (2, "30 vol"), (4, "40 vol")]
)
def test_guia_de_oxidante(tonos, volumen):
    assert mezclador.sugerir_oxidante(tonos)[0] == volumen
