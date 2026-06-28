-- SchoolData — contributions table
-- Run this in the Supabase dashboard → SQL Editor → New query → Run.

create table if not exists public.contributions (
  id            uuid primary key default gen_random_uuid(),
  nces_id       text not null,
  school_name   text,
  school_state  text,
  school_city   text,
  school_lat    double precision,
  school_lon    double precision,
  has_wikipedia boolean default false,
  info          jsonb,                 -- the contributed school facts
  contact_name  text,
  contact_email text,                  -- stored lowercase for lookup
  contact_role  text,
  contact_org   text,
  created_at    timestamptz default now()
);

create index if not exists contributions_email_idx on public.contributions (contact_email);
create index if not exists contributions_nces_idx  on public.contributions (nces_id);

-- Row Level Security.
alter table public.contributions enable row level security;

-- DEMO policies: anyone (anon key) may submit a contribution and look one up by
-- email. This is fine for a prototype but means contributions are world-readable.
-- For production, switch to Supabase Auth (magic link) and replace the SELECT
-- policy with:  using (auth.jwt() ->> 'email' = contact_email)
create policy "anon can insert" on public.contributions
  for insert to anon with check (true);

create policy "anon can select" on public.contributions
  for select to anon using (true);
