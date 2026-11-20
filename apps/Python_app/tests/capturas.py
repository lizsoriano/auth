"""Toma una captura PNG de cada pestaña de la app (evidencia de la GUI funcionando contra los microservicios).

Mismos requisitos que gui_integration.py (servicios arriba y LIB_DEMO_PASSWORD) más Pillow (`pip install pillow`).
Uso: python tests/capturas.py [carpeta_de_salida] [rol: admin|staff|customer]
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import session_store  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tk_cap_"))
config.CONFIG_PATH = TMP / "config.json"
session_store.SESSION_PATH = TMP / "session.json"
session_store.COOKIE_PATH = TMP / "cookies.txt"

from tkinter import messagebox  # noqa: E402

messagebox.showinfo = messagebox.showwarning = messagebox.showerror = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True

import app as app_module  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "capturas")
ROLE = sys.argv[2] if len(sys.argv) > 2 else "admin"
OUT.mkdir(parents=True, exist_ok=True)
base = int(os.environ.get("LIB_BASE_PORT", "15000"))
urls = config.remote_urls(os.environ["LIB_VM"]) if os.environ.get("LIB_VM") else {k: f"http://localhost:{base + i}" for i, k in enumerate(config.KEYS)}
config.save({f"{k}_url": v for k, v in urls.items()})


def spin(app, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def _print_window(app):
    """Le pide a la PROPIA ventana que se dibuje en un bitmap (Win32 PrintWindow): no depende de qué haya delante ni
    del escritorio, y nunca incluye otras aplicaciones."""
    import ctypes
    from ctypes import wintypes

    from PIL import Image

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = app.winfo_id()
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right, rect.bottom

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bitmap)
    user32.PrintWindow(hwnd, mem, 2)  # 2 = PW_RENDERFULLCONTENT
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buffer = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bitmap, 0, h, buffer, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGBA", (w, h), buffer, "raw", "BGRA", 0, 1).convert("RGB")


def shot(app, name):
    spin(app, 0.5)
    app.update()
    _print_window(app).save(OUT / f"{name}.png")
    print("captura:", OUT / f"{name}.png")


app = app_module.App()
app.geometry("1180x780+40+20")
app.attributes("-topmost", True)  # al frente aunque otra app tenga el foco: así la captura nunca incluye otras ventanas
spin(app, 0.6)
shot(app, "01_login")
lv = app.login_view
lv.email.insert(0, f"demo-{ROLE}@example.com")
lv.password.insert(0, os.environ["LIB_DEMO_PASSWORD"])
lv.do_login()
spin(app, 1)
mv = app.main_view


def tab(key):
    mv.notebook.select(mv.tabs[key][0])
    spin(app, 0.6)
    return mv.tabs[key][0]


# datos para que las tablas no salgan vacías
pedidos = tab("pedidos")
if not pedidos.tree.get_children():
    pedidos.new.set("isbn", "9780000000006")
    pedidos.add_line()
    pedidos.crear()
tab("catalogo")
shot(app, "02_catalogo")
tab("libros")
shot(app, "03_libros_books")
a = tab("autores")
a.listar()
shot(app, "04_autores")
u = tab("usuarios")
u.mi_cuenta()
u.listar(quiet=True)
shot(app, "05_usuarios")
p = tab("pedidos")
p.listar()
if p.tree.get_children():
    p.tree.selection_set(p.tree.get_children()[0])
spin(app, 0.6)
shot(app, "06_pedidos")
g = tab("pagos")
if p.tree.get_children():
    order = app.api.get_order(int(p.tree.get_children()[0]))
    if order["status"] == "pendiente":
        g.prefill(order)
        g.pagar()
        g.reintentar()
g.listar()
shot(app, "07_pagos")
tab("perfil")
shot(app, "08_perfil")
e = tab("estado")
e.check_now()
spin(app, 1.5)
shot(app, "09_semaforos")
tab("bitacora")
shot(app, "10_bitacora")
tab("config")
shot(app, "11_configuracion")
app.on_logout()
app.destroy()
