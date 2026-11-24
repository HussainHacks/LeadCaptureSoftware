-- Initialize dedicated database for n8n using the configured PostgreSQL administrator
SELECT 'CREATE DATABASE n8n OWNER ' || quote_ident(current_user)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec

DO $$
BEGIN
    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE n8n TO %I', current_user);
END
$$;

\c n8n

DO $$
BEGIN
    EXECUTE format('GRANT ALL ON SCHEMA public TO %I', current_user);
END
$$;
