import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.1.9"],
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    const backendApiUrl = (
      process.env.BACKEND_API_URL ?? "http://localhost:8000"
    ).replace(/\/$/, "");

    return [
      {
        source: "/api/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
