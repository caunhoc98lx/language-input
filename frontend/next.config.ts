import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  output: 'standalone',
  images: { qualities: [75, 90] }, // 90 for the cheerleader portraits
};

export default nextConfig;
