# Contrato Backend ↔ Frontend — Scytal

**Versión 1.0 — Fase Auth.** Este documento es la fuente única de verdad del contrato API para el frontend.
Los módulos nuevos (organizations, users, groups, recipients, templates, campaigns, track, maturity, alerts, audit, reports)
se **añadirán como secciones nuevas** al final de este documento conforme se integren; las rutas existentes de `/auth`
**no cambian**. Los códigos de error nuevos también se agregan al final (§6.3).

---

## 1. Base

- Base URL (dev): `http://localhost:8000`
- Docs OpenAPI: `/docs` (Swagger UI) y `/openapi.json`
- Healthcheck: `GET /health` → `{"status": "ok", "service": "scytal-auth"}`
- Todas las respuestas incluyen el header `X-Request-Id` (guárdalo para soporte/bugs).
- Formato de error estándar en TODAS las respuestas de error (4xx/5xx):

```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Correo o contraseña incorrectos", "details": null } }
```

## 2. Roles y estados

| Rol | Significado |
|---|---|
| `admin_plataforma` | Dueño del producto. Sin organización (`org_id null`) |
| `admin_organizacion` | Admin de una organización (creado en `/auth/register`) |
| `analista` | Invitado por un `admin_organizacion` (sección §5) |

| Estado | Significado |
|---|---|
| `pendiente_2fa` | Cuenta nueva: falta enrolar/confirmar TOTP |
| `activo` | Cuenta normal |
| `inactivo` | Desactivado por un admin (borrado lógico) |

## 3. Flujo completo

```
1. POST /auth/register            → org + admin_organizacion en pendiente_2fa
2. POST /auth/login               → must_enroll_totp:true + provisional_access_token
3. POST /auth/totp/enroll         → secreto + QR (mostrar UNA sola vez)
4. POST /auth/totp/confirm        → cuenta pasa a activo
5. POST /auth/login               → requires_totp:true + pending_token (5 min)
6. POST /auth/login/verify-totp   → access_token (15 min) + refresh_token (7 días)
7. Uso normal: Authorization: Bearer <access_token>
8. POST /auth/refresh             → nuevo access_token
9. POST /auth/logout              → invalida todos los JWT de ese usuario
```

## 4. Endpoints `/auth`

### POST `/auth/register` — Público · 201
Body: `{ "correo": "...", "contrasena": "...", "nombre_organizacion": "...", "slug": "mi-org"? }`
Respuesta: `{ id_usuarios, correo, rol, estado, org_id, nombre_organizacion, slug }`
Notas: contraseña mínimo 10 caracteres, zxcvbn ≥ 3, no HIBP, no lista local. `slug` opcional (se autogenera del nombre). Errores: 409 `DUPLICATE`, 422 `INVALID_PASSWORD` / `VALIDATION_ERROR`.

### POST `/auth/login` — Público (rate limit 10/15 min por IP+correo) · 200
Body: `{ "correo": "...", "contrasena": "..." }`
Respuesta — cuenta SIN TOTP (recién registrada):
```json
{ "must_enroll_totp": true, "requires_totp": false, "provisional_access_token": "eyJ...", "pending_token": null, "requires_password_change": false }
```
Respuesta — cuenta CON TOTP:
```json
{ "requires_totp": true, "must_enroll_totp": false, "pending_token": "eyJ...", "provisional_access_token": null, "requires_password_change": false }
```
`requires_password_change: true` → el frontend DEBE forzar el cambio de contraseña antes de mostrar la app
(el backend además bloqueará las rutas de negocio con `PASSWORD_CHANGE_REQUIRED` hasta que se cambie).
Errores: 401 `INVALID_CREDENTIALS` (nunca revela si falló el correo o la contraseña), 429 `RATE_LIMITED` (header `Retry-After`).

### POST `/auth/login/verify-totp` — Público con `pending_token` (rate limit 5/15 min) · 200
Body: `{ "pending_token": "eyJ...", "codigo": "123456" }`
Respuesta: `{ access_token, refresh_token, token_type: "bearer", expires_in_minutes }`
Errores: 401 `INVALID_TOTP` (código incorrecto o ya usado — replay bloqueado), `INVALID_TOKEN` (pending_token expirado: volver a login).

### POST `/auth/refresh` — Con refresh_token · 200
Body: `{ "refresh_token": "eyJ..." }` → mismo formato que verify-totp.

### POST `/auth/logout` — Bearer access (cualquier estado) · 200
Respuesta: `{ "ok": true }`. Invalida access y refresh previos (`SESSION_INVALIDATED` si se reutilizan).

### POST `/auth/totp/enroll` — Bearer access, estado `pendiente_2fa` · 200
Respuesta: `{ "secreto_en_claro": "JBSW...", "uri": "otpauth://...", "qr_base64": "iVBOR..." }`
El QR se muestra **una sola vez**. El frontend puede renderizar `qr_base64` como `data:image/png;base64,...`.

