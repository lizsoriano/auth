#!/usr/bin/env python3
"""Crea (o reutiliza) 3 usuarios de demostración para probar el cliente de escritorio: admin, staff y customer.

Los correos son fijos (demo-admin@example.com, demo-staff@..., demo-customer@...) y la contraseña se toma de la
variable DEMO_PASSWORD: no se escribe en ningún archivo del repositorio. Uso (lo llama e2e/serve_local.sh):
    DEMO_PASSWORD=... ADMIN_DSN=postgresql://... python seed_demo_users.py
"""
import os

import bcrypt
import psycopg

USERS = (("demo-admin@example.com", 1, "Demo Admin"), ("demo-staff@example.com", 2, "Demo Staff"),
         ("demo-customer@example.com", 3, "Demo Customer"))

password = os.environ["DEMO_PASSWORD"]
pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()
with psycopg.connect(os.environ["ADMIN_DSN"], autocommit=True) as conn:
    for email, role_id, name in USERS:
        conn.execute(
            """INSERT INTO users (email, password_hash, display_name, role_id, email_verified_at)
               VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, role_id = EXCLUDED.role_id,
                                                  is_active = true""",
            (email, pw_hash, name, role_id))
print("usuarios demo listos:", ", ".join(email for email, _r, _n in USERS))
