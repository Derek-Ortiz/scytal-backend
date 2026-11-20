import uuid

from app.services.destinatario_service import parse_csv_import

G1, G2 = uuid.uuid4(), uuid.uuid4()
GRUPOS = {"soporte": G1, "ventas": G2}

def test_csv_valido_basico():
    r = parse_csv_import("correo,grupo\na@x.com,Soporte\nb@y.com,ventas\n", GRUPOS)
    assert r.total_filas == 2
    assert r.validos == [("a@x.com", G1), ("b@y.com", G2)]
    assert r.invalidos == 0 and r.duplicados_in_file == 0 and not r.errores

def test_csv_grupo_case_insensitive():
    r = parse_csv_import("correo,grupo\na@x.com,SOPORTE\n", GRUPOS)
    assert r.validos == [("a@x.com", G1)]

def test_csv_correo_normalizado_a_minusculas():
    r = parse_csv_import("correo,grupo\nJuan.Perez@Empresa.COM,Soporte\n", GRUPOS)
    assert r.validos == [("juan.perez@empresa.com", G1)]

def test_csv_encabezado_invalido_lanza_error():
    for contenido in ("grupo,correo\na@x.com,Soporte\n", "email,grupo\na@x.com,Soporte\n", "sin encabezado\n"):
        try:
            parse_csv_import(contenido, GRUPOS)
            assert False, f"debió rechazar: {contenido!r}"
        except ValueError as e:
            assert "correo,grupo" in str(e)

def test_csv_vacio_lanza_error():
    try:
        parse_csv_import("\n\n", GRUPOS)
        assert False
    except ValueError:
        pass

def test_csv_fila_invalida_correo_malo():
    r = parse_csv_import("correo,grupo\nno-es-correo,Soporte\nb@y.com,Soporte\n", GRUPOS)
    assert r.total_filas == 2
    assert r.validos == [("b@y.com", G1)]
    assert r.invalidos == 1
    assert "fila 2" in r.errores[0] and "correo no válido" in r.errores[0]

def test_csv_grupo_inexistente_es_invalido():
    r = parse_csv_import("correo,grupo\na@x.com,Contabilidad\n", GRUPOS)
    assert r.invalidos == 1
    assert "no existe en tu organización" in r.errores[0]

def test_csv_duplicado_dentro_del_archivo():
    r = parse_csv_import("correo,grupo\na@x.com,Soporte\nA@X.com,Ventas\nb@y.com,Soporte\n", GRUPOS)
    assert r.validos == [("a@x.com", G1), ("b@y.com", G1)]
    assert r.duplicados_in_file == 1
    assert "duplicado" in r.errores[0]

def test_csv_fila_con_menos_columnas():
    r = parse_csv_import("correo,grupo\nsolo-correo@x.com\nb@y.com,Soporte\n", GRUPOS)
    assert r.invalidos == 1 and r.total_filas == 2
    assert r.validos == [("b@y.com", G1)]

def test_csv_lineas_vacias_intermedias_se_ignoran():
    r = parse_csv_import("correo,grupo\n\na@x.com,Soporte\n\nb@y.com,ventas\n\n", GRUPOS)
    assert r.total_filas == 2 and len(r.validos) == 2

def test_csv_columnas_extra_se_aceptan():
    r = parse_csv_import('correo,grupo\n"a@x.com",Soporte,"nota"\n', GRUPOS)
    assert r.validos == [("a@x.com", G1)]

def test_csv_bom_utf8():
    r = parse_csv_import("\ufeffcorreo,grupo\na@x.com,Soporte\n", GRUPOS)
    assert r.validos == [("a@x.com", G1)]

def test_csv_sin_grupos_registrados_todo_invalido():
    r = parse_csv_import("correo,grupo\na@x.com,Soporte\n", {})
    assert r.invalidos == 1 and not r.validos
