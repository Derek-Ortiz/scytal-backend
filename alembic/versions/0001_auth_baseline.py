"""Baseline de autenticación sobre squema.sql existente.
Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE organizaciones ADD COLUMN IF NOT EXISTS slug VARCHAR(150);
        UPDATE organizaciones SET slug = regexp_replace(lower(nombre), '[^a-z0-9]+', '-', 'g') WHERE slug IS NULL OR slug = '';
        UPDATE organizaciones SET slug = btrim(slug, '-') WHERE slug <> '';
        UPDATE organizaciones SET slug = lower(replace(id_organizaciones::text, '-', '')) WHERE slug = '';
        ALTER TABLE organizaciones ALTER COLUMN slug SET NOT NULL,
            ADD CONSTRAINT uk_organizaciones_slug UNIQUE (slug);
    """)


def downgrade():
    op.execute("ALTER TABLE organizaciones DROP COLUMN IF EXISTS slug;")
