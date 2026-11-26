-- Least-privilege notes: the application role owns only the atlas database.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
