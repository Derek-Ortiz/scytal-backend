import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""DO $$ BEGIN
    IF to_regclass('public.organizaciones') IS NOT NULL THEN
        ALTER TABLE organizaciones ADD COLUMN IF NOT EXISTS slug VARCHAR(150);
        UPDATE organizaciones SET slug = regexp_replace(lower(nombre), '[^a-z0-9]+', '-', 'g') WHERE slug IS NULL OR slug = '';
        UPDATE organizaciones SET slug = btrim(slug, '-') WHERE slug <> '';
        UPDATE organizaciones SET slug = lower(replace(id_organizaciones::text, '-', '')) WHERE slug = '';
        ALTER TABLE organizaciones ALTER COLUMN slug SET NOT NULL;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uk_organizaciones_slug') THEN
            ALTER TABLE organizaciones ADD CONSTRAINT uk_organizaciones_slug UNIQUE (slug);
        END IF;
    END IF; END $$;""")

def downgrade():
    op.execute("""DO $$ BEGIN
    IF to_regclass('public.organizaciones') IS NOT NULL THEN
        ALTER TABLE organizaciones DROP COLUMN IF EXISTS slug;
    END IF; END $$;""")
