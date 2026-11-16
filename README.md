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
| POST | `/auth/login` | Público (rate-limit 10/15min) | Cuenta con TOTP: `{requires_totp:true, pending_token, ...}`. Cuenta nueva sin TOTP: `{must_enroll_totp:true, provisional_access_token, ...}` |
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
  models/              # 12 tablas del dominio (auth + orgs + campañas + tracking + alertas)
  schemas/             # Pydantic v2 por módulo (auth, organizacion, usuario, grupo, destinatario)
  routers/             # auth.py, organizations.py, users.py, groups.py, recipients.py
  services/            # auth, password (zxcvbn+HIBP), hibp, email (reintentos+delay), usuario, organizacion, grupo, destinatario (CSV), maturity (puro)
  repositories/        # acceso a datos con filtro org_id (§6.1)
  middlewares/         # security_headers (CORS ya en main, cabeceras, request_id)
alembic/               # 0001 baseline auth + 0002 dominio completo (fuente única del esquema)
tests/                 # unit/ + integration/ (pytest, 32 pruebas)
seeds/seed_admin.py    # admin_plataforma inicial
migrations/add_slug.sql # referencia histórica (el sistema ya no lo usa)
squema.sql             # esquema original de referencia (el sistema ya no lo usa)
docker-compose.yml     # db + redis + mailhog + api (api corre alembic + seed al arrancar)
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

Cobertura actual (32 pruebas):
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

## 8. Notas de despliegue local

- Si tu entorno Windows resuelve mal `localhost` (DNS falla con `getaddrinfo failed`), usa `127.0.0.1` en `DATABASE_URL`/`REDIS_URL` del `.env` local; dentro de Docker Compose, los nombres de servicio son `db`/`redis` (ya están fijados en `docker-compose.yml`).
- Verifica el contenido de `.env` tras editarlo; si aparece el texto de `.env.example`, regrábalo.

## 9. Prompt para conectar con el frontend

Ver `prompt_frontend.md` en esta carpeta. Contiene el contrato completo que el frontend necesita conocer: base URL, flujo de registro → login → TOTP → enroll/confirm, tokens y tiempos de expiración, formato de errores, rate limits y reglas de seguridad (qué guardar y qué no).
