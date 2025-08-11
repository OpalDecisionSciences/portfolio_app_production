-- init-db.sql
-- PostgreSQL extensions for the portfolio application
-- pgvector for AI embeddings and PostGIS for geospatial features

-- Enable pgvector for semantic search and embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable PostGIS for optimized geospatial queries
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;