from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime
import os, html as html_mod, threading

PORT = int(os.environ.get("DATABRICKS_APP_PORT",
           os.environ.get("PORT", os.environ.get("APP_PORT", "8000"))))

# ── Databricks SDK ─────────────────────────────────────────────
from databricks.sdk import WorkspaceClient
from databricks import sql as dbsql
import psycopg

w = WorkspaceClient()

# ── SQL Warehouse (tbobras reference data) ─────────────────────
WH = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
CAT, SCH = "dipidev", "default"


def delta_conn():
    return dbsql.connect(
        server_hostname=w.config.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WH}",
        credentials_provider=lambda: w.config.authenticate,
    )


def delta_sql(q, fetch=True):
    with delta_conn() as c:
        with c.cursor() as cur:
            cur.execute(q)
            return cur.fetchall() if fetch else None


# ── Lakebase config ────────────────────────────────────────────
LAKEBASE_ENDPOINT = os.environ.get("LAKEBASE_ENDPOINT", "")
PGHOST = os.environ.get("PGHOST", "")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGDATABASE = os.environ.get("PGDATABASE", "databricks_postgres")
PGUSER = os.environ.get("PGUSER", "")


def pg_conn():
    """Fresh connection with a new OAuth token (tokens expire ~1h)."""
    cred = w.postgres.generate_database_credential(endpoint=LAKEBASE_ENDPOINT)
    return psycopg.connect(
        host=PGHOST, dbname=PGDATABASE, user=PGUSER,
        port=PGPORT, password=cred.token, sslmode="require",
        autocommit=True,
    )


def pg_sql(q, params=None, fetch=True):
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            return cur.fetchall() if fetch else None


# ── Init Lakebase tables ──────────────────────────────────────
_pg_ready = False
_pg_lock = threading.Lock()


def ensure_pg_tables():
    global _pg_ready
    if _pg_ready:
        return
    with _pg_lock:
        if _pg_ready:
            return
        pg_sql("""
            CREATE TABLE IF NOT EXISTS notas_obra (
                id BIGSERIAL PRIMARY KEY,
                id_obra INT,
                nombre_obra TEXT,
                tipo_nota TEXT,
                descripcion TEXT,
                prioridad TEXT,
                evidencia_url TEXT,
                usuario TEXT,
                fecha_registro TIMESTAMP DEFAULT NOW()
            )
        """, fetch=False)
        pg_sql("""
            CREATE TABLE IF NOT EXISTS bitacora_app (
                id BIGSERIAL PRIMARY KEY,
                accion TEXT,
                detalle TEXT,
                usuario TEXT,
                ip_cliente TEXT,
                fecha TIMESTAMP DEFAULT NOW()
            )
        """, fetch=False)
        # Migration: add estado columns
        pg_sql(
            "ALTER TABLE notas_obra ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'Abierta'",
            fetch=False,
        )
        pg_sql(
            "ALTER TABLE notas_obra ADD COLUMN IF NOT EXISTS fecha_estado TIMESTAMP",
            fetch=False,
        )
        _pg_ready = True
        print("[LAKEBASE] Tables ready (with estado)", flush=True)


# ── Bitacora helper ───────────────────────────────────────────
def log_bitacora(accion, detalle="", usuario="system", ip=""):
    try:
        ensure_pg_tables()
        pg_sql(
            "INSERT INTO bitacora_app (accion, detalle, usuario, ip_cliente) "
            "VALUES (%s, %s, %s, %s)",
            (accion, detalle[:500], usuario, ip),
            fetch=False,
        )
    except Exception as e:
        print(f"[BITACORA ERROR] {e}", flush=True)


# ── Load obras from Lakebase ──────────────────────────────────
def obra_opts():
    try:
        ensure_pg_tables()
        rows = pg_sql(
            "SELECT id_obra, nombre_obra FROM obras_catalogo ORDER BY id_obra"
        )
        return "\n".join(
            f'<option value="{r[0]}">{r[0]} - {html_mod.escape(str(r[1]))}</option>'
            for r in rows
        )
    except Exception as e:
        return f'<option value="">Error: {html_mod.escape(str(e)[:80])}</option>'


