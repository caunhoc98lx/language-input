import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: 'standalone',
  images: { qualities: [75, 90] },
  webpack: (config) => {
    config.resolve.alias["@"] = path.resolve(process.cwd()); // hoặc "src" nếu dùng src/
    return config;
  },
};

export default nextConfig;