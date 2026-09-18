# The openDox runtime — a runbook

`split-opendox-two-layer-product` § 3.5 and § 3.6, at
`opensoft/openxFactory` issue #656.

> **RULING Q2** (comment `5542792997`, Brett Heap, 2026-09-04T15:31Z) — "reuse
> the Hermes install pattern — FastAPI + Postgres, deployed the way
> `xFactory-Hermes-Install` is (live on AKS since 2026-07-19), OIDC through the
> Keycloak broker being adopted in QA".
>
> **RULING Q1** (comment `5542694957`) — "the database owns identity and
> coordination; git owns governed artifacts. Users, memberships, projects, the
> project-to-repository mapping, sessions and unsaved drafts live in the
> openDox database. Specs, changes, ideation documents and contracts stay in
> git, read from repositories and written back only through the apply lane. …
> the database is disposable relative to the corpus."
>
> **RULING C3** (comment `5544381563`) — "standalone openDox creates and
> manages a plain local git repository per project. Documents are always
> git-backed; commits are the write path; a remote can be attached later. …
> moving a student or lab-assistant project into a governed factory is a push,
> not a migration."

## 1. What this runtime is, and what it is not

It is identity and coordination: six tables, six collections, one bearer token
verified against the Keycloak broker.

It is **not** a document store and it is not a second dashboard. It does not
import `opendox.serve` — the stdlib document surface a student runs from a
checkout — and the two are joined only by one database row, the
project-to-repository map. Nothing under `/api/v1` reads or writes a spec, a
change, an ideation document or a contract.

The one place bytes live in the database is `drafts.body`, and RULING Q1 rules
it in by name: a draft is the text that has **not** entered the corpus yet.

## 2. The layout, all at the root of this leg

```
migrations/          0001 pinned canonical, 0002+ additive
deploy/compose/      docker-compose.yaml, Dockerfile, init-runtime-role.sh, .env.example
deploy/kubernetes/   base/ + overlays/dev/
src/opendox/runtime/ config, migrations, identity, db, oidc, app, cli,
                     local_git_adapter, repository_act
tests_runtime/       the hermetic half (required check) and the DB-backed half
```

§ 3.5's own sentence is "**all at the root of `openDox-code`, not of the
assembly root**", and `tests_runtime/test_migration_shape.py` asserts it.

## 3. Configuration

Every setting is an environment variable, and
`deploy/compose/.env.example` is the list.
`src/opendox/runtime/config.py` is the only place their names appear in Python;
`tests_runtime/test_deploy_shape.py` holds the three declarations — the Python,
the compose example, the Kubernetes manifests — to each other.

Required, with no default: `OPENDOX_DATABASE_URL`, `OPENDOX_OIDC_ISSUER`,
`OPENDOX_OIDC_AUDIENCE`. A runtime missing one **refuses to start and names
it** rather than falling back to a local database or an unpinned issuer.

`OPENDOX_MIGRATION_DATABASE_URL` is separate on purpose and
`opendox-runtime runtime migrate` will not borrow the served DSN if it is unset. The
compose package and the Kubernetes base keep the two identities in different
containers; the refusal is what stops a convenience undoing that.

## 4. The lifecycle CLI

```
opendox-runtime runtime init      # local state and a coherent config; no database
opendox-runtime runtime migrate   # apply the ordered SQL (privileged DSN); --plan to report
opendox-runtime runtime serve     # run the API
opendox-runtime runtime status    # report config (redacted), schema pin, ledger, broker
opendox-runtime runtime reset     # drop the coordination schema (see § 7)
```

Every verb prints one redacted JSON object and exits nonzero on a refusal.
No DSN, token or password is ever printed.

