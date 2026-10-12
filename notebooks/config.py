# ============================================================
# Workshop CFE — Data Engineering en Databricks
# Configuración editable. Ajusta estos valores y ejecuta
# %run ./_setup  al inicio de cada notebook.
# ============================================================

# ── Catálogo de datos (NO CAMBIAR) ───────────────────────────
# Catálogo donde viven los Volumes con los Parquets de origen.
# Este valor es fijo — los datos siempre están en dipidev.
DATA_CATALOG = "dipidev"

# ── Catálogo de trabajo (editable) ───────────────────────────
# Catálogo donde cada participante crea sus tablas Delta, esquemas, etc.
# Cámbialo si tu admin te asignó otro catálogo.
CATALOG = "dipidev"

# ── Esquema de trabajo ───────────────────────────────────────
# Esquema donde creas tus tablas Delta. Cada participante usa el suyo.
# Ejemplo: "workshop_cfe_juan", "workshop_cfe_equipo_1", etc.
WORK_SCHEMA = "default"

# ── Origen de datos ──────────────────────────────────────────
# Ruta donde viven los Parquets exportados del universo de proyectos CFE.
# 54 archivos Parquet (uno por tabla) del backup SQL Server original.
# Usa DATA_CATALOG (fijo) para que siempre apunte a los datos reales.
DATA_PATH = f"/Volumes/{DATA_CATALOG}/default/archivos_workshop/parquets"

# ── Carpeta de ejercicio 1 (labs 01 y 02) ─────────────────────
# Contiene tbobras.parquet: 318 obras de construcción con 50 columnas
# (IdObra, NombreObra, ImporteContratoMxn, AvanceActualConstruccion, ...)
EJERCICIO1_PATH = f"/Volumes/{DATA_CATALOG}/default/archivos_workshop/ejercicio1"
DELTA_LAB_FILE  = f"{EJERCICIO1_PATH}/tbobras.parquet"

# ── Archivo de proyectos (para enriquecer y join) ─────────────
# tbproyectos.parquet: 78 proyectos con 72 columnas
PROYECTOS_FILE = f"{DATA_PATH}/tbproyectos.parquet"
