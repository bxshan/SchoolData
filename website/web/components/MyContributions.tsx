"use client";

import { useEffect, useState } from "react";
import { supabase, usingSupabase } from "../lib/supabase";
import type { School } from "../lib/types";

type Contact = { name: string; email: string; role: string; org: string; consent: boolean };
type Saved = { school: School; contact?: Contact; at: string };

const isEmail = (e: string) => /\S+@\S+\.\S+/.test(e);

// Local fallback (demo without Supabase): this browser's own submissions.
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

// Map a Supabase row back into the UI's Saved shape.
function rowToSaved(r: any): Saved {
  return {
    school: {
      i: r.nces_id, n: r.school_name, s: r.school_state, ci: r.school_city,
      x: r.school_lon, y: r.school_lat, w: r.has_wikipedia ? 1 : 0,
      lv: "", e: null, c: "",
    },
    contact: r.contact_email
      ? { name: r.contact_name, email: r.contact_email, role: r.contact_role, org: r.contact_org, consent: true }
      : undefined,
    at: (r.created_at || "").slice(0, 10),
  };
}

// Signed-in lookup. Row-level security returns only rows whose contact_email is
// the signed-in user's verified email, so nobody can list someone else's.
async function lookupCloud(): Promise<Saved[]> {
  const { data, error } = await supabase!
    .from("contributions")
    .select("nces_id, school_name, school_state, school_city, school_lat, school_lon, has_wikipedia, contact_name, contact_email, contact_role, contact_org, created_at")
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
  const [signedInAs, setSignedInAs] = useState<string | null>(null);
  const [linkSent, setLinkSent] = useState(false);
  const [results, setResults] = useState<Saved[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Track the Supabase session (set when the user returns from the email link).
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSignedInAs(data.session?.user.email ?? null));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      setSignedInAs(session?.user.email ?? null));
    return () => sub.subscription.unsubscribe();
  }, []);

  // Once signed in, load that user's contributions.
  useEffect(() => {
    if (!signedInAs) return;
    setLoading(true); setErr(null);
    lookupCloud()
      .then(setResults)
      .catch((e) => setErr(e.message || "lookup failed"))
      .finally(() => setLoading(false));
  }, [signedInAs]);

  async function sendLink() {
    if (!isEmail(email) || !supabase) return;
    setLoading(true); setErr(null);
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim().toLowerCase(),
      options: { emailRedirectTo: window.location.origin },
    });
    setLoading(false);
    if (error) setErr(error.message);
    else setLinkSent(true);
  }

  function lookupHere() {
    if (isEmail(email)) setResults(lookupLocal(email));
  }

  const withHours = results?.filter((r) => r.contact).length ?? 0;

  return (
    <aside className="editor account">
      <button className="close" onClick={onClose}>×</button>
      <h2>My contributions</h2>

      {usingSupabase && signedInAs ? (
        <div className="ed-sub">
          Signed in as <b>{signedInAs}</b> ·{" "}
          <button className="ed-link-btn" onClick={() => { supabase!.auth.signOut(); setResults(null); }}>
            sign out
          </button>
        </div>
      ) : (
        <>
          <div className="ed-sub">
            {usingSupabase
              ? "We'll email you a sign-in link, so only you can see your contributions."
              : "Look up what you've submitted from this browser, by email."}
          </div>
          <label className="ed-field">
            <span>Your email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setLinkSent(false); }}
              onKeyDown={(e) => e.key === "Enter" && (usingSupabase ? sendLink() : lookupHere())}
              placeholder="jane@example.com"
            />
          </label>
          {usingSupabase ? (
            <button className="cta" disabled={!isEmail(email) || loading || linkSent} onClick={sendLink}>
              {loading ? "Sending…" : linkSent ? "Check your inbox ✓" : "Email me a sign-in link"}
            </button>
          ) : (
            <button className="cta" disabled={!isEmail(email)} onClick={lookupHere}>
              Look up my contributions
            </button>
          )}
          {linkSent && <p className="ed-hint">Open the link in the email on this device to see your contributions.</p>}
        </>
      )}

      {err && <p className="ed-hint">Couldn&apos;t load: {err}</p>}
      {loading && signedInAs && <p className="ed-hint">Loading…</p>}

      {results && (
        <>
          <div className="acct-summary">
            <b>{results.length}</b> contribution{results.length === 1 ? "" : "s"}
            {withHours > 0 && (
              <> · eligible for <b>{withHours * 3}–{withHours * 5}</b> volunteer hours</>
            )}
          </div>

          {results.length === 0 ? (
            <p className="note">No contributions found for this email.</p>
          ) : (
            <div className="acct-list">
              {results.map((r, idx) => (
                <button key={`${r.school.i}-${r.at}-${idx}`} className="acct-row" onClick={() => onOpenSchool(r.school)}>
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

      {!usingSupabase && (
        <p className="note">
          Demo mode: contributions are stored in this browser only. With Supabase
          configured, you sign in by email link and see your work from any device.
        </p>
      )}
    </aside>
  );
}
