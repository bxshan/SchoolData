import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  SITE_URL, cityKey, describe, factValue, getFactSheet, getSchool, getWikidata, pageSchools,
  schemaType, schoolPath,
  schoolsInState, sectorLabel, source, stateName, statePath, wikipediaUrl,
} from "../../../lib/schools";

// One static page per school in the enabled states; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return pageSchools().map((s) => ({ id: s.i }));
}

// A school with a fact sheet is shown under its official name; NCES often abbreviates.
// The sheet's value may carry a note in parentheses (other spellings); the table
// shows it, the title does not.
function displayName(id: string, fallback: string): string {
  return factValue(getFactSheet(id), "Official name")?.split(" (")[0].trim() || fallback;
}

const isUrl = (v: string) => /^https?:\/\/\S+$/.test(v);
const shortUrl = (u: string) => u.replace(/^https?:\/\//, "").replace(/\/$/, "");

export function generateMetadata({ params }: { params: { id: string } }): Metadata {
  const s = getSchool(params.id);
  if (!s) return {};
  return {
    // City and state in the title: many US schools share a name.
    title: `${displayName(s.i, s.n)} — ${s.ci}, ${s.s} | SchoolData`,
    description: describe(s),
    alternates: { canonical: schoolPath(s) },
  };
}

export default function SchoolPage({ params }: { params: { id: string } }) {
  const s = getSchool(params.id);
  if (!s) notFound();

  const wiki = wikipediaUrl(s);
  const wd = getWikidata(s.i);
  const wdUrl = wd && `https://www.wikidata.org/wiki/${wd.q}`;
  const sheet = getFactSheet(s.i);
  const name = displayName(s.i, s.n);
  const sheetSite = factValue(sheet, "Official website");
  const website = sheetSite && isUrl(sheetSite) ? sheetSite : wd?.u;
  const founded = factValue(sheet, "Year opened")?.match(/^\d{4}\b/)?.[0] ?? wd?.f;
  const sameAs = [wiki, wdUrl, website].filter((u): u is string => Boolean(u));
  const ncesUrl = `https://nces.ed.gov/ccd/schoolsearch/school_detail.asp?ID=${s.i}`;
  const nearby = schoolsInState(s.s).filter((o) => cityKey(o.ci) === cityKey(s.ci) && o.i !== s.i).slice(0, 12);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": schemaType(s),
    name,
    ...(name !== s.n && { alternateName: s.n }),
    url: `${SITE_URL}${schoolPath(s)}`,
    description: describe(s),
    identifier: { "@type": "PropertyValue", propertyID: "NCES", value: s.i },
    address: {
      "@type": "PostalAddress",
      ...(s.a && { streetAddress: s.a }),
      addressLocality: s.ci,
      addressRegion: s.s,
      ...(s.z && { postalCode: s.z }),
      addressCountry: "US",
    },
    geo: { "@type": "GeoCoordinates", latitude: s.y, longitude: s.x },
    ...(s.ph && { telephone: s.ph }),
    ...(founded && { foundingDate: founded }),
    ...(sameAs.length && { sameAs }),
  };

  const facts: [string, string][] = [
    ["Type", sectorLabel(s)],
    ...(wd?.f ? [["Founded", `${wd.f} (Wikidata)`] as [string, string]] : []),
    ["Grades", s.gl && s.gh ? (s.gl === s.gh ? s.gl : `${s.gl}–${s.gh}`) : "Unknown"],
    ["Enrollment", s.e != null ? s.e.toLocaleString("en-US") : "Unknown"],
    ...(s.tf != null ? [["Teachers (FTE)", String(s.tf)] as [string, string]] : []),
    ...(s.d ? [["District", s.d] as [string, string]] : []),
    ["Address", [s.a, s.ci, `${s.s} ${s.z ?? ""}`.trim()].filter(Boolean).join(", ")],
    ...(s.ph ? [["Phone", s.ph] as [string, string]] : []),
    ["NCES ID", s.i],
  ];

  return (
    <main className="about school">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <nav className="about-nav">
        <Link href={statePath(s.s)}>← {stateName(s.s)} schools</Link>
        <Link href="/">Map</Link>
      </nav>

      <section className="about-hero">
        <h1>{name}</h1>
        <p>{s.ci}, {stateName(s.s)}</p>
      </section>

      <section className="about-section school-body">
        <p className="lead">{describe(s)}</p>
        {sheet ? (
          <>
            <table className="school-facts school-facts-sourced">
              <thead><tr><th>Fact</th><td>Value</td><td>Source</td></tr></thead>
              <tbody>
                {sheet.facts.map((x) => (
                  <tr key={x.f}>
                    <th>{x.f}</th>
                    <td>{isUrl(x.v) ? <a href={x.v} rel="nofollow">{shortUrl(x.v)}</a> : x.v}</td>
                    <td className="school-sources">
                      {x.s.map(([label, url]) => (
                        <a key={url} href={url} rel="nofollow">{label}</a>
                      ))}
                    </td>
                  </tr>
                ))}
                {s.ph && <tr><th>Phone</th><td>{s.ph}</td><td className="school-sources"><a href={ncesUrl}>NCES</a></td></tr>}
                <tr><th>NCES ID</th><td>{s.i}</td><td className="school-sources"><a href={ncesUrl}>NCES</a></td></tr>
              </tbody>
            </table>
            <p className="muted">
              Compiled from public sources as of {sheet.asOf}. Not yet confirmed by the school.
              Each fact links to where it was found.
            </p>
          </>
        ) : (<>
        <table className="school-facts">
          <tbody>
            {facts.map(([k, v]) => (
              <tr key={k}><th>{k}</th><td>{v}</td></tr>
            ))}
            {wd?.u && (
              <tr><th>Website</th><td><a href={wd.u} rel="nofollow">{wd.u.replace(/^https?:\/\//, "").replace(/\/$/, "")}</a> (Wikidata)</td></tr>
            )}
          </tbody>
        </table>
        <p className="muted">
          Source: {source(s)}. Federal public-domain data.
          {wd && <> Founding year and website, where shown: <a href={wdUrl}>Wikidata {wd.q}</a> (CC0).</>}
        </p>
        </>)}
        {wiki ? (
          <p>Wikipedia: <a href={wiki}>{s.wt}</a></p>
        ) : (
          <p className="muted">This school does not have an English Wikipedia article yet.</p>
        )}
      </section>

      <section className="about-band">
        <h2>Is this your school?</h2>
        <p className="lead">
          Help make sure AI and search describe it correctly. Check these facts and
          tell us what is missing{sheet?.missing.length ? "." : ": founding year, programs, history."}
        </p>
        {sheet && sheet.missing.length > 0 && (
          <p>
            We could not find a public source for: {sheet.missing.join("; ")}. If your
            school website or a news article mentions any of these, a link helps.
          </p>
        )}
        <a
          className="about-cta"
          href={`mailto:boxuan.shan@gmail.com?subject=${encodeURIComponent(`Verify: ${name} (NCES ${s.i})`)}`}
        >
          Help verify
        </a>
      </section>

      {nearby.length > 0 && (
        <section className="about-section school-body">
          <h2>Other schools in {s.ci}</h2>
          <ul className="school-list">
            {nearby.map((o) => (
              <li key={o.i}><Link href={schoolPath(o)}>{o.n}</Link></li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
