import type { NextConfig } from "next";

const apiPort = process.env.API_PORT ?? "8030";
const apiBase = `http://127.0.0.1:${apiPort}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/health", destination: `${apiBase}/health` },
      { source: "/ready", destination: `${apiBase}/ready` },
      { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
    ];
  },
};

export default nextConfig;
