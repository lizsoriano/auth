-- AUDITORÍA DE SOLO LECTURA del esquema actual (no modifica nada).
-- Úsala ANTES de normalizar/alterar tablas existentes: books, la app Electron y el monolito
-- dependen de ellas (vistas, funciones, consultas con columnas explícitas).
--
--   psql -h localhost -U library_user -d library_db -f data/audit_schema.sql -o audit_schema.txt
-- (el resultado solo contiene estructura, no datos; puede compartirse)

\echo '== Tablas y filas estimadas =='
SELECT c.relname AS tabla, c.reltuples::bigint AS filas_aprox
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1;

\echo '== Columnas =='
SELECT table_name, ordinal_position AS pos, column_name, data_type, is_nullable, column_default
  FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position;

\echo '== Llaves primarias, únicas, foráneas y checks =='
SELECT conrelid::regclass AS tabla, conname, contype, pg_get_constraintdef(oid) AS definicion
  FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 3, 2;

\echo '== Índices =='
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2;

\echo '== Vistas (renombrar/borrar columnas las rompería) =='
SELECT viewname, definition FROM pg_views WHERE schemaname = 'public' ORDER BY 1;

\echo '== Funciones y procedimientos (soap/books las invocan) =='
SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args, p.prosecdef AS security_definer
  FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace ORDER BY 1;

\echo '== Quién depende de qué: privilegios por rol y tabla =='
SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privilegios
  FROM information_schema.role_table_grants WHERE table_schema = 'public' AND grantee <> 'PUBLIC'
 GROUP BY grantee, table_name ORDER BY 1, 2;

\echo '== Privilegios por columna =='
SELECT grantee, table_name, column_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privilegios
  FROM information_schema.column_privileges WHERE table_schema = 'public' AND grantee NOT IN ('PUBLIC', 'library_user', 'postgres')
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
