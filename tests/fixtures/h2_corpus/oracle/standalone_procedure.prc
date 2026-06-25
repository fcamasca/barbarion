CREATE OR REPLACE PROCEDURE demo_rebuild_cache IS
BEGIN
  DELETE FROM demo_cache;
  INSERT INTO demo_cache(id, description) VALUES (1, 'synthetic');
END demo_rebuild_cache;
/
