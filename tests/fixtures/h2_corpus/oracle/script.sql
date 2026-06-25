-- Script generico con comandos no estructurados.
CREATE TABLE demo_script_table (
  id NUMBER PRIMARY KEY,
  note VARCHAR2(100)
);

INSERT INTO demo_script_table(id, note) VALUES (1, 'comentario sintetico');
COMMIT;
