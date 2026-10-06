# Capturas de evidencia — Redis + JWT + microservicios (Library)

Capturas tomadas en la VM `maquina-02` (CentOS Stream 10) con los 6 microservicios, PostgreSQL y Redis reales.
Los JWT y refresh tokens salen recortados, la contraseña enmascarada (`********`) y no aparece ningún secreto.

## 1. Terminal en la VM

| Imagen | Qué demuestra |
|---|---|
| [`vm_01_health_6_servicios_y_nginx.png`](1_Terminal_VM/vm_01_health_6_servicios_y_nginx.png) | `/health` de los 6 microservicios (puertos 5000-5005) y de Nginx: todos 200. |
| [`vm_02_evidencia_faseA_parte1.png`](1_Terminal_VM/vm_02_evidencia_faseA_parte1.png) | Evidencia de punta a punta, Fase A (parte 1): JWT de 20 min, sesión en Redis, caché de Books y su invalidación, Authors. |
| [`vm_03_redis_stop_start_is-active.png`](1_Terminal_VM/vm_03_redis_stop_start_is-active.png) | Redis apagado y encendido con `systemctl`; `is-active` responde `active`. |

## 2. curl: petición y respuesta por microservicio

| Imagen | Qué demuestra |
|---|---|
| [`curl_01_login_JWT.png`](2_curl_microservicios/curl_01_login_JWT.png) | Login: JWT HS256 de 20 min (`token_expires_in_seconds` 1200) y refresh token. |
| [`curl_03_books_cache_parte1.png`](2_curl_microservicios/curl_03_books_cache_parte1.png) | Books `GET /books`: 1.ª consulta y 2.ª consulta (más rápida, desde Redis). |
| [`curl_03_books_cache_parte2_clave_redis.png`](2_curl_microservicios/curl_03_books_cache_parte2_clave_redis.png) | Clave `books:list:all` en Redis con TTL de 60 s. |
| [`curl_04_books_seguridad_401_403_200.png`](2_curl_microservicios/curl_04_books_seguridad_401_403_200.png) | Books `PATCH`: sin JWT 401, customer 403, admin 200, y la caché invalidada (0 claves `books:*`). |
| [`curl_05_users_roles.png`](2_curl_microservicios/curl_05_users_roles.png) | Users: el customer ve su cuenta (200) y no puede listar usuarios (403). |
| [`curl_06_authors_publico_y_401.png`](2_curl_microservicios/curl_06_authors_publico_y_401.png) | Authors: lectura pública (200) y `POST` sin JWT (401). |
| [`curl_07_pedidos.png`](2_curl_microservicios/curl_07_pedidos.png) | Pedidos: crear pedido (201, pendiente de pago) y consultarlo (200). |
| [`curl_08_pagos_idempotencia.png`](2_curl_microservicios/curl_08_pagos_idempotencia.png) | Pagos: pago 201 y reintento con la misma `Idempotency-Key` (200, `Idempotent-Replay: true`). |
| [`curl_09_logout_revocacion.png`](2_curl_microservicios/curl_09_logout_revocacion.png) | Logout: `jwt:revoked:<jti>` en Redis y el mismo JWT rechazado (401 `token_revoked`) en Users y Pagos. |
| [`curl_10_redis_caido_parte1.png`](2_curl_microservicios/curl_10_redis_caido_parte1.png) | Redis apagado: el catálogo público sigue (200) y `/users/me` con JWT válido falla cerrado (503). |
| [`curl_10_redis_caido_parte2.png`](2_curl_microservicios/curl_10_redis_caido_parte2.png) | Redis apagado: `POST /login` 503 y `/health` de Books con `redis: unavailable`. |

## 3. App de escritorio Python Tk (contra la VM)

| Imagen | Qué demuestra |
|---|---|
| [`tk_01_login_admin_jwt_y_configuracion_VM.png`](3_App_Python_Tk/tk_01_login_admin_jwt_y_configuracion_VM.png) | App Tk: sesión como admin con el reloj del JWT (20 min) y las 6 URLs de los microservicios. |
| [`tk_02_semaforos_verdes.png`](3_App_Python_Tk/tk_02_semaforos_verdes.png) | Semáforos: los 6 microservicios y Redis en verde. |
| [`tk_03_libros_crear_POST.png`](3_App_Python_Tk/tk_03_libros_crear_POST.png) | Libros (Books): alta de un libro con `POST`. |
| [`tk_04_autores_crear_POST_201.png`](3_App_Python_Tk/tk_04_autores_crear_POST_201.png) | Autores (Authors): alta de un autor, `POST` 201. |
| [`tk_06_usuarios_listar_GET_200.png`](3_App_Python_Tk/tk_06_usuarios_listar_GET_200.png) | Usuarios (Users): lista de usuarios y roles como admin, `GET` 200. |
| [`tk_07_pedidos_crear_POST_201.png`](3_App_Python_Tk/tk_07_pedidos_crear_POST_201.png) | Pedidos: alta de un pedido, `POST` 201, pendiente de pago. |
| [`tk_08_pagos_registrar_POST_201.png`](3_App_Python_Tk/tk_08_pagos_registrar_POST_201.png) | Pagos: pago del pedido, `POST` 201. |
| [`tk_09_pagos_idempotencia_NO_se_cobro_otra_vez.png`](3_App_Python_Tk/tk_09_pagos_idempotencia_NO_se_cobro_otra_vez.png) | Pagos: reintento con la misma clave, `Idempotent-Replay: true` («NO se cobró otra vez»). |
| [`tk_10_semaforos_redis_apagado.png`](3_App_Python_Tk/tk_10_semaforos_redis_apagado.png) | Semáforos con Redis apagado: los 6 servicios en amarillo (degradado) y Redis en rojo. |
| [`tk_11_semaforos_redis_recuperado.png`](3_App_Python_Tk/tk_11_semaforos_redis_recuperado.png) | Semáforos: Redis de nuevo encendido, todo en verde. |

## Pendiente (se agrega después)

- `4_Animacion_y_portafolio/`: capturas de la animación y de la página Parcial 2 (se agregan después).
