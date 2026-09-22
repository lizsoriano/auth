"""Punto de entrada del servicio SOAP de clasificación Cloud.

Expone:
  GET  /wsdl  -> sirve wsdl/library-classifier.wsdl tal cual.
  POST /soap  -> recibe el Envelope SOAP y lo despacha vía soap/service.py.

  Actividad en clase (microservicio bilingüe XML/JSON, ver rest_api.py):
  GET  /books            -> lista de libros (XML por defecto, JSON con ?format=json)
  GET  /books/<isbn>     -> un libro
  GET  /books/images     -> libros con sus imágenes
  GET  /concepts         -> conceptos de Cloud Computing + datos del libro

Arrancar con: python app.py  (usa SOAP_HOST/SOAP_PORT de .env).
"""
from pathlib import Path

from flask import Flask, Response, request

from config.settings import Config, configure_logging
from soap import service
import rest_api

configure_logging()

app = Flask(__name__)
rest_api.register(app)

WSDL_PATH = Path(__file__).resolve().parent / "wsdl" / "library-classifier.wsdl"


@app.get("/wsdl")
def get_wsdl():
    return Response(WSDL_PATH.read_bytes(), mimetype="text/xml")


@app.post("/soap")
def post_soap():
    raw_body = request.get_data()
    response_bytes, status = service.handle_request(raw_body, remote_addr=request.remote_addr)
    return Response(response_bytes, status=status, mimetype="text/xml")


if __name__ == "__main__":
    app.run(
        host=Config.SOAP_HOST,
        port=Config.SOAP_PORT,
        debug=(Config.FLASK_ENV == "development"),
    )