# ── Nombre obra lookup from Lakebase ──────────────────────────
def get_nombre_obra(id_obra):
    try:
        ensure_pg_tables()
        rows = pg_sql(
            "SELECT nombre_obra FROM obras_catalogo WHERE id_obra = %s LIMIT 1",
            (int(id_obra),),
        )
        return rows[0][0] if rows else "Desconocida"
    except Exception:
        return "Desconocida"


# ── Fetch recent notes from Lakebase ──────────────────────────
def notas_html(id_obra):
    if not id_obra:
        return ""
    try:
        ensure_pg_tables()
        rows = pg_sql(
            "SELECT fecha_registro, tipo_nota, prioridad, descripcion, "
            "COALESCE(evidencia_url, ''), usuario, COALESCE(estado, 'Abierta'), id "
            "FROM notas_obra WHERE id_obra = %s "
            "ORDER BY fecha_registro DESC LIMIT 20",
            (int(id_obra),),
        )
        if not rows:
            return '<p style="color:#888;margin-top:24px;">Sin notas registradas para esta obra.</p>'
        trs = ""
        for r in rows:
            fecha = r[0].strftime("%Y-%m-%d %H:%M") if hasattr(r[0], "strftime") else str(r[0])
            ev_link = (
                f'<a href="{html_mod.escape(r[4])}" target="_blank" style="color:#81c784;">Ver</a>'
                if r[4] else ""
            )
            pri_color = {"Alta": "#ef5350", "Media": "#ffa726", "Baja": "#66bb6a"}.get(r[2], "#888")
            estado = str(r[6])
            nid = r[7]
            est_cfg = {"Abierta": ("#ffa726", "#3e2723"), "En Proceso": ("#42a5f5", "#0d2137"), "Resuelta": ("#66bb6a", "#1b3a1d")}
            ec, eb = est_cfg.get(estado, ("#888", "#333"))
            est_badge = f'<span style="background:{eb};color:{ec};padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;">{html_mod.escape(estado)}</span>'
            next_states = {"Abierta": ["En Proceso", "Resuelta"], "En Proceso": ["Resuelta", "Abierta"], "Resuelta": ["Abierta"]}
            btns = ""
            for ns in next_states.get(estado, []):
                btns += (
                    f'<form method="POST" action="/estado" style="display:inline;margin:0 2px;">'
                    f'<input type="hidden" name="nota_id" value="{nid}">'
                    f'<input type="hidden" name="nuevo_estado" value="{ns}">'
                    f'<input type="hidden" name="obra" value="{id_obra}">'
                    f'<button type="submit" style="background:none;border:1px solid #555;color:#ccc;padding:2px 6px;border-radius:4px;font-size:11px;cursor:pointer;">{html_mod.escape(ns)}</button>'
                    f'</form>'
                )
            trs += (
                f'<tr><td>{html_mod.escape(fecha)}</td>'
                f'<td>{html_mod.escape(str(r[1]))}</td>'
                f'<td style="color:{pri_color};font-weight:600;">{html_mod.escape(str(r[2]))}</td>'
                f'<td style="max-width:220px;">{html_mod.escape(str(r[3]))}</td>'
                f'<td>{ev_link}</td>'
                f'<td>{html_mod.escape(str(r[5]))}</td>'
                f'<td>{est_badge}<div style="margin-top:4px;">{btns}</div></td></tr>'
            )
        return (
            '<h3 style="margin-top:28px;color:#a5d6a7;">Notas recientes</h3>'
            '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;">'
            '<tr style="border-bottom:1px solid #444;color:#a5d6a7;">'
            '<th style="text-align:left;padding:8px;">Fecha</th>'
            '<th style="text-align:left;padding:8px;">Tipo</th>'
            '<th style="text-align:left;padding:8px;">Prioridad</th>'
            '<th style="text-align:left;padding:8px;">Descripcion</th>'
            '<th style="text-align:left;padding:8px;">Evidencia</th>'
            '<th style="text-align:left;padding:8px;">Usuario</th>'
            '<th style="text-align:left;padding:8px;">Estado</th>'
            f'</tr>{trs}</table>'
        )
    except Exception as e:
        return f'<p style="color:#ef5350;">Error cargando notas: {html_mod.escape(str(e)[:100])}</p>'


