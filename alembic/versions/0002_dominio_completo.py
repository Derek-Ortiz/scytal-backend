"""Baseline completo del dominio (equivalente a squema.sql) para BD nuevas.

Idempotente: en BDs existentes creadas con squema.sql solo garantiza lo faltante
(triggers, índices); en BDs nuevas crea todo el esquema desde cero.
Alembic es la única fuente de verdad de aquí en adelante: squema.sql se conserva
intacto en el repo como referencia, pero el sistema ya no lo usa.
Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = [
    "organizaciones", "usuarios", "historial_contrasenas", "grupos", "destinatarios",
    "plantillas", "campanas", "campana_canales", "destinatarios_campana",
    "eventos_tracking", "eventos_auditoria", "alertas", "instantaneas_phishing",
]

ENUMS = ["rol_usuario", "estado_usuario", "estado_campana", "tipo_evento", "tipo_canal", "nivel_madurez"]

DDL_TABLES = """
CREATE TABLE IF NOT EXISTS organizaciones (
    id_organizaciones UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(255) NOT NULL,
    slug VARCHAR(150) NOT NULL UNIQUE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuarios UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    correo CITEXT NOT NULL UNIQUE,
    rol rol_usuario NOT NULL,
    hash_contrasena TEXT NOT NULL,
    totp_secreto_enc TEXT,
    totp_habilitado BOOLEAN NOT NULL DEFAULT FALSE,
    ultimo_totp_step BIGINT,
    contrasena_actualizada_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    debe_cambiar_contrasena BOOLEAN NOT NULL DEFAULT FALSE,
    version_token INT NOT NULL DEFAULT 1,
    estado estado_usuario NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_usuarios_org_segun_rol CHECK (
        (rol = 'admin_plataforma' AND org_id IS NULL) OR
        (rol IN ('admin_organizacion', 'analista') AND org_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS historial_contrasenas (
    id_historial_contrasenas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID NOT NULL REFERENCES usuarios(id_usuarios) ON DELETE CASCADE,
    hash_contrasena TEXT NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS grupos (
    id_grupos UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    nombre VARCHAR(150) NOT NULL,
    perfil VARCHAR(100) NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_grupos_org_nombre UNIQUE (org_id, nombre)
);

CREATE TABLE IF NOT EXISTS destinatarios (
    id_destinatarios UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    grupo_id UUID NOT NULL REFERENCES grupos(id_grupos) ON DELETE CASCADE,
    correo CITEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_destinatarios_org_correo UNIQUE (org_id, correo)
);

CREATE TABLE IF NOT EXISTS plantillas (
    id_plantillas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    nombre VARCHAR(255) NOT NULL,
    perfil VARCHAR(100) NOT NULL,
    canal tipo_canal NOT NULL,
    asunto VARCHAR(255),
    contenido_html TEXT NOT NULL,
    landing_html TEXT NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campanas (
    id_campanas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    grupo_id UUID NOT NULL REFERENCES grupos(id_grupos) ON DELETE RESTRICT,
    plantilla_id UUID REFERENCES plantillas(id_plantillas) ON DELETE SET NULL,
    nombre VARCHAR(255) NOT NULL,
    estado estado_campana NOT NULL DEFAULT 'pendiente',
    programada_en TIMESTAMP WITH TIME ZONE,
    iniciada_en TIMESTAMP WITH TIME ZONE,
    finalizada_en TIMESTAMP WITH TIME ZONE,
    feedback_enviado_en TIMESTAMP WITH TIME ZONE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campana_canales (
    campana_id UUID NOT NULL REFERENCES campanas(id_campanas) ON DELETE CASCADE,
    canal tipo_canal NOT NULL,
    PRIMARY KEY (campana_id, canal)
);

CREATE TABLE IF NOT EXISTS destinatarios_campana (
    id_destinatarios_campana UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campana_id UUID NOT NULL REFERENCES campanas(id_campanas) ON DELETE CASCADE,
    destinatario_id UUID NOT NULL REFERENCES destinatarios(id_destinatarios) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expira_en TIMESTAMP WITH TIME ZONE NOT NULL,
    abierto_en TIMESTAMP WITH TIME ZONE,
    clic_en TIMESTAMP WITH TIME ZONE,
    enviado_en TIMESTAMP WITH TIME ZONE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_destinatario_campana UNIQUE (campana_id, destinatario_id)
);

CREATE TABLE IF NOT EXISTS eventos_tracking (
    id_eventos_tracking UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destinatario_campana_id UUID NOT NULL REFERENCES destinatarios_campana(id_destinatarios_campana) ON DELETE CASCADE,
    tipo tipo_evento NOT NULL,
    canal_origen tipo_canal,
    direccion_ip VARCHAR(45),
    user_agent TEXT,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS eventos_auditoria (
    id_eventos_auditoria UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    tipo VARCHAR(100) NOT NULL,
    actor_id UUID REFERENCES usuarios(id_usuarios) ON DELETE SET NULL,
    actor_tipo VARCHAR(50) NOT NULL DEFAULT 'user',
    detalle TEXT NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alertas (
    id_alertas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    tipo VARCHAR(100) NOT NULL,
    referencia_tipo VARCHAR(50),
    referencia_id UUID,
    resuelto BOOLEAN NOT NULL DEFAULT FALSE,
    resuelto_en TIMESTAMP WITH TIME ZONE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instantaneas_phishing (
    id_instantaneas_phishing UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    destinatario_id UUID NOT NULL REFERENCES destinatarios(id_destinatarios) ON DELETE CASCADE,
    campana_id UUID REFERENCES campanas(id_campanas) ON DELETE SET NULL,

    puntaje_phishing NUMERIC(5,2) NOT NULL,
    nivel nivel_madurez NOT NULL,

    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_usuarios_org_id ON usuarios(org_id);
CREATE INDEX IF NOT EXISTS idx_grupos_org_id ON grupos(org_id);
CREATE INDEX IF NOT EXISTS idx_destinatarios_org_id ON destinatarios(org_id);
CREATE INDEX IF NOT EXISTS idx_campanas_org_id ON campanas(org_id);
CREATE INDEX IF NOT EXISTS idx_eventos_auditoria_org_id ON eventos_auditoria(org_id);
CREATE INDEX IF NOT EXISTS idx_alertas_org_id ON alertas(org_id);
CREATE INDEX IF NOT EXISTS idx_instantaneas_phishing_destinatario_fecha ON instantaneas_phishing(destinatario_id, creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_instantaneas_phishing_org_id ON instantaneas_phishing(org_id);
CREATE INDEX IF NOT EXISTS idx_campanas_org_estado ON campanas(org_id, estado);
CREATE INDEX IF NOT EXISTS idx_alertas_org_resuelto ON alertas(org_id, resuelto);
CREATE INDEX IF NOT EXISTS idx_auditoria_org_fecha ON eventos_auditoria(org_id, creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_destinatarios_grupo_id ON destinatarios(grupo_id);
CREATE INDEX IF NOT EXISTS idx_destinatarios_campana_campana_id ON destinatarios_campana(campana_id);
CREATE INDEX IF NOT EXISTS idx_destinatarios_campana_destinatario_id ON destinatarios_campana(destinatario_id);
CREATE INDEX IF NOT EXISTS idx_destinatarios_campana_token_hash ON destinatarios_campana(token_hash);
CREATE INDEX IF NOT EXISTS idx_eventos_tracking_destinatario_campana ON eventos_tracking(destinatario_campana_id);
CREATE INDEX IF NOT EXISTS idx_eventos_tracking_tipo ON eventos_tracking(tipo);
"""


def _trigger_guard(table: str) -> str:
    """DO block: crea el trigger solo si no existe."""
    return f"""
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.triggers
            WHERE trigger_name = 'trg_{table}_actualizado' AND event_object_table = '{table}'
        ) THEN
            CREATE TRIGGER trg_{table}_actualizado
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();
        END IF;
    END $$;
    """


def _exec_each(sql_multi: str) -> None:
    """asyncpg no admite múltiples comandos en un statement: ejecuta uno por uno (sin $$
    dentro de este SQL, el split por ';' es seguro)."""
    for stmt in (s.strip() for s in sql_multi.split(";")):
        if stmt:
            op.execute(stmt)


def upgrade():
    # Extensiones
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')

    # Enums (se crean completos solo si no existen — en BDs con squema.sql ya están)
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rol_usuario') THEN
        CREATE TYPE rol_usuario AS ENUM ('admin_plataforma', 'admin_organizacion', 'analista');
    END IF; END $$;""")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_usuario') THEN
        CREATE TYPE estado_usuario AS ENUM ('pendiente_2fa', 'activo', 'suspendido', 'inactivo');
    END IF; END $$;""")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_campana') THEN
        CREATE TYPE estado_campana AS ENUM ('pendiente', 'programada', 'activa', 'completada', 'cancelada');
    END IF; END $$;""")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_evento') THEN
        CREATE TYPE tipo_evento AS ENUM ('abierto', 'click', 'subido');
    END IF; END $$;""")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_canal') THEN
        CREATE TYPE tipo_canal AS ENUM ('correo', 'qr');
    END IF; END $$;""")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'nivel_madurez') THEN
        CREATE TYPE nivel_madurez AS ENUM ('bajo', 'medio', 'alto', 'critico');
    END IF; END $$;""")

    # Función de actualizado_en
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_actualizar_timestamp()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.actualizado_en = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # Tablas (ANTES que los triggers que referencian las tablas)
    _exec_each(DDL_TABLES)

    # Triggers actualizado_en
    for table in ("organizaciones", "usuarios", "grupos", "destinatarios", "plantillas", "campanas"):
        op.execute(_trigger_guard(table))

    # Índices
    _exec_each(DDL_INDEXES)


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for enum_name in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS fn_actualizar_timestamp")
