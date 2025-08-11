-- init-db.sql
-- PostgreSQL extensions for the portfolio application
-- pgvector for AI embeddings and PostGIS for geospatial features

-- Enable extensions with error handling and verification
DO $$ 
BEGIN
    -- Install pgvector extension (for embeddings/RAG)
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
        RAISE NOTICE '✅ pgvector extension loaded successfully';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING '❌ Failed to create pgvector extension: %', SQLERRM;
        RAISE EXCEPTION 'pgvector extension is required for application functionality';
    END;

    -- Install PostGIS extension (for geospatial queries)
    BEGIN
        CREATE EXTENSION IF NOT EXISTS postgis;
        RAISE NOTICE '✅ PostGIS extension loaded successfully';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING '❌ Failed to create PostGIS extension: %', SQLERRM;
        RAISE EXCEPTION 'PostGIS extension is required for GeoDjango functionality';
    END;

    -- Install PostGIS topology (optional but recommended)
    BEGIN
        CREATE EXTENSION IF NOT EXISTS postgis_topology;
        RAISE NOTICE '✅ PostGIS topology extension loaded successfully';
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE '⚠️  PostGIS topology extension not available (optional): %', SQLERRM;
    END;

    RAISE NOTICE '🎉 Database initialization complete with pgvector + PostGIS';
END $$;