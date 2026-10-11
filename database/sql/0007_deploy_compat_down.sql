-- Revert revision 0007: remove the membership of ddr_readonly that revision 0007 granted to the migrating role (a no-op when absent).
DO $$
BEGIN
  EXECUTE format('REVOKE ddr_readonly FROM %I', current_user);
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'ddr_readonly membership of % was not revoked: %', current_user, SQLERRM;
END $$;
