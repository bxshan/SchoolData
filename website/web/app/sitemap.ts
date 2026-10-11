import type { MetadataRoute } from "next";
import {
  SITEMAP_CHUNK as CHUNK, SITE_URL, pageSchools, pageStates, schoolPath, sitemapIds, statePath,
} from "../lib/schools";

// Served at /sitemap/<id>.xml; robots.ts lists every chunk.
export async function generateSitemaps() {
  return sitemapIds();
}

export default function sitemap({ id }: { id: number }): MetadataRoute.Sitemap {
  const schools = pageSchools().slice(id * CHUNK, (id + 1) * CHUNK);
  const pages = schools.map((s) => ({ url: `${SITE_URL}${schoolPath(s)}` }));
  if (id !== 0) return pages;
  return [
    { url: `${SITE_URL}/` },
    { url: `${SITE_URL}/about` },
    ...pageStates().map((s) => ({ url: `${SITE_URL}${statePath(s)}` })),
    ...pages,
  ];
}
