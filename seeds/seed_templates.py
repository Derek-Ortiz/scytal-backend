import asyncio
import sys

sys.path.insert(0, "/srv/app")

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.plantilla import Plantilla
from app.services.plantilla_service import aplicar_leyenda

LEYENDA = (
    '<div style="margin-top:24px;padding:14px;text-align:center;font-family:Arial,sans-serif;'
    'background:#f8d7da;color:#58151c;border-top:2px solid #f5c2c7;font-size:14px;">'
    '<strong>PÁGINA DE PRUEBA</strong> — simulacro de phishing de Scytal con fines educativos. '
    'Ninguna credencial fue enviada a un servicio real.</div>'
)

CONTENIDO_GENERICO = (
    '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">'
    '<h2 style="color:#0d3b66;">Verificación de seguridad de tu cuenta</h2>'
    '<p>Detectamos una actividad inusual en tu cuenta corporativa. Para confirmar tu identidad '
    'y evitar la suspensión del servicio, valida tus credenciales en el siguiente enlace:</p>'
    '<p><a href="{{enlace}}">Verificar mi cuenta ahora</a></p>'
    '<p style="font-size:12px;color:#666;">Si no realizaste ninguna acción, ignora este mensaje.</p>'
    '{{pixel}}'
    '</div>'
)
LANDING_GENERICO = (
    '<html><body style="font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:0;">'
    '<div style="max-width:380px;margin:60px auto;background:#fff;padding:32px;border-radius:8px;'
    'box-shadow:0 2px 10px rgba(0,0,0,.1);text-align:center;">'
    '<h2 style="color:#0d3b66;">Iniciar sesión</h2>'
    '<p style="color:#555;">Sesión expirada por seguridad. Vuelve a entrar para continuar.</p>'
    '<form method="post" action="#">'
    '<input name="correo" type="text" placeholder="Correo" required '
    'style="width:100%;padding:10px;margin:8px 0;box-sizing:border-box;">'
    '<input name="contrasena" type="password" placeholder="Contraseña" required '
    'style="width:100%;padding:10px;margin:8px 0;box-sizing:border-box;">'
    '<button type="submit" style="width:100%;padding:10px;background:#0d3b66;color:#fff;'
    'border:none;border-radius:4px;cursor:pointer;">Entrar</button>'
    '</form>' + LEYENDA + '</div></body></html>'
)

CONTENIDO_FACEBOOK = (
    '<div style="font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;">'
    '<div style="background:#1877f2;color:#fff;padding:14px 20px;font-size:20px;font-weight:bold;">facebook</div>'
    '<div style="padding:20px;border:1px solid #dddfe2;border-top:none;">'
    '<h3>Se inició sesión en tu cuenta</h3>'
    '<p>Vimos un inicio de sesión desde un dispositivo no reconocido (Chrome, Windows). '
    'Si fuiste tú, ignora este mensaje. Si no, <a href="{{enlace}}">asegura tu cuenta ahora</a>.</p>'
    '<p style="font-size:12px;color:#606770;">Este enlace caduca en 24 horas.</p>'
    '{{pixel}}'
    '</div></div>'
)
LANDING_FACEBOOK = (
    '<html><body style="font-family:Helvetica,Arial,sans-serif;background:#f0f2f5;margin:0;padding:0;">'
    '<div style="max-width:380px;margin:60px auto;background:#fff;padding:32px;border-radius:8px;'
    'box-shadow:0 2px 10px rgba(0,0,0,.1);text-align:center;">'
    '<div style="color:#1877f2;font-size:28px;font-weight:bold;margin-bottom:8px;">facebook</div>'
    '<p style="color:#606770;">Inicia sesión para asegurar tu cuenta</p>'
    '<form method="post" action="#">'
    '<input name="correo" type="text" placeholder="Correo o teléfono" required '
    'style="width:100%;padding:12px;margin:8px 0;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">'
    '<input name="contrasena" type="password" placeholder="Contraseña" required '
    'style="width:100%;padding:12px;margin:8px 0;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">'
    '<button type="submit" style="width:100%;padding:12px;background:#1877f2;color:#fff;font-weight:bold;'
    'border:none;border-radius:6px;cursor:pointer;">Iniciar sesión</button>'
    '</form>' + LEYENDA + '</div></body></html>'
)

