-- =====================================================================
-- Setup de la app cfe-notas-obra-lh (version Lakehouse)
-- Ejecutar UNA VEZ antes del primer despliegue, con un usuario que sea
-- duenio del esquema (o tenga MANAGE). Reemplaza:
--   dipidev.default  -> tu CATALOG.WORK_SCHEMA de config.py
--   <APP_SP_ID>      -> application ID del service principal de la app
--                       (campo service_principal_client_id en `databricks apps get <app>`)
-- =====================================================================

-- 1. Tablas Delta que usa la app (la app NO las crea; asi no necesita CREATE TABLE)
CREATE TABLE IF NOT EXISTS dipidev.default.notas_obra (
  id BIGINT GENERATED ALWAYS AS IDENTITY,
  id_obra BIGINT,
  nombre_obra STRING,
  tipo_nota STRING,
  descripcion STRING,
  prioridad STRING,
  evidencia_url STRING,
  usuario STRING,
  fecha_registro TIMESTAMP,
  estado STRING,
  fecha_estado TIMESTAMP
) COMMENT 'Notas de campo capturadas por la app cfe-notas-obra-lh';

CREATE TABLE IF NOT EXISTS dipidev.default.bitacora_app (
  id BIGINT GENERATED ALWAYS AS IDENTITY,
  accion STRING,
  detalle STRING,
  usuario STRING,
  ip_cliente STRING,
  fecha TIMESTAMP
) COMMENT 'Bitacora de eventos de la app cfe-notas-obra-lh';

-- 2. Permisos de Unity Catalog para el service principal de la app
GRANT USE CATALOG ON CATALOG dipidev TO `<APP_SP_ID>`;
GRANT USE SCHEMA ON SCHEMA dipidev.default TO `<APP_SP_ID>`;
GRANT SELECT ON TABLE dipidev.default.gold_fact_obras TO `<APP_SP_ID>`;
GRANT SELECT, MODIFY ON TABLE dipidev.default.notas_obra TO `<APP_SP_ID>`;
GRANT SELECT, MODIFY ON TABLE dipidev.default.bitacora_app TO `<APP_SP_ID>`;

-- 3. Permiso sobre el SQL Warehouse (no es SQL): ligar el warehouse como
--    recurso de la app (llave "sql-warehouse", permiso CAN_USE) desde la
--    pagina de la app, o pedir al duenio del warehouse que otorgue CAN_USE.
