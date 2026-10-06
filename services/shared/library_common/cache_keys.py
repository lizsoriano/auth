"""Claves de la caché del catálogo y su invalidación (las usan books, authors y pedidos).

Claves: books:list:<filtros> (lista) y books:<isbn> (un libro), siempre con TTL corto.
Hoy GET /books no admite filtros, así que la lista es siempre books:list:all; si algún día se agregan filtros,
se incluyen aquí en SUPPORTED_FILTERS (solo los conocidos entran en la clave: un cliente no puede crear claves
nuevas con parámetros inventados y llenar la memoria de Redis).
"""
import re

ISBN_RE = re.compile(r"[0-9A-Za-z-]{1,17}")  # mismo alfabeto/longitud máxima que books.isbn
SUPPORTED_FILTERS = ()
BOOKS_LIST_PREFIX = "books:list:"


def books_list_key(args=None):
    """books:list:all, o books:list:<k=v&...> con los filtros soportados en orden alfabético."""
    pairs = sorted((k, str(v)) for k, v in (args or {}).items() if k in SUPPORTED_FILTERS and str(v) != "")
    return BOOKS_LIST_PREFIX + ("&".join(f"{k}={v}" for k, v in pairs) if pairs else "all")


def book_key(isbn):
    """books:<isbn>. Devuelve None si el isbn no tiene forma de ISBN (no se cachea: evita claves arbitrarias)."""
    return f"books:{isbn}" if isinstance(isbn, str) and ISBN_RE.fullmatch(isbn) else None


def invalidate_books(redis_layer, isbns=()):
    """Tras una escritura que cambia lo que muestra el catálogo: borra books:<isbn> y TODAS las listas.

    Es de la caché OPCIONAL: si Redis no responde no lanza (la clave expirará sola por su TTL corto).
    """
    keys = [k for k in (book_key(i) for i in isbns) if k]
    removed = redis_layer.cache_delete(*keys) if keys else 0
    return removed + redis_layer.cache_delete_pattern(BOOKS_LIST_PREFIX + "*")


def invalidate_all_books(redis_layer):
    """Cambios que afectan a muchos libros a la vez (p. ej. un autor): borra todo books:*."""
    return redis_layer.cache_delete_pattern("books:*")