### POST `/auth/totp/confirm` — Bearer access, estado `pendiente_2fa` · 200
Body: `{ "codigo": "123456" }` → `{ "ok": true, "message": "2FA activado" }`. La cuenta pasa a `activo`.
Errores: 401 `INVALID_TOTP`, 403 `ALREADY_ACTIVE`.

### POST `/auth/password/change` — Bearer access (cualquier estado) · 200
Body: `{ "contrasena_actual": "...", "contrasena_nueva": "..." }`
→ `{ "ok": true }`. **Invalida todos los tokens previos** del usuario (hay que volver a hacer login).
Errores: 401 `INVALID_CREDENTIALS` (contraseña actual incorrecta), 422 `INVALID_PASSWORD` (reglas §5 o reutilización de las últimas 3).

### GET `/auth/me` — Bearer access (cualquier estado) · 200
Respuesta: `{ id_usuarios, correo, rol, estado, org_id?, activo, totp_habilitado, debe_cambiar_contrasena }`

## 5. Reglas de seguridad para el frontend

1. Guardar `access_token` en memoria (no localStorage si es posible) y `refresh_token` con cuidado; **nunca** exponer el secreto TOTP tras el enrolamiento.
2. Con `must_enroll_totp: true`, el token provisional SOLO sirve para: `totp/enroll`, `totp/confirm`, `me`, `logout`, `password/change`. Cualquier ruta de negocio devuelve 403.
3. Un código TOTP usado no puede reutilizarse (ni siquiera en otra sesión) — si el usuario envía dos veces el mismo código, el segundo dará `INVALID_TOTP`.
4. Después de `password/change` y `logout`: limpiar tokens y volver a pedir login.
5. 2FA es obligatorio y **no se puede deshabilitar** (solo se puede re-enrolar si el usuario perdió el acceso).

## 6. Códigos de error

### 6.1 Actuales (Fase Auth)
`UNAUTHENTICATED` 401 · `INVALID_TOKEN` 401 · `SESSION_INVALIDATED` 401 · `INVALID_CREDENTIALS` 401 ·
`PENDING_2FA` 403 · `ALREADY_ACTIVE` 403 · `FORBIDDEN` 403 · `INVALID_TOTP` 401 · `INVALID_PASSWORD` 422 ·
`DUPLICATE` 409 · `RATE_LIMITED` 429 (header `Retry-After`) · `VALIDATION_ERROR` 422 (details.errors) · `INTERNAL_ERROR` 500

### 6.2 Rate limits activos
| Endpoint | Límite |
|---|---|
| `/auth/login` | 10 intentos / 15 min por IP + correo |
| `/auth/login/verify-totp` | 5 intentos / 15 min por sesión temporal |

### 6.3 Códigos que se añaden con Organizations/Users (v1.1)
- `PASSWORD_CHANGE_REQUIRED` (403) — rutas de negocio bloqueadas hasta cambiar la contraseña temporal (invitados nuevos)
- `NOT_FOUND` (404) — recurso inexistente **o fuera de tu organización** (nunca se revela cuál de las dos)
- `DUPLICATE` (409) — correo/slug ya existe
- `FORBIDDEN` (403) — rol insuficiente o recurso de otra organización

---

## 7. `/organizations` (nuevo — v1.1)

| Método | Ruta | Quién | Body / Respuesta |
|---|---|---|---|
| POST | `/organizations` | `admin_plataforma` | Body `{nombre, slug?, correo_admin?}` → 201 `{organizacion: {id_organizaciones, nombre, slug, creado_en}, admin?: {id_usuarios, correo, estado, contrasena_temporal_enviada}}`. Si `correo_admin` viene, se crea el admin de la org (pendiente_2fa + cambio forzado) y se le envía correo con credenciales |
| GET | `/organizations` | `admin_plataforma` | → `{total, items, limit, offset}`; cada item trae `metricas: {usuarios_activos, grupos, destinatarios_activos, campanas_totales, campanas_activas}` |
| GET | `/organizations/{id}` | `admin_plataforma` o miembro de esa org | Detalle + métricas. Un miembro que pide otra org → 403 |
| PATCH | `/organizations/{id}` | `admin_organizacion` de ESA org | Body `{nombre?|slug?}` → organizacion actualizada. Slug duplicado → 409 |

Notas: `limit` máx 100 (`limit=20`, `offset=0` por defecto). Solo el admin de la propia org puede editarla.

## 8. `/users` (nuevo — v1.1)

| Método | Ruta | Quién | Body / Respuesta |
|---|---|---|---|
| GET | `/users` | `admin_organizacion`, `analista` | → `{total, items: [{id_usuarios, correo, rol, estado, activo, creado_en}], limit, offset}`. Siempre de la propia organización |
| POST | `/users/invite` | `admin_organizacion` | Body `{correo}` → 201 `{id_usuarios, correo, rol: "analista", estado: "pendiente_2fa", correo_enviado}`. La contraseña temporal va SOLO por correo (nunca en la respuesta). Duplicado → 409 |
| PATCH | `/users/{id}/role` | `admin_organizacion` | Body `{rol: "analista" \| "admin_organizacion"}` → usuario actualizado. No se puede cambiar el propio rol ni dejar la org sin admin → 422 |
| PATCH | `/users/{id}/deactivate` | `admin_organizacion` | → usuario con `activo: false, estado: "inactivo"`. Mata sus sesiones activas. No autodesactivación → 422 |

