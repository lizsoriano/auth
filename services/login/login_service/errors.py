class ApiError(Exception):
    """Error de negocio que se serializa a XML/JSON con su código HTTP."""

    def __init__(self, code, message, status, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


class EmailAlreadyExists(Exception):
    """Lanzada por el repositorio cuando el email viola la unicidad."""
