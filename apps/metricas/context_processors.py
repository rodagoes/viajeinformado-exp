from .services.real import habilitado


def metricas(request):
    """METRICAS_ACTIVAS: si hay que cargar metricas.js. Falso con el seguimiento apagado y para staff (no se rastrea)."""
    usuario = getattr(request, "user", None)
    es_staff = usuario is not None and usuario.is_authenticated and (usuario.is_staff or usuario.is_superuser)
    return {"METRICAS_ACTIVAS": habilitado() and not es_staff}