CONTENIDO_INSTAGRAM = (
    '<div style="font-family:-apple-system,Arial,sans-serif;max-width:560px;margin:0 auto;">'
    '<h3 style="color:#262626;">Alguien intentó entrar en tu cuenta</h3>'
    '<p>Detectamos un intento de acceso desde Ciudad de México, MX. Si no fuiste tú, '
    '<a href="{{enlace}}">cambia tu contraseña de inmediato</a> para proteger tu cuenta.</p>'
    '<p style="font-size:12px;color:#8e8e8e;">Instagram Security · No respondas a este correo.</p>'
    '{{pixel}}'
    '</div>'
)
LANDING_INSTAGRAM = (
    '<html><body style="font-family:-apple-system,Arial,sans-serif;background:#fafafa;margin:0;padding:0;">'
    '<div style="max-width:380px;margin:60px auto;background:#fff;padding:32px;border:1px solid #dbdbdb;'
    'border-radius:8px;text-align:center;">'
    '<div style="font-size:26px;font-weight:bold;margin-bottom:12px;'
    'background:-webkit-linear-gradient(#f09433,#dc2743);-webkit-background-clip:text;'
    '-webkit-text-fill-color:transparent;">Instagram</div>'
    '<p style="color:#262626;">Verifica tu identidad para recuperar el acceso</p>'
    '<form method="post" action="#">'
    '<input name="correo" type="text" placeholder="Correo o usuario" required '
    'style="width:100%;padding:10px;margin:6px 0;border:1px solid #dbdbdb;border-radius:4px;box-sizing:border-box;">'
    '<input name="contrasena" type="password" placeholder="Contraseña" required '
    'style="width:100%;padding:10px;margin:6px 0;border:1px solid #dbdbdb;border-radius:4px;box-sizing:border-box;">'
    '<button type="submit" style="width:100%;padding:10px;background:#0095f6;color:#fff;font-weight:bold;'
    'border:none;border-radius:4px;cursor:pointer;margin-top:6px;">Acceder</button>'
    '</form>' + LEYENDA + '</div></body></html>'
)

PLANTILLAS = [
    {
        "nombre": "Login genérico", "perfil": "corporativo", "canal": "correo",
        "asunto": "Verificación de seguridad de tu cuenta",
        "contenido_html": CONTENIDO_GENERICO, "landing_html": LANDING_GENERICO,
    },
    {
        "nombre": "Clon Facebook", "perfil": "redes_sociales", "canal": "correo",
        "asunto": "Se inició sesión en tu cuenta de Facebook",
        "contenido_html": CONTENIDO_FACEBOOK, "landing_html": LANDING_FACEBOOK,
    },
    {
        "nombre": "Clon Instagram", "perfil": "redes_sociales", "canal": "correo",
        "asunto": "Alguien intentó entrar en tu cuenta de Instagram",
        "contenido_html": CONTENIDO_INSTAGRAM, "landing_html": LANDING_INSTAGRAM,
    },
]

async def main():
    async with SessionLocal() as db:
        creadas = 0
        for datos in PLANTILLAS:
            existe = (await db.execute(
                select(Plantilla).where(Plantilla.org_id.is_(None), Plantilla.nombre == datos["nombre"])
            )).scalar_one_or_none()
            if existe:
                print(f"plantilla global '{datos['nombre']}' ya existe, nada que hacer.")
                continue
            db.add(Plantilla(
                org_id=None, nombre=datos["nombre"], perfil=datos["perfil"], canal=datos["canal"],
                asunto=datos["asunto"], contenido_html=datos["contenido_html"],
                landing_html=aplicar_leyenda(datos["landing_html"]),
            ))
            creadas += 1
        if creadas:
            await db.commit()
        print(f"seed_templates: {creadas} plantilla(s) creada(s), {len(PLANTILLAS) - creadas} ya existían.")

if __name__ == "__main__":
    asyncio.run(main())