Notas:
- IDs de usuarios de otra organización responden `404 NOT_FOUND` (no se revela que existen).
- El invitado nuevo debe: login → 2FA enroll/confirm → las rutas de negocio dan `403 PASSWORD_CHANGE_REQUIRED` → `/auth/password/change` → login de nuevo → acceso normal.
- `correo_enviado: false` en la invitación = el SMTP falló (ver logs); reinvitar generará error de correo duplicado — contactar soporte o desactivar/reinvitar.

---

## 9. `/groups` (nuevo — v1.2)

Gestión de grupos de destinatarios dentro de la organización del token (§6.1). **Lecturas:** `admin_organizacion` + `analista`. **Escrituras:** solo `admin_organizacion`.

| Método | Ruta | Quién | Body / Respuesta |
|---|---|---|---|
| POST | `/groups` | `admin_organizacion` | Body `{nombre (1-150), perfil (1-100)}` → 201 `{id_grupos, nombre, perfil, creado_en, metricas: {destinatarios_activos, indice_promedio}}`. Nombre duplicado en la org (sin distinguir mayúsculas) → 409 `DUPLICATE` |
| GET | `/groups` | ambos roles | → `{total, items: [GrupoDetail], limit, offset}`; cada item incluye `metricas`. `indice_promedio` es `null` si el grupo aún no tiene campañas finalizadas |
| GET | `/groups/{id}` | ambos roles | Detalle + métricas. Grupo de otra org o inexistente → 404 `NOT_FOUND` |
| PATCH | `/groups/{id}` | `admin_organizacion` | Body `{nombre?|perfil?}` → grupo actualizado. Sin campos → 422. Nombre duplicado → 409 |
| DELETE | `/groups/{id}` | `admin_organizacion` | → 204 sin cuerpo. **409 `CONFLICT`** si el grupo tiene campañas asociadas (RESTRICT). Eliminar un grupo elimina en cascada sus destinatarios (no se puede deshacer) |

## 10. `/recipients` (nuevo — v1.2)

Destinatarios (empleados que recibirán las simulaciones). Mismos permisos que `/groups`.

| Método | Ruta | Quién | Body / Respuesta |
|---|---|---|---|
| POST | `/recipients` | `admin_organizacion` | Body `{correo, grupo_id}` → 201 `{id_destinatarios, correo (normalizado en minúsculas), grupo_id, activo: true, creado_en}`. El grupo debe existir en TU organización (si no → 404). Correo repetido en la org → 409 `DUPLICATE` |
| POST | `/recipients/import` | `admin_organizacion` | **multipart/form-data** con campo `file` (CSV, máx 2 MB). Encabezados EXACTOS en la primera línea: `correo,grupo` — grupo por NOMBRE, debe existir en la org → 201 `{total_filas, creados, duplicados, invalidos, errores: ["fila 3: ...", ...]}` (detalle máx 100 filas). **Nunca falla por filas inválidas**: las reporta y crea las válidas. Encabezados incorrectos o archivo vacío → 422 |
| GET | `/recipients` | ambos roles | → `{total, items: [...], limit, offset}`. Query opcional `?grupo_id=<uuid>` (grupo ajeno → 404). Incluye activos E inactivos (campo `activo: bool`) |
| GET | `/recipients/{id}` | ambos roles | Detalle + `historico: [{campana_id?, puntaje_phishing (0-100), nivel: "alto"\|"medio"\|"bajo"\|"critico", creado_en}, ...]` (más reciente primero; vacío `[]` si aún no hay campañas) |
| PATCH | `/recipients/{id}` | `admin_organizacion` | Body `{correo?|grupo_id?}` → destinatario actualizado (404/409 igual que arriba) |
| PATCH | `/recipients/{id}/deactivate` | `admin_organizacion` | Borrado lógico → `activo: false`. Los datos e histórico se CONSERVAN (no se anonimiza). Ya desactivado → 422 |

Notas CSV (formato exacto esperado):

```csv
correo,grupo
juan.perez@empresa.com,Ventas
ana.lopez@empresa.com,Soporte
```

- La unicidad del correo es **por organización** (case-insensitive): el mismo correo puede existir en orgs distintas.
- Un correo desactivado sigue bloqueando su re-creación (único en la org, activo o no) — cuenta como `duplicados` en el CSV.
- `duplicados` = repetidos dentro del archivo + ya existentes en la org.
- Formato de correo validado estrictamente (igual que `/auth`); en el CSV una fila con correo inválido NO aborta nada: entra en `invalidos` + `errores`.
- Límite: 5000 filas por archivo (más → 422).