# ── HTML template ─────────────────────────────────────────────
PAGE = '''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notas de Campo CFE</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans','Segoe UI',sans-serif;background:#121212;color:#e0e0e0}
.hdr{background:#00843D;padding:24px 32px;display:flex;align-items:center;gap:24px}
.logo{font-size:36px;font-weight:700;color:#fff;background:#006530;padding:14px 22px;border-radius:10px;letter-spacing:6px}
.hdr h1{color:#fff;font-size:22px}.hdr p{color:#c8e6c9;font-size:14px;margin-top:4px}
.badge{display:inline-block;background:#1b5e20;color:#81c784;font-size:11px;padding:3px 10px;border-radius:12px;margin-top:6px}
.box{max-width:900px;margin:32px auto;padding:0 24px}
form{background:#1e1e1e;padding:28px;border-radius:12px;border:1px solid #333}
label{display:block;margin-top:16px;font-weight:600;font-size:14px;color:#a5d6a7}
select,textarea,input[type=text]{width:100%;margin-top:6px;padding:10px 12px;background:#2a2a2a;color:#e0e0e0;border:1px solid #444;border-radius:6px;font-size:14px;font-family:inherit}
select:focus,textarea:focus,input:focus{outline:none;border-color:#00843D}
textarea{resize:vertical;min-height:100px}
.rg{display:flex;gap:16px;margin-top:8px}
.rg label{display:flex;align-items:center;gap:6px;font-weight:400;color:#e0e0e0;cursor:pointer}
.rg input[type=radio]{accent-color:#00843D}
button[type=submit]{margin-top:24px;width:100%;padding:14px;background:#00843D;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;letter-spacing:1px}
button[type=submit]:hover{background:#006530}
.ok{margin-top:16px;padding:12px 16px;border-radius:8px;background:#1b5e20;color:#c8e6c9;font-size:14px}
.err{margin-top:16px;padding:12px 16px;border-radius:8px;background:#b71c1c;color:#ffcdd2;font-size:14px}
table{background:#1e1e1e;border-radius:8px;overflow:hidden}
tr:nth-child(even){background:#252525}
td,th{padding:8px;border-bottom:1px solid #333}
footer{text-align:center;color:#555;font-size:12px;padding:32px 0}
</style></head><body>
<div class="hdr"><div class="logo">CFE</div><div>
<h1>Notas de Campo &mdash; Obras de Construccion</h1>
<p>Captura avances, bloqueos, incidentes y mas para las obras de construccion</p>
<span class="badge">Lakebase PostgreSQL</span></div></div>
<div class="box"><form method="POST" action="/submit">
<label for="obra">Obra</label>
<select name="obra" id="obra"><option value="">-- Selecciona una obra --</option>{OPTS}</select>
<label for="tipo">Tipo de Nota</label>
<select name="tipo" id="tipo">
<option>Avance</option><option>Bloqueo</option><option>Incidente de Seguridad</option>
<option>Solicitud de Cambio</option><option>Condiciones Climaticas</option>
<option>Entrega de Materiales</option><option>Hito Completado</option>
<option>Nivel de Riesgo</option></select>
<label>Prioridad</label>
<div class="rg"><label><input type="radio" name="prioridad" value="Alta"> Alta</label>
<label><input type="radio" name="prioridad" value="Media" checked> Media</label>
<label><input type="radio" name="prioridad" value="Baja"> Baja</label></div>
<label for="desc">Descripcion</label>
<textarea name="desc" id="desc" placeholder="Describe el avance, bloqueo o incidente..."></textarea>
<label for="url">URL de Evidencia (opcional)</label>
<input type="text" name="url" id="url" placeholder="https://...">
<button type="submit">Registrar Nota</button>
</form>{MSG}{NOTAS}</div>
<footer>Comision Federal de Electricidad &mdash; Powered by Databricks Lakebase</footer>
</body></html>'''


