# Scytal — Backend

API FastAPI. **Fase Auth** (§4.1) + **Fase Organizations/Users** (§4.3/§4.4) implementadas; el resto de módulos
(groups, recipients, templates, campaigns, track, maturity, alerts, audit, reports) se integra por fases según
`Scytal_Especificacion_Backend.md`.

Stack: Python 3.12 · FastAPI · SQLAlchemy 2.0 async · PostgreSQL 15 · Redis 7 · Argon2id · TOTP (pyotp) · JWT.

## 1. Levantar todo con Docker Compose

```bash
cp .env.example .env
# Editar .env: generar JWT_SECRET y TOTP_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build -d
curl http://localhost:8000/health
```

El contenedor `api` ejecuta automáticamente al arrancar: `alembic upgrade head && python -m seeds.seed_admin`
(Alembic es la única fuente de verdad del esquema: 0001 baseline auth + 0002 dominio completo).
**`squema.sql` y `migrations/add_slug.sql` se conservan en el repo solo como referencia histórica** — el sistema ya no los usa.

## 2. Flujo de autenticación

1. **Register** — `POST /auth/register` crea organización + primer `admin_organizacion` (atómico, estado `pendiente_2fa`).
2. **Login (cuenta nueva, sin TOTP)** — `POST /auth/login` responde `must_enroll_totp:true` y `provisional_access_token` (solo sirve para `totp/enroll`, `totp/confirm`, `me`, `logout` y `password/change`; las rutas de negocio dan `403`).
3. **Enrolamiento TOTP** — `POST /auth/totp/enroll` devuelve secreto + QR **una sola vez**.
4. **Confirm** — `POST /auth/totp/confirm` con el primer código → cuenta `activo`.
5. **Login (normal)** — `POST /auth/login` responde `requires_totp:true` + `pending_token` (5 min).
6. **Verify TOTP** — `POST /auth/login/verify-totp` con `pending_token` + código de 6 dígitos → `access_token` (15 min) + `refresh_token` (7 días). Control de replay: un código usado se rechaza aunque la sesión sea otra.
7. **Uso normal** — `Authorization: Bearer <access_token>`.
8. **Refresh** — `POST /auth/refresh` → nuevo access.
9. **Logout / cambio de contraseña** — incrementan `version_token` e **invalidan todos los JWT previos** de ese usuario.

## 3. Endpoints implementados

### `/auth` (§4.1 — 9 rutas)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/auth/register` | Público | Crea org + `admin_organizacion` en `pendiente_2fa`. Body: `{correo, contrasena, nombre_organizacion, slug?}` |
| POST | `/auth/login` | Público (rate-limit 10/15min) | Cuenta con TOTP: `{requires_totp:true, pending_token, ...}`. Cuenta nueva sin TOTP: `{must_enroll_totp:true, provisional_access_token, ...}`. Si la contraseña está en HIBP (§7) → `requires_password_change:true` + cambio forzado persistido; HIBP caído no bloquea (fail-open). Audita `login_ok`/`login_failed` |
| POST | `/auth/login/verify-totp` | Público con `pending_token` (rate-limit 5/15min) | Body `{codigo, pending_token}` → `{access_token, refresh_token, expires_in_minutes}` |
| POST | `/auth/refresh` | Refresh token | Body `{refresh_token}` |
| POST | `/auth/logout` | Bearer access (cualquier estado) | Invalida sesión |
| POST | `/auth/totp/enroll` | Bearer access, estado `pendiente_2fa` | Devuelve `{secreto_en_claro, uri, qr_base64}` |
| POST | `/auth/totp/confirm` | Bearer access, estado `pendiente_2fa` | Body `{codigo}` → estado `activo` |
| POST | `/auth/password/change` | Bearer access (cualquier estado) | Body `{contrasena_actual, contrasena_nueva}` |
| GET | `/auth/me` | Bearer access (cualquier estado) | Datos de la cuenta en sesión |

