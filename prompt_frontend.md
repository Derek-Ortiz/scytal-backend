# Prompt para conectar el frontend con `/auth` (Scytal Backend)

Pega este prompt en tu agente de frontend. Funciona tal cual contra el backend ya implementado y **probado de punta a punta**.

---
Actúa como desarrollador frontend de Scytal y conecta la aplicación con el backend de autenticación ya implementado según este contrato. No cambies el flujo; sigue el orden exacto.

**Base URL**: `http://localhost:8000` en desarrollo (variable `VITE_API_URL` o similar). El backend expone docs OpenAPI en `/docs` y salud en `GET /health`.

## Contrato de endpoints

### `POST /auth/register` (público, 201)
Body: `{correo, contrasena, nombre_organizacion, slug?}`
- Reglas de contraseña (se validan TODAS en backend): mín. 10 caracteres, zxcvbn ≥ 3, no en lista local de comunes, no filtrada en HIBP, no reutilizar las últimas 3.
- `slug`: minúsculas, números y guiones (`mi-empresa`). Si no lo envías, se genera automáticamente desde el nombre.
- Respuesta: `{id_usuarios, correo, rol:"admin_organizacion", estado:"pendiente_2fa", org_id, nombre_organizacion, slug}`
- Errores: `422 INVALID_PASSWORD` (el `message` lista las razones), `409 DUPLICATE`.

### `POST /auth/login` (público) — respuesta con DOS modos
Body: `{correo, contrasena}`. Rate limit: 10 intentos / 15 min por IP+correo → `429`.

**Modo A — cuenta con TOTP ya configurado** (caso normal):
```json
{ "requires_totp": true, "must_enroll_totp": false, "pending_token": "<JWT 5 min>", "provisional_access_token": null, "requires_password_change": false }
```
→ guarda `pending_token` SOLO EN MEMORIA y pasa a la pantalla de TOTP.

**Modo B — cuenta recién registrada (sin TOTP aún)**:
```json
{ "requires_totp": false, "must_enroll_totp": true, "pending_token": null, "provisional_access_token": "<JWT>", "requires_password_change": false }
```
→ usa `provisional_access_token` como si fuera el access_token para: `totp/enroll`, `totp/confirm`, `me`, `logout`, `password/change`. **NO sirve** para rutas de negocio (darán `403 PENDING_2FA` hasta completar el TOTP).

Errores: `401 INVALID_CREDENTIALS` ("Correo o contraseña incorrectos" — el backend nunca dice qué falló).

### `POST /auth/totp/enroll` (Bearer access con estado `pendiente_2fa`)
- Respuesta: `{secreto_en_claro, uri, qr_base64}`
- Muestra el QR con `<img src="data:image/png;base64,{{qr_base64}}">` y el secreto **UNA SOLA VEZ**, con botón "ya lo guardé". No lo almacenes ni lo vuelvas a pedir (no se puede: la respuesta nunca se repite igual).

### `POST /auth/totp/confirm` (Bearer access con estado `pendiente_2fa`)
Body: `{codigo}` (6 dígitos) → `{ok:true, message:"2FA activado"}`. La cuenta pasa a `activo`.
Errores: `401 INVALID_TOTP`; `403 ALREADY_ACTIVE` si ya confirmó.

### `POST /auth/login/verify-totp` (público, requiere `pending_token`)
Body: `{codigo, pending_token}` → `{access_token, refresh_token, token_type:"bearer", expires_in_minutes:15}`
- Rate limit: 5 intentos / 15 min por pending_token → `429`.
- `401 INVALID_TOTP`. Un código ya usado se rechaza SIEMPRE aunque sea la misma sesión del usuario (control replay): si el usuario usa un código y reabre la app, debe esperar el siguiente código del Authenticator (los códigos rotan cada 30 s).

### `POST /auth/refresh` (público, body-only)
Body: `{refresh_token}` → nuevo `{access_token, refresh_token, ...}`. El refresh rotativo: devuelve par nuevo.

### `POST /auth/logout` (Bearer access)
Invalida la sesión: TODOS los tokens anteriores del usuario dejan de ser válidos.

