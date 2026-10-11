import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cityKey, pageStates, schoolPath, schoolsInState, stateName } from "../../../lib/schools";

// A plain list of links per enabled state, so crawlers can reach every school page.
export const dynamicParams = false;

export function generateStaticParams() {
  return pageStates().map((s) => ({ state: s.toLowerCase() }));
}

export function generateMetadata({ params }: { params: { state: string } }): Metadata {
  const code = params.state.toUpperCase();
  return {
    title: `K–12 schools in ${stateName(code)} | SchoolData`,
    description: `Every public and private K–12 school in ${stateName(code)}, from federal NCES records.`,
    alternates: { canonical: `/schools/${params.state}` },
  };
}

export default function StatePage({ params }: { params: { state: string } }) {
  const code = params.state.toUpperCase();
  const schools = schoolsInState(code);
  if (!schools.length) notFound();

  const byCity = new Map<string, typeof schools>();
  for (const s of schools) {
    const list = byCity.get(cityKey(s.ci)) ?? [];
    list.push(s);
    byCity.set(cityKey(s.ci), list);
  }
  // Heading: prefer the mixed-case spelling (public records) over the all-caps one.
  const cityLabel = (list: typeof schools) =>
    (list.find((s) => s.ci !== s.ci.toUpperCase()) ?? list[0]).ci;

  return (
    <main className="about school">
      <nav className="about-nav">
        <Link href="/">← Map</Link>
        <Link href="/about">About</Link>
      </nav>
      <section className="about-hero">
        <h1>Schools in {stateName(code)}</h1>
        <p>{schools.length.toLocaleString("en-US")} K–12 schools from federal NCES records.</p>
      </section>
      <section className="about-section school-body">
        {Array.from(byCity, ([key, list]) => (
          <div key={key} className="school-city">
            <h3>{cityLabel(list)}</h3>
            <ul className="school-list">
              {list.map((s) => (
                <li key={s.i}><Link href={schoolPath(s)}>{s.n}</Link></li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </main>
  );
}