The verbs are registered by `opendox.runtime.cli.register`, which is reached
two ways: the `opendox-runtime` console script, and
`opendox.runtime.cli.RuntimeSubcommand`, an object that structurally conforms
to `subcommand_extension.SubcommandExtension`. The module's own header records
why they are not (yet) in `opendox.cli.build_parser`: that file is a CARVED
file whose edits are declared at openxFactory, and it cannot be imported at
this leg until the BUILD arc repairs `opendox.serve`'s `ideation_dashboard`
reach.

## 5. Migrations

`migrations/0001_identity_and_coordination.sql` is **canonical and immutable**.
`opendox.runtime.migrations.CANONICAL_MIGRATION_SHA256` pins its bytes, the
runner verifies the digest **before any mutation** and refuses the whole run on
a mismatch, and `tests_runtime/test_migration_shape.py` hashes the file against
the constant on every `validate`. Changing the schema is an additive `0002_…`,
`0003_…` file. Moving the pin is a two-file act somebody has to mean.

The ledger is `opendox_schema_migrations`. The runner bootstraps it with
`create table if not exists` (it has to exist before migration 0001 can be
recorded); `migrations/0002_migration_state.sql` carries the reviewable copy
and a test asserts the two texts are identical. An already-applied migration
whose file has changed aborts the run — the database and the tree disagreeing
is a fact to resolve, not a difference to skip past.

## 6. Running it

### Locally, with compose

```sh
cp deploy/compose/.env.example deploy/compose/.env    # fill it in; it is gitignored
docker compose --env-file deploy/compose/.env -f deploy/compose/docker-compose.yaml \
  --profile migration run --rm --build migrate
docker compose --env-file deploy/compose/.env -f deploy/compose/docker-compose.yaml up -d
```

