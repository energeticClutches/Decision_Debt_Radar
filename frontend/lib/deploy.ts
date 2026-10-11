// Build-time deployment flags. NEXT_PUBLIC_ variables are inlined by Next.js when the app is built.

/** The hosted public demo (shared data, reset nightly). Set NEXT_PUBLIC_DDR_PUBLIC_DEMO=1 on the host; unset locally. */
export const PUBLIC_DEMO = process.env.NEXT_PUBLIC_DDR_PUBLIC_DEMO === "1";
export const PUBLIC_DEMO_NOTE = "Public demo · shared data · resets nightly";
