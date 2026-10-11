import type { Metadata } from "next";
import Link from "next/link";
import stateCoverage from "../../public/data/state_coverage.json";
import { pageStates, stateName, statePath } from "../../lib/schools";

export const metadata: Metadata = {
  title: "About — SchoolData",
  description:
    "SchoolData is a student-led open data project making every US K-12 school visible to AI.",
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
        <h1>Make every school visible.</h1>
        <p>
          SchoolData is a student-led open data project. We’re building verified,
          structured data for every K–12 school in the US, so AI and search can
          know about all of them, not just the famous ones.
        </p>
      </section>

      <section className="about-band">
        <h2>The data desert.</h2>
        <p className="lead">
          AI tools like ChatGPT and Gemini learn much of what they know from
          Wikipedia and the public web. A school with no presence there is
          invisible to them.
        </p>
        <div className="about-stats">
          <div><b>{fmt(total)}</b><span>K–12 schools in federal records</span></div>
          <div><b className="green">{pct.toFixed(1)}%</b><span>have an English Wikipedia page</span></div>
          <div><b className="red">{fmt(missing)}</b><span>have none at all</span></div>
        </div>
        <p className="muted">
          The gap falls hardest on under-resourced and rural schools, the
          communities that would benefit most from being seen.
        </p>
      </section>

      <section className="about-section">
        <h2>Work with us.</h2>
        <p className="lead">
          Help complete the record for your school or district. Reply to confirm
          interest, and name a student or staff member who can spend a short
          time filling in publicly available facts. We handle the outreach and
          the data; the time asked of your contact is minimal.
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
