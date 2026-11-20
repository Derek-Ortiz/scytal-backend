from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE campanas_qr_zonas ADD COLUMN IF NOT EXISTS expira_en TIMESTAMP WITH TIME ZONE")
    op.execute("""
        UPDATE campanas_qr_zonas z
        SET expira_en = NOW() + MAKE_INTERVAL(hours => c.expiracion_horas)
        FROM campanas c
        WHERE c.id_campanas = z.campana_id AND z.expira_en IS NULL
          AND c.estado IN ('activa', 'completada')
    """)
    op.execute("""
        UPDATE campanas_qr_zonas z
        SET expira_en = NOW()
        FROM campanas c
        WHERE c.id_campanas = z.campana_id AND z.expira_en IS NULL AND c.estado = 'cancelada'
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_qr_zonas_expira ON campanas_qr_zonas(expira_en)")

def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_qr_zonas_expira")
    op.execute("ALTER TABLE campanas_qr_zonas DROP COLUMN IF EXISTS expira_en")
