# cfe-notas-obra-lh — Notas de Campo CFE (version Lakehouse)

App de Databricks para capturar notas de campo de las obras de construccion de CFE.
Es la version **solo Lakehouse** de `cfe-notas-obra`: misma funcionalidad, pero sin Lakebase.
Todo vive en Delta (Unity Catalog) y se accede via un SQL Warehouse.

## Funcionalidad
* Catalogo de obras leido de la capa **Gold** (`gold_fact_obras`, generada por el pipeline del lab 03)
* Formulario de nota: obra, tipo de nota (8 tipos), prioridad, descripcion y URL de evidencia
* Ultimas 20 notas por obra
* Flujo de estado por nota: Abierta → En Proceso → Resuelta
* Bitacora de eventos (PAGE_VIEW, NOTA_CREADA, ESTADO_CAMBIO, ERROR, APP_START)
* Registra el correo del usuario final (header `X-Forwarded-Email`), no el del service principal
* SQL parametrizado (sin concatenar valores del usuario)

## Tablas
| Tabla | Uso |
| --- | --- |
| `<CATALOG>.<SCHEMA>.gold_fact_obras` | Lectura: catalogo de obras |
| `<CATALOG>.<SCHEMA>.notas_obra` | Lectura/escritura: notas de campo |
| `<CATALOG>.<SCHEMA>.bitacora_app` | Escritura: bitacora de eventos |

## Archivos
* `app.py` — servidor HTTP en Python puro (sin frameworks)
* `app.yaml` — comando de arranque y variables de entorno
* `requirements.txt` — `databricks-sql-connector`, `databricks-sdk`
* `setup_tablas_y_permisos.sql` — creacion de tablas y GRANTs para el service principal

## Pasos para desplegar
1. **Crear la app** en Databricks Apps (por ejemplo `cfe-notas-obra-lh`) y anotar el `service_principal_client_id`.
2. **Crear tablas y permisos**: ejecutar `setup_tablas_y_permisos.sql` reemplazando `<APP_SP_ID>` y el catalogo/esquema.
3. **Ligar el SQL Warehouse** como recurso de la app con la llave `sql-warehouse` y permiso `CAN_USE`.
   Requiere `CAN_MANAGE` sobre el warehouse. Si no lo tienes, pide al duenio del warehouse que lo ligue
   o que otorgue `CAN_USE` al service principal, y usa `value: "<WAREHOUSE_ID>"` en `app.yaml`.
4. **Ajustar variables** en `app.yaml`: `CFE_CATALOG` y `CFE_SCHEMA` (mismos valores que `config.py`).
5. **Desplegar** desde la carpeta de este repo:
   `databricks apps deploy cfe-notas-obra-lh --source-code-path /Workspace/<ruta>/workshopcfe/apps/cfe-notas-obra-lh`

## Notas
* La primera carga puede tardar 1-2 minutos si el warehouse esta detenido (arranque en frio).
* Para escrituras de alta frecuencia o baja latencia, la version con Lakebase (`cfe-notas-obra`) es mas adecuada;
  esta version prioriza simplicidad y gobierno con Unity Catalog.
