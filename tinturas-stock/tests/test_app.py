"""Smoke test de las páginas de Streamlit con AppTest.

Corre cada script de verdad (sin browser) y falla si alguno tira una excepción.
Cubre lo que los tests de lógica no ven: nombres mal escritos en la UI,
column_config inválidos, dataframes mal armados.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = [RAIZ / "app.py", *sorted((RAIZ / "pages").glob("*.py"))]


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base temporal con catálogo y algo de stock, y el cache de Streamlit limpio."""
    from src import catalogo, db, stock, ui

    destino = tmp_path / "tinturas.db"
    monkeypatch.setattr(db, "DB_PATH", destino)
    monkeypatch.setattr(ui, "DB_PATH", destino)
    ui.conn.clear()

    conn = db.conectar(destino)
    catalogo.sembrar(conn)
    tono = catalogo.productos(conn, tipo=db.TINTURA)[0]["id"]
    oxi = catalogo.productos(conn, tipo=db.OXIDANTE)[0]["id"]
    hoy = date.today()
    stock.ingresar(conn, tono, 4, (hoy + timedelta(days=200)).isoformat(), lote="OK")
    stock.ingresar(conn, tono, 1, (hoy - timedelta(days=5)).isoformat(), lote="VENCIDO")
    stock.ingresar(conn, oxi, 2, (hoy + timedelta(days=20)).isoformat(), lote="POR-VENCER")
    conn.close()
    yield destino
    ui.conn.clear()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_la_pagina_corre_sin_excepciones(script, base):
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception, f"{script.name}: {[e.value for e in app.exception]}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_la_pagina_corre_con_la_base_vacia(script, tmp_path, monkeypatch):
    """Primer arranque: la base ni siquiera existe todavía."""
    from src import db, ui

    destino = tmp_path / "vacia.db"
    monkeypatch.setattr(db, "DB_PATH", destino)
    monkeypatch.setattr(ui, "DB_PATH", destino)
    ui.conn.clear()

    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception, f"{script.name}: {[e.value for e in app.exception]}"
    ui.conn.clear()
