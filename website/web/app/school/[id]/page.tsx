import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  SITE_URL, cityKey, describe, getSchool, getWikidata, pageSchools, schemaType, schoolPath,
  schoolsInState, sectorLabel, source, stateName, statePath, wikipediaUrl,
} from "../../../lib/schools";

// One static page per school in the enabled states; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return pageSchools().map((s) => ({ id: s.i }));
}

export function generateMetadata({ params }: { params: { id: string } }): Metadata {
  const s = getSchool(params.id);
  if (!s) return {};
  return {
    // City and state in the title: many US schools share a name.
    title: `${s.n} — ${s.ci}, ${s.s} | SchoolData`,
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
  const sameAs = [wiki, wdUrl, wd?.u].filter((u): u is string => Boolean(u));
  const nearby = schoolsInState(s.s).filter((o) => cityKey(o.ci) === cityKey(s.ci) && o.i !== s.i).slice(0, 12);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": schemaType(s),
    name: s.n,
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
    ...(wd?.f && { foundingDate: wd.f }),
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
        <h1>{s.n}</h1>
        <p>{s.ci}, {stateName(s.s)}</p>
      </section>

      <section className="about-section school-body">
        <p className="lead">{describe(s)}</p>
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
          tell us what is missing: founding year, programs, history.
        </p>
        <a
          className="about-cta"
          href={`mailto:boxuan.shan@gmail.com?subject=${encodeURIComponent(`Verify: ${s.n} (NCES ${s.i})`)}`}
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
