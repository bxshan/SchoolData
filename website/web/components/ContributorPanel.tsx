"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type School = {
  i: string; n: string; s: string; c: string; ci: string;
  a?: string; z?: string; d?: string;
  lv: string; e: number | null; w: 0 | 1; x: number; y: number;
};

type Info = {
  type: string; established: string; grades: string; enrollment: string;
  address: string; zipcode: string; district: string; website: string;
  principal: string; staff: string; ratio: string;
  motto: string; colors: string; mascot: string; team: string;
  conference: string; newspaper: string; yearbook: string;
  lead: string; history: string; academics: string; athletics: string;
  alumni: string; sources: string;
};
type Contact = { name: string; email: string; role: string; org: string; consent: boolean };
type Saved = { school: School; info: Info; contact?: Contact; at: string };

const ROLES = ["Student", "Alumni", "Teacher / staff", "Parent", "Community member", "Other"];
const LEVEL_WORD: Record<string, string> = { elementary: "elementary", middle: "middle", high: "high", other: "" };
const LEVEL_GRADES: Record<string, string> = { elementary: "K–5", middle: "6–8", high: "9–12", other: "K–12" };
const emptyContact: Contact = { name: "", email: "", role: "Student", org: "", consent: false };

const WP_API = "https://en.wikipedia.org/w/api.php";

