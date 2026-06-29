"use client";

import { useEffect, useState } from "react";
import { supabase, usingSupabase } from "../lib/supabase";

type School = {
  i: string; n: string; s: string; c: string; ci: string;
  a?: string; z?: string; d?: string;
  ph?: string; tf?: number | null; gl?: string; gh?: string; ch?: string; mg?: string;
  lv: string; e: number | null; w: 0 | 1; x: number; y: number;
};

type Info = {
  type: string; established: string; grades: string; enrollment: string;
  address: string; zipcode: string; district: string; website: string; phone: string;
  principal: string; staff: string; ratio: string;
  motto: string; colors: string; mascot: string; team: string;
  conference: string; newspaper: string; yearbook: string;
  lead: string; history: string; academics: string; athletics: string;
  alumni: string; sources: string;
};
type Contact = { name: string; email: string; role: string; org: string; consent: boolean };

// A pasted reference link the contributor wants us to cite.
type SourceLink = { url: string; kind: string; note: string };
// In-form state for "this fact is wrong" (keyed by Info field).
type FlagState = { on: boolean; corrected: string; source: string };
type Flags = Partial<Record<keyof Info, FlagState>>;
// Persisted shape of a single flagged fact.
type FactFlag = { field: string; label: string; current_value: string; corrected_value: string; source_url: string };
type Saved = { school: School; facts: Info | null; sources: SourceLink[]; flags: FactFlag[]; contact?: Contact; at: string };

const ROLES = ["Student", "Alumni", "Teacher / staff", "Parent", "Community member", "Other"];
const LEVEL_WORD: Record<string, string> = { elementary: "elementary", middle: "middle", high: "high", other: "" };
const LEVEL_GRADES: Record<string, string> = { elementary: "K–5", middle: "6–8", high: "9–12", other: "K–12" };
const emptyContact: Contact = { name: "", email: "", role: "Student", org: "", consent: false };

