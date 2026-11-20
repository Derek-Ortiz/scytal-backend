from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE campanas ADD COLUMN IF NOT EXISTS expiracion_horas INTEGER NOT NULL DEFAULT 72")
    op.execute("""DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'campanas_qr_zonas') THEN
        CREATE TABLE campanas_qr_zonas (
            id_campanas_qr_zonas UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            campana_id UUID NOT NULL REFERENCES campanas(id_campanas) ON DELETE CASCADE,
            zona VARCHAR(100) NOT NULL,
            token_qr VARCHAR(64) NOT NULL UNIQUE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            clic_en TIMESTAMP WITH TIME ZONE,
            creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uk_qr_zona UNIQUE (campana_id, zona)
        );
    END IF; END $$;""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qr_zonas_campana ON campanas_qr_zonas(campana_id)")

def downgrade():
    op.execute("DROP TABLE IF EXISTS campanas_qr_zonas CASCADE")
    op.execute("ALTER TABLE campanas DROP COLUMN IF EXISTS expiracion_horas")
