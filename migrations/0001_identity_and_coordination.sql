-- 0001 — the CANONICAL openDox operational schema: identity and coordination,
-- and nothing else.
--
-- RULING Q1 (opensoft/openxFactory#656 comment 5542694957, Brett Heap,
-- 2026-09-04T15:24Z), verbatim on the boundary this file draws:
--
--   "the database owns identity and coordination; git owns governed artifacts.
--    Users, memberships, projects, the project-to-repository mapping, sessions
--    and unsaved drafts live in the openDox database. Specs, changes, ideation
--    documents and contracts stay in git, read from repositories and written
--    back only through the apply lane. ... the database is disposable relative
--    to the corpus."
--
-- So the table list below IS the ruling's own list, and it is CLOSED:
-- `users`, `memberships`, `projects`, `project_repositories`, `sessions`,
-- `drafts`. `tests_runtime/test_schema_shape.py` reads this file and refuses a
-- seventh table, exactly as `corpus_adapter.OPERATIONS` refuses a seventh
-- operation — a table nobody meant is how "the database owns identity and
-- coordination" stops being true without anybody deciding it should.
--
-- THIS FILE IS PINNED AND IMMUTABLE. `opendox.runtime.migrations`
-- declares `CANONICAL_MIGRATION_SHA256`, the runner refuses to apply a 0001
-- whose bytes hash to anything else (fail closed, before any mutation), and a
-- test hashes the file against that constant. Changing the schema is therefore
-- an ADDITIVE `0002_…`/`0003_…` file, never an edit here — the shape
-- `xFactory-Hermes-Install` uses for the same reason (its
-- `migrations/COMPATIBILITY.md`: 0001 is applied verbatim and gated by a
-- fail-closed SHA-256 check; 0002+ are install-owned additive extensions).
--
-- THE ONE CONTENT-BEARING COLUMN IS `drafts.body`, AND IT IS RULED IN. Q1 puts
-- "unsaved drafts" in the database by name: a draft is precisely the text that
-- has NOT entered the corpus yet, so it has nowhere else to live and its
-- presence here is what makes "written back only through the apply lane" a
-- boundary rather than a data-loss policy. Everything that HAS entered the
-- corpus is addressed by `drafts.document_key` + `drafts.basis_revision` —
-- an address and a revision, never bytes. The schema-shape test asserts that
-- `drafts.body` is the only such column in the whole file.
--
-- NO CREDENTIAL COLUMN ANYWHERE, and that is a boundary too. Authentication
-- delegates to the Keycloak broker (RULING Q2, comment 5542792997); this
-- schema stores the broker's `(issuer, subject)` pair and never a password, a
-- token, a refresh token or a client secret. `tests_runtime/` asserts it over
-- the file's own text.
--
-- IDENTIFIERS ARE `text`, NOT `uuid`, AND ORDERING IS BY PRIMARY KEY. The
-- Hermes install's `persistence/database.py` records the reason the estate
-- already holds: keyset pagination ordered by a text primary key is "a stable
-- total order independent of the wall clock (this host's clock can step
-- backwards under load, so ordering must never depend on insertion
-- wall-time)". Application-generated ids keep that property and keep this
-- schema free of a server-side id extension.

-- ---------------------------------------------------------------------------
-- users — the one genuinely new object (design § D5)
--
-- "an account is a durable row, authentication delegates to the Keycloak
--  broker, and authorization stops being a property of the request's origin"
--
-- `(issuer, subject)` is the broker's identity for this principal and is the
-- natural key: `subject` alone is unique only WITHIN an issuer, and a runtime
-- that treated it as globally unique would merge two people the day a second
-- realm is brokered. `id` stays a separate surrogate so every foreign key
-- below is one column and a re-brokered principal keeps its memberships.
-- ---------------------------------------------------------------------------
create table users (
  id            text primary key,
  issuer        text not null,
  subject       text not null,
  email         text,
  display_name  text,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  constraint users_issuer_subject_key unique (issuer, subject)
);

-- ---------------------------------------------------------------------------
-- projects — the coordination half of the origin complaint
--
-- Design § D5: Q1 answers "no good place to store my projects" with its
-- COORDINATION half — projects, members and the project-to-repository map live
-- in a database every tenant install has — "while the specs still land in a
-- repository".
--
-- `slug` is the human address and is unique across the install; `title` is the
-- display name and is not. No `content`, no `body`, no document of any kind:
-- a project is a NAME plus the map row below.
-- ---------------------------------------------------------------------------
create table projects (
  id          text primary key,
  slug        text not null,
  title       text not null,
  created_by  text not null references users (id),
  created_at  timestamptz not null default now(),
  constraint projects_slug_key unique (slug)
);

