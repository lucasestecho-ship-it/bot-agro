-- Capataz Campo - migracion convergente e idempotente para Supabase
-- Ejecutar completa en Supabase > SQL Editor antes de desplegar esta version.

alter table public.field_items
add column if not exists session_id text,
add column if not exists photo_label text,
add column if not exists audio_label text,
add column if not exists transcript_status text,
add column if not exists transcript_text text,
add column if not exists transcript_error text,
add column if not exists transcript_model text,
add column if not exists transcript_at timestamptz;

alter table public.field_reports
add column if not exists pdf_storage_path text,
add column if not exists pdf_public_url text;

create index if not exists idx_field_items_session_id
on public.field_items (session_id);

create table if not exists public.clients (
  id text primary key,
  name text not null,
  email text,
  phone text,
  status text not null default 'active',
  followup_days integer,
  last_contact_at timestamptz,
  next_contact_at timestamptz,
  notes text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.clients
add column if not exists name text,
add column if not exists email text,
add column if not exists phone text,
add column if not exists status text default 'active',
add column if not exists followup_days integer,
add column if not exists last_contact_at timestamptz,
add column if not exists next_contact_at timestamptz,
add column if not exists notes text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create unique index if not exists idx_clients_name_lower on public.clients (lower(name));

create table if not exists public.client_events (
  id text primary key,
  client_id text,
  client_name text,
  source text,
  source_text text,
  summary text,
  event_type text,
  agents jsonb not null default '[]'::jsonb,
  economic_review boolean not null default false,
  water_project boolean not null default false,
  field_name text,
  created_at timestamptz not null default now()
);

alter table public.client_events
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists source text,
add column if not exists source_text text,
add column if not exists summary text,
add column if not exists event_type text,
add column if not exists agents jsonb default '[]'::jsonb,
add column if not exists economic_review boolean default false,
add column if not exists water_project boolean default false,
add column if not exists field_name text,
add column if not exists created_at timestamptz default now();

create index if not exists idx_client_events_client_created
on public.client_events (client_id, created_at desc);

create table if not exists public.tasks (
  id text primary key,
  client_id text,
  client_name text,
  event_id text,
  title text not null,
  due_date date,
  priority text not null default 'media',
  agent text not null default 'Cartera',
  status text not null default 'pending',
  notes text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.tasks
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists event_id text,
add column if not exists title text,
add column if not exists due_date date,
add column if not exists priority text default 'media',
add column if not exists agent text default 'Cartera',
add column if not exists status text default 'pending',
add column if not exists notes text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_tasks_status_due_date on public.tasks (status, due_date);
create index if not exists idx_tasks_client on public.tasks (client_id);

create table if not exists public.water_projects (
  id text primary key,
  client_id text,
  client_name text,
  title text not null,
  status text not null default 'active',
  next_action text,
  next_review_date date,
  notes text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.water_projects
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists title text,
add column if not exists status text default 'active',
add column if not exists next_action text,
add column if not exists next_review_date date,
add column if not exists notes text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_water_projects_status_review
on public.water_projects (status, next_review_date);

create table if not exists public.agent_runs (
  id text primary key,
  event_id text not null,
  agent text not null,
  status text not null default 'queued',
  input_summary text,
  output jsonb not null default '{}'::jsonb,
  error text default '',
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.agent_runs
add column if not exists event_id text,
add column if not exists agent text,
add column if not exists status text default 'queued',
add column if not exists input_summary text,
add column if not exists output jsonb default '{}'::jsonb,
add column if not exists error text default '',
add column if not exists started_at timestamptz,
add column if not exists finished_at timestamptz,
add column if not exists created_at timestamptz default now();

create index if not exists idx_agent_runs_event_status
on public.agent_runs (event_id, status, created_at desc);

create table if not exists public.decisions (
  id text primary key,
  event_id text not null,
  client_id text,
  client_name text,
  topic text,
  agents jsonb not null default '[]'::jsonb,
  summary text,
  technical_basis text,
  economic_summary text,
  recommendation text,
  risks jsonb not null default '[]'::jsonb,
  missing_data jsonb not null default '[]'::jsonb,
  next_actions jsonb not null default '[]'::jsonb,
  confidence text not null default 'media',
  status text not null default 'pending_review',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.decisions
add column if not exists event_id text,
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists topic text,
add column if not exists agents jsonb default '[]'::jsonb,
add column if not exists summary text,
add column if not exists technical_basis text,
add column if not exists economic_summary text,
add column if not exists recommendation text,
add column if not exists risks jsonb default '[]'::jsonb,
add column if not exists missing_data jsonb default '[]'::jsonb,
add column if not exists next_actions jsonb default '[]'::jsonb,
add column if not exists confidence text default 'media',
add column if not exists status text default 'pending_review',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create unique index if not exists idx_decisions_event on public.decisions (event_id);
create index if not exists idx_decisions_status_created
on public.decisions (status, created_at desc);

create table if not exists public.push_subscriptions (
  id text primary key,
  endpoint text not null,
  subscription jsonb not null,
  active boolean not null default true,
  last_success_at timestamptz,
  last_error text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.push_subscriptions
add column if not exists endpoint text,
add column if not exists subscription jsonb default '{}'::jsonb,
add column if not exists active boolean default true,
add column if not exists last_success_at timestamptz,
add column if not exists last_error text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_push_subscriptions_active
on public.push_subscriptions (active, created_at desc);

create table if not exists public.email_drafts (
  id text primary key,
  event_id text,
  client_id text,
  client_name text,
  to_email text,
  subject text not null,
  body_text text not null,
  status text not null default 'prepared',
  gmail_draft_id text,
  gmail_message_id text,
  error text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.email_drafts
add column if not exists event_id text,
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists to_email text,
add column if not exists subject text,
add column if not exists body_text text,
add column if not exists status text default 'prepared',
add column if not exists gmail_draft_id text,
add column if not exists gmail_message_id text,
add column if not exists error text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_email_drafts_status_created
on public.email_drafts (status, created_at desc);

create table if not exists public.client_facts (
  id text primary key,
  client_id text,
  client_name text,
  category text,
  variable text,
  value_number double precision,
  value_text text,
  unit text,
  fact_date date,
  event_id text,
  source_quote text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists client_facts_client_name_idx on public.client_facts (client_name);
create index if not exists client_facts_category_idx on public.client_facts (category);

create table if not exists public.intake_assets (
  id text primary key,
  event_id text,
  client_id text,
  client_name text,
  source text not null default 'telegram',
  asset_type text not null,
  file_name text not null,
  content_type text,
  transcript_text text,
  storage_status text,
  storage_provider text,
  storage_path text,
  storage_public_url text,
  storage_error text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.intake_assets
add column if not exists event_id text,
add column if not exists client_id text,
add column if not exists client_name text,
add column if not exists source text default 'telegram',
add column if not exists asset_type text,
add column if not exists file_name text,
add column if not exists content_type text,
add column if not exists transcript_text text,
add column if not exists storage_status text,
add column if not exists storage_provider text,
add column if not exists storage_path text,
add column if not exists storage_public_url text,
add column if not exists storage_error text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_intake_assets_event_created
on public.intake_assets (event_id, created_at desc);

create table if not exists public.archive_objects (
  id text primary key,
  source_table text not null,
  source_id text not null,
  object_role text not null,
  client_name text,
  session_id text,
  object_path text not null,
  relative_path text not null,
  file_name text not null,
  content_type text,
  status text not null default 'pending',
  sha256 text,
  size_bytes bigint,
  archive_machine text,
  downloaded_at timestamptz,
  storage_deleted_at timestamptz,
  error text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.archive_objects
add column if not exists source_table text,
add column if not exists source_id text,
add column if not exists object_role text,
add column if not exists client_name text,
add column if not exists session_id text,
add column if not exists object_path text,
add column if not exists relative_path text,
add column if not exists file_name text,
add column if not exists content_type text,
add column if not exists status text default 'pending',
add column if not exists sha256 text,
add column if not exists size_bytes bigint,
add column if not exists archive_machine text,
add column if not exists downloaded_at timestamptz,
add column if not exists storage_deleted_at timestamptz,
add column if not exists error text default '',
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create unique index if not exists idx_archive_objects_source_path
on public.archive_objects (source_table, source_id, object_role, object_path);

create index if not exists idx_archive_objects_status_created
on public.archive_objects (status, created_at asc);

-- Una confirmacion se guarda completa o no se guarda nada.
create or replace function public.confirm_capataz_intake(payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  if payload is null or jsonb_typeof(payload->'event') <> 'object' then
    raise exception 'payload.event es obligatorio';
  end if;

  if jsonb_typeof(payload->'client') = 'object'
     and coalesce(payload->'client'->>'id', '') <> '' then
    insert into public.clients
    select * from jsonb_populate_record(null::public.clients, payload->'client')
    on conflict (id) do update set
      name = excluded.name,
      email = coalesce(excluded.email, clients.email),
      phone = coalesce(excluded.phone, clients.phone),
      status = excluded.status,
      followup_days = excluded.followup_days,
      last_contact_at = excluded.last_contact_at,
      next_contact_at = excluded.next_contact_at,
      notes = excluded.notes,
      updated_at = excluded.updated_at;
  end if;

  insert into public.client_events
  select * from jsonb_populate_record(null::public.client_events, payload->'event')
  on conflict (id) do update set
    client_id = excluded.client_id,
    client_name = excluded.client_name,
    source = excluded.source,
    source_text = excluded.source_text,
    summary = excluded.summary,
    event_type = excluded.event_type,
    agents = excluded.agents,
    economic_review = excluded.economic_review,
    water_project = excluded.water_project,
    field_name = excluded.field_name;

  insert into public.tasks
  select * from jsonb_populate_recordset(
    null::public.tasks,
    coalesce(payload->'tasks', '[]'::jsonb)
  )
  on conflict (id) do update set
    client_id = excluded.client_id,
    client_name = excluded.client_name,
    event_id = excluded.event_id,
    title = excluded.title,
    due_date = excluded.due_date,
    priority = excluded.priority,
    agent = excluded.agent,
    status = excluded.status,
    notes = excluded.notes,
    updated_at = excluded.updated_at;

  insert into public.water_projects
  select * from jsonb_populate_recordset(
    null::public.water_projects,
    coalesce(payload->'water_projects', '[]'::jsonb)
  )
  on conflict (id) do update set
    client_id = excluded.client_id,
    client_name = excluded.client_name,
    title = excluded.title,
    status = excluded.status,
    next_action = excluded.next_action,
    next_review_date = excluded.next_review_date,
    notes = excluded.notes,
    updated_at = excluded.updated_at;

  return jsonb_build_object(
    'ok', true,
    'event_id', payload->'event'->>'id',
    'tasks_count', jsonb_array_length(coalesce(payload->'tasks', '[]'::jsonb))
  );
end;
$$;

-- Aprobar una decision y crear sus tareas tambien es una sola transaccion.
create or replace function public.approve_capataz_decision(payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  selected_status text;
begin
  select status into selected_status
  from public.decisions
  where id = payload->>'decision_id'
  for update;

  if selected_status is null then
    raise exception 'decision no encontrada';
  end if;

  if selected_status <> 'approved' then
    insert into public.tasks
    select * from jsonb_populate_recordset(
      null::public.tasks,
      coalesce(payload->'tasks', '[]'::jsonb)
    )
    on conflict (id) do update set
      title = excluded.title,
      due_date = excluded.due_date,
      priority = excluded.priority,
      agent = excluded.agent,
      status = excluded.status,
      notes = excluded.notes,
      updated_at = excluded.updated_at;

    if jsonb_typeof(payload->'executor_run') = 'object' then
      insert into public.agent_runs
      select * from jsonb_populate_record(null::public.agent_runs, payload->'executor_run')
      on conflict (id) do update set
        status = excluded.status,
        input_summary = excluded.input_summary,
        output = excluded.output,
        error = excluded.error,
        started_at = excluded.started_at,
        finished_at = excluded.finished_at;
    end if;

    update public.decisions
    set status = 'approved',
        updated_at = coalesce((payload->>'approved_at')::timestamptz, now())
    where id = payload->>'decision_id';
  end if;

  return jsonb_build_object(
    'ok', true,
    'decision_id', payload->>'decision_id',
    'status', 'approved'
  );
end;
$$;

revoke all on function public.confirm_capataz_intake(jsonb) from public;
revoke all on function public.approve_capataz_decision(jsonb) from public;
grant execute on function public.confirm_capataz_intake(jsonb) to service_role;
grant execute on function public.approve_capataz_decision(jsonb) to service_role;

-- La PWA no recibe la service-role: las escrituras pasan por Render.
alter table public.clients enable row level security;
alter table public.client_events enable row level security;
alter table public.tasks enable row level security;
alter table public.water_projects enable row level security;
alter table public.agent_runs enable row level security;
alter table public.decisions enable row level security;
alter table public.push_subscriptions enable row level security;
alter table public.email_drafts enable row level security;
alter table public.intake_assets enable row level security;
alter table public.archive_objects enable row level security;

insert into public.clients (id, name, status)
values
  ('client-riendas-sueltas', 'Riendas Sueltas', 'active'),
  ('client-la-susana', 'La Susana', 'active'),
  ('client-la-nueva-trinidad', 'La Nueva Trinidad', 'active'),
  ('client-medalla-milagrosa', 'Medalla Milagrosa', 'active'),
  ('client-manuel-vilas', 'Manuel Vilas', 'active'),
  ('client-policarpo', 'Policarpo', 'active'),
  ('client-nuevo-cliente-en-villaguay', 'Nuevo cliente en Villaguay', 'active'),
  ('client-agropecuaria-don-cacho', 'Agropecuaria Don Cacho', 'active'),
  ('client-dona-elena', 'Doña Elena', 'active'),
  ('client-yuqueri-chico', 'Yuquerí Chico', 'active')
on conflict (id) do update
set name = excluded.name,
    status = excluded.status,
    updated_at = now();

-- Diagnostico: este resultado debe ser cero para nuevas cargas.
select count(*) as items_sin_recorrida
from public.field_items
where session_id is null or btrim(session_id) = '';
