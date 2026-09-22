"""Excepciones propias de la capa de acceso a datos.

Deliberadamente NO conocen nada de SOAP/XML — son errores de negocio
puros. Es soap/service.py quien las atrapa y las traduce a un
soap.faults.SoapFaultError concreto (mantiene db/ desacoplado de soap/).
"""


class ConceptoInexistenteError(Exception):
    """El par (book_id, concept_id) no existe en book_concepts."""


class ClasificacionDuplicadaError(Exception):
    """Ya existe una fila en clasificaciones_cloud para ese
    (clasificador_id, book_id, concept_id) — violación de
    uq_clasificaciones_sin_duplicado."""
