-- Revision 0007: deploy compatibility. NO schema change and NO semantic change.
--
-- The SQL guard executor runs every catalogue query under "SET LOCAL ROLE ddr_readonly". A role may only SET ROLE to a role it is a
-- member of with the SET option. A superuser always may; the owner of a managed database (for example Neon, where the application
-- connects as a non-superuser) may not: on PostgreSQL 16 and later the creator of a role receives ADMIN OPTION on it but neither INHERIT
-- nor SET. This grants the migrating (connecting) role membership in ddr_readonly with the SET option and without INHERIT, so that
-- SET ROLE works and the role's privileges are still only taken on by an explicit SET ROLE.
-- ddr_readonly itself, its privileges and every view stay exactly as revision 0003 and 0005 left them.
DO $$
BEGIN
  IF current_user = 'ddr_readonly' THEN
    RETURN;
  END IF;
  IF current_setting('server_version_num')::int >= 160000 THEN
    EXECUTE format('GRANT ddr_readonly TO %I WITH SET TRUE, INHERIT FALSE', current_user);
  ELSE
    EXECUTE format('GRANT ddr_readonly TO %I', current_user);
  END IF;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE WARNING 'could not grant ddr_readonly to %: SET ROLE ddr_readonly may fail for this login. Run as an administrator: GRANT ddr_readonly TO %;', current_user, current_user;
END $$;
