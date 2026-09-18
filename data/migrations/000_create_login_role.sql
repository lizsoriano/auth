-- Crea el rol de base de datos del microservicio login (idempotente).
-- Ejecutar como superusuario (postgres). La contraseña NO vive en el repo:
--
--   sudo -u postgres psql -d library_db -v login_password='UNA-CLAVE-LARGA' -f data/migrations/000_create_login_role.sql
--
-- Nota: CREATE ROLE puede quedar en el log de PostgreSQL si log_statement = 'all'.
SELECT format('CREATE ROLE login_service_user LOGIN PASSWORD %L', :'login_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'login_service_user')
\gexec
