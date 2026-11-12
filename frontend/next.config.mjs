/** @type {import('next').NextConfig} */
const backendInternal = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  allowedDevOrigins: ["*.e2b.app", "localhost", "127.0.0.1", "0.0.0.0"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendInternal}/api/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${backendInternal}/health/:path*`,
      },
    ];
  },
};

export default nextConfig;
