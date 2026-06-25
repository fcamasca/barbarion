CREATE OR REPLACE PACKAGE demo_accounts AS
  PROCEDURE refresh_totals(p_account_id IN NUMBER);
  FUNCTION status_label(p_status IN VARCHAR2) RETURN VARCHAR2;
END demo_accounts;
/