# ── HTTP Handler ───────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ip = self.client_address[0] if self.client_address else ""
        log_bitacora("PAGE_VIEW", "GET /", ip=ip)
        body = PAGE.replace("{OPTS}", obra_opts()).replace("{MSG}", "").replace("{NOTAS}", "").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        d = parse_qs(self.rfile.read(ln).decode())
        ip = self.client_address[0] if self.client_address else ""
        # Route: change note estado
        if self.path == "/estado":
            return self._handle_estado(d, ip)

        msg, nota_obra = "", ""
        try:
            oid = d.get("obra", [""])[0]
            tip = d.get("tipo", ["Avance"])[0]
            pri = d.get("prioridad", ["Media"])[0]
            des = d.get("desc", [""])[0]
            ev = d.get("url", [""])[0]
            if not oid or not des.strip():
                msg = '<div class="err">Selecciona una obra y escribe una descripcion.</div>'
            else:
                ensure_pg_tables()
                usr = w.current_user.me().user_name
                nombre = get_nombre_obra(oid)
                pg_sql(
                    "INSERT INTO notas_obra "
                    "(id_obra, nombre_obra, tipo_nota, descripcion, prioridad, evidencia_url, usuario, estado) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'Abierta')",
                    (int(oid), nombre, tip, des, pri, ev, usr),
                    fetch=False,
                )
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msg = f'<div class="ok">Nota registrada para obra {oid} ({html_mod.escape(nombre)}) a las {now}</div>'
                log_bitacora("NOTA_CREADA", f"obra={oid}, tipo={tip}, prioridad={pri}", usr, ip)
                nota_obra = oid
        except Exception as ex:
            msg = f'<div class="err">Error: {html_mod.escape(str(ex)[:200])}</div>'
            log_bitacora("ERROR", str(ex)[:300], ip=ip)
        notas = notas_html(nota_obra or d.get("obra", [""])[0])
        body = PAGE.replace("{OPTS}", obra_opts()).replace("{MSG}", msg).replace("{NOTAS}", notas).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _handle_estado(self, d, ip):
        msg = ""
        try:
            nota_id = d.get("nota_id", [""])[0]
            nuevo_estado = d.get("nuevo_estado", [""])[0]
            obra_id = d.get("obra", [""])[0]
            valid = ("Abierta", "En Proceso", "Resuelta")
            if nota_id and nuevo_estado in valid:
                ensure_pg_tables()
                usr = w.current_user.me().user_name
                pg_sql(
                    "UPDATE notas_obra SET estado = %s, fecha_estado = NOW() WHERE id = %s",
                    (nuevo_estado, int(nota_id)),
                    fetch=False,
                )
                msg = f'<div class="ok">Estado actualizado a {html_mod.escape(nuevo_estado)}</div>'
                log_bitacora("ESTADO_CAMBIO", f"nota={nota_id}, estado={nuevo_estado}", usr, ip)
            else:
                msg = '<div class="err">Parametros invalidos.</div>'
        except Exception as ex:
            msg = f'<div class="err">Error: {html_mod.escape(str(ex)[:200])}</div>'
            log_bitacora("ERROR", str(ex)[:300], ip=ip)
        notas = notas_html(d.get("obra", [""])[0])
        body = PAGE.replace("{OPTS}", obra_opts()).replace("{MSG}", msg).replace("{NOTAS}", notas).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


# ── Start ──────────────────────────────────────────────────────
print(f"CFE Notas server starting on port {PORT} (Lakebase-backed)...", flush=True)
log_bitacora("APP_START", f"port={PORT}")
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
