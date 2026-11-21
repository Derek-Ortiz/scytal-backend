from app.services import hibp_service, password_service

def test_fortaleza_local_debil():
    res = password_service.fortaleza_local("password123")
    assert res["es_fuerte"] is False and res["score"] < 3
    assert any("comunes" in e for e in res["errores"])

def test_fortaleza_local_corta():
    res = password_service.fortaleza_local("abc")
    assert res["es_fuerte"] is False
    assert any("10 caracteres" in e for e in res["errores"])

def test_fortaleza_local_fuerte():
    res = password_service.fortaleza_local("Correcta-Caballo-42-Bateria!")
    assert res["es_fuerte"] is True and res["score"] >= 3
    assert res["errores"] == []

def test_parsear_rango():
    body = "AAA111:2\nBBB222:345\nlinea_mala\nCCC333:0\n"
    conteos = hibp_service._parsear_rango(body)
    assert conteos == {"AAA111": 2, "BBB222": 345, "CCC333": 0}

def test_parsear_rango_vacio():
    assert hibp_service._parsear_rango("") == {}

def test_count_in_reusa_parser():
    body = "ABCDEF:7\n"
    assert hibp_service._count_in(body, "abcdef") == 7
    assert hibp_service._count_in(body, "ZZZZZZ") == 0
