from app.repositories.organizacion_repository import slugify

def test_slugify_basico():
    assert slugify("Empresa Demo") == "empresa-demo"

def test_slugify_acentos_espacios_y_simbolos():
    assert slugify("  ¡A.C.M.E -- Corp!  ") == "a-c-m-e-corp"

def test_slugify_vacio_da_fallback():
    assert slugify("###") == "org"
