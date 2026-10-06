-- Crea los roles de base de datos de los microservicios Users, Authors, Pedidos y Pagos (idempotente).
-- Ejecutar como superusuario (postgres). Las contraseñas NO viven en el repo: llegan por -v.
--
--   sudo -u postgres psql -d library_db \
--     -v users_password='...' -v authors_password='...' \
--     -v pedidos_password='...' -v pagos_password='...' \
--     -f data/migrations/007_service_db_roles.sql
--
-- (deploy/setup_db_vm.sh las pide en la terminal y las genera; nunca se escriben en un archivo versionado.)
-- Nota: CREATE ROLE puede quedar en el log de PostgreSQL si log_statement = 'all'.
SELECT format('CREATE ROLE users_service_user LOGIN PASSWORD %L', :'users_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'users_service_user')
\gexec

SELECT format('CREATE ROLE authors_service_user LOGIN PASSWORD %L', :'authors_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authors_service_user')
\gexec

SELECT format('CREATE ROLE pedidos_service_user LOGIN PASSWORD %L', :'pedidos_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pedidos_service_user')
\gexec

SELECT format('CREATE ROLE pagos_service_user LOGIN PASSWORD %L', :'pagos_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pagos_service_user')
\gexec