Errores estándar §6.5: `{"error": {"code": "...", "message": "...", "details": null}}` (el handler global de HTTPException
normaliza todas las respuestas; `RATE_LIMITED` 429 incluye header `Retry-After`). Códigos: `INVALID_CREDENTIALS` (401, sin revelar qué falló), `INVALID_TOKEN`, `SESSION_INVALIDATED`, `PENDING_2FA`, `INVALID_TOTP`, `INVALID_PASSWORD`, `DUPLICATE`, `RATE_LIMITED` (429 con `Retry-After`), `VALIDATION_ERROR`, `NOT_FOUND`, `FORBIDDEN`, `INTERNAL_ERROR`.

### `/organizations` (§4.3 + decisión #7)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/organizations` | `admin_plataforma` | Crea organización. `correo_admin?` opcional: crea además su admin con contraseña temporal + correo de credenciales |
| GET | `/organizations` | `admin_plataforma` | Lista TODAS las organizaciones con métricas (usuarios, grupos, destinatarios, campañas) |
| GET | `/organizations/{id}` | `admin_plataforma` o miembro de la org | Detalle + métricas (org_id del JWT, §6.1) |
| PATCH | `/organizations/{id}` | `admin_organizacion` de esa org | Edita nombre/slug (audita `org_updated`) |

### `/users` (§4.4 + decisiones #9 y #11)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/users` | `admin_organizacion`, `analista` | Usuarios de la propia organización (paginado, limit ≤ 100) |
| POST | `/users/invite` | `admin_organizacion` | Invita `analista`: contraseña temporal aleatoria (§5) por correo, `pendiente_2fa`, cambio FORZOSO en primer login |
| PATCH | `/users/{id}/role` | `admin_organizacion` | `analista` ↔ `admin_organizacion` (no deja a la org sin admin; audita `role_change`) |
| PATCH | `/users/{id}/deactivate` | `admin_organizacion` | Borrado lógico: conserva datos, mata sesiones (`version_token+1`) |

**Cambio forzado de contraseña (invitados):** las rutas de negocio responden `403 PASSWORD_CHANGE_REQUIRED`
hasta que el invitado use `/auth/password/change` (el login ya trae `requires_password_change: true`).

### `/groups` (§4.5 — Fase 2)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/groups` | `admin_organizacion` | Crea grupo `{nombre, perfil}`; nombre duplicado (case-insensitive) → 409 |
| GET | `/groups` | `admin_organizacion`, `analista` | Grupos de la org con métricas: destinatarios activos + índice promedio (último puntaje por destinatario) |
| GET | `/groups/{id}` | ambos roles | Detalle + métricas |
| PATCH | `/groups/{id}` | `admin_organizacion` | Edita nombre/perfil |
| DELETE | `/groups/{id}` | `admin_organizacion` | 204; **409 `CONFLICT`** si tiene campañas (RESTRICT); destinatarios se borran en cascada |

