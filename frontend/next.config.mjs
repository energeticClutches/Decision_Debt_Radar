/** @type {import('next').NextConfig} */
// The browser calls /api/... on its own origin and Next rewrites it to the backend, so no CORS change is needed.
//   local:  API_ORIGIN unset            -> http://127.0.0.1:8000  ("localhost" can hang on some Windows setups)
//   Vercel: API_ORIGIN=https://<your-service>.onrender.com   (read when the app is built and when the server starts; no trailing slash)
// DDR_API_ORIGIN is the older name of the same setting and is still read.
const API_ORIGIN = (process.env.API_ORIGIN || process.env.DDR_API_ORIGIN || "http://127.0.0.1:8000").replace(/\/+$/, "");

const dev = process.env.NODE_ENV !== "production";

// A conservative Content-Security-Policy for a Next.js app (App Router) that self-hosts its fonts (next/font) and calls only its own origin.
// 'unsafe-inline' is needed for the inline bootstrap scripts and styles Next.js emits (a nonce would force every page to be rendered per
// request); there is no eval in production, and no third-party origin of any kind. There is deliberately no upgrade-insecure-requests,
// so the same build also runs over plain http on 127.0.0.1.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${dev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()" },
  { key: "Content-Security-Policy", value: csp },
];

const nextConfig = {
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
