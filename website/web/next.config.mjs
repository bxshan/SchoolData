/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // deck.gl ships ESM; transpile to be safe across Next versions.
  transpilePackages: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/react"],
};

export default nextConfig;