async function fetchWiki(name: string) {
  const sr = await fetch(`${WP_API}?action=query&list=search&srsearch=${encodeURIComponent(name)}&srlimit=1&format=json&origin=*`).then((r) => r.json());
  const title = sr?.query?.search?.[0]?.title;
  if (!title) throw new Error("not found");
  const [pt, ex] = await Promise.all([
    fetch(`${WP_API}?action=parse&page=${encodeURIComponent(title)}&prop=wikitext&format=json&formatversion=2&origin=*`).then((r) => r.json()),
    fetch(`${WP_API}?action=query&prop=extracts&exintro&explaintext&titles=${encodeURIComponent(title)}&format=json&formatversion=2&origin=*`).then((r) => r.json()),
  ]);
  return { title, wikitext: pt?.parse?.wikitext || "", extract: ex?.query?.pages?.[0]?.extract || "" };
}
function clean(s: string) {
  return s.replace(/<ref[^>]*\/>/g, "").replace(/<ref[^>]*>[\s\S]*?<\/ref>/g, "")
    .replace(/\{\{[^{}]*\}\}/g, "").replace(/\[\[(?:[^\]|]*\|)?([^\]]*)\]\]/g, "$1")
    .replace(/'''?/g, "").replace(/\n{3,}/g, "\n\n").trim();
}
function extractSection(wt: string, names: string[]): string {
  for (const name of names) {
    const re = new RegExp(`==+\\s*${name}\\s*==+([\\s\\S]*?)(?=\\n==|$)`, "i");
    const m = wt.match(re);
    if (m && m[1].trim()) return clean(m[1]).slice(0, 1500);
  }
  return "";
}
function parseInfobox(wt: string): Record<string, string> {
  const i = wt.search(/\{\{\s*Infobox school/i);
  if (i < 0) return {};
  let depth = 0, end = -1;
  for (let j = i; j < wt.length - 1; j++) {
    if (wt[j] === "{" && wt[j + 1] === "{") { depth++; j++; }
    else if (wt[j] === "}" && wt[j + 1] === "}") { depth--; j++; if (depth === 0) { end = j + 1; break; } }
  }
  const block = wt.slice(i, end > 0 ? end : undefined);
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/\|\s*([a-zA-Z0-9_ ]+?)\s*=\s*([^\n|]*)/g)) {
    const v = clean(m[2]); if (v) out[m[1].trim().toLowerCase()] = v;
  }
  return out;
}
function templateInfo(s: School): Info {
  const lvl = LEVEL_WORD[s.lv] || "";
  const where = [s.ci, s.s].filter(Boolean).join(", ");
  return {
    type: "Public", established: "", grades: LEVEL_GRADES[s.lv] || "",
    enrollment: s.e != null ? String(s.e) : "",
    address: s.a || "", zipcode: s.z || "", district: s.d || "", website: "",
    principal: "", staff: "", ratio: "",
    motto: "", colors: "", mascot: "", team: "",
    conference: "", newspaper: "", yearbook: "",
    lead: `${s.n} is a public ${lvl ? lvl + " " : ""}school${where ? ` in ${where}` : ""}.`,
    history: "", academics: "", athletics: "", alumni: "", sources: "",
  };
}
function fromWiki(s: School, res: { wikitext: string; extract: string }): Info {
  const ib = parseInfobox(res.wikitext); const base = templateInfo(s);
  const g = (...keys: string[]) => keys.map((k) => ib[k]).find(Boolean) || "";
  return {
    type: g("type") || base.type,
    established: g("established", "founded", "opened"),
    grades: g("grades", "gradespan") || base.grades,
    enrollment: g("enrollment") || base.enrollment,
    address: g("address", "streetaddress", "location") || base.address,
    zipcode: g("zipcode", "postcode", "postalcode") || base.zipcode,
    district: g("district", "schoolboard") || base.district,
    website: g("website", "homepage"),
    principal: g("principal", "head", "headteacher", "headofschool"),
    staff: g("teaching_staff", "staff", "faculty"),
    ratio: g("ratio"),
    motto: g("motto"),
    colors: g("colors", "colours", "color"),
    mascot: g("mascot"),
    team: g("team_name", "athletics_nickname", "nickname"),
    conference: g("athletic_conference", "conference", "athletics"),
    newspaper: g("newspaper"),
    yearbook: g("yearbook"),
    lead: clean(res.extract) || base.lead,
    history: extractSection(res.wikitext, ["History"]),
    academics: extractSection(res.wikitext, ["Academics", "Academic", "Curriculum"]),
    athletics: extractSection(res.wikitext, ["Athletics", "Sports"]),
    alumni: extractSection(res.wikitext, ["Notable alumni", "Notable people", "Alumni", "Notable faculty"]),
    sources: "",
  };
}

export default function ContributorPanel({ school, onClose }: { school: School; onClose: () => void }) {
  const [step, setStep] = useState<"contribute" | "contact" | "done">("contribute");
  const [info, setInfo] = useState<Info | null>(null);
  const [contact, setContact] = useState<Contact>(emptyContact);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [loading, setLoading] = useState(true);
  const [wikiTitle, setWikiTitle] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStep("contribute"); setInfo(null); setContact(emptyContact); setSaved(null);
    setLoading(true); setWikiTitle(null);

    const prev = localStorage.getItem("contrib:" + school.i);
    if (prev) { try { const p = JSON.parse(prev); setSaved(p); setInfo(p.info); setStep("done"); setLoading(false); return; } catch {} }

    if (school.w) {
      fetchWiki(school.n)
        .then((res) => { if (cancelled) return; setWikiTitle(res.title); setInfo(fromWiki(school, res)); })
        .catch(() => { if (!cancelled) setInfo(templateInfo(school)); })
        .finally(() => { if (!cancelled) setLoading(false); });
    } else { setInfo(templateInfo(school)); setLoading(false); }
    return () => { cancelled = true; };
  }, [school.i]); // eslint-disable-line react-hooks/exhaustive-deps

  function setI<K extends keyof Info>(k: K, v: string) { setInfo((f) => (f ? { ...f, [k]: v } : f)); }
  function setC<K extends keyof Contact>(k: K, v: Contact[K]) { setContact((c) => ({ ...c, [k]: v })); }

  async function persist(withContact?: Contact) {
    if (!info) return;
    const rec: Saved = { school, info, contact: withContact, at: new Date().toLocaleDateString() };
    // local cache for offline resume
    localStorage.setItem("contrib:" + school.i, JSON.stringify(rec));
    // cloud (only if Supabase is configured)
    if (supabase) {
      try {
        await supabase.from("contributions").insert({
          nces_id: school.i, school_name: school.n, school_state: school.s,
          school_city: school.ci, school_lat: school.y, school_lon: school.x,
          has_wikipedia: !!school.w, info,
          contact_name: withContact?.name ?? null,
          contact_email: withContact?.email?.trim().toLowerCase() ?? null,
          contact_role: withContact?.role ?? null,
          contact_org: withContact?.org ?? null,
        });
      } catch (e) { /* keep local copy even if the network write fails */ }
    }
    setSaved(rec); setStep("done");
  }
  const contactValid = contact.name.trim() && /\S+@\S+\.\S+/.test(contact.email) && contact.consent;
  const where = [school.ci, school.s].filter(Boolean).join(", ");

  return (
    <aside className="editor">
      <button className="close" onClick={onClose}>×</button>
      <div className="ed-status">
        <span className={`badge ${school.w ? "yes" : "no"}`}>{school.w ? "Has Wikipedia article" : "No article yet"}</span>
        {step !== "done" && <span className="ed-pending">Step {step === "contribute" ? "1" : "2"} of 2</span>}
      </div>
      <h2>{school.n}</h2>
      <div className="ed-sub">
        {where} · NCES {school.i}
        {wikiTitle && <> · <a href={`https://en.wikipedia.org/wiki/${encodeURIComponent(wikiTitle)}`} target="_blank" rel="noreferrer">source ↗</a></>}
      </div>

      {loading || !info ? (
        <div className="ed-loading">{school.w ? "Loading existing article…" : "Preparing…"}</div>
      ) : step === "contribute" ? (
        <>
          <p className="ed-intro">
            {school.w
              ? "Help improve what we know about this school. We pulled the current article — verify and add facts. (No Wikipedia editing here.)"
              : "Share what you know about this school. Anything helps build the public record — sources especially."}
          </p>
          <div className="ed-section-title">Basics <span className="opt">infobox</span></div>
          <div className="ed-grid">
            <L k="Type"><input value={info.type} onChange={(e) => setI("type", e.target.value)} placeholder="Public / Private / Charter" /></L>
            <L k="Established"><input value={info.established} onChange={(e) => setI("established", e.target.value)} placeholder="year" /></L>
            <L k="Grades"><input value={info.grades} onChange={(e) => setI("grades", e.target.value)} /></L>
            <L k="Enrollment"><input value={info.enrollment} onChange={(e) => setI("enrollment", e.target.value)} /></L>
          </div>

          <div className="ed-section-title">Location & contact</div>
          <div className="ed-grid">
            <L k="Street address"><input value={info.address} onChange={(e) => setI("address", e.target.value)} /></L>
            <L k="ZIP code"><input value={info.zipcode} onChange={(e) => setI("zipcode", e.target.value)} /></L>
            <L k="School district"><input value={info.district} onChange={(e) => setI("district", e.target.value)} /></L>
            <L k="Website"><input value={info.website} onChange={(e) => setI("website", e.target.value)} placeholder="https://" /></L>
          </div>

          <div className="ed-section-title">People & size</div>
          <div className="ed-grid">
            <L k="Principal"><input value={info.principal} onChange={(e) => setI("principal", e.target.value)} placeholder="name" /></L>
            <L k="Teaching staff"><input value={info.staff} onChange={(e) => setI("staff", e.target.value)} placeholder="# teachers (FTE)" /></L>
            <L k="Student–teacher ratio"><input value={info.ratio} onChange={(e) => setI("ratio", e.target.value)} placeholder="e.g. 18:1" /></L>
          </div>

          <div className="ed-section-title">Identity & athletics</div>
          <div className="ed-grid">
            <L k="Motto"><input value={info.motto} onChange={(e) => setI("motto", e.target.value)} /></L>
            <L k="School colors"><input value={info.colors} onChange={(e) => setI("colors", e.target.value)} /></L>
            <L k="Mascot"><input value={info.mascot} onChange={(e) => setI("mascot", e.target.value)} /></L>
            <L k="Team / nickname"><input value={info.team} onChange={(e) => setI("team", e.target.value)} /></L>
            <L k="Athletic conference"><input value={info.conference} onChange={(e) => setI("conference", e.target.value)} /></L>
            <L k="Newspaper"><input value={info.newspaper} onChange={(e) => setI("newspaper", e.target.value)} /></L>
            <L k="Yearbook"><input value={info.yearbook} onChange={(e) => setI("yearbook", e.target.value)} /></L>
          </div>

          <div className="ed-group">Article body <span className="opt">what the article text needs</span></div>
          <div className="ed-section-title">Lead / introduction</div>
          <textarea rows={3} value={info.lead} onChange={(e) => setI("lead", e.target.value)} />
          <div className="ed-section-title">History <span className="opt">most common section</span></div>
          <textarea rows={4} value={info.history} onChange={(e) => setI("history", e.target.value)} placeholder="Founding year, milestones, renamings, notable events…" />
          <div className="ed-section-title">Academics</div>
          <textarea rows={3} value={info.academics} onChange={(e) => setI("academics", e.target.value)} placeholder="Programs, AP/IB, curriculum, rankings…" />
          <div className="ed-section-title">Athletics</div>
          <textarea rows={3} value={info.athletics} onChange={(e) => setI("athletics", e.target.value)} placeholder="Teams, conference, state titles, rivalries…" />
          <div className="ed-section-title">Notable alumni</div>
          <textarea rows={3} value={info.alumni} onChange={(e) => setI("alumni", e.target.value)} placeholder="One per line — Name — what they're known for" />

          <div className="ed-group">References <span className="req">required — aim for 3+</span></div>
          <p className="ed-hint">A typical school article cites ~6 sources, mostly news articles and official pages. Paste links (one per line); these become the citations.</p>
          <textarea rows={4} value={info.sources} onChange={(e) => setI("sources", e.target.value)} placeholder={"https://district.org/school-page\nhttps://localnews.com/article-about-the-school\n…"} />
          <button className="cta" onClick={() => setStep("contact")}>Submit contribution →</button>
        </>
      ) : step === "contact" ? (
        <>
          <div className="vol-thanks">✓ Contribution recorded for this school.</div>
          <p className="ed-intro">
            Optionally leave your contact info to receive <b>volunteer hours</b> for
            this contribution. You can also skip — your info above is saved either way.
          </p>
          <div className="ed-section-title">Contact <span className="opt">optional</span></div>
          <L k="Full name"><input value={contact.name} onChange={(e) => setC("name", e.target.value)} placeholder="Jane Doe" /></L>
          <L k="Email"><input type="email" value={contact.email} onChange={(e) => setC("email", e.target.value)} placeholder="jane@example.com" /></L>
          <div className="ed-grid">
            <L k="I am a…"><select value={contact.role} onChange={(e) => setC("role", e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></L>
            <L k="School / org"><input value={contact.org} onChange={(e) => setC("org", e.target.value)} placeholder="for hour credit" /></L>
          </div>
          <label className="vol-consent">
            <input type="checkbox" checked={contact.consent} onChange={(e) => setC("consent", e.target.checked)} />
            <span>I agree to be contacted about volunteer hours.</span>
          </label>
          <div className="vol-actions">
            <button className="ghost" onClick={() => persist(undefined)}>Skip</button>
            <button className="cta" disabled={!contactValid} onClick={() => persist(contact)}>Submit & get hours</button>
          </div>
        </>
      ) : (
        <div className="vol-confirm">
          <div className="vol-check">✓</div>
          <h3>Thanks for contributing!</h3>
          <p>Your information for <b>{school.n}</b> was saved{saved?.at ? ` on ${saved.at}` : ""}.</p>
          {saved?.contact ? (
            <div className="vol-hours">⏱ {saved.contact.name.split(" ")[0]}, you&apos;re eligible for <b>3–5 verified volunteer hours</b> once reviewed. We&apos;ll email <b>{saved.contact.email}</b>.</div>
          ) : (
            <div className="vol-hours">No contact left — add it anytime to claim volunteer hours.</div>
          )}
          <button className="ed-link-btn" onClick={() => setStep("contribute")}>Edit my contribution</button>
        </div>
      )}
    </aside>
  );
}

function L({ k, children }: { k: string; children: React.ReactNode }) {
  return (<label className="ed-field"><span>{k}</span>{children}</label>);
}
