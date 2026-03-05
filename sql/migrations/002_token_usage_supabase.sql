-- Token usage tracking schema for Supabase (Postgres)
--
-- Creates:
--   public.token_usage_daily
--   public.add_token_usage(...) RPC helper
--
-- Apply in Supabase SQL editor (or your migration runner).

begin;

create table if not exists public.token_usage_daily (
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  total_tokens integer not null default 0,
  estimated_tokens integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, day)
);

create index if not exists token_usage_daily_user_day_idx on public.token_usage_daily (user_id, day desc);

create or replace function public._touch_token_usage_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_touch_token_usage_updated_at on public.token_usage_daily;
create trigger trg_touch_token_usage_updated_at
before update on public.token_usage_daily
for each row execute function public._touch_token_usage_updated_at();

-- RLS
alter table public.token_usage_daily enable row level security;

drop policy if exists "Token usage: select own" on public.token_usage_daily;
create policy "Token usage: select own" on public.token_usage_daily
for select using (auth.uid() = user_id);

drop policy if exists "Token usage: insert own" on public.token_usage_daily;
create policy "Token usage: insert own" on public.token_usage_daily
for insert with check (auth.uid() = user_id);

drop policy if exists "Token usage: update own" on public.token_usage_daily;
create policy "Token usage: update own" on public.token_usage_daily
for update using (auth.uid() = user_id);

-- RPC helper to atomically add token counts for the current authenticated user.
create or replace function public.add_token_usage(
  p_day date,
  p_prompt integer,
  p_completion integer,
  p_total integer,
  p_estimated integer
)
returns void
language plpgsql
as $$
declare
  uid uuid;
begin
  uid := auth.uid();
  if uid is null then
    raise exception 'Not authenticated';
  end if;

  insert into public.token_usage_daily(user_id, day, prompt_tokens, completion_tokens, total_tokens, estimated_tokens)
  values (uid, p_day, greatest(p_prompt,0), greatest(p_completion,0), greatest(p_total,0), greatest(p_estimated,0))
  on conflict (user_id, day) do update
    set prompt_tokens = public.token_usage_daily.prompt_tokens + excluded.prompt_tokens,
        completion_tokens = public.token_usage_daily.completion_tokens + excluded.completion_tokens,
        total_tokens = public.token_usage_daily.total_tokens + excluded.total_tokens,
        estimated_tokens = public.token_usage_daily.estimated_tokens + excluded.estimated_tokens;
end;
$$;

grant execute on function public.add_token_usage(date, integer, integer, integer, integer) to authenticated;

commit;
