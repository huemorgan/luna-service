-- Pre-create test tenant schemas for scenario 08 (schema scoping)
CREATE SCHEMA IF NOT EXISTS luna_test_alice;
CREATE SCHEMA IF NOT EXISTS luna_test_bob;

-- pgvector extension (needed for Luna's memory plugin)
CREATE EXTENSION IF NOT EXISTS vector;
