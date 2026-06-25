CREATE OR REPLACE PACKAGE BODY demo_accounts AS
  PROCEDURE refresh_totals(p_account_id IN NUMBER) IS
  BEGIN
    UPDATE demo_account_totals
       SET refreshed_at = SYSDATE
     WHERE account_id = p_account_id;
  END refresh_totals;

  FUNCTION status_label(p_status IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE p_status WHEN 'A' THEN 'Activo' ELSE 'Pendiente' END;
  END status_label;
END demo_accounts;
/