### `/recipients` (§4.6 — Fase 2)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/recipients` | `admin_organizacion` | Alta individual `{correo, grupo_id}`; correo único por org (case-insensitive) → 409 |
| POST | `/recipients/import` | `admin_organizacion` | CSV multipart (`file`, máx 2 MB, encabezados `correo,grupo`): dedupe in-file y contra la org, reporta fila por fila → `{total_filas, creados, duplicados, invalidos, errores}` |
| GET | `/recipients` | ambos roles | Listado con filtro `?grupo_id=`; incluye inactivos |
| GET | `/recipients/{id}` | ambos roles | Detalle + histórico de instantáneas del índice de phishing |
| PATCH | `/recipients/{id}` | `admin_organizacion` | Edita correo y/o grupo |
| PATCH | `/recipients/{id}/deactivate` | `admin_organizacion` | Borrado lógico: conserva datos e histórico (decisión #9) |

### `/templates` (§4.7 — Fase 3)

| Método | Ruta | Roles | Descripción |
|---|---|---|---|
| GET | `/templates` | ambos roles | Globales (`org_id NULL`) + propias; filtros `?perfil=`, `?canal=correo\|qr`; cada item con `en_uso` |
| POST | `/templates` | `admin_organizacion` | Crea plantilla `{nombre, perfil, canal, asunto?, contenido_html, landing_html}` → 201. **canal=correo exige `asunto` → 422** (§5, en el schema). La landing recibe la leyenda `PÁGINA DE PRUEBA` automática si falta |
| GET | `/templates/{id}` | ambos roles | Detalle con HTML completo + `en_uso`. Global visible para todas; ajena → 404 |
| PATCH | `/templates/{id}` | `admin_organizacion` | Edita parcialmente; regla canal⇒asunto con el estado final → 422. Global → 403 |
| DELETE | `/templates/{id}` | `admin_organizacion` | 204; **409** si la usan campañas pendientes/programadas/activas; global → 403 |
| GET | `/templates/{id}/previsualizar` | ambos roles | → `{url, expira_en_minutos}`. Enlace efímero (JWT 30 min, tipo `previsualizacion`) que sirve la landing EXACTA que verá el destinatario. Ajena → 404 |
| POST | `/templates/importar` | `admin_organizacion` | Clona una página de login real por URL (decisión A+B) → 201 plantilla propia. Opción A: descarga estática con guardas SSRF (solo http/https, DNS validado por salto, sin IPs internas/metadata, máx 5 redirects, 2 MB, 10 s, UA de Chrome). Si el HTML es una carcasa SPA vacía → Opción B: render con Chromium headless (Playwright; si falta → 422). **Snapshot autocontenido**: scripts/iframes/CSP fuera, URLs absolutizadas, todo form → `/track/submit`, form mínimo si no hay password, y TODO el CSS externo se inlinea como `<style data-fuente>` (≤1.5 MB/hoja, ≤2 MB total, landing final ≤3 MB; hoja que falle/exceda conserva su `<link>`). Nombre/asunto autogenerados con el dominio. Errores → 422 `VALIDATION_ERROR` |

### `/previsualizar` (extensión del clonador)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/previsualizar/{token}` | Público con JWT efímero | Sirve la landing congelada como página real (`text/html`, `Cache-Control: no-store`). El token solo se obtiene de `/templates/{id}/previsualizar`, expira en 30 min y solo abre ESA plantilla de ESA org. CSP sin JavaScript (estilos inline + https; el snapshot ya es autocontenido) |

**Nota temporal:** la leyenda `PÁGINA DE PRUEBA` está DESACTIVADA en las plantillas importadas (se quita para validar la previsualización del frontend); las plantillas creadas a mano siguen recibiéndola. Reactivar el parámetro `leyenda` de `procesar_html` cuando se apruebe.

### `/campaigns` (§4.8 — Fase 3)

Estados: `pendiente` (= draft) → `activa` → `completada` / `cancelada`. `programada` sin uso (sin ruta de programación).

| Método | Ruta | Roles | Descripción |
|---|---|---|---|
| GET | `/campaigns` | ambos roles | Listado con filtros `?estado=`, `?grupo_id=`; incluye canales y zonas QR |
| POST | `/campaigns` | `admin_organizacion` | Crea en `pendiente` `{nombre, grupo_id, plantilla_id?, expiracion_horas? (default 72)}` → 201 |
| GET | `/campaigns/{id}` | ambos roles | Detalle con `canales: [{canal, zonas}]`. Ajena → 404 |
| PATCH | `/campaigns/{id}` | `admin_organizacion` | `pendiente`: todo editable. `activa`: SOLO `expiracion_horas` (re-datura todos los tokens, revive vencidos); resto → **409**. Otros estados → 409 |
| POST | `/campaigns/{id}/channels` | `admin_organizacion` | Solo en `pendiente`: define `canales` (reemplaza). Si va `qr` exige `zonas` ≥1 → 422. Regenera zonas QR |
| POST | `/campaigns/{id}/launch` | `admin_organizacion` | `pendiente/completada/cancelada` → `activa`. Exige plantilla, ≥1 canal, zonas si qr, ≥1 destinatario activo (→ 422). Regenera tokens y reinicia contadores (el histórico se conserva). Correos en **background** (send_many_detailed, éxito individual estampa `enviado_en`) |
| GET | `/campaigns/{id}/qr` | ambos roles | Extensión: render de zonas QR → `[{zona, url, qr_base64}]` (PNG base64). 404 sin zonas |
| GET | `/campaigns/{id}/stats` | ambos roles | Embudo `{total_destinatarios, enviados, abiertos, clics, subidos}` + `qr_clics` aparte (anónimos, no entran al embudo). Solo cuenta eventos del ciclo actual |
| GET | `/campaigns/{id}/recipients` | ambos roles | Tabla por destinatario: enviado/abrio/clico/subio, token vencido, puntaje/nivel del último finish |
| POST | `/campaigns/{id}/finish` | `admin_organizacion` | Solo desde `activa` → `completada`: instantáneas §7 (25/25/50) + 1 alerta por quien envió datos en el formulario falso (el contenido NUNCA se guarda) |
| POST | `/campaigns/{id}/send-feedback` | `admin_organizacion` | Solo desde `completada`, una sola vez (2ª → **409**); marca `feedback_enviado_en` y envía en background el correo de resultados |
| POST | `/campaigns/{id}/cancel` | `admin_organizacion` | `pendiente/activa` → `cancelada`; **tokens mueren al instante** (`expira_en = ahora`) |

### `/track` (§4.9 — Fase 4)

Endpoints **públicos** de rastreo (sin autenticación). El token viaja como `?t=` y se valida por **SHA-256** contra `token_hash` + `expira_en` (nunca el UUID). Token vencido/inválido → **respuesta genérica idéntica** en todos los endpoints (mismo pixel / redirect al awareness) **sin actualizar métricas**: no se revela si llegó a existir (§5). Rate limit **60/min por IP** (§6.2) con `Retry-After`. CSP de previsualización en `/track/`.

Los tokens QR comparten la vida de los de destinatario (columna `campanas_qr_zonas.expira_en`, migración `0004`): se fijan al lanzar, mueren al cancelar y se re-daturan con el PATCH de expiración; `NULL` = aún no lanzada → inválido en `/track`.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/track/open?t=` | Pixel 1x1 GIF: evento `abierto` + estampa `abierto_en` (solo el 1º). QR/inválido → el **mismo** pixel sin métricas |
| GET | `/track/click?t=` | Evento `click` + `clic_en` → **302** a `/track/landing?t=`. QR: estampa `clic_en` en la zona (anónimo, **sin eventos**, fuera del embudo). Inválido → 302 al awareness |
| GET | `/track/landing?t=` | Landing de la campaña con el form reescrito a `action="/track/submit?t={token}"` (marcador `ACCION_FORM` del clonador, solo en memoria). Sin plantilla o token inválido → awareness |
| POST | `/track/submit?t=` | Evento `subido` → **303** al awareness. **Sin modelo Pydantic de body**: los campos del formulario falso jamás se leen ni se guardan (§7). QR anónimo → solo awareness |
| GET | `/track/awareness?t=` | Página educativa post-envío: estática y autocontenida, **siempre la misma respuesta** (el `t` no se valida) |

### `/audit` (§4.12)

Bitácora de la organización: SIEMPRE filtrada por `org_id` del JWT (§6.1). Todas las acciones del §6.6 ya se escriben desde sus módulos; aquí solo se leen.

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/audit` | `admin_organizacion`, `analista` | Lista paginada (limit ≤ 100) ordenada por fecha desc. Filtros: `?tipo=`, `?actor_id=`, `?desde=`, `?hasta=`. Cada fila incluye `actor_correo` resuelto (LEFT JOIN a usuarios) |

### `/alerts` (§4.11)

Alertas creadas por `/campaigns/{id}/finish` (1 por destinatario que envió datos en el formulario falso).

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/alerts` | `admin_organizacion`, `analista` | Lista paginada con filtros `?tipo=`, `?resuelto=true\|false` |
| PATCH | `/alerts/{id}/resolve` | `admin_organizacion` | Marca `resuelto` + estampa `resuelto_en` y audita `alert_resolved` (§6.6). Ajena → 404. **Ya resuelta → 409 `CONFLICT`** |

### `/maturity` (§4.10)

Índices calculados con la fórmula §7 (25% no abrir + 25% no clic + 50% no enviar) que `finish` persiste en `instantaneas_phishing`.

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/maturity/recipients/{id}/history` | `admin_organizacion`, `analista` | Histórico de instantáneas del destinatario (más reciente primero, `limit ≤ 100`). Ajeno/inesistente → 404 |
| GET | `/maturity/groups/{id}/trend` | `admin_organizacion`, `analista` | Serie cronológica por campaña finalizada: `{campana_id, nombre, finalizada_en, promedio, n_destinatarios}` |
| GET | `/maturity/organization/summary` | `admin_organizacion`, `analista` | Dashboard: `{destinatarios_activos, indice_promedio, distribucion: {bajo,medio,alto,critico}, campanas: {total, completadas}, ultima_finalizacion}`. Sin datos → `null`/ceros |

### `/reports` (§4.13)

Exportables en `?format=csv|pdf` (`Content-Disposition: attachment`); `format` distinto → **422 `VALIDATION_ERROR`**. Cada export audita `report_exported`. PDF con `reportlab` (latín-1: sin `→` ni caracteres exóticos en el contenido).

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/reports/campaigns/{id}/export?format=` | `admin_organizacion`, `analista` | Metadata de campaña + embudo (con %) + tabla por destinatario (enviado/abrió/clicó/envió, puntaje, nivel). Ajena → 404 |
| GET | `/reports/groups/{id}/export?format=` | `admin_organizacion`, `analista` | Índice promedio + distribución por nivel (último puntaje) + tabla de destinatarios con su último puntaje. Ajeno → 404 |

### `/pwned` (§4.2)

Proxy hacia HIBP con **k-anonimato** + chequeo rápido de fortaleza. El navegador nunca habla con HIBP (el API key y el tráfico quedan del lado del backend).

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/pwned/range/{prefijo5}` | Público o autenticado | Devuelve `{prefijo, total_conocidas, conteos: {sufijo: n}}` para los 5 primeros hex del SHA-1 (cache Redis `hibp:{prefijo}` + `Cache-Control: max-age=3600`). Prefijo ≠ 5 hex → **422**; HIBP caído → **503 `HIBP_UNAVAILABLE`**. Rate limit (§6.2): **10/min por IP** si es público, **20/min por sesión** si manda Bearer válido |
| POST | `/pwned/strength-check` | Público o autenticado | Body `{password}` → `{score (0-4), es_fuerte, errores}` con zxcvbn + lista local, **sin llamar a HIBP**. Mismo rate limit (clave separada `rl:pwned:strength`) |

## 4. Seguridad implementada

- **Contraseñas**: Argon2id (OWASP), mín. 10 caracteres, zxcvbn ≥ 3, lista local, HIBP (k-anonimato, cache Redis), historial últimas 3, rotación 90 días.
- **Correos**: validación de formato estricta (RFC simplificado) y normalización a minúsculas; se aceptan dominios de desarrollo como `@scytal.local` (MailHog), que `EmailStr` estándar rechazaría.
- **TOTP**: pyotp con `valid_window=1` y control de replay por `ultimo_totp_step`. Secreto cifrado con Fernet en `totp_secreto_enc`, nunca expuesto tras el QR.
- **JWT**: `HS256` con claims `sub, org_id, rol, version_token, tipo, exp`. Invalidate vía `version_token` (logout / cambio de contraseña).
- **Rate limiting (Redis)**: login y verify-totp (5/15 min por `pending_token`), fail-open si Redis cae.
- **Auditoría (opción B)**: solo se escribe en `eventos_auditoria` si se resuelve `org_id` (login/register/password/2FA). Para `admin_plataforma` o correo inexistente solo queda en log estructurado con `request_id`.
- **Multi-tenant**: `get_current_org` extrae `org_id` del JWT; nunca de la URL/body.
- **Cabeceras**: CORS restringido, `nosniff`, `DENY`, `X-Request-Id` en todas las respuestas. La CSP estricta (`default-src 'none'`) se aplica a las rutas de API; `/docs`, `/redoc` y `/openapi.json` usan una CSP relajada solo para esa UI porque Swagger UI carga CSS/JS del CDN y un script inline.
- **Seed `admin_plataforma`**: único usuario sin org (`org_id NULL`, permitido por el CHECK del SQL), pasa por las mismas reglas. Se crea desde `.env` (`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`), nunca hardcodeado.

## 5. Estructura

```
app/
  main.py              # FastAPI, middlewares, handler de errores §6.5
  deps.py              # get_current_user / get_current_org / get_pending_user / require_roles
  core/                # config, security (Argon2/JWT/Fernet/TOTP), rate_limit, logging
  db/                  # engine async + Base
  models/              # 13 tablas del dominio (auth + orgs + campañas + zonas QR + tracking + alertas)
  schemas/             # Pydantic v2 por módulo (auth, organizacion, usuario, grupo, destinatario, plantilla, campana, auditoria, alerta, maturity)
  routers/             # auth.py, organizations.py, users.py, groups.py, recipients.py, templates.py, campaigns.py, previsualizar.py, track.py, audit.py, alerts.py, maturity.py, reports.py, pwned.py
  services/            # auth, password (zxcvbn+HIBP), hibp (rango k-anonimato + cache), email (reintentos+delay+lote detallado), usuario, organizacion, grupo, destinatario (CSV), plantilla (leyenda), campana (launch/cancel/finish/feedback/QR), qr (PNG base64), maturity (puro), report (CSV/PDF con reportlab), clonador (importar plantilla por URL: descarga estática A + render Chromium B, guardas SSRF, HTML domesticado, CSS inlineado = snapshot autocontenido)
  repositories/        # acceso a datos con filtro org_id (§6.1)
  middlewares/         # security_headers (CORS ya en main, cabeceras, request_id)
alembic/               # 0001 baseline auth + 0002 dominio + 0003 zonas QR + 0004 expiración QR (fuente única del esquema)
tests/                 # unit/ + integration/ (pytest, 137 pruebas)
seeds/seed_admin.py    # admin_plataforma inicial
seeds/seed_templates.py # 3 plantillas globales (login genérico, clon Facebook, clon Instagram)
migrations/add_slug.sql # referencia histórica (el sistema ya no lo usa)
squema.sql             # esquema original de referencia (el sistema ya no lo usa)
docker-compose.yml     # db + redis + mailhog + api (api corre alembic + seeds al arrancar)
prompt_frontend.md     # contrato API ↔ frontend (fuente única para el IA del frontend)
```

Regla de capas: routers → services → repositories; nunca SQL directo en routers.

## 6. Variables de entorno

Ver `.env.example`. Obligatorias: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `TOTP_ENCRYPTION_KEY`. Además `PLATFORM_ADMIN_EMAIL` y `PLATFORM_ADMIN_PASSWORD` para el seed, `CORS_ALLOWED_ORIGINS` con el origen del frontend, y `HIBP_API_URL`.

## 7. Pruebas

```bash
# Unitarias (sin BD, HIBP mockeado)
python -m pytest tests/unit -q

# Integración (requiere docker compose con db+redis; crea orgs/usuarios de prueba en scytal_test)
$env:DATABASE_URL="postgresql+asyncpg://scytal:scytal_pass@127.0.0.1:5432/scytal_test"
$env:REDIS_URL="redis://127.0.0.1:6379/0"
$env:JWT_SECRET="un-secreto-de-prueba-largo"
$env:TOTP_ENCRYPTION_KEY=(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python -m pytest tests -q
```

Cobertura actual (137 pruebas):
| # | Prueba | Qué valida |
|---|---|---|
| 1-3 | slugify | Normalización de slugs (unitaria) |
| 4-8 | índice de phishing | Fórmula 25/25/50 y niveles (unitaria) |
| 9-10 | contraseña temporal | Cumple §5, aleatoria (unitaria) |
| 11-23 | **validador CSV** | Encabezados, correos, grupos inexistentes, dedupe in-file, BOM, líneas vacías, límites (unitaria) |
| 24 | **Aislamiento multi-tenant** | Org A → 403 sobre org B (leer/editar/listar); ve la propia con métricas |
| 25 | `admin_plataforma` lista todas las orgs | Decisión #7 con métricas |
| 26 | **Invitación de analista completa** | Invite → login → 403 `PASSWORD_CHANGE_REQUIRED` → cambio → acceso; cambio/desactivación de rol; sesión muerta tras desactivar |
| 27 | **Grupos: flujo completo** | Crear, duplicado 409 case-insensitive, métricas, editar, analista lee pero no escribe |
| 28 | **Grupos: borrado** | 409 con campañas (RESTRICT) → 204 sin ellas → destinatarios en cascada |
| 29 | **Grupos: aislamiento** | Org B → 404 sobre grupos de org A |
| 30 | **Destinatarios: flujo completo** | Alta, 409 CITEXT, filtro por grupo, histórico, edición, desactivación lógica, métricas solo activos |
| 31 | **Destinatarios: CSV** | Mezcla válidos/duplicados/inválidos con detalle por fila; re-import dedupe; encabezados malos 422 |
| 32 | **Destinatarios: aislamiento** | Org B → 404 sobre destinatarios de org A; correo repetido entre orgs permitido |
| 33-41 | **Plantillas y campañas: unitarias** | Leyenda de landing idempotente, render `{{enlace}}`/`{{pixel}}` con y sin marcadores, canal=correo exige asunto, canales QR exigen zonas, PNG QR válido |
| 42 | **Plantillas: flujo completo** | CRUD, leyenda automática, canal⇒asunto final 422, filtros, global solo lectura, analista, multi-tenant |
| 43 | **Plantilla global** | org_id NULL la lee cualquier org; PATCH/DELETE → 403 |
| 44 | **Plantilla en uso** | DELETE → 409 con campaña pendiente; cancelada la suelta (SET NULL) |
| 45 | **Campañas: flujo completo** | pendiente → canales → launch (tokens únicos + correos en background) → stats en ceros → PATCH activa solo expiración → interacciones simuladas → finish (75/25/100, 1 alerta) → índice del grupo → feedback una vez → relanzado reinicia sin arrastrar el embudo |
| 46 | **Campañas: QR + cancel + relanzar** | QR sin zonas 422, zonas con trim, render PNG, launch con correo+qr, cancel mata tokens al instante, relanzado revive tokens, cancelar cancelada 409, qr_clics aparte |
| 47 | **Campañas: permisos** | Analista lee/no escribe; org B → 404; filtros por estado/grupo |
| 48 | **Campañas: launch exige destinatarios** | Grupo vacío → 422; destinatario desactivado no cuenta |
| 49-52 | **Importador por URL: unitarias** | Guardas SSRF (`_ip_bloqueada` parametrizada: loopback/privadas/metadata/link-local/multicast/reservadas; IPs públicas fuera), `_url_valida` (solo http/https), detección de carcasa SPA (React/Next vs página real), `procesar_html`: domestica (scripts/iframe/base/CSP/refresh/on*/javascript: fuera), absolutiza src/href/srcset contra la URL final (incl. CSS), todo form → `/track/submit`, form mínimo si no hay password, leyenda solo con `leyenda=True` (imports sin leyenda por ahora), fragmento sin `<body>` |
| 53-60 | **Importador: inlining de CSS (unitarias)** | Hoja externa → `<style data-fuente>` (link fuera, `url()` absolutizada contra la HOJA), `@import` anidado absolutizado contra su propia hoja, 404/403 conserva el `<link>`, content-type no-CSS conserva el link, `</style>` dentro del CSS no se inlinea, hoja >1.5 MB conserva el link, presupuesto total (la 2ª hoja que no cabe conserva su link), `_css_a_absoluto` puro (relativa/absoluta/data:) |
| 61-68 | **Importador por URL: integración** | Flujo A con redirect (asunto/nombre autogenerados, correo con `{{enlace}}`, landing domesticada + CSS inlineado + leyenda ausente, en el listado), fallback a B con render mockeado, render B real con Chromium local (skip si no está), errores 422 (500, no-HTML, >2 MB, ftp, canal inválido), SSRF real bloqueado (127.0.0.1/localhost/169.254.169.254/192.168.x), permisos (analista 403, sin token 401), previsualización: enlace efímero → GET público 200 text/html con CSS inline y CSP sin JS, token falso/vencido → 404, permisos del enlace (analista OK, otra org 404, sin sesión 401) |
| 69-75 | **/track: unitarias** | Reescritura del `action` (doble/comilla simple, sin duplicar `?t=`, sin form sin cambios, marcador `ACCION_FORM = /track/submit`), pixel GIF 1x1, awareness sin scripts ni recursos externos |
| 76-80 | **/track: integración** | Flujo completo open→click→landing (`action` reescrito)→submit (body del form DESCARTADO, 303)→awareness; token vencido → respuesta genérica sin métricas e idéntica a la de un token inexistente; QR anónimo (zona marcada, 0 eventos, embudo intacto), QR inválido sin lanzar y tras cancelar; rate limit 60/min → 429 + `Retry-After` |
| 81-82 | **/audit: integración** | Listado con `register`+`actor_correo`, filtros por tipo/actor/fecha, paginación y limit 101 → 422, sin token 401; aislamiento (org B no ve eventos de org A) |
| 83-84 | **/alerts: integración** | Lista tras `finish` (1 alerta), filtros `tipo`/`resuelto`, resolve → 200 + fila `alert_resolved` en auditoría, **2ª resolve → 409**, 404 inexistente/ajena; analista lee pero resolve → 403, org B ve lista vacía |
| 85-86 | **/maturity: integración** | trend con 2 campañas (promedios 87.5 y 62.5 en orden), history por destinatario, summary con distribución=2, campanas 2/2 y última finalización; 404 de grupo/destinatario ajeno, summary de org vacía en null/ceros, 401 sin token |
| 87-88 | **/reports: integración** | CSV campaña (BOM, embudo con %, 2 filas por destinatario) + PDF `%PDF-`, `format=xlsx` → 422, campaña ajena → 404, auditoría `report_exported`; CSV/PDF de grupo, analista exporta, grupo de otra org → 404 |
| 89-94 | **/pwned: unitarias** | `fortaleza_local` débil (lista local + zxcvbn < 3), corta (<10), fuerte (score ≥ 3, sin errores); parser del rango HIBP (líneas OK/malas/vacías) y `_count_in` reusándolo |
| 95-99 | **/pwned: integración** | range con rango mockeado (200 + `Cache-Control` + prefijo en mayúsculas), prefijos malos (3/6/letras) → 422, HIBP caído → 503 `HIBP_UNAVAILABLE`; strength-check débil/fuerte/corto + body vacío 422; rate limit IP (11ª llamada → 429 + `Retry-After: 60`, strength-check con clave aparte sigue pasando); rate limit sesión autenticada (21ª → 429) |
| 100-103 | **Login + HIBP (§7): integración** | Contraseña filtrada en login → `requires_password_change:true`, `debe_cambiar_contrasena` persistido y fila `password_breached` en auditoría; contraseña limpia no fuerza el cambio; HIBP caído (-1) no bloquea (fail-open); `login_ok` y `login_failed` quedan en `eventos_auditoria` (§6.6) |

## 8. Notas de despliegue local

- Si tu entorno Windows resuelve mal `localhost` (DNS falla con `getaddrinfo failed`), usa `127.0.0.1` en `DATABASE_URL`/`REDIS_URL` del `.env` local; dentro de Docker Compose, los nombres de servicio son `db`/`redis` (ya están fijados en `docker-compose.yml`).
- Verifica el contenido de `.env` tras editarlo; si aparece el texto de `.env.example`, regrábalo.
- **Importador por URL (Opción B):** el Dockerfile instala Chromium vía `RUN playwright install --with-deps chromium` (primera build más lenta y ~500 MB más de imagen, aceptado en decisión). Sin ese paso, las páginas 100% JS responden 422 con mensaje claro.

## 9. Prompt para conectar con el frontend

Ver `prompt_frontend.md` en esta carpeta. Contiene el contrato completo que el frontend necesita conocer: base URL, flujo de registro → login → TOTP → enroll/confirm, tokens y tiempos de expiración, formato de errores, rate limits y reglas de seguridad (qué guardar y qué no).
