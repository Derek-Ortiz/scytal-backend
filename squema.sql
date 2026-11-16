CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";  

CREATE TYPE rol_usuario AS ENUM ('admin_plataforma', 'admin_organizacion', 'analista');
CREATE TYPE estado_usuario AS ENUM ('pendiente_2fa', 'activo', 'suspendido', 'inactivo');
CREATE TYPE estado_campana AS ENUM ('pendiente', 'programada', 'activa', 'completada', 'cancelada');
CREATE TYPE tipo_evento AS ENUM ('abierto', 'click', 'subido');
CREATE TYPE tipo_canal AS ENUM ('correo', 'qr');
CREATE TYPE nivel_madurez AS ENUM ('bajo', 'medio', 'alto', 'critico');


CREATE OR REPLACE FUNCTION fn_actualizar_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.actualizado_en = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE organizaciones (
    id_organizaciones UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(255) NOT NULL,
    slug VARCHAR(150) NOT NULL UNIQUE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trg_organizaciones_actualizado
    BEFORE UPDATE ON organizaciones
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE usuarios (
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

CREATE TRIGGER trg_usuarios_actualizado
    BEFORE UPDATE ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE historial_contrasenas (
    id_historial_contrasenas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID NOT NULL REFERENCES usuarios(id_usuarios) ON DELETE CASCADE,
    hash_contrasena TEXT NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE grupos (
    id_grupos UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    nombre VARCHAR(150) NOT NULL,
    perfil VARCHAR(100) NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_grupos_org_nombre UNIQUE (org_id, nombre)
);

CREATE TRIGGER trg_grupos_actualizado
    BEFORE UPDATE ON grupos
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE destinatarios (
    id_destinatarios UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    grupo_id UUID NOT NULL REFERENCES grupos(id_grupos) ON DELETE CASCADE,
    correo CITEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_destinatarios_org_correo UNIQUE (org_id, correo)
);

CREATE TRIGGER trg_destinatarios_actualizado
    BEFORE UPDATE ON destinatarios
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE plantillas (
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

CREATE TRIGGER trg_plantillas_actualizado
    BEFORE UPDATE ON plantillas
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE campanas (
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

CREATE TRIGGER trg_campanas_actualizado
    BEFORE UPDATE ON campanas
    FOR EACH ROW EXECUTE FUNCTION fn_actualizar_timestamp();

CREATE TABLE campana_canales (
    campana_id UUID NOT NULL REFERENCES campanas(id_campanas) ON DELETE CASCADE,
    canal tipo_canal NOT NULL,
    PRIMARY KEY (campana_id, canal)
);


CREATE TABLE destinatarios_campana (
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


CREATE TABLE eventos_tracking (
    id_eventos_tracking UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destinatario_campana_id UUID NOT NULL REFERENCES destinatarios_campana(id_destinatarios_campana) ON DELETE CASCADE,
    tipo tipo_evento NOT NULL,
    canal_origen tipo_canal, 
    direccion_ip VARCHAR(45),
    user_agent TEXT,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE eventos_auditoria (
    id_eventos_auditoria UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    tipo VARCHAR(100) NOT NULL,
    actor_id UUID REFERENCES usuarios(id_usuarios) ON DELETE SET NULL,  
    actor_tipo VARCHAR(50) NOT NULL DEFAULT 'user',        
    detalle TEXT NOT NULL,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE alertas (
    id_alertas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    tipo VARCHAR(100) NOT NULL,
    referencia_tipo VARCHAR(50),
    referencia_id UUID,
    resuelto BOOLEAN NOT NULL DEFAULT FALSE,
    resuelto_en TIMESTAMP WITH TIME ZONE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE instantaneas_phishing (
    id_instantaneas_phishing UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizaciones(id_organizaciones) ON DELETE CASCADE,
    destinatario_id UUID NOT NULL REFERENCES destinatarios(id_destinatarios) ON DELETE CASCADE,
    campana_id UUID REFERENCES campanas(id_campanas) ON DELETE SET NULL,

    puntaje_phishing NUMERIC(5,2) NOT NULL,  -- 0 a 100
    nivel nivel_madurez NOT NULL,

    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE INDEX idx_usuarios_org_id ON usuarios(org_id);
CREATE INDEX idx_grupos_org_id ON grupos(org_id);
CREATE INDEX idx_destinatarios_org_id ON destinatarios(org_id);
CREATE INDEX idx_campanas_org_id ON campanas(org_id);
CREATE INDEX idx_eventos_auditoria_org_id ON eventos_auditoria(org_id);
CREATE INDEX idx_alertas_org_id ON alertas(org_id);
CREATE INDEX idx_instantaneas_phishing_destinatario_fecha ON instantaneas_phishing(destinatario_id, creado_en DESC);
CREATE INDEX idx_instantaneas_phishing_org_id ON instantaneas_phishing(org_id);
CREATE INDEX idx_campanas_org_estado ON campanas(org_id, estado);
CREATE INDEX idx_alertas_org_resuelto ON alertas(org_id, resuelto);
CREATE INDEX idx_auditoria_org_fecha ON eventos_auditoria(org_id, creado_en DESC);
CREATE INDEX idx_destinatarios_grupo_id ON destinatarios(grupo_id);
CREATE INDEX idx_destinatarios_campana_campana_id ON destinatarios_campana(campana_id);
CREATE INDEX idx_destinatarios_campana_destinatario_id ON destinatarios_campana(destinatario_id);
CREATE INDEX idx_destinatarios_campana_token_hash ON destinatarios_campana(token_hash);
CREATE INDEX idx_eventos_tracking_destinatario_campana ON eventos_tracking(destinatario_campana_id);
CREATE INDEX idx_eventos_tracking_tipo ON eventos_tracking(tipo);