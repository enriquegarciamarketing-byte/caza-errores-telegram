"""15/11/2026: precio estable de marca conocida no se descarta por «no es ninguna bajada»; el truco sí."""

from datetime import datetime, timezone

import historial

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def _hist(rows):
    return {"B0TEST0001": rows}


def test_estable_marca_conocida_pasa():
    h = _hist([[20261112, 269.0, 269.0], [20261113, 269.0, 269.0], [20261114, 269.0, 269.0]])
    honest, why, _ = historial.check("B0TEST0001", 269.0, 399.0, NOW, h, min_drop_pct=30, estable_ok=True)
    assert why == "" and honest is None


def test_estable_sin_marca_conocida_sigue_fuera():
    h = _hist([[20261112, 269.0, 269.0], [20261113, 269.0, 269.0], [20261114, 269.0, 269.0]])
    _, why, _ = historial.check("B0TEST0001", 269.0, 399.0, NOW, h, min_drop_pct=30)
    assert why.startswith("no es ninguna bajada")


def test_sube_y_baja_sigue_fuera_aunque_sea_marca_conocida():
    h = _hist([[20261112, 30.0, 30.0], [20261113, 30.0, 59.0], [20261114, 30.0, 30.0]])
    _, why, _ = historial.check("B0TEST0001", 30.0, 59.0, NOW, h, min_drop_pct=30, estable_ok=True)
    assert why.startswith("no es ninguna bajada")


def test_mas_caro_que_esta_semana_sigue_fuera():
    h = _hist([[20261112, 50.0, 50.0], [20261113, 50.0, 50.0], [20261114, 50.0, 50.0]])
    _, why, _ = historial.check("B0TEST0001", 54.0, 99.0, NOW, h, min_drop_pct=30, estable_ok=True)
    assert why.startswith("no es ninguna bajada")
