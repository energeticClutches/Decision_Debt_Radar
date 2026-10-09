/** @type {import('next').NextConfig} */
// Day 6: the browser calls /api/... on its own origin and Next rewrites it to the backend. The backend CORS configuration is unchanged.
// 127.0.0.1, not localhost: "localhost" can hang on some Windows setups.
const API_ORIGIN = process.env.DDR_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
