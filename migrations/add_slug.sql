-- Agrega slug unico a organizaciones (decision del usuario).
ALTER TABLE organizaciones
  ADD COLUMN IF NOT EXISTS slug VARCHAR(150) NOT NULL DEFAULT '';

UPDATE organizaciones
SET slug = regexp_replace(lower(nombre), '[^a-z0-9]+', '-', 'g')
WHERE slug = '';

-- Eliminar guiones al inicio/fin
UPDATE organizaciones
SET slug = btrim(slug, '-')
WHERE slug <> '';

-- Rellenar vacios con el id
UPDATE organizaciones
SET slug = lower(replace(id_organizaciones::text, '-', ''))
WHERE slug = '';

ALTER TABLE organizaciones
  ALTER COLUMN slug DROP DEFAULT,
  ADD CONSTRAINT uk_organizaciones_slug UNIQUE (slug);
