"""
CFE Notas de Campo - version Lakehouse (sin Lakebase).
Misma funcionalidad que app_v3.py de cfe-notas-obra, pero todo vive en Delta
(Unity Catalog) y se accede via SQL Warehouse:
  - Catalogo de obras : <CAT>.<SCH>.gold_fact_obras   (capa Gold del pipeline)
  - Notas             : <CAT>.<SCH>.notas_obra       (Delta)
  - Bitacora          : <CAT>.<SCH>.bitacora_app     (Delta)
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime
import os, time, threading, html as html_mod

from databricks.sdk import WorkspaceClient
from databricks import sql as dbsql

PORT = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
WH = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
CAT = os.environ.get("CFE_CATALOG", "dipidev")
SCH = os.environ.get("CFE_SCHEMA", "default")

T_OBRAS = f"`{CAT}`.`{SCH}`.gold_fact_obras"
T_NOTAS = f"`{CAT}`.`{SCH}`.notas_obra"
T_BITA = f"`{CAT}`.`{SCH}`.bitacora_app"

w = WorkspaceClient()

# -- SQL Warehouse: conexion reutilizable con reconexion automatica --------
_conn = None
_conn_lock = threading.Lock()


def _connect():
    return dbsql.connect(
        server_hostname=w.config.host.replace("https://", "").rstrip("/"),
        http_path=f"/sql/1.0/warehouses/{WH}",
        credentials_provider=lambda: w.config.authenticate,
    )


def run_sql(query, params=None, fetch=True):
    """Ejecuta SQL parametrizado (marcadores :nombre). Reintenta una vez si la conexion expiro."""
    global _conn
    for attempt in (1, 2):
        try:
            with _conn_lock:
                if _conn is None:
                    _conn = _connect()
                with _conn.cursor() as cur:
                    cur.execute(query, params or {})
                    return cur.fetchall() if fetch else None
        except Exception:
            with _conn_lock:
                try:
                    if _conn is not None:
                        _conn.close()
                except Exception:
                    pass
                _conn = None
            if attempt == 2:
                raise


# -- Bitacora (asincrona para no frenar la respuesta) ----------------------
def _log_bitacora(accion, detalle, usuario, ip):
    try:
        run_sql(
            f"INSERT INTO {T_BITA} (accion, detalle, usuario, ip_cliente, fecha) "
            "VALUES (:accion, :detalle, :usuario, :ip, current_timestamp())",
            {"accion": accion, "detalle": (detalle or "")[:500], "usuario": usuario, "ip": ip},
            fetch=False,
        )
    except Exception as e:
        print(f"[BITACORA ERROR] {e}", flush=True)


def log_bitacora(accion, detalle="", usuario="system", ip=""):
    threading.Thread(target=_log_bitacora, args=(accion, detalle, usuario, ip), daemon=True).start()


# -- Catalogo de obras (Gold, con cache de 10 min) --------------------------
_obras_cache = {"ts": 0.0, "rows": []}


def get_obras():
    if time.time() - _obras_cache["ts"] > 600 or not _obras_cache["rows"]:
        rows = run_sql(f"SELECT IdObra, NombreObra FROM {T_OBRAS} ORDER BY IdObra")
        _obras_cache.update(ts=time.time(), rows=[(int(r[0]), str(r[1])) for r in rows])
    return _obras_cache["rows"]


def obra_opts(selected=""):
    try:
        out = []
        for oid, nombre in get_obras():
            sel = " selected" if str(oid) == str(selected) else ""
            out.append(f'<option value="{oid}"{sel}>{oid} - {html_mod.escape(nombre)}</option>')
        return "\n".join(out)
    except Exception as e:
        return f'<option value="">Error (el warehouse puede estar iniciando): {html_mod.escape(str(e)[:80])}</option>'


def get_nombre_obra(id_obra):
    for oid, nombre in get_obras():
        if oid == int(id_obra):
            return nombre
    return "Desconocida"


# -- Notas recientes ------------------------------------------------------
EST_CFG = {"Abierta": ("#ffa726", "#3e2723"), "En Proceso": ("#42a5f5", "#0d2137"), "Resuelta": ("#66bb6a", "#1b3a1d")}
NEXT_STATES = {"Abierta": ["En Proceso", "Resuelta"], "En Proceso": ["Resuelta", "Abierta"], "Resuelta": ["Abierta"]}
PRI_COLOR = {"Alta": "#ef5350", "Media": "#ffa726", "Baja": "#66bb6a"}


def notas_html(id_obra):
    if not id_obra:
        return ""
    try:
        rows = run_sql(
            "SELECT fecha_registro, tipo_nota, prioridad, descripcion, "
            "COALESCE(evidencia_url, ''), usuario, COALESCE(estado, 'Abierta'), id "
            f"FROM {T_NOTAS} WHERE id_obra = :id_obra "
            "ORDER BY fecha_registro DESC LIMIT 20",
            {"id_obra": int(id_obra)},
        )
        if not rows:
            return '<p style="color:#888;margin-top:24px;">Sin notas registradas para esta obra.</p>'
        trs = ""
        for r in rows:
            fecha = r[0].strftime("%Y-%m-%d %H:%M") if hasattr(r[0], "strftime") else str(r[0])
            ev_link = (f'<a href="{html_mod.escape(r[4])}" target="_blank" style="color:#81c784;">Ver</a>' if r[4] else "")
            estado, nid = str(r[6]), r[7]
            ec, eb = EST_CFG.get(estado, ("#888", "#333"))
            badge = (f'<span style="background:{eb};color:{ec};padding:2px 8px;border-radius:10px;'
                     f'font-size:12px;font-weight:600;">{html_mod.escape(estado)}</span>')
            btns = ""
            for ns in NEXT_STATES.get(estado, []):
                btns += (
                    '<form method="POST" action="/estado" style="display:inline;margin:0 2px;padding:0;border:none;background:none;">'
                    f'<input type="hidden" name="nota_id" value="{nid}">'
                    f'<input type="hidden" name="nuevo_estado" value="{ns}">'
                    f'<input type="hidden" name="obra" value="{int(id_obra)}">'
                    '<button type="submit" class="mini">' + html_mod.escape(ns) + '</button></form>'
                )
            trs += (
                f'<tr><td>{html_mod.escape(fecha)}</td>'
                f'<td>{html_mod.escape(str(r[1]))}</td>'
                f'<td style="color:{PRI_COLOR.get(r[2], "#888")};font-weight:600;">{html_mod.escape(str(r[2]))}</td>'
                f'<td style="max-width:220px;">{html_mod.escape(str(r[3]))}</td>'
                f'<td>{ev_link}</td>'
                f'<td>{html_mod.escape(str(r[5]))}</td>'
                f'<td>{badge}<div style="margin-top:4px;">{btns}</div></td></tr>'
            )
        return (
            '<h3 style="margin-top:28px;color:#a5d6a7;">Notas recientes</h3>'
            '<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;">'
            '<tr style="color:#a5d6a7;"><th>Fecha</th><th>Tipo</th><th>Prioridad</th>'
            '<th>Descripcion</th><th>Evidencia</th><th>Usuario</th><th>Estado</th></tr>'
            f'{trs}</table>'
        )
    except Exception as e:
        return f'<p style="color:#ef5350;">Error cargando notas: {html_mod.escape(str(e)[:150])}</p>'


# -- HTML ------------------------------------------------------------------
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
form.main{background:#1e1e1e;padding:28px;border-radius:12px;border:1px solid #333}
label{display:block;margin-top:16px;font-weight:600;font-size:14px;color:#a5d6a7}
select,textarea,input[type=text]{width:100%;margin-top:6px;padding:10px 12px;background:#2a2a2a;color:#e0e0e0;border:1px solid #444;border-radius:6px;font-size:14px;font-family:inherit}
select:focus,textarea:focus,input:focus{outline:none;border-color:#00843D}
textarea{resize:vertical;min-height:100px}
.rg{display:flex;gap:16px;margin-top:8px}
.rg label{display:flex;align-items:center;gap:6px;font-weight:400;color:#e0e0e0;cursor:pointer;margin-top:0}
.rg input[type=radio]{accent-color:#00843D}
.btn{margin-top:24px;width:100%;padding:14px;background:#00843D;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;letter-spacing:1px}
.btn:hover{background:#006530}
.btn2{margin-top:10px;width:100%;padding:10px;background:none;color:#a5d6a7;border:1px solid #00843D;border-radius:8px;font-size:14px;cursor:pointer}
.mini{background:none;border:1px solid #555;color:#ccc;padding:2px 6px;border-radius:4px;font-size:11px;cursor:pointer}
.ok{margin-top:16px;padding:12px 16px;border-radius:8px;background:#1b5e20;color:#c8e6c9;font-size:14px}
.err{margin-top:16px;padding:12px 16px;border-radius:8px;background:#b71c1c;color:#ffcdd2;font-size:14px}
table{background:#1e1e1e;border-radius:8px;overflow:hidden}
tr:nth-child(even){background:#252525}
td,th{padding:8px;border-bottom:1px solid #333;text-align:left;vertical-align:top}
footer{text-align:center;color:#555;font-size:12px;padding:32px 0}
</style></head><body>
<div class="hdr"><div class="logo">CFE</div><div>
<h1>Notas de Campo &mdash; Obras de Construccion</h1>
<p>Captura avances, bloqueos, incidentes y mas para las obras de construccion</p>
<span class="badge">Lakehouse &middot; Delta Lake + Unity Catalog</span></div></div>
<div class="box"><form class="main" method="POST" action="/submit">
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
<button class="btn" type="submit">Registrar Nota</button>
<button class="btn2" type="submit" formaction="/ver">Ver notas de la obra seleccionada</button>
</form>{MSG}{NOTAS}</div>
<footer>Comision Federal de Electricidad &mdash; Powered by Databricks Lakehouse</footer>
</body></html>'''

VALID_ESTADOS = ("Abierta", "En Proceso", "Resuelta")
VALID_TIPOS = ("Avance", "Bloqueo", "Incidente de Seguridad", "Solicitud de Cambio",
               "Condiciones Climaticas", "Entrega de Materiales", "Hito Completado", "Nivel de Riesgo")
VALID_PRI = ("Alta", "Media", "Baja")


class H(BaseHTTPRequestHandler):
    def _user(self):
        # Databricks Apps reenvia la identidad del usuario final en estos headers
        return (self.headers.get("X-Forwarded-Email")
                or self.headers.get("X-Forwarded-Preferred-Username")
                or "desconocido")

    def _ip(self):
        return self.headers.get("X-Forwarded-For", self.client_address[0] if self.client_address else "")

    def _render(self, msg="", obra=""):
        body = (PAGE.replace("{OPTS}", obra_opts(obra))
                    .replace("{MSG}", msg)
                    .replace("{NOTAS}", notas_html(obra))).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        log_bitacora("PAGE_VIEW", "GET /", self._user(), self._ip())
        self._render()

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        d = parse_qs(self.rfile.read(ln).decode("utf-8"))
        f = lambda k, default="": d.get(k, [default])[0]
        if self.path == "/estado":
            return self._handle_estado(f)
        if self.path == "/ver":
            return self._render(obra=f("obra"))

        usr, ip, oid, msg = self._user(), self._ip(), f("obra"), ""
        try:
            tip, pri, des, ev = f("tipo", "Avance"), f("prioridad", "Media"), f("desc"), f("url")
            if not oid or not des.strip():
                msg = '<div class="err">Selecciona una obra y escribe una descripcion.</div>'
            elif tip not in VALID_TIPOS or pri not in VALID_PRI:
                msg = '<div class="err">Tipo de nota o prioridad invalidos.</div>'
            else:
                nombre = get_nombre_obra(oid)
                run_sql(
                    f"INSERT INTO {T_NOTAS} (id_obra, nombre_obra, tipo_nota, descripcion, prioridad, "
                    "evidencia_url, usuario, fecha_registro, estado) VALUES "
                    "(:id_obra, :nombre, :tipo, :descr, :pri, :ev, :usr, current_timestamp(), 'Abierta')",
                    {"id_obra": int(oid), "nombre": nombre, "tipo": tip, "descr": des.strip()[:4000],
                     "pri": pri, "ev": ev.strip()[:1000], "usr": usr},
                    fetch=False,
                )
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msg = f'<div class="ok">Nota registrada para obra {int(oid)} ({html_mod.escape(nombre)}) a las {now}</div>'
                log_bitacora("NOTA_CREADA", f"obra={oid}, tipo={tip}, prioridad={pri}", usr, ip)
        except Exception as ex:
            msg = f'<div class="err">Error: {html_mod.escape(str(ex)[:200])}</div>'
            log_bitacora("ERROR", str(ex)[:300], usr, ip)
        self._render(msg, oid)

    def _handle_estado(self, f):
        usr, ip, oid, msg = self._user(), self._ip(), f("obra"), ""
        try:
            nota_id, nuevo = f("nota_id"), f("nuevo_estado")
            if nota_id and nuevo in VALID_ESTADOS:
                run_sql(
                    f"UPDATE {T_NOTAS} SET estado = :estado, fecha_estado = current_timestamp() WHERE id = :id",
                    {"estado": nuevo, "id": int(nota_id)},
                    fetch=False,
                )
                msg = f'<div class="ok">Estado actualizado a {html_mod.escape(nuevo)}</div>'
                log_bitacora("ESTADO_CAMBIO", f"nota={nota_id}, estado={nuevo}", usr, ip)
            else:
                msg = '<div class="err">Parametros invalidos.</div>'
        except Exception as ex:
            msg = f'<div class="err">Error: {html_mod.escape(str(ex)[:200])}</div>'
            log_bitacora("ERROR", str(ex)[:300], usr, ip)
        self._render(msg, oid)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"CFE Notas (Lakehouse) starting on port {PORT} | warehouse={WH} | {CAT}.{SCH}", flush=True)
    log_bitacora("APP_START", f"port={PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
