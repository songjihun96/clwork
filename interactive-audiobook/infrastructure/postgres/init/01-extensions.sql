-- Runs once when the local Docker volume is created.
-- The first Alembic revision creates the same extensions for managed databases.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
