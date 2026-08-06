from datetime import date, timedelta

import pytest

from src import catalogo, stock
from src.db import TINTURA, conectar


@pytest.fixture()
def conn(tmp_path):
    c = conectar(tmp_path / "test.db")
    catalogo.sembrar(c)
    yield c
    c.close()


@pytest.fixture()
def tono(conn):
    return catalogo.productos(conn, tipo=TINTURA)[0]["id"]


def iso(dias: int) -> str:
    return (date.today() + timedelta(days=dias)).isoformat()


def test_ingreso_crea_lote_y_movimiento(conn, tono):
    lote_id = stock.ingresar(conn, tono, 5, vencimiento=iso(200), lote="A1")
    assert stock.disponible(conn, tono) == 5
    movs = stock.movimientos(conn, producto_id=tono)
    assert [m["tipo"] for m in movs] == ["ingreso"]
    assert movs[0]["lote_id"] == lote_id


def test_ingreso_invalido(conn, tono):
    with pytest.raises(ValueError):
        stock.ingresar(conn, tono, 0)


def test_consumo_es_fefo(conn, tono):
    tarde = stock.ingresar(conn, tono, 3, vencimiento=iso(300), lote="TARDE")
    temprano = stock.ingresar(conn, tono, 2, vencimiento=iso(60), lote="TEMPRANO")

    asignaciones = stock.consumir(conn, tono, 3, motivo="test")

    assert asignaciones[0].lote_id == temprano
    assert asignaciones[0].unidades == 2
    assert asignaciones[1].lote_id == tarde
    assert asignaciones[1].unidades == 1
    assert stock.disponible(conn, tono) == 2


def test_lotes_sin_vencimiento_van_al_final(conn, tono):
    sin_fecha = stock.ingresar(conn, tono, 5, vencimiento=None)
    con_fecha = stock.ingresar(conn, tono, 1, vencimiento=iso(500))

    asignaciones = stock.consumir(conn, tono, 2)

    assert asignaciones[0].lote_id == con_fecha
    assert asignaciones[1].lote_id == sin_fecha


def test_consumo_ignora_vencidos(conn, tono):
    stock.ingresar(conn, tono, 10, vencimiento=iso(-1), lote="VIEJO")
    vigente = stock.ingresar(conn, tono, 2, vencimiento=iso(90), lote="NUEVO")

    assert stock.disponible(conn, tono) == 2
    asignaciones = stock.consumir(conn, tono, 2)
    assert [a.lote_id for a in asignaciones] == [vigente]


def test_consumo_sin_stock_no_deja_negativo(conn, tono):
    stock.ingresar(conn, tono, 1, vencimiento=iso(90))
    with pytest.raises(stock.StockInsuficiente):
        stock.consumir(conn, tono, 4)
    assert stock.disponible(conn, tono) == 1


def test_plan_fefo_no_toca_la_base(conn, tono):
    stock.ingresar(conn, tono, 2, vencimiento=iso(30))
    asignaciones, faltante = stock.plan_fefo(conn, tono, 5)
    assert faltante == 3
    assert sum(a.unidades for a in asignaciones) == 2
    assert stock.disponible(conn, tono) == 2


def test_ajuste_registra_diferencia(conn, tono):
    lote_id = stock.ingresar(conn, tono, 6, vencimiento=iso(120))
    assert stock.ajustar(conn, lote_id, 4) == -2
    assert stock.disponible(conn, tono) == 4
    assert stock.ajustar(conn, lote_id, 4) == 0


def test_descartar_vencidos(conn, tono):
    stock.ingresar(conn, tono, 3, vencimiento=iso(-10))
    stock.ingresar(conn, tono, 1, vencimiento=iso(365))

    descartados = stock.descartar_vencidos(conn)

    assert len(descartados) == 1 and descartados[0][1] == 3
    assert stock.disponible(conn, tono, incluir_vencidos=True) == 1


@pytest.mark.parametrize(
    "dias, esperado",
    [(-1, stock.VENCIDO), (10, stock.CRITICO), (60, stock.AVISO), (400, stock.OK)],
)
def test_estados_de_vencimiento(dias, esperado):
    assert stock.estado_vencimiento(iso(dias))[0] == esperado


def test_estado_sin_fecha():
    assert stock.estado_vencimiento(None)[0] == stock.SIN_FECHA


def test_alertas_agrupa_por_estado(conn, tono):
    stock.ingresar(conn, tono, 1, vencimiento=iso(-5))
    stock.ingresar(conn, tono, 1, vencimiento=iso(15))
    stock.ingresar(conn, tono, 1, vencimiento=iso(60))

    a = stock.alertas(conn)

    assert len(a["vencidos"]) == 1
    assert len(a["criticos"]) == 1
    assert len(a["avisos"]) == 1


def test_alerta_bajo_minimo(conn, tono):
    catalogo.actualizar_producto(conn, tono, stock_minimo=3)
    stock.ingresar(conn, tono, 1, vencimiento=iso(200))
    assert [f["producto_id"] for f in stock.alertas(conn)["bajo_minimo"]] == [tono]


def test_resumen_separa_vencido_de_util(conn, tono):
    stock.ingresar(conn, tono, 2, vencimiento=iso(-3))
    stock.ingresar(conn, tono, 4, vencimiento=iso(200))

    fila = next(f for f in stock.resumen(conn) if f["producto_id"] == tono)

    assert fila["unidades"] == 4
    assert fila["vencidas"] == 2
    assert fila["estado"] == stock.VENCIDO
