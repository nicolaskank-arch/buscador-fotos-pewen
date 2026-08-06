from datetime import date, timedelta

import pytest

from src import catalogo, stock, verificacion
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


def test_abrir_congela_los_lotes_con_stock(conn, tono):
    stock.ingresar(conn, tono, 4, vencimiento=iso(200))
    vacio = stock.ingresar(conn, tono, 1, vencimiento=iso(200))
    stock.descartar(conn, vacio)

    vid = verificacion.abrir(conn, usuario="Nico")

    filas = verificacion.detalle(conn, vid)
    assert len(filas) == 1
    assert filas[0]["esperado"] == 4
    assert filas[0]["contado"] is None


def test_faltante_y_sobrante(conn, tono):
    lote_a = stock.ingresar(conn, tono, 10, vencimiento=iso(200), lote="A")
    lote_b = stock.ingresar(conn, tono, 5, vencimiento=iso(300), lote="B")
    vid = verificacion.abrir(conn)

    verificacion.contar(conn, vid, lote_a, 8)
    verificacion.contar(conn, vid, lote_b, 6)

    r = verificacion.resumen(conn, vid)
    assert r["con_diferencia"] == 2
    assert r["faltantes"] == 2
    assert r["sobrantes"] == 1
    assert r["pendientes"] == 0


def test_cerrar_ajusta_el_stock(conn, tono):
    lote_id = stock.ingresar(conn, tono, 10, vencimiento=iso(200))
    vid = verificacion.abrir(conn)
    verificacion.contar(conn, vid, lote_id, 7)

    ajustes = verificacion.cerrar(conn, vid)

    assert ajustes == [(lote_id, -3)]
    assert stock.disponible(conn, tono) == 7
    assert stock.movimientos(conn, producto_id=tono)[0]["tipo"] == "ajuste"


def test_lotes_sin_contar_no_se_tocan(conn, tono):
    contado = stock.ingresar(conn, tono, 4, vencimiento=iso(200), lote="A")
    sin_contar = stock.ingresar(conn, tono, 6, vencimiento=iso(300), lote="B")
    vid = verificacion.abrir(conn)
    verificacion.contar(conn, vid, contado, 3)

    verificacion.cerrar(conn, vid)

    assert stock.lotes(conn, tono)[1]["cantidad"] == 6
    assert sum(l["cantidad"] for l in stock.lotes(conn, tono) if l["id"] == sin_contar) == 6


def test_cerrar_sin_aplicar_deja_el_stock_igual(conn, tono):
    lote_id = stock.ingresar(conn, tono, 10, vencimiento=iso(200))
    vid = verificacion.abrir(conn)
    verificacion.contar(conn, vid, lote_id, 2)

    assert verificacion.cerrar(conn, vid, aplicar_ajustes=False) == []
    assert stock.disponible(conn, tono) == 10


def test_no_se_puede_contar_ni_cerrar_dos_veces(conn, tono):
    lote_id = stock.ingresar(conn, tono, 3, vencimiento=iso(200))
    vid = verificacion.abrir(conn)
    verificacion.cerrar(conn, vid)

    with pytest.raises(verificacion.VerificacionCerrada):
        verificacion.contar(conn, vid, lote_id, 1)
    with pytest.raises(verificacion.VerificacionCerrada):
        verificacion.cerrar(conn, vid)


def test_lote_nuevo_durante_el_conteo(conn, tono):
    stock.ingresar(conn, tono, 2, vencimiento=iso(200))
    vid = verificacion.abrir(conn)
    tardio = stock.ingresar(conn, tono, 5, vencimiento=iso(400), lote="LLEGÓ DESPUÉS")

    verificacion.contar(conn, vid, tardio, 5)

    assert len(verificacion.detalle(conn, vid)) == 2
    assert verificacion.resumen(conn, vid)["con_diferencia"] == 0


def test_conteo_negativo_rechazado(conn, tono):
    lote_id = stock.ingresar(conn, tono, 2, vencimiento=iso(200))
    vid = verificacion.abrir(conn)
    with pytest.raises(ValueError):
        verificacion.contar(conn, vid, lote_id, -1)


def test_abierta_devuelve_la_ultima(conn, tono):
    stock.ingresar(conn, tono, 1, vencimiento=iso(200))
    assert verificacion.abierta(conn) is None
    vid = verificacion.abrir(conn)
    assert verificacion.abierta(conn)["id"] == vid
    verificacion.cerrar(conn, vid)
    assert verificacion.abierta(conn) is None
