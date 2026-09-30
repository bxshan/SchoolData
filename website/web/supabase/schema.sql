-- SchoolData — contributions table
-- Run this in the Supabase dashboard → SQL Editor → New query → Run.
-- Safe to re-run: every statement is idempotent.
--
-- Access model
--   anonymous visitors  may INSERT a contribution, and read only the total
--                       count (contribution_count()) — never the rows, which
--                       hold contributors' names and emails
--   signed-in users     (Supabase Auth email link) may SELECT their own rows:
--                       contact_email = the email they verified
--
-- Also required in the dashboard: Authentication → Providers → Email enabled,
-- and Authentication → URL Configuration → the site URL (and localhost for
-- development) in "Redirect URLs", so the sign-in link returns to the map.

create table if not exists public.contributions (
  id            uuid primary key default gen_random_uuid(),
  nces_id       text not null,
  school_name   text,
  school_state  text,
  school_city   text,
  school_lat    double precision,
  school_lon    double precision,
  has_wikipedia boolean default false,
  info          jsonb,                 -- snapshot of the facts we showed the contributor
  source_links  jsonb,                 -- [{url, kind, note}] references we can cite
  fact_flags    jsonb,                 -- [{field, label, current_value, corrected_value, source_url}]
  contact_name  text,
  contact_email text,                  -- stored lowercase for lookup
  contact_role  text,
  contact_org   text,
  created_at    timestamptz default now()
);

-- For tables created before these columns existed (create-if-not-exists won't add them):
alter table public.contributions add column if not exists source_links jsonb;
alter table public.contributions add column if not exists fact_flags   jsonb;

create index if not exists contributions_email_idx on public.contributions (contact_email);
create index if not exists contributions_nces_idx  on public.contributions (nces_id);

-- Row Level Security.
alter table public.contributions enable row level security;

-- Remove the prototype's world-readable policy (it exposed every contributor's
-- name and email to anyone holding the public anon key).
drop policy if exists "anon can select" on public.contributions;

drop policy if exists "anon can insert" on public.contributions;
create policy "anon can insert" on public.contributions
  for insert to anon, authenticated with check (true);

drop policy if exists "owner can select" on public.contributions;
create policy "owner can select" on public.contributions
  for select to authenticated
  using (contact_email = lower(auth.jwt() ->> 'email'));

-- The public counter on the map: a total, nothing else.
create or replace function public.contribution_count()
returns bigint
language sql
stable
security definer
set search_path = public
as $$ select count(*) from public.contributions $$;

revoke all on function public.contribution_count() from public;
grant execute on function public.contribution_count() to anon, authenticated;
