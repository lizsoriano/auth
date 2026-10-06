from library_common.errors import ApiError  # noqa: F401  (misma clase en los 6 servicios)


class EmailAlreadyExists(Exception):
    """Lanzada por el repositorio cuando el email viola la unicidad."""
