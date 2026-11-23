# Contribuir a Scytal Backend

Gracias por tu interés. Este es un proyecto de capacitación en ciberseguridad.

## Flujo de trabajo

1. Abre un issue describiendo el cambio antes de trabajar en algo grande.
2. Crea una rama desde `main`: `git checkout -b feat/mi-cambio`.
3. Haz commits pequeños y con mensajes claros (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
4. Abre un pull request contra `main`. El workflow CI debe pasar (pruebas unitarias + bandit).

## Reglas del código

- **No se aceptan secretos, credenciales ni `.env` versionados** (gitleaks lo verifica).
- Respeta la arquitectura por capas: `routers → services → repositories`. Nada de SQL directo en routers.
- Toda consulta filtra por `org_id` del JWT (aislamiento multi-tenant, §6.1 de la spec).
- Las acciones sensibles deben generar una fila en `eventos_auditoria` (§6.6).
- Cada cambio relevante necesita al menos una prueba del camino feliz y una de error.
- No subas comentarios ni docstrings de archivo al código: la documentación vive en el README.

## Correr las pruebas

```bash
# Unitarias (sin BD)
python -m pytest tests/unit -q

# Integración (requiere docker compose con db + redis)
python -m pytest tests -q
```

## Seguridad

Reporta vulnerabilidades según [SECURITY.md](SECURITY.md), nunca en issues públicos.

## Licencia

Al contribuir, aceptas que tu trabajo se distribuya bajo la licencia [MIT](LICENSE).