-- ---------------------------------------------------------------------------
-- memberships — a user's standing in one project
--
-- RULING Q1 names "memberships" and names no container other than the project,
-- so a membership here joins a USER to a PROJECT and this schema invents no
-- organization or tenant table on top of it. Inventing one would be a
-- coordination object no ruling asked for, and the ruling's list is what this
-- file is held to.
--
-- The role vocabulary is a CHECK constraint rather than a lookup table: three
-- values that change only by a migration are a closed set, and a lookup table
-- would advertise a configurability the runtime does not have.
-- ---------------------------------------------------------------------------
create table memberships (
  id          text primary key,
  user_id     text not null references users (id) on delete cascade,
  project_id  text not null references projects (id) on delete cascade,
  role        text not null,
  created_at  timestamptz not null default now(),
  constraint memberships_user_project_key unique (user_id, project_id),
  constraint memberships_role_check check (role in ('owner', 'member', 'reader'))
);

-- ---------------------------------------------------------------------------
-- project_repositories — THE PROJECT-TO-REPOSITORY MAP, by name in RULING Q1
--
-- One row per project (`unique (project_id)`): RULING C3 (comment 5544381563)
-- gives a standalone project "a plain local git repository per project", and a
-- second row would make "the project's repository" ambiguous for every read.
--
-- `adapter` names WHICH corpus adapter serves this project and `location` is
-- OPAQUE to this schema — the adapter interprets it, exactly as
-- `corpus_adapter.CorpusRef.location` is "opaque here; the implementation
-- interprets it". That is what keeps the local-git case one adapter
-- implementation rather than a mode: a governed factory's project differs from
-- a student's by these two strings and by nothing else in this schema.
--
-- `remote_url` is nullable because RULING C3 says so in terms — "a remote can
-- be attached later" — and attaching one is an UPDATE of this column, not a
-- migration of anything: "moving a student or lab-assistant project into a
-- governed factory is a push, not a migration".
-- ---------------------------------------------------------------------------
create table project_repositories (
  id          text primary key,
  project_id  text not null references projects (id) on delete cascade,
  adapter     text not null,
  location    text not null,
  remote_url  text,
  created_at  timestamptz not null default now(),
  constraint project_repositories_project_key unique (project_id)
);

-- ---------------------------------------------------------------------------
-- sessions — coordination state, and disposable by design
--
-- `project_id` is nullable: a session exists from sign-in, before a project is
-- chosen. `ended_at` null means open. Losing this table loses "where I was",
-- which is exactly the class of loss Q1 calls disposable.
-- ---------------------------------------------------------------------------
create table sessions (
  id            text primary key,
  user_id       text not null references users (id) on delete cascade,
  project_id    text references projects (id) on delete cascade,
  started_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  ended_at      timestamptz
);

-- ---------------------------------------------------------------------------
-- drafts — UNSAVED work, the one place bytes live (RULING Q1, by name)
--
-- `document_key` is where this draft WOULD be written back — a
-- `corpus_adapter.DocumentId.key`, which that interface declares OPAQUE: "a
-- consumer may compare it, sort it and hand it back, and may not parse it".
-- `basis_revision` is the revision the author was looking at, which is what
-- `write_back` needs "in order to refuse a stale one".
--
-- A draft is deleted when it is written back. Nothing in this table is a
-- governed artifact and nothing reads it as one.
-- ---------------------------------------------------------------------------
create table drafts (
  id              text primary key,
  session_id      text not null references sessions (id) on delete cascade,
  project_id      text not null references projects (id) on delete cascade,
  document_key    text not null,
  body            text not null,
  basis_revision  text,
  updated_at      timestamptz not null default now(),
  constraint drafts_session_document_key unique (session_id, document_key)
);

-- ---------------------------------------------------------------------------
-- indexes — the foreign-key columns every list query filters on. Postgres
-- indexes a primary key and a unique constraint and nothing else, so each
-- `references` column that is not already the left-most column of a unique
-- constraint gets one here.
-- ---------------------------------------------------------------------------
create index memberships_project_id_idx on memberships (project_id);
create index projects_created_by_idx on projects (created_by);
create index sessions_user_id_idx on sessions (user_id);
create index sessions_project_id_idx on sessions (project_id);
create index drafts_project_id_idx on drafts (project_id);
