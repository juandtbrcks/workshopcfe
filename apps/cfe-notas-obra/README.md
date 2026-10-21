# cfe-notas-obra — Notas de Campo CFE (version Lakebase)

App de Databricks para capturar notas de campo de las obras de construccion de CFE.
Las escrituras transaccionales (notas, cambios de estado, bitacora) van a **Lakebase (PostgreSQL administrado)**
y se sincronizan hacia Delta en Unity Catalog para analitica.

## Arquitectura
```
Usuario → App (app_v3.py) → Lakebase Postgres
                               ├─ obras_catalogo  (lectura: lista de obras)
                               ├─ notas_obra      (lectura/escritura)
                               └─ bitacora_app    (escritura)
                                     │
          sync_lakebase_to_delta (Job) ▼
          dipidev.default.notas_obra_sync / bitacora_app_sync / obras_catalogo_sync (Delta)
```

## Funcionalidad
* Lista de obras desde `obras_catalogo` en Lakebase
* Formulario de nota: obra, tipo de nota (8 tipos), prioridad, descripcion y URL de evidencia
* Ultimas 20 notas por obra
* Flujo de estado por nota: Abierta → En Proceso → Resuelta
* Bitacora de eventos (PAGE_VIEW, NOTA_CREADA, ESTADO_CAMBIO, ERROR, APP_START)
* Token OAuth de Postgres renovado en cada conexion (expira aprox. 1 h)
* La app crea `notas_obra` y `bitacora_app` en Lakebase si no existen

## Archivos
* `app_v3.py` — servidor HTTP en Python puro
* `app.yaml` — comando de arranque, variables de entorno y recurso Lakebase
* `requirements.txt` — `psycopg[binary]`, `databricks-sql-connector`, `databricks-sdk`
* `sync_lakebase_to_delta` — notebook que copia las tablas de Lakebase a Delta (programable como Job)

## Valores especificos del workspace (ajustar en `app.yaml` y en el notebook de sync)
| Variable | Descripcion | Valor actual |
| --- | --- | --- |
| `LAKEBASE_ENDPOINT` | Endpoint del branch de Lakebase | `projects/lakebaseworkshop/branches/production/endpoints/primary` |
| `PGHOST` | Host del endpoint Postgres | `ep-lively-mountain-eb5kgl2c.database.southcentralus.azuredatabricks.net` |
| `PGDATABASE` | Base de datos | `databricks_postgres` |
| `PGUSER` | Rol Postgres = client ID del service principal de la app | `a4b54d8f-d30b-46b2-92f4-07cc332bf8d1` |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse (no se usa en el flujo actual de la app) | `13ccaff5dbf9dd2f` |
| `resources.postgres.branch` | Branch de Lakebase ligado como recurso | `projects/lakebaseworkshop/branches/production` |

## Pasos para desplegar
1. **Lakebase**: tener un proyecto de Lakebase con su branch `production` (en este workspace: `lakebaseworkshop`).
2. **Crear la app** en Databricks Apps y ligar el branch como recurso (`lakebase-db`, permiso `CAN_CONNECT_AND_CREATE`).
   Esto crea el rol Postgres del service principal de la app.
3. **Catalogo de obras**: cargar la tabla `obras_catalogo (id_obra, nombre_obra)` en Lakebase a partir de
   `tbobras` o `gold_fact_obras` (prerequisito: la app solo la lee).
4. **Ajustar `app.yaml`** con los valores de tu workspace (tabla anterior).
5. **Desplegar** desde la carpeta de este repo:
   `databricks apps deploy <nombre-app> --source-code-path /Workspace/<ruta>/workshopcfe/apps/cfe-notas-obra`
6. **Analitica (opcional)**: programar `sync_lakebase_to_delta` como Job para tener las notas en Delta.

## Version alternativa
Si no hay Lakebase disponible, ver `../cfe-notas-obra-lh` (misma funcionalidad, solo Delta + SQL Warehouse).