`--build` on the FIRST command only, and it is not decoration: `docker compose
run` does not build by policy — it is the one subcommand of the three here that
carries no `--no-build` flag, because there is nothing to suppress — while `up`
and `create` do build a missing image. The default `OPENDOX_IMAGE` is the local
tag `opendox-runtime:local`, which no registry has, so on a clean checkout the
documented first command otherwise fails trying to pull an image that has never
been built (Copilot review of openDox-code#25, round 11). `up -d` needs no flag
for the same reason in reverse: by then the image exists, and it would build one
if it did not.

No service publishes a host port: TLS and ingress terminate at the platform.
Reach it over the compose network or with `docker compose exec`.

**The two blocks below are fenced `bash`, and that is a prerequisite rather
than a label.** They prompt with `read -rs -p`, and neither `-s` nor `-p` is in
POSIX `read` — under `/bin/sh` as dash the prompt is consumed as the variable
name and the block fails before a Secret file holds anything, so a block fenced
`sh` could not do what it documents (Copilot review of openDox-code#25, round
30). Everything else here is POSIX; it is the hidden prompt that needs bash.

### On Kubernetes

```bash
# THE NAMESPACE FIRST. Every command below is `-n opendox`, and on a clean
# cluster that namespace does not exist until the manifest is applied — which
# is the LAST line here, so the three `create secret` calls failed with
# `namespaces "opendox" not found` and the documented install could not
# proceed (Copilot review of openDox-code#25). It is in the base as
# `namespace.yaml` too; applying it first is idempotent.
kubectl apply -f deploy/kubernetes/base/namespace.yaml

# THREE secrets and FOUR keys. The bundled Postgres needs both its own
# superuser password and the least-privileged role's, because the base creates
# that role on first start; a secret with only `password` leaves the pod unable
# to resolve `runtime-password` and the install does not come up.
#
# AND NOT ON A COMMAND LINE. A `--from-literal` argument carrying the value
# puts it in the shell's history file and in `/proc/<pid>/cmdline`, where every other
# process on the host can read it for as long as `kubectl` runs — which is the
# same exposure the managed-database block below already avoids with `read
# -rs`, so these two paths said different things about the same secret (Copilot
# review of openDox-code#25, round 19, suppressed). `--from-file` takes the
# value from a file whose name is the KEY, so the password is never an
# argument.
# A SUBSHELL WITH `set -e`, AND A TRAP IMMEDIATELY INSIDE IT. These files hold
# plaintext passwords and DSNs. The trap alone (round 26) removed them, but the
# block RAN ON after a failed `kubectl create secret`: the remaining creates
# went ahead, the final `rm` succeeded, and a block that had not created the
# credentials it exists to create looked like one that had (Copilot review of
# openDox-code#25, round 29, suppressed). `set -e` is what stops that, and it
# is inside a subshell because `set -e` pasted into an interactive shell closes
# THAT shell on the first failure — including the operator's. The signal traps
# `exit` rather than re-raising for the same reason: `$$` inside a subshell is
# still the parent's pid, so `kill -INT $$` would have signalled the operator's
# shell. The EXIT trap fires on every one of these paths.
(
  set -e
  umask 077
  secrets="$(mktemp -d)"
  trap 'rm -rf "$secrets"' EXIT
  trap 'rm -rf "$secrets"; exit 130' INT
  trap 'rm -rf "$secrets"; exit 143' TERM
  read -rs -p 'postgres superuser password: ' pw && printf %s "$pw" > "$secrets/password"
  read -rs -p 'served role password: '      rpw && printf %s "$rpw" > "$secrets/runtime-password"
  unset pw rpw
  kubectl -n opendox create secret generic opendox-postgres \
      --from-file=password="$secrets/password" \
      --from-file=runtime-password="$secrets/runtime-password"
  # `opendox-db-runtime`'s DSN authenticates as the SERVED role, and that
  # role's NAME is `runtime_pg_role` in the `opendox-runtime-config` ConfigMap.
  # They must be the same role: the migration run narrows the named one's
  # rights on the ledger, so narrowing a role nobody serves as leaves the real
  # served role able to rewrite it. An overlay that changes this DSN's user
  # changes that literal in the same commit.
  # A DSN CARRIES A PASSWORD, so it takes the same route.
  read -rs -p 'served DSN: '    dsn  && printf %s "$dsn"  > "$secrets/runtime-dsn"
  read -rs -p 'migration DSN: ' mdsn && printf %s "$mdsn" > "$secrets/migration-dsn"
  unset dsn mdsn
  kubectl -n opendox create secret generic opendox-db-runtime \
      --from-file=dsn="$secrets/runtime-dsn"
  kubectl -n opendox create secret generic opendox-db-migration \
      --from-file=dsn="$secrets/migration-dsn"
  rm -rf "$secrets"      # the EXIT trap does this too; this is the ordinary path
)
# `$?` ON ITS OWN LINE, AND NOT `) && ok=yes || ok=no`. MEASURED: bash
# SUPPRESSES `set -e` inside a compound command that is an operand of `&&` or
# `||`, and the suppression is inherited by the subshell — so the first form of
# this block ran every remaining `kubectl` after one had failed and reported
# success. Driven with a `kubectl` stub that refuses the first create: with the
# `&&` form all three creates ran and the status was 0; with this form the
# block stops at the first failure, the EXIT trap removes the files, and the
# status is the failure's.
secrets_created=$?

# THE IMAGE, AND THIS REPOSITORY PUBLISHES NONE. Every overlay carries the
# placeholder tag `0.0.0`, which `kustomize build` emits at all THREE runtime
# container sites (the Deployment and the migration Job's two containers), so
# an apply that skips this step reaches `ImagePullBackOff` before the migration
# or the runtime can start — measured against kustomize v5.4.3 (Copilot review
# of openDox-code#25, round 26). Replace it with the digest you reviewed;
# `edit set image` writes `digest:`, which is the one form kustomize resolves
# to immutable bytes:
(cd deploy/kubernetes/overlays/dev && kustomize edit set image \
   ghcr.io/opensoft/opendox-runtime=<your registry>/opendox-runtime@sha256:<the reviewed digest>)

# AND THE BUILD SAYS WHETHER YOU DID. The pattern is the placeholder the base
# declares; `tests_runtime/test_deploy_shape.py` keeps the two the same, and
# refuses a documented apply that does not carry this guard.
if [ "${secrets_created:-1}" -ne 0 ]; then
    echo 'a Secret was not created, so nothing is applied; fix it and re-run' >&2
elif kustomize build deploy/kubernetes/overlays/dev | grep -q 'opendox-runtime:0\.0\.0'; then
    echo 'the image is still the placeholder 0.0.0; this apply would ImagePullBackOff' >&2
else
    kustomize build deploy/kubernetes/overlays/dev | kubectl apply -f -
fi
```

**A managed database instead of the bundled Postgres.** Build the
`managed-database` overlay instead of `dev`, and create only the two DSN
Secrets — not `opendox-postgres`:

**Nothing is applied yet, and that ordering is the point.** Applying this
overlay before the role exists and before `runtime_pg_role` names it makes the
migration Job narrow `opendox_runtime` — the bundled database's role — or fail
because that role does not exist, while the role actually serving keeps the
right to rewrite the ledger (Copilot review of openDox-code#25, round 27). The
apply command for this path is at the end of the prerequisite below.


**Set `runtime_pg_role` in that overlay to the role you provisioned** — the
user in `opendox-db-runtime`'s DSN. The base's value, `opendox_runtime`, is the
role the BUNDLED Postgres creates on first start; a managed database runs no
init script, so the role is whichever one you created. If the two differ the
migration Job narrows `opendox_runtime` — or fails because it does not exist —
while the role actually serving keeps the right to rewrite the ledger (Copilot
review of openDox-code#25, round 24). It is the same name as
`OPENDOX_RUNTIME_PG_ROLE` in the prerequisite below: one name, now in four
places.

That overlay removes `postgres-statefulset.yaml`, `postgres-service.yaml` and
the init-script ConfigMap from the base, and sets `migration_wait_host=`
(empty) so the migration Job's readiness gate exits immediately instead of
waiting four minutes for a Service this cluster does not have. **Pointing the
DSNs at a managed database is not enough on its own**: the base still carries
the bundled Postgres, so an install that only changed the DSNs started a second
database nobody uses and failed on the `opendox-postgres` Secret the
StatefulSet mounts and this path never creates (Copilot review of
openDox-code#25, round 19, suppressed). An overlay is the only place kustomize
can remove a base resource, which is why the instruction ships with one.

**And provision the served role FIRST — this is a prerequisite, not a
suggestion.** The bundled Postgres creates and grants that role on its first
start (`deploy/compose/init-runtime-role.sh`, mounted by the StatefulSet); a
managed database runs no init script, so nothing else will. Without it the
migration owner creates the six tables and the served role has no privilege on
any of them: the Job succeeds, `/readyz` reports a database that answers and an
applied schema, and every API request then fails with `permission denied for
table …` (Copilot review of openDox-code#25, round 10). Run this once, on the
managed database, as an administrator, BEFORE the migration Job.
`OPENDOX_MIGRATION_PG_USER` is the role in `opendox-db-migration`'s DSN, and
`OPENDOX_RUNTIME_PG_ROLE` is both the role in `opendox-db-runtime`'s DSN and
the `runtime_pg_role` value in the ConfigMap — one name, three places, which is
the rule this install already states for that role.

AND THAT ROLE'S NAME MUST BE A PLAIN SQL IDENTIFIER — `[A-Za-z_][A-Za-z0-9_]{0,62}`
— because the migration run narrows it on the ledger with a `revoke`, where SQL
takes a role name as SYNTAX and not as a value:
`config.load_migration_settings` refuses anything else before `migrate`
connects, and `MigrationRunner.protect_ledger` refuses it again for a caller
that did not come through the loader. The block below still quotes every name
with `%I`, and that is not redundant under this rule: `OPENDOX_MIGRATION_PG_USER`
and `OPENDOX_PG_DB` are under no such constraint, and a served role that IS a
plain identifier can still collide with an SQL keyword. The block by itself
accepted a served role this runtime then refuses — measured, a name holding a
space — which is a prerequisite an operator could complete and still not start
(Copilot review of openDox-code#25, round 14).

NOTHING BELOW IS SUBSTITUTED BY HAND. Every name and the password come from
the environment, through psql's own `\getenv`, and every one of them is quoted
by `format` — `%I` for an identifier, `%L` for a literal — so a name or a
password holding a quote is a name or a password rather than a syntax error
(Copilot review of openDox-code#25, rounds 12 and 13). **The password of course
reaches the database**: `create role … password %L` is the statement that sets
it, and an earlier wording here said otherwise, which could mislead an operator
about what this block does (round 29). What it keeps the password out of is the
operator's own shell — it is never an argument, so it is not in `argv`, not in
`/proc/<pid>/cmdline` and not in the history file — and what `%L` keeps out of
the database is a *mistyped placeholder*, which without it would be sent as
SQL rather than as a value. Set the four, then run the block:

```bash
read -rs OPENDOX_RUNTIME_PG_PASSWORD && export OPENDOX_RUNTIME_PG_PASSWORD
export OPENDOX_RUNTIME_PG_ROLE=...      # the user in opendox-db-runtime's DSN
export OPENDOX_MIGRATION_PG_USER=...    # the user in opendox-db-migration's DSN
export OPENDOX_PG_DB=...                # the database both DSNs name
```

```sql
\getenv runtime_role OPENDOX_RUNTIME_PG_ROLE
\getenv migration_owner OPENDOX_MIGRATION_PG_USER
\getenv database OPENDOX_PG_DB
\getenv runtime_password OPENDOX_RUNTIME_PG_PASSWORD
select format('create role %I login password %L', :'runtime_role',
              :'runtime_password')
\gexec
select format('grant connect on database %I to %I', :'database',
              :'runtime_role')
\gexec
select format('grant usage on schema public to %I', :'runtime_role')
\gexec
-- THE COORDINATION TABLES THAT ALREADY EXIST, and only those. A database
-- migrated before this prerequisite ran already holds them, and a `grant … on
-- table` for one that is absent is an error — so the list is a JOIN against
-- the catalogue rather than seven statements, and it emits NOTHING on a fresh
-- database. It used to read `on all tables in schema public`, which on a
-- REUSED database handed the served role another application's data (Copilot
-- review of openDox-code#25, round 30). The names are Q1's six plus the
-- ledger; `tests_runtime/test_deploy_shape.py` derives them from
-- `identity.TABLES` and `migrations.LEDGER_TABLE` so this list cannot drift.
select format('grant select, insert, update, delete on table %I to %I',
              c.relname, :'runtime_role')
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r'
   and c.relname = any (array['drafts', 'memberships',
                              'opendox_schema_migrations',
                              'project_repositories', 'projects', 'sessions',
                              'users'])
\gexec
-- and everything the migration owner creates from here on, so a later
-- migration that adds a table needs no second visit
select format('alter default privileges for role %I in schema public grant '
              'select, insert, update, delete on tables to %I',
              :'migration_owner', :'runtime_role')
\gexec
```

**NOW apply the overlay.** The served role exists, `runtime_pg_role` names it,
and both DSNs point at the managed database, so the migration Job narrows the
role this install will actually serve as:

```sh
# THE IMAGE, AND THIS REPOSITORY PUBLISHES NONE. Every overlay carries the
# placeholder tag `0.0.0`, which `kustomize build` emits at all THREE runtime
# container sites (the Deployment and the migration Job's two containers), so
# an apply that skips this step reaches `ImagePullBackOff` before the migration
# or the runtime can start — measured against kustomize v5.4.3 (Copilot review
# of openDox-code#25, round 26). Replace it with the digest you reviewed;
# `edit set image` writes `digest:`, which is the one form kustomize resolves
# to immutable bytes:
(cd deploy/kubernetes/overlays/managed-database && kustomize edit set image \
   ghcr.io/opensoft/opendox-runtime=<your registry>/opendox-runtime@sha256:<the reviewed digest>)

# AND THE BUILD SAYS WHETHER YOU DID. The pattern is the placeholder the base
# declares; `tests_runtime/test_deploy_shape.py` keeps the two the same, and
# refuses a documented apply that does not carry this guard.
if kustomize build deploy/kubernetes/overlays/managed-database | grep -q 'opendox-runtime:0\.0\.0'; then
    echo 'the image is still the placeholder 0.0.0; this apply would ImagePullBackOff' >&2
else
    kustomize build deploy/kubernetes/overlays/managed-database | kubectl apply -f -
fi
```


The migration run then NARROWS that role on the ledger alone
(`MigrationRunner.protect_ledger`, which is why the role has to exist before
the Job runs and why the Job fails loudly if it does not): the served identity
keeps `select` on `opendox_schema_migrations` for `/readyz` and loses every
write, so it cannot rewrite the runner's own tamper-evident record. That
narrowing is the one privilege difference between the bundled and the managed
path; the four statements above are the rest of what the bundled init script
does, spelled for an operator who has to do it by hand.

**And the run CHECKS this, so a prerequisite that was skipped is a failed
migration and not a failed request.** `MigrationRunner.verify_runtime_access`
is the last act of every run: it asks Postgres — through `has_table_privilege`,
which counts ownership and group membership — whether the configured
`runtime_pg_role` holds `select, insert, update, delete` on every table in the
schema except the ledger, and raises `RuntimeAccessMissingError` naming the
missing `table:privilege` pairs when it does not. Without it the Job succeeded,
`/readyz` reported an applied schema, and the first API request was where the
install found out (Copilot review of openDox-code#25, round 12). The same check
covers the bundled path's own mismatch: `alter default privileges` belongs to
the role that creates the table, so a migration DSN authenticating as somebody
other than `POSTGRES_USER` needs `OPENDOX_MIGRATION_PG_USER` (compose) or the
`migration_pg_user` ConfigMap key (Kubernetes) set to that owner, and the
first-start bootstrap aims the default privileges there.

**Re-running the migration Job.** A Job's pod template is immutable, so a
second `kubectl apply` after the first run does not start a new migration. Ask
for one:

```sh
kubectl -n opendox delete job opendox-migrate --ignore-not-found
# The same guard: a re-run from a fresh clone has the placeholder again.
if kustomize build deploy/kubernetes/overlays/dev | grep -q 'opendox-runtime:0\.0\.0'; then
    echo 'the image is still the placeholder 0.0.0; this apply would ImagePullBackOff' >&2
else
    kustomize build deploy/kubernetes/overlays/dev | kubectl apply -f -
fi
```

The Job carries `ttlSecondsAfterFinished: 3600`, so the delete is usually a
no-op — and "usually" is not a migration guarantee, which is why it is written
here.

This repository commits every Secret's **name and key** and no Secret's value;
`tests_runtime/test_deploy_shape.py` refuses a `kind: Secret` anywhere under
`deploy/kubernetes/`.

The Deployment is one replica with a `Recreate` strategy, and that is a
property of RULING C3 rather than a capacity decision: the pod mounts the
per-project git repositories read-write and git has no cross-writer protocol
over a shared filesystem. Scaling first moves those repositories behind a
remote — which is what C3's "a remote can be attached later" already describes.

## 6a. The repository-creation act (§ 3.6)

`split-opendox-two-layer-product` § 3.6: "**openDox CREATES A REPOSITORY AS A
FIRST-CLASS ACT**, or the origin complaint returns one level down." So it is a
verb, not a side effect of creating a project:

```
POST /api/v1/projects/{id}/repository           # create it
PUT  /api/v1/projects/{id}/repository/remote    # RULING C3: attach one later
POST /api/v1/projects/{id}/repository/push      # the move IS a push
```

```sh
opendox-runtime project create-repository --project-id <id> --actor 'Name <a@b>'
opendox-runtime project attach-remote     --project-id <id> --remote-url <url>
opendox-runtime project push              --project-id <id>
```

**The act is the PAIR**: the map row and the repository, together or not at
all. The row is written first, inside the request's transaction, so a
repository that fails to initialize leaves no row pointing at nothing. The
window a transaction cannot cover — a process killed between `git init` and the
commit — leaves a directory with no row, and the next act **refuses and names
it** rather than adopting a directory nobody can account for.

**The repository is BARE**, at
`<OPENDOX_PROJECT_REPOSITORY_ROOT>/<project id>`, and its first commit is
empty. Both are decisions:

* bare, because the corpus is the HISTORY. `LocalGitCorpus.write_back` builds a
  blob, a tree and a commit with plumbing against a temporary index and moves
  the branch ref — it writes no file, because `corpus_adapter.write_back`'s
  contract is that it "never touches the corpus tree". A checkout beside the
  history would therefore be a second answer to "what does this project
  contain" that the adapter is forbidden to keep up to date. openDox *manages*
  this repository (RULING C3's own verb); a human who wants a checkout clones
  it;
* empty, because a README this act invented would be content the project's
  owner did not write, in the one place the product's promise is that the
  documents are theirs.

**The adapter, for § 3.7.** The conformant implementation is
`opendox.runtime.local_git_adapter.LocalGitCorpus` — that import path is what
`split-opendox-two-layer-product` § 3.7's neutral conformance corpus needs, and
importing it costs the standard library only. It is STRUCTURALLY conformant
with `opendox.corpus_adapter.CorpusAdapter`: six operations, no seventh,
nothing inherited, checked with `isinstance` in the required `validate` job.
`opendox.runtime.repository_act.initialize_repository` builds a corpus to check
without a database.

One thing the adapter deliberately does not do: refuse a stale write.
`write_back`'s declared refusal row is `CORPUS_READ_ONLY` and
`WRITE_PATH_UNREACHABLE` and nothing else, and the closed refusal vocabulary
has no kind for staleness — so `basis_revision` is recorded as a commit trailer
and the branch ref moves by compare-and-swap, which means a writer working from
a superseded revision loses its dispatch rather than overwriting the other one.

## 7. `reset`, and what "disposable" does and does not cover

`opendox-runtime runtime reset --confirm yes-drop-the-coordination-database`
drops the six coordination tables and the ledger. It exists because of RULING
Q1's last sentence — "the database is disposable relative to the corpus"; lose
it and you lose coordination state, not a governed artifact.

**The project repositories are not covered by that sentence.** The coordination
database can be rebuilt from a migration; the repositories under
`OPENDOX_PROJECT_REPOSITORY_ROOT` hold documents and cannot be rebuilt from
anything. `reset` does not touch them, and nor should a cluster teardown that
deletes the `opendox-project-repositories` claim.

## 8. Tests

| suite | where it runs | what it needs |
|---|---|---|
| `test_migration_shape.py` | `validate` (required) | `.[test]` |
| `test_schema_shape.py` | `validate` (required) | `.[test]` |
| `test_runtime_surface.py` | `validate` (required) | `.[test]` |
| `test_runtime_cli.py` | `validate` (required) | `.[test]` |
| `test_deploy_shape.py` | `validate` (required) | `.[test]` |
| `test_local_git_adapter.py` | `validate` (required) | `.[test]` + `git` |
| `test_migrations_apply.py` | `runtime` | `.[runtime,test]` + Postgres |
| `test_oidc_verifier.py` | `runtime` | `.[runtime,test]` |
| `test_api_endpoints.py` | `runtime` | `.[runtime,test]` + Postgres |
| `test_repository_act.py` | `runtime` | `.[runtime,test]` + Postgres + `git` |

The split is the package's import-weight contract
(`src/opendox/runtime/__init__.py`), and `test_runtime_surface.py` measures it
in a fresh interpreter rather than asserting it in prose. Locally:

```sh
docker run -d --name opendox-test-pg -e POSTGRES_USER=opendox \
  -e POSTGRES_PASSWORD=opendox -e POSTGRES_DB=opendox -p 55432:5432 postgres:16
export OPENDOX_TEST_DATABASE_URL='postgresql://opendox:opendox@127.0.0.1:55432/opendox'
python -m pytest -q tests_runtime/
```

Without that variable the DB-backed cases **skip with the reason printed** —
never pass silently, never fail a tree for not running Postgres.

## 8a. The lifecycle, run end to end (2026-09-16, measured)

Not a test: the installed console script, a real Postgres and a real socket.
Every figure below is that run's own output.

```
$ opendox-runtime runtime init
{ "ok": true, "canonical_sha256": "6db4710578b012a3318…", "directories_created": ["/tmp/smoke-projects"],
  "migrations_on_disk": ["0001","0002"], "next": "opendox-runtime runtime migrate" }

$ opendox-runtime runtime migrate
{ "ok": true, "applied": ["0001","0002"], "planned": [] }

$ opendox-runtime runtime status --probe-timeout 5
{ "ok": false, "database": "reachable", "applied_migrations": ["0001","0002"],
  "pending_migrations": [], "migration_drift": [],
  "broker_keys": "unreachable: IdentityUnavailableError" }

$ opendox-runtime runtime serve &          # then, over the socket:
GET /livez             200  {"status":"live"}
GET /readyz            503  {"status":"not-ready","checks":{"database":"ok","schema":"applied",
                                                            "broker_keys":"unavailable: IdentityUnavailableError"}}
GET /docs              404                 # off unless OPENDOX_PUBLISH_OPENAPI
GET /api/v1/projects   401                 # no bearer token

$ opendox-runtime runtime reset --confirm yes-drop-the-coordination-database
{ "ok": true, "dropped": ["drafts","sessions","project_repositories","memberships","projects","users",
                          "opendox_schema_migrations"] }
```

**`status` and `/readyz` are `ok: false` / `not-ready` on purpose here**: there
is no Keycloak broker in that environment, and both surfaces say so by name
rather than reporting healthy. The database half is green in both, the schema
is applied and nothing has drifted — which is the whole of what this act can
prove without a broker, and it proves it rather than asserting it.

## 9. Residue this runbook records rather than resolves

* **A pre-governed scratch space.** Design § D5: "The hybrid where ideas live
  in the database until promoted was REJECTED, so an idea is a governed
  document in git from its first save — consistent, and heavier than a lab
  assistant may want. Whether openDox needs a pre-governed scratch space that
  is NOT 'a draft of a document' is a real residual, it is not one of the open
  questions." `drafts` is the draft of a document and is not that scratch
  space. Unresolved, and deliberately.
* **`validate`'s remaining narrowing** (RULED Q-L5 (b′)). This act lifts none
  of it. `opendox.serve` still cannot import at this leg —
  `tests/test_consumer_reach.py::STILL_REACHING` records the line — and the
  runtime is written so that no part of it depends on that being repaired.
* **The `runtime` job is not a required check.** Making one required is a
  repository setting (`docs/branch-protection.md`), a separate act.
* **Not taken from the Hermes install**, and each for a reason: its three-layer
  Subject/Tenant/Domain topology (openDox is single-layer, so a `layer` claim
  would be a shape without a meaning), its worker-readiness surface, its
  correlated backup job, and its `uv.lock` supply-chain pin (a real act with a
  real owner, recorded rather than invented here).
