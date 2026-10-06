import pytest

from library_common.cache_keys import (
    book_key, books_list_key, invalidate_all_books, invalidate_books)


def test_lista_sin_filtros_es_all_y_format_no_entra_en_la_clave():
    assert books_list_key() == "books:list:all"
    assert books_list_key({"format": "json"}) == "books:list:all"
    assert books_list_key({"format": "xml", "x": "1", "y": "2"}) == "books:list:all"  # parámetros inventados no crean claves


@pytest.mark.parametrize("isbn,esperado", [
    ("9780000000006", "books:9780000000006"), ("0-306-40615-2", "books:0-306-40615-2"),
    ("", None), ("a" * 18, None), ("97 80", None), ("../etc", None), ("x\ny", None), (None, None), (123, None)])
def test_clave_de_libro_solo_para_isbn_con_forma_valida(isbn, esperado):
    assert book_key(isbn) == esperado


def test_invalidate_books_borra_el_libro_y_todas_las_listas(layer, raw):
    layer.cache_set("books:list:all", [1], 60)
    layer.cache_set("books:list:otra", [2], 60)
    layer.cache_set("books:9780000000006", {"a": 1}, 60)
    layer.cache_set("books:9780000000001", {"b": 1}, 60)
    layer.cache_set("authors:1", {"c": 1}, 60)
    assert invalidate_books(layer, ["9780000000006"]) == 3
    assert raw.exists("books:9780000000001") == 1 and raw.exists("authors:1") == 1
    assert raw.exists("books:list:all") == 0 and raw.exists("books:9780000000006") == 0


def test_invalidate_books_ignora_isbn_con_forma_rara(layer, raw):
    layer.cache_set("books:list:all", [1], 60)
    assert invalidate_books(layer, ["../x", "", None]) == 1


def test_invalidate_all_books_borra_todo_books(layer, raw):
    layer.cache_set("books:list:all", [1], 60)
    layer.cache_set("books:1", {"a": 1}, 60)
    layer.cache_set("authors:1", {"c": 1}, 60)
    assert invalidate_all_books(layer) == 2 and raw.exists("authors:1") == 1


def test_invalidar_con_redis_caido_no_lanza(layer, redis_down, metrics):
    assert invalidate_books(layer, ["9780000000006"]) == 0
    assert invalidate_all_books(layer) == 0
    assert metrics.get("cache_errors_total", op="delete") == 1
