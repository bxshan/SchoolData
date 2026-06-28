"use client";

import { useState } from "react";
import { supabase, usingSupabase } from "../lib/supabase";

type School = {
  i: string; n: string; s: string; c: string; ci: string;
  a?: string; z?: string; d?: string;
  lv: string; e: number | null; w: 0 | 1; x: number; y: number;
};
type Contact = { name: string; email: string; role: string; org: string; consent: boolean };
type Saved = { school: School; info: any; contact?: Contact; at: string };

// local fallback (demo without Supabase)
function lookupLocal(email: string): Saved[] {
  const e = email.trim().toLowerCase();
  const out: Saved[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k || !k.startsWith("contrib:")) continue;
    try {
      const rec = JSON.parse(localStorage.getItem(k) as string) as Saved;
      if (rec?.contact?.email?.toLowerCase() === e) out.push(rec);
    } catch {}
  }
  return out;
}

// map a Supabase row back into the UI's Saved shape
function rowToSaved(r: any): Saved {
  return {
    school: {
      i: r.nces_id, n: r.school_name, s: r.school_state, ci: r.school_city,
      x: r.school_lon, y: r.school_lat, w: r.has_wikipedia ? 1 : 0,
      lv: "", e: null, c: "",
    },
    info: r.info,
    contact: r.contact_email
      ? { name: r.contact_name, email: r.contact_email, role: r.contact_role, org: r.contact_org, consent: true }
      : undefined,
    at: (r.created_at || "").slice(0, 10),
  };
}

async function lookupCloud(email: string): Promise<Saved[]> {
  const { data, error } = await supabase!
    .from("contributions")
    .select("*")
    .eq("contact_email", email.trim().toLowerCase())
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data || []).map(rowToSaved);
}

export default function MyContributions({
  onClose,
  onOpenSchool,
}: {
  onClose: () => void;
  onOpenSchool: (s: School) => void;
}) {
  const [email, setEmail] = useState("");
  const [results, setResults] = useState<Saved[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!/\S+@\S+\.\S+/.test(email)) return;
    setLoading(true);
    try {
      setResults(usingSupabase ? await lookupCloud(email) : lookupLocal(email));
    } catch {
      setResults(lookupLocal(email));
    } finally {
      setLoading(false);
    }
  }

  const withHours = results?.filter((r) => r.contact).length ?? 0;

  return (
    <aside className="editor account">
      <button className="close" onClick={onClose}>×</button>
      <h2>My contributions</h2>
      <div className="ed-sub">Look up everything you&apos;ve submitted, by email.</div>

      <label className="ed-field">
        <span>Your email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="jane@example.com"
        />
      </label>
      <button className="cta" disabled={!/\S+@\S+\.\S+/.test(email) || loading} onClick={run}>
        {loading ? "Looking up…" : "Look up my contributions"}
      </button>

      {results && (
        <>
          <div className="acct-summary">
            <b>{results.length}</b> contribution{results.length === 1 ? "" : "s"}
            {withHours > 0 && (
              <> · eligible for <b>{withHours * 3}–{withHours * 5}</b> volunteer hours</>
            )}
          </div>

          {results.length === 0 ? (
            <p className="note">
              No contributions found for this email in this browser. (This demo only
              sees what was submitted here; the production version looks them up from
              the server.)
            </p>
          ) : (
            <div className="acct-list">
              {results.map((r) => (
                <button key={r.school.i} className="acct-row" onClick={() => onOpenSchool(r.school)}>
                  <span className={`sdot ${r.school.w ? "g" : "r"}`} />
                  <span className="acct-main">
                    <span className="acct-name">{r.school.n}</span>
                    <span className="acct-meta">
                      {[r.school.ci, r.school.s].filter(Boolean).join(", ")} · {r.at}
                      {r.contact ? " · ⏱ hours pending" : " · no contact left"}
                    </span>
                  </span>
                  <span className="acct-go">›</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      <p className="note">
        Drafts and contributions are stored in this browser for the prototype. In
        production this screen queries Supabase by email, so you can see your work
        and approved volunteer hours from any device.
      </p>
    </aside>
  );
}
