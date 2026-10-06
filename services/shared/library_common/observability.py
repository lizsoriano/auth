"""GET /metrics (texto de Prometheus). Exige JWT de administrador: expone detalles internos."""
from flask import Response


def register_metrics_endpoint(app, metrics, guard):
    """`guard` es el decorador `auth.required(roles=("admin",))` del servicio."""

    @app.get("/metrics")
    @guard
    def metrics_view():
        response = Response(metrics.render_prometheus(), mimetype="text/plain")
        response.headers["Cache-Control"] = "no-store"
        return response