### `POST /auth/password/change` (Bearer access)
Body: `{contrasena_actual, contrasena_nueva}` → `{ok:true}`.
- `401 INVALID_CREDENTIALS` (contraseña actual mal), `422 INVALID_PASSWORD` (nueva débil/repetida/filtrada).
- Tras cambiar, TODOS los tokens previos mueren: pide re-login. Atiende además `requires_password_change:true` del login: redirige a esta pantalla antes que nada.

### `GET /auth/me` (Bearer access, cualquier estado)
`{id_usuarios, correo, rol, estado, org_id, activo, totp_habilitado, debe_cambiar_contrasena}`
- `org_id: null` es válido para `admin_plataforma` (no pertenece a ninguna organización).
- `estado` posibles: `pendiente_2fa`, `activo`, `suspendido`, `inactivo`.

## Formato de errores (SIEMPRE)
```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "...", "details": null } }
```
Códigos: `INVALID_CREDENTIALS`, `INVALID_TOKEN`, `SESSION_INVALIDATED`, `PENDING_2FA`, `ALREADY_ACTIVE`, `INVALID_TOTP`, `INVALID_PASSWORD`, `DUPLICATE`, `RATE_LIMITED`, `VALIDATION_ERROR`, `INTERNAL_ERROR`. Todas las respuestas llevan cabecera `X-Request-Id` (muéstrala en errores genéricos 500 como "código de reporte").

## Qué implementar (checklist ejecutable)

1. **Pantallas**: Register → Login → TOTP (una sola pantalla inteligente: si `must_enroll_totp` muestra enroll+confirm; si `requires_totp` muestra pedir código) → App.
2. **Interceptor HTTP**: añade `Authorization: Bearer <access_token>`; en `401`, intenta UNAvez `/auth/refresh` y reintenta; si falla o llega `SESSION_INVALIDATED`, limpia estado y → Login.
3. **Almacenamiento**: tokens y `pending_token` solo en memoria (estado global tipo Zustand/React Query), nunca `localStorage`. Option: `sessionStorage` con clearance al logout.
4. **Guard de rutas**: si `GET /auth/me` responde `estado: "pendiente_2fa"`, redirige SIEMPRE al bloque enroll/confirm aunque la URL sea otro módulo.
5. **Formularios**: espejo de validación backend — correo sintaxis normal (el backend acepta dominios de desarrollo `.local`), contrasena ≥ 10 + medidor zxcvbn (libraría `zxcvbn-ts`), TOTP numero exacto 6 dígitos. Normaliza el correo a minúsculas en el submit.
6. **Rate limit (429)**: lectura de `Retry-After` si existe; muestra contador "intenta en Xs".
7. **CORS**: backend permite `http://localhost:3000` y `http://localhost:5173` (vite). Otro puerto → añadirlo a `CORS_ALLOWED_ORIGINS` del backend.

## Prueba de humo con curl (orden recomendado antes de codificar)

```bash
# 1. registrar
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"correo":"demo@empresa.com","contrasena":"Str0ng-Pass-2026!x","nombre_organizacion":"Empresa Demo"}'
# 2. login (modo B: provisional)
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"correo":"demo@empresa.com","contrasena":"Str0ng-Pass-2026!x"}'
# 3. enroll con el provisional (usa el token de arriba)
curl -X POST http://localhost:8000/auth/totp/enroll -H "Authorization: Bearer <provisional>"
# 4. confirm con el codigo de Google Authenticator escaneando el QR
curl -X POST http://localhost:8000/auth/totp/confirm -H "Authorization: Bearer <provisional>" \
  -H "Content-Type: application/json" -d '{"codigo":"123456"}'
# 5. login de nuevo (modo A) + verify-totp + GET /auth/me
```
---

## Notas técnicas para ti (no van al agente del frontend)
- Token provisional = JWT con `estado pendiente_2fa`; el backend lo limita por diseño (`deps.get_current_user` rechaza ese estado con 403 PENDING_2FA para rutas de negocio).
- `version_token` en la BD invalida JWTs: tras el logout o el cambio de contraseña los tokens viven hasta expirar pero son inútiles.
- Seed del admin de plataforma: `docker compose exec api python -m seeds.seed_admin` (lee `PLATFORM_ADMIN_EMAIL`/`PASSWORD` del `.env`); flujo idéntico al demás: enroll → confirm → login TOTP.
- Los reply que incluya `X-Frame-Options: DENY` etc. no afectan la SPA: es para recursos del backend. `CSP` del backend ya está hecha.