// The verifiable, scalar facts we show read-only and let people flag.
const FACT_FIELDS: { k: keyof Info; label: string }[] = [
  { k: "type", label: "Type" },
  { k: "established", label: "Established" },
  { k: "grades", label: "Grades" },
  { k: "enrollment", label: "Enrollment" },
  { k: "address", label: "Street address" },
  { k: "zipcode", label: "ZIP code" },
  { k: "district", label: "School district" },
  { k: "website", label: "Website" },
  { k: "phone", label: "Phone" },
  { k: "principal", label: "Principal" },
  { k: "staff", label: "Teaching staff" },
  { k: "ratio", label: "Student–teacher ratio" },
  { k: "motto", label: "Motto" },
  { k: "colors", label: "School colors" },
  { k: "mascot", label: "Mascot" },
  { k: "team", label: "Team / nickname" },
  { k: "conference", label: "Athletic conference" },
];
const SOURCE_KINDS = ["School homepage", "News article", "Official school material", "Other"];
const emptySource = (): SourceLink => ({ url: "", kind: SOURCE_KINDS[0], note: "" });
// Accept a bare domain too (e.g. "school.org/about"); the scheme is optional.
const isUrl = (u: string) => /^(https?:\/\/)?([\w-]+\.)+[a-z]{2,}(\/\S*)?$/i.test(u.trim());
// Normalize for storage: add https:// when the contributor omitted the scheme.
const normUrl = (u: string) => { const t = u.trim(); return /^https?:\/\//i.test(t) ? t : `https://${t}`; };

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
  const type = ["Public", s.ch === "Yes" ? "charter" : "", s.mg === "Yes" ? "magnet" : ""].filter(Boolean).join(" ");
  const grades = s.gl && s.gh ? `${s.gl}–${s.gh}` : (LEVEL_GRADES[s.lv] || "");
  const ratio = s.e && s.tf ? `${(s.e / s.tf).toFixed(1)}:1` : "";
  return {
    type, established: "", grades,
    enrollment: s.e != null ? String(s.e) : "",
    address: s.a || "", zipcode: s.z || "", district: s.d || "", website: "", phone: s.ph || "",
    principal: "", staff: s.tf != null ? String(s.tf) : "", ratio,
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
    phone: g("telephone", "phone") || base.phone,
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
  const [flags, setFlags] = useState<Flags>({});
  const [sources, setSources] = useState<SourceLink[]>([emptySource()]);
  const [contact, setContact] = useState<Contact>(emptyContact);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [loading, setLoading] = useState(true);
  const [wikiTitle, setWikiTitle] = useState<string | null>(null);
  const [cloudErr, setCloudErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStep("contribute"); setInfo(null); setContact(emptyContact); setSaved(null);
    setLoading(true); setWikiTitle(null);
    setFlags({}); setSources([emptySource()]);

    const prev = localStorage.getItem("contrib:" + school.i);
    if (prev) {
      try {
        const p = JSON.parse(prev) as Saved;
        setSaved(p); setInfo(p.facts);
        const rf: Flags = {};
        (p.flags || []).forEach((f) => { rf[f.field as keyof Info] = { on: true, corrected: f.corrected_value, source: f.source_url }; });
        setFlags(rf);
        setSources(p.sources?.length ? p.sources : [emptySource()]);
        setStep("done"); setLoading(false); return;
      } catch {}
    }

    if (school.w) {
      fetchWiki(school.n)
        .then((res) => { if (cancelled) return; setWikiTitle(res.title); setInfo(fromWiki(school, res)); })
        .catch(() => { if (!cancelled) setInfo(templateInfo(school)); })
        .finally(() => { if (!cancelled) setLoading(false); });
    } else { setInfo(templateInfo(school)); setLoading(false); }
    return () => { cancelled = true; };
  }, [school.i]); // eslint-disable-line react-hooks/exhaustive-deps

  function setC<K extends keyof Contact>(k: K, v: Contact[K]) { setContact((c) => ({ ...c, [k]: v })); }

  function toggleFlag(k: keyof Info) {
    setFlags((f) => {
      if (f[k]?.on) { const { [k]: _drop, ...rest } = f; return rest; }
      return { ...f, [k]: { on: true, corrected: "", source: "" } };
    });
  }
  function setFlag(k: keyof Info, patch: Partial<FlagState>) {
    setFlags((f) => ({ ...f, [k]: { ...(f[k] ?? { on: true, corrected: "", source: "" }), ...patch } }));
  }
  function setSrc(i: number, patch: Partial<SourceLink>) { setSources((s) => s.map((row, idx) => (idx === i ? { ...row, ...patch } : row))); }
  function addSrc() { setSources((s) => [...s, emptySource()]); }
  function removeSrc(i: number) { setSources((s) => (s.length > 1 ? s.filter((_, idx) => idx !== i) : s)); }

  const filledSources = sources.filter((s) => s.url.trim());
  const activeFlags = (Object.entries(flags) as [keyof Info, FlagState][]).filter(([, v]) => v?.on);
  const sourcesValid = filledSources.every((s) => isUrl(s.url));
  const flagsValid = activeFlags.every(([, v]) => isUrl(v.source)); // source required per flag
  const hasContribution = filledSources.length > 0 || activeFlags.length > 0;
  const canSubmit = hasContribution && sourcesValid && flagsValid;

  async function persist(withContact?: Contact) {
    if (!info) return;
    const cleanSources: SourceLink[] = filledSources.map((s) => ({ url: normUrl(s.url), kind: s.kind, note: s.note.trim() }));
    const cleanFlags: FactFlag[] = activeFlags.map(([k, v]) => ({
      field: k, label: FACT_FIELDS.find((f) => f.k === k)?.label ?? k,
      current_value: String(info[k] ?? ""), corrected_value: v.corrected.trim(), source_url: normUrl(v.source),
    }));
    const rec: Saved = { school, facts: info, sources: cleanSources, flags: cleanFlags, contact: withContact, at: new Date().toLocaleDateString() };
    // local cache for offline resume
    localStorage.setItem("contrib:" + school.i, JSON.stringify(rec));
    // cloud (only if Supabase is configured)
    if (supabase) {
      const { error } = await supabase.from("contributions").insert({
        nces_id: school.i, school_name: school.n, school_state: school.s,
        school_city: school.ci, school_lat: school.y, school_lon: school.x,
        has_wikipedia: !!school.w, info,
        source_links: cleanSources, fact_flags: cleanFlags,
        contact_name: withContact?.name ?? null,
        contact_email: withContact?.email?.trim().toLowerCase() ?? null,
        contact_role: withContact?.role ?? null,
        contact_org: withContact?.org ?? null,
      });
      if (error) {
        console.error("Supabase insert failed:", error);
        setCloudErr(error.message || "insert failed");
      } else {
        setCloudErr(null);
        console.log("Saved to Supabase ✓");
      }
    } else {
      console.warn("Supabase NOT configured (env vars missing) — saved to localStorage only");
      setCloudErr("not-configured");
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
        <span className="ed-pending" title="Where submissions are saved">
          {usingSupabase ? "☁ Supabase" : "💾 Local only"}
        </span>
        {step !== "done" && <span className="ed-pending">· Step {step === "contribute" ? "1" : "2"} of 2</span>}
      </div>
      <h2>{school.n}</h2>
      <div className="ed-sub">
        {where} · NCES {school.i}
        {wikiTitle && <> · <a href={`https://en.wikipedia.org/wiki/${encodeURIComponent(wikiTitle)}`} target="_blank" rel="noreferrer">source ↗</a></>}
      </div>

      {loading || !info ? (
        <div className="ed-loading">{school.w ? "Loading what we have…" : "Preparing…"}</div>
      ) : step === "contribute" ? (
        <>
          <p className="ed-intro">
            Don&apos;t rewrite the article — help us <b>verify</b> it. Add links we can
            cite, and flag anything below that looks wrong. Every correction needs a source.
          </p>

          <div className="ed-group">What we have <span className="opt">tick anything wrong</span></div>
          <div className="ed-facts">
            {FACT_FIELDS.map(({ k, label }) => {
              const val = String(info[k] ?? "").trim();
              const fl = flags[k];
              return (
                <div className={`fact-row${fl?.on ? " flagged" : ""}`} key={k}>
                  <label className="fact-head">
                    <input type="checkbox" checked={!!fl?.on} onChange={() => toggleFlag(k)} />
                    <span className="fact-label">{label}</span>
                    <span className="fact-val">{val || <em>unknown</em>}</span>
                  </label>
                  {fl?.on && (
                    <div className="fact-fix">
                      <L k="Correct value">
                        <input value={fl.corrected} onChange={(e) => setFlag(k, { corrected: e.target.value })}
                          placeholder={val ? "what it should be (optional)" : "the right value (optional)"} />
                      </L>
                      <L k="Source — required">
                        <input value={fl.source} onChange={(e) => setFlag(k, { source: e.target.value })}
                          className={fl.source && !isUrl(fl.source) ? "bad" : ""} placeholder="https://…" />
                      </L>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="ed-group">Add sources <span className="req">links we can cite</span></div>
          <p className="ed-hint">School homepage, local news coverage, or the school&apos;s own materials. These become the article&apos;s citations.</p>
          <div className="ed-sources">
            {sources.map((s, i) => (
              <div className="src-row" key={i}>
                <div className="src-line">
                  <select value={s.kind} onChange={(e) => setSrc(i, { kind: e.target.value })}>
                    {SOURCE_KINDS.map((x) => <option key={x}>{x}</option>)}
                  </select>
                  <input value={s.url} onChange={(e) => setSrc(i, { url: e.target.value })}
                    className={s.url && !isUrl(s.url) ? "bad" : ""} placeholder="https://…" />
                  {sources.length > 1 && <button className="src-del" onClick={() => removeSrc(i)} title="Remove">×</button>}
                </div>
                <input className="src-note" value={s.note} onChange={(e) => setSrc(i, { note: e.target.value })}
                  placeholder="What does this support? (optional)" />
              </div>
            ))}
            <button className="ghost src-add" onClick={addSrc}>+ Add another source</button>
          </div>

          <button className="cta" disabled={!canSubmit} onClick={() => setStep("contact")}>Submit contribution →</button>
          {!hasContribution
            ? <p className="ed-hint">Add at least one source or flag a fact to continue.</p>
            : !canSubmit && <p className="ed-hint">Every flagged fact and source link needs a valid https:// link.</p>}
        </>
      ) : step === "contact" ? (
        <>
          <div className="vol-thanks">✓ Contribution recorded for this school.</div>
          <p className="ed-intro">
            Optionally leave your contact info to receive <b>volunteer hours</b> for
            this contribution. You can also skip — your input above is saved either way.
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
          <p>
            Your {summarize(saved)} for <b>{school.n}</b> {saved?.at ? `was saved on ${saved.at}` : "was saved"}.
          </p>
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

function summarize(s: Saved | null): string {
  const nS = s?.sources?.length ?? 0;
  const nF = s?.flags?.length ?? 0;
  const parts: string[] = [];
  if (nS) parts.push(`${nS} source${nS === 1 ? "" : "s"}`);
  if (nF) parts.push(`${nF} correction${nF === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" and ") : "contribution";
}

function L({ k, children }: { k: string; children: React.ReactNode }) {
  return (<label className="ed-field"><span>{k}</span>{children}</label>);
}
