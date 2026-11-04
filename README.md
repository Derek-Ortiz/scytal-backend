# Scytal — Backend de Autenticación (Fase Auth)

API FastAPI con las 9 rutas de `/auth` definidas en `Scytal_Especificacion_Backend.md` (§4.1), alineadas con `squema.sql` + columna `slug` en `organizaciones`.

Stack: Python 3.12 · FastAPI · SQLAlchemy 2.0 async · PostgreSQL 15 · Redis 7 · Argon2id · TOTP (pyotp) · JWT.

## 1. Levantar todo con Docker Compose

```bash
cp .env.example .env
# Editar .env: generar JWT_SECRET y TOTP_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up --build -d
curl http://localhost:8000/health
# Crear el admin_plataforma inicial (una sola vez)
docker compose exec api python -m seeds.seed_admin
```

Servicios:
- API: http://localhost:8000 (docs OpenAPI en /docs)
- PostgreSQL: `localhost:5432` (scytal / scytal_pass)
- Redis: `localhost:6379`
- MailHog: http://localhost:8025 (SMTP en 1025)

La BD se crea desde `squema.sql` + `migrations/add_slug.sql` (volúmenes en `docker-compose.yml`). Si ya existía la BD, aplica la migración Alembic `0001` o el SQL de slug suelto.

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

## 3. Endpoints (`/auth`)

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

Errores estándar §6.5: `{"error": {"code": "...", "message": "...", "details": null}}`. Códigos: `INVALID_CREDENTIALS` (401, sin revelar qué falló), `INVALID_TOKEN`, `SESSION_INVALIDATED`, `PENDING_2FA`, `INVALID_TOTP`, `INVALID_PASSWORD`, `DUPLICATE`, `RATE_LIMITED` (429 con `Retry-After`), `INTERNAL_ERROR`.

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
  main.py              # FastAPI, middlewares, handler de errores
  deps.py              # get_current_user / get_current_org / get_pending_user
  core/                # config, security (Argon2/JWT/Fernet/TOTP), rate_limit, logging
  db/                  # engine async + Base
  models/              # Organizacion (con slug), Usuario, HistorialContrasenas, EventoAuditoria
  schemas/             # Pydantic v2 por módulo
  routers/             # auth.py (prefix /auth, 9 rutas)
  services/            # auth_service, password_service (zxcvbn+HIBP+historial), hibp_service (cache Redis)
  repositories/        # acceso a datos con filtro org_id
  middlewares/         # security_headers (CORS ya en main, cabeceras, request_id)
alembic/               # migraciones (0001 baseline + slug)
seeds/seed_admin.py   # admin_plataforma inicial
migrations/add_slug.sql # ALTER TABLE para slug (también corre en initdb)
squema.sql             # esquema original del proyecto
docker-compose.yml     # db + redis + mailhog + api
```

Regla de capas: routers → services → repositories; nunca SQL directo en routers.

## 6. Variables de entorno

Ver `.env.example`. Obligatorias: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `TOTP_ENCRYPTION_KEY`. Además `PLATFORM_ADMIN_EMAIL` y `PLATFORM_ADMIN_PASSWORD` para el seed, `CORS_ALLOWED_ORIGINS` con el origen del frontend, y `HIBP_API_URL`.

## 7. Pruebas ejecutadas (verificación)

| # | Prueba | Resultado |
|---|---|---|
| 1 | Register con contraseña débil | 422 — rechaza por lista local + zxcvbn + HIBP (en vivo) |
| 2 | Register válido (correo con espacios/mayúsculas, slug null) | 201 — correo normalizado, slug `empresa-demo` autogenerado |
| 3 | Register duplicado | 409 DUPLICATE |
| 4 | Login cuenta nueva | `must_enroll_totp:true` + `provisional_access_token` |
| 5 | Enroll TOTP | QR + secreto retornados una vez |
| 6 | Confirm con código real pyotp | `2FA activado`; re-confirm → 403 ALREADY_ACTIVE |
| 7 | Login con TOTP | `requires_totp:true` + `pending_token` |
| 8 | Verify-TOTP con código | Tokens access+refresh emitidos |
| 9 | Replay del mismo código | 401 INVALID_TOTP (bloqueado por `ultimo_totp_step`) |
| 10-11 | `/auth/me` con y sin token | 200 con datos / 401 sin token |
| 12 | Refresh | nuevo access emitido |
| 13-15 | Logout y tokens viejos | access y refresh anteriores → 401 SESSION_INVALIDATED |
| 17-20 | Cambio de contraseña | 401 actual incorrecta / 422 reutilizada / OK / sesión vieja muerta |
| 21 | Rate limit login (11 intentos) | 429 tras el presupuesto 10/15min por IP+correo |
| 22-27 | Flujo completo `admin_plataforma` (org nula) | provisional → enroll → confirm → login → verify OK |

Reset completo de la BD de pruebas: `docker compose down -v && docker compose up db redis mailhog -d`.

## 8. Notas de despliegue local

- Si tu entorno Windows resuelve mal `localhost` (DNS falla con `getaddrinfo failed`), usa `127.0.0.1` en `DATABASE_URL`/`REDIS_URL` del `.env` local; dentro de Docker Compose, los nombres de servicio son `db`/`redis` (ya están fijados en `docker-compose.yml`).
- Verifica el contenido de `.env` tras editarlo; si aparece el texto de `.env.example`, regrábalo.

## 9. Prompt para conectar con el frontend

Ver `prompt_frontend.md` en esta carpeta. Contiene el contrato completo que el frontend necesita conocer: base URL, flujo de registro → login → TOTP → enroll/confirm, tokens y tiempos de expiración, formato de errores, rate limits y reglas de seguridad (qué guardar y qué no).
