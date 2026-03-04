-- Conversation backup schema for Supabase (Postgres)
--
-- Creates:
--   public.chats
--   public.chat_messages
-- With RLS so each user can only access their own chats/messages.
--
-- Apply in Supabase SQL editor (or your migration runner).

begin;

-- Ensure gen_random_uuid() is available (Supabase usually has this already).
create extension if not exists pgcrypto;

create table if not exists public.chats (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists chats_user_updated_idx on public.chats (user_id, updated_at desc);

create table if not exists public.chat_messages (
  id bigint generated always as identity primary key,
  chat_id text not null references public.chats(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('system','user','assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists chat_messages_chat_created_idx on public.chat_messages (chat_id, created_at asc);

-- Keep chats.updated_at in sync.
create or replace function public._touch_chat_updated_at()
returns trigger
language plpgsql
as $$
begin
  update public.chats set updated_at = now() where id = new.chat_id;
  return new;
end;
$$;

drop trigger if exists trg_touch_chat_updated_at on public.chat_messages;
create trigger trg_touch_chat_updated_at
after insert on public.chat_messages
for each row execute function public._touch_chat_updated_at();

-- RLS
alter table public.chats enable row level security;
alter table public.chat_messages enable row level security;

-- Chats policies
drop policy if exists "Chats: select own" on public.chats;
create policy "Chats: select own" on public.chats
for select using (auth.uid() = user_id);

drop policy if exists "Chats: insert own" on public.chats;
create policy "Chats: insert own" on public.chats
for insert with check (auth.uid() = user_id);

drop policy if exists "Chats: update own" on public.chats;
create policy "Chats: update own" on public.chats
for update using (auth.uid() = user_id);

drop policy if exists "Chats: delete own" on public.chats;
create policy "Chats: delete own" on public.chats
for delete using (auth.uid() = user_id);

-- Messages policies
drop policy if exists "Chat messages: select own" on public.chat_messages;
create policy "Chat messages: select own" on public.chat_messages
for select using (auth.uid() = user_id);

drop policy if exists "Chat messages: insert own" on public.chat_messages;
create policy "Chat messages: insert own" on public.chat_messages
for insert with check (auth.uid() = user_id);

drop policy if exists "Chat messages: delete own" on public.chat_messages;
create policy "Chat messages: delete own" on public.chat_messages
for delete using (auth.uid() = user_id);

commit;
