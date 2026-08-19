import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // La pastille de dev Next se superpose au coin bas-gauche — là où vit
  // justement le menu compte de la sidebar. On la masque : elle gêne la
  // navigation en local et pollue les captures d'écran.
  devIndicators: false,
};

export default nextConfig;
