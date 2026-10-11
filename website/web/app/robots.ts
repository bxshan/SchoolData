import type { MetadataRoute } from "next";
import { SITE_URL, sitemapIds } from "../lib/schools";

// The point of the school pages is to be read by search and AI crawlers, so every
// known AI crawler is allowed by name as well as by the catch-all rule.
const AI_CRAWLERS = [
  "GPTBot", "OAI-SearchBot", "ChatGPT-User",   // OpenAI
  "Google-Extended", "Googlebot",              // Google
  "CCBot",                                     // Common Crawl
  "ClaudeBot", "Claude-SearchBot",             // Anthropic
  "PerplexityBot", "Applebot-Extended", "Bingbot",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/" },
      { userAgent: AI_CRAWLERS, allow: "/" },
    ],
    sitemap: sitemapIds().map(({ id }) => `${SITE_URL}/sitemap/${id}.xml`),
  };
}
