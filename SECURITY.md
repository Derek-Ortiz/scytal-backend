# Seguridad

## Reportar una vulnerabilidad

Si encontraste una vulnerabilidad en Scytal Backend, **no la publiques en un issue público**.

Envía un correo a 243742@ids.upchiapas.edu.mx con:

- Descripción del problema y sus pasos para reproducirlo.
- Versión o commit afectado (`git log -1 --oneline`).
- Impacto estimado (qué podría explotar un atacante).
- Corrección sugerida, si la tienes.

Recibirás una respuesta de acuse en un plazo máximo de **5 días hábiles** y una
evaluación con fecha estimada de corrección en **30 días**.

## Alcance

Incluyen: autenticación y autorización, inyección SQL/XSS, SSRF en el importador
de plantillas, manipulación de tokens de rastreo, fugas de secretos o datos entre
organizaciones (multi-tenant) y dependencias vulnerables.

No incluyen: denegación de servicio por volumen (el rate limiting ya cubre los
casos relevantes), problemas que requieran acceso físico o credenciales ya
comprometidas, y hallazgos en dependencias sin ruta de explotación real.

## Prácticas del proyecto

- Los secretos viven en variables de entorno; `.env` está excluido de git y de la imagen Docker.
- Las contraseñas se almacenan con Argon2id; los secretos TOTP se cifran con Fernet.
- El escaneo de secretos (gitleaks) y las auditorías de dependencias (pip-audit)
  forman parte de la revisión antes de publicar.
