// Server-only access to public/data/schools.json for the crawlable school pages.
// The map loads the same file in the browser; here it is read once at build time.
import fs from "node:fs";
import path from "node:path";
import type { School } from "./types";

export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.opendata.school").replace(/\/$/, "");

// States that get a static page per school. Start with one state, check crawling and
// indexing, then widen. "ALL" builds every state (122k pages; check build limits first).
const RAW_STATES = (process.env.SCHOOL_PAGE_STATES ?? "CA").toUpperCase();

let cache: School[] | null = null;

export function allSchools(): School[] {
  if (!cache) {
    const file = path.join(process.cwd(), "public/data/schools.json");
    cache = JSON.parse(fs.readFileSync(file, "utf8")) as School[];
  }
  return cache;
}

export function pageStates(): string[] {
  if (RAW_STATES === "ALL") return Array.from(new Set(allSchools().map((s) => s.s))).sort();
  return RAW_STATES.split(",").map((s) => s.trim()).filter(Boolean);
}

export function pageSchools(): School[] {
  const states = new Set(pageStates());
  return allSchools().filter((s) => states.has(s.s));
}

// Wikidata facts for well-matched schools (see build_dataset.py): QID, founding
// year, official website. Wikidata is CC0.
export type WikidataFacts = { q: string; f?: string; u?: string };

let wikidata: Record<string, WikidataFacts> | null = null;

export function getWikidata(id: string): WikidataFacts | undefined {
  if (!wikidata) {
    const file = path.join(process.cwd(), "public/data/school_wikidata.json");
    wikidata = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, WikidataFacts>;
  }
  return wikidata[id];
}

let byId: Map<string, School> | null = null;

export function getSchool(id: string): School | undefined {
  if (!byId) byId = new Map(pageSchools().map((s) => [s.i, s]));
  return byId.get(id);
}

export function schoolsInState(state: string): School[] {
  return allSchools()
    .filter((s) => s.s === state)
    .sort((a, b) => cityKey(a.ci).localeCompare(cityKey(b.ci)) || a.n.localeCompare(b.n));
}

// Private-school (PSS) cities are upper case ("SAN DIEGO"); public ones are not.
// Compare cities case-insensitively so both land in the same group.
export function cityKey(city: string): string {
  return city.toLowerCase();
}

// A sitemap file holds at most 50,000 URLs, so school pages are split into chunks.
export const SITEMAP_CHUNK = 45_000;

export function sitemapIds(): { id: number }[] {
  const n = Math.max(1, Math.ceil(pageSchools().length / SITEMAP_CHUNK));
  return Array.from({ length: n }, (_, id) => ({ id }));
}

export function schoolPath(s: School): string {
  return `/school/${s.i}`;
}

export function statePath(state: string): string {
  return `/schools/${state.toLowerCase()}`;
}

export const STATE_NAMES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
  IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
  ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon",
  PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
  TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia",
  WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
  AS: "American Samoa", GU: "Guam", MP: "Northern Mariana Islands",
  PR: "Puerto Rico", VI: "U.S. Virgin Islands", BI: "Bureau of Indian Education",
};

export function stateName(code: string): string {
  return STATE_NAMES[code] ?? code;
}

const GRADE_WORDS: Record<string, string> = { PK: "pre-kindergarten", K: "kindergarten", KG: "kindergarten" };

export function gradeLabel(g?: string): string {
  if (!g) return "";
  return GRADE_WORDS[g.toUpperCase()] ?? g.replace(/^0+(?=\d)/, "");
}

export function gradeRange(s: School): string | null {
  if (!s.gl || !s.gh) return null;
  return s.gl === s.gh ? `grade ${gradeLabel(s.gl)}` : `grades ${gradeLabel(s.gl)} through ${gradeLabel(s.gh)}`;
}

export function sectorLabel(s: School): string {
  if (s.pv) return "private";
  return s.ch === "Yes" ? "public charter" : "public";
}

export function source(s: School): string {
  return s.pv
    ? "NCES Private School Survey (PSS), 2023–24"
    : "NCES Common Core of Data (CCD), 2024–25";
}

// schema.org type by the level the map already assigns (highest grade offered).
export function schemaType(s: School): string {
  switch (s.lv) {
    case "elementary": return "ElementarySchool";
    case "middle": return "MiddleSchool";
    case "high": return "HighSchool";
    default: return "School";
  }
}

export function wikipediaUrl(s: School): string | null {
  return s.wt ? `https://en.wikipedia.org/wiki/${encodeURIComponent(s.wt.replace(/ /g, "_"))}` : null;
}

// A plain-language paragraph built only from the NCES fields — no inference.
export function describe(s: School): string {
  const level = s.lv === "other" ? "" : `${s.lv} `;
  const parts = [`${s.n} is a ${sectorLabel(s)} ${level}school in ${s.ci}, ${stateName(s.s)}`];
  if (s.d) parts[0] += `, in the ${s.d} district`;
  parts[0] += ".";
  const grades = gradeRange(s);
  const serve: string[] = [];
  if (grades) serve.push(`serves ${grades}`);
  if (s.e != null) serve.push(`enrolls ${s.e.toLocaleString("en-US")} students`);
  if (serve.length) parts.push(`It ${serve.join(" and ")}.`);
  return parts.join(" ");
}
