/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: { turbo: { rules: {} } },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },
};
module.exports = nextConfig;
