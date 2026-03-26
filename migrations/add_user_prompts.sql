-- Migration: add prompts column to users table
-- Run once against the dating_app database:
--   docker exec -i <postgres_container> psql -U dating_user -d dating_app < migrations/add_user_prompts.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS prompts JSONB;
