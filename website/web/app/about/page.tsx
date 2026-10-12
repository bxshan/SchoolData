import type { Metadata } from "next";
import Link from "next/link";
import stateCoverage from "../../public/data/state_coverage.json";
import { pageStates, stateName, statePath } from "../../lib/schools";

export const metadata: Metadata = {
  title: "About — SchoolData",
  description:
    "SchoolData is a student-led open data project building a consistent, sourced record of every US K-12 school.",
};

// Headline numbers come from the same file the map uses, so they never drift.
const counts = Object.values(stateCoverage as unknown as Record<string, [number, number]>);
const total = counts.reduce((n, [t]) => n + t, 0);
const has = counts.reduce((n, [, h]) => n + h, 0);
const missing = total - has;
const pct = (100 * has) / total;
const fmt = (n: number) => n.toLocaleString("en-US");

export default function About() {
  return (
    <main className="about">
      <nav className="about-nav">
        <Link href="/">← Map</Link>
        <span>SchoolData</span>
      </nav>

      <section className="about-hero">
        <h1>Every school, on the record.</h1>
        <p>
          SchoolData is a student-led open data project. We bring federal, state
          and school sources together into one consistent record for every K–12
          school in the US, attach a source to every fact, and ask schools to
          confirm what we found.
        </p>
      </section>

      <section className="about-band">
        <h2>Uneven coverage.</h2>
        <p className="lead">
          Information about schools is scattered across federal statistics, state
          directories and school websites, and it is unevenly represented in
          Wikipedia and Wikidata, which search engines and AI tools draw on
          heavily. A large high school may have a detailed article; the middle
          school nearby often has only a directory listing.
        </p>
        <div className="about-stats">
          <div><b>{fmt(total)}</b><span>K–12 schools in federal records</span></div>
          <div><b className="green">{pct.toFixed(1)}%</b><span>have an English Wikipedia page</span></div>
          <div><b className="red">{fmt(missing)}</b><span>have no article</span></div>
        </div>
        <p className="muted">
          Most articles are about high schools. How coverage varies with locale
          and school poverty is something we are measuring, not assuming.
        </p>
      </section>

      <section className="about-section">
        <h2>What we add.</h2>
        <p className="lead">
          Federal data is the starting point, not the product. For each school we
          measure whether Wikipedia and Wikidata cover it, compare federal, state
          and school records and flag where they disagree, link every fact to a
          public source, add facts federal data does not carry (year opened,
          namesake, programs, awards), and ask the school to confirm the result.
        </p>
      </section>

      <section className="about-section">
        <h2>Work with us.</h2>
        <p className="lead">
          Help complete the record for your school or district. We send a short
          fact sheet compiled from public sources; someone at the school marks
          each fact correct or incorrect and fills in what we could not find. It
          takes about ten minutes.
        </p>
        <a className="about-cta" href="mailto:boxuan.shan@gmail.com">
          Get in touch
        </a>
        <p className="muted">
          <b>Privacy.</b> We collect only public, factual information about
          schools. We never collect, request, or store personal student data.
        </p>
      </section>

      <section className="about-band about-contact">
        <p>
          SchoolData is a nonprofit project fiscally sponsored by Hack Club Bank,
          a 501(c)(3) organization.
        </p>
        <p>Boxuan Shan, Founder &amp; Student Lead</p>
        <p className="about-links">
          <a href="https://github.com/bxshan/SchoolData">GitHub</a>
          <a href="https://huggingface.co/datasets/SchoolData/us-k12-schools">Dataset</a>
          <a href="http://www.opendata.school">opendata.school</a>
          {pageStates().map((s) => (
            <Link key={s} href={statePath(s)}>{stateName(s)} schools</Link>
          ))}
        </p>
      </section>
    </main>
  );
}
