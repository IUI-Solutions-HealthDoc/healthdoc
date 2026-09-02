import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "HealthDoc HMIS",
    short_name: "HealthDoc",
    description: "Hospital Information Management System",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#001f54",
    icons: [
      {
        src: "/healthdoc-logo.png",
        sizes: "1183x1183",
        type: "image/png",
        purpose: "any",
      },
    ],
  };
}

