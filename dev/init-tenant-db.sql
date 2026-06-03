-- Separate database for Luna tenant data (avoids table name collisions with control plane)
CREATE DATABASE lunatenants OWNER luna;
\c lunatenants
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
