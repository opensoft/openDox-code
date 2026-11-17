# The runtime image: build, scan and push to the QA registry

`.github/workflows/image.yml` builds the openDox runtime image
(`deploy/compose/Dockerfile`) at a commit of this repository, scans it, and
pushes it to the Azure Container Registry that the `acr-qa` environment names.
It reports the pushed image's digest, which is what a deployment pins. Brett
Heap approved a pipeline for the QA registry on 2026-11-17 ("lets setup so that
we can have a pipeline that can deploy to it" ... "go ahead with the
pipeline").

It cannot push anything until an operator has done the one-time setup below:
an Azure identity, its federated credential, one role assignment, the `acr-qa`
environment and four variables. Until then a dispatch builds and scans, and
the build job stops at the environment check, naming what is missing.

## What a run does

Two jobs. The second waits for the first and for an approval.

**build** (no Azure access, a read-only `GITHUB_TOKEN`):

1. Refuses any target but `qa`.
2. Resolves the `revision` input to a commit and requires it to be on this
   repository's `main`.
3. Requires the `acr-qa` environment to name a required reviewer and to limit
   the refs that may deploy to it.
4. Checks out that commit and builds the Dockerfile for `linux/amd64`, with
   `SOURCE_REVISION` set to the full commit (the image's
   `org.opencontainers.image.revision` label), tagged
   `opendox-runtime:<tag>`. `<tag>` is the tag you named, or the commit's first
   12 characters.
5. Records the image ID and the sha256 of its `docker save` archive, checks the
   revision label and the platform, and uploads the archive (artifact `image`,
   kept 7 days).
6. Downloads Trivy at a pinned version, checks its sha256, and scans the
   archive for vulnerabilities and secrets. It also writes a CycloneDX SBOM.
   Both go up as the artifact `scan`, and a table goes to the job summary.

**push** (in the `acr-qa` environment, after an approval):

1. Requires the four variables, each in its shape.
2. Re-checks the environment's rules, and that this run's deployment to it
   was approved: `release.yml`'s own script.
3. Loads the archive only at the recorded sha256, and only if it loads as the
   recorded image ID.
4. Signs in to Azure by OIDC (`azure/login`). There is no stored password.
5. `az acr login`, `docker push`, then pulls the image back by the digest the
   push reported. The pulled image must be the recorded image ID.
6. Writes the digest to the job summary, a notice, the job output `digest`
   and the artifact `image-release` (`image-release.json`).

`image-release.json` holds:

```json
{
  "image": "opendox-runtime:v0.1.0",
  "digest": "sha256:<64 hex>",
  "source_revision": "<the full commit>",
  "ref": "v0.1.0",
  "target": "qa"
}
```

`image` is the name inside the registry. No output or artifact names the
registry's host, so the full pull reference is
`<ACR_NAME>.azurecr.io/opendox-runtime@<digest>`.

## How to run it

From the repository's **Actions** tab: choose **image**, then **Run workflow**.
Leave **Use workflow from** on `main`. Set **revision** to a tag (for example
`v0.1.0`) or a full 40-character commit, and leave **target** on `qa`. Or from
a shell:

```sh
gh workflow run image.yml --repo opensoft/openDox-code --ref main \
  -f revision=v0.1.0 -f target=qa
```

When the build job finishes, the run waits for a reviewer of `acr-qa`. Approve
the deployment on the run's page. The digest is then in the run's summary,
and in its `image-release` artifact:

```sh
gh run download <run-id> --repo opensoft/openDox-code --name image-release
```

### Which commits QA accepts, and why

QA builds any commit on this repository's `main`: `main` itself or any commit
behind it. It does **not** require the commit the openDox root pins in
`contracts/code-pin.yaml`. QA exists to test a fix before the root pin moves,
and requiring the pin would make QA test only what is already released.

A tag must name a commit on `main`, and its name must also be a valid image
tag (letters, digits, `_`, `.` and `-`, at most 128 characters, not starting
with `.` or `-`). A branch name is not accepted: name the commit.

Run the workflow from `main`. The `revision` input says what is built; the
**Use workflow from** branch says which copy of `image.yml` runs. `acr-qa`
accepts deployments from `main` alone, so a run from another branch builds and
scans but cannot push.

### Prod is not built yet

Prod will be added to this workflow as a **promotion**, never a rebuild. It
will import a digest QA already holds into the prod registry (`az acr import`
by digest) in its own job and environment (`acr-prod`). Two rules will be
stricter than QA's:

- the commit must be the one opensoft/openDox `main` pins, by `release.yml`'s
  own pin script;
- the scan gate fails on CRITICAL and HIGH findings, where QA's only reports.

The `target` step marks where this goes.

## The scan

For QA the scan reports and refuses nothing. Brett Heap ruled on 2026-11-17
that "the scan findings are acceptable for qa". That ruling covers QA only. The
gate is a parameter (the `target` step's `scan-fail-on` output, empty for QA),
and the prod path will set it to failing.

At `v0.1.0` the scan, run on 2026-11-17 with this workflow's own steps, found 1
CRITICAL (certifi 2026.7.22 from the dependency lock, fixed in 2026.10.18) and
119 HIGH findings, of which 1 has a fix (zlib1g).

## One-time setup by an operator

Every value in angle brackets is a placeholder. None of these identifiers
belongs in this repository: it is public, so they live in Azure and in the
`acr-qa` environment's variables. Run the `az` commands as someone who may
create a managed identity in `<IDENTITY_RESOURCE_GROUP>` and assign roles on the
registry (`Owner` or `Role Based Access Control Administrator` on it).

### 1. The OIDC subject the federated credential must match

This repository uses GitHub's **immutable** subject format, so the subject
carries the owner's and the repository's numeric IDs. It is **not**
`repo:opensoft/openDox-code:environment:acr-qa`. A credential with that
name-based subject would never match, and the sign-in would fail with
`AADSTS70021` or `AADSTS700213` ("No matching federated identity record
found"). Read the prefix from GitHub:

```sh
prefix="$(gh api repos/opensoft/openDox-code/actions/oidc/customization/sub --jq .sub_claim_prefix)"
subject="$prefix:environment:acr-qa"
echo "$subject"   # repo:opensoft@<owner-id>/openDox-code@<repository-id>:environment:acr-qa
```

If the API answers `"use_immutable_subject": false` and no `sub_claim_prefix`,
the subject is the name-based one instead.

### 2. The identity and its federated credential

A user-assigned managed identity, with no secret of any kind. An app
registration works too, with `az ad app federated-credential create`.

```sh
az identity create \
  --name <IDENTITY_NAME> \
  --resource-group <IDENTITY_RESOURCE_GROUP> \
  --location <LOCATION>

az identity federated-credential create \
  --name github-opendox-code-acr-qa \
  --identity-name <IDENTITY_NAME> \
  --resource-group <IDENTITY_RESOURCE_GROUP> \
  --issuer https://token.actions.githubusercontent.com \
  --subject "$subject" \
  --audiences api://AzureADTokenExchange
```

### 3. One role, on the one registry

First check the registry's role assignment permissions mode:

```sh
az acr show --name <REGISTRY_NAME> --resource-group <REGISTRY_RESOURCE_GROUP> \
  --query roleAssignmentMode --output tsv
```

In **RBAC Registry Permissions** mode, assign `AcrPush`, scoped to the
registry's resource ID:

```sh
registry_id="$(az acr show --name <REGISTRY_NAME> --resource-group <REGISTRY_RESOURCE_GROUP> --query id --output tsv)"
principal_id="$(az identity show --name <IDENTITY_NAME> --resource-group <IDENTITY_RESOURCE_GROUP> --query principalId --output tsv)"

az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPush \
  --scope "$registry_id"
```

In **RBAC Registry + ABAC Repository Permissions** mode (`rbac-abac`), the
registry does not honour `AcrPush`. Assign `Container Registry Repository
Writer` instead, scoped to the one repository by a condition. The condition
below follows Microsoft's single-repository example, with the role's two write
actions added. Check it in the portal's condition editor before relying on it.

```sh
condition=$(cat <<'EOF' | tr -d '\n'
(
 (
  !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/read'})
  AND
  !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/read'})
  AND
  !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/write'})
  AND
  !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/write'})
 )
 OR
 (
  @Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEqualsIgnoreCase 'opendox-runtime'
 )
)
EOF
)
az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "Container Registry Repository Writer" \
  --scope "$registry_id" \
  --description "openDox-code image.yml pushes opendox-runtime" \
  --condition "$condition" \
  --condition-version "2.0"
```

Assign nothing else. In particular, do not assign `Container Registry
Contributor and Data Access Configuration Administrator`, even though
Microsoft lists it as the role for `az acr login`. It can delete the registry.
The workflow does not need it: it runs `az acr login --name` with no resource
group. Without control-plane read, the CLI's lookup of the registry finds
nothing, so it falls back to `<name>.azurecr.io` and exchanges the Entra token
for a registry token on the data plane (traced in the Azure CLI's
`acr/_docker_utils.py`, `_get_credentials`). `AcrPush` is exactly
`registries/pull/read` and `registries/push/write`.

**Why not `az acr build`.** It runs the build on ACR Tasks. That needs
`Container Registry Tasks Contributor`, a registry-wide control-plane role
that can create, run and delete any task on the registry, plus a read of the
registry for the CLI's lookup. Building on the runner and pushing with
`docker` needs only the push role above.

### 4. The `acr-qa` environment

Create it with a required reviewer and a deployment limit of the branch `main`
alone. This mirrors the `pypi` environment, which limits to the tag `v*` and
allows self-review so that its owner can approve his own dispatch.

```sh
reviewer_id="$(gh api users/<REVIEWER_LOGIN> --jq .id)"

gh api --method PUT repos/opensoft/openDox-code/environments/acr-qa --input - <<EOF
{
  "prevent_self_review": false,
  "reviewers": [{"type": "User", "id": $reviewer_id}],
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}
}
EOF

gh api --method POST repos/opensoft/openDox-code/environments/acr-qa/deployment-branch-policies \
  -f name=main -f type=branch
```

### 5. The four variables, on the environment

Environment variables reach only the jobs that run in `acr-qa`. A later
`acr-prod` will carry the same names with prod's values.

```sh
client_id="$(az identity show --name <IDENTITY_NAME> --resource-group <IDENTITY_RESOURCE_GROUP> --query clientId --output tsv)"
tenant_id="$(az identity show --name <IDENTITY_NAME> --resource-group <IDENTITY_RESOURCE_GROUP> --query tenantId --output tsv)"
subscription_id="$(az account show --query id --output tsv)"   # the subscription that holds the registry

gh variable set AZURE_CLIENT_ID       --env acr-qa --repo opensoft/openDox-code --body "$client_id"
gh variable set AZURE_TENANT_ID       --env acr-qa --repo opensoft/openDox-code --body "$tenant_id"
gh variable set AZURE_SUBSCRIPTION_ID --env acr-qa --repo opensoft/openDox-code --body "$subscription_id"
gh variable set ACR_NAME              --env acr-qa --repo opensoft/openDox-code --body "<REGISTRY_NAME>"
```

`ACR_NAME` is the registry's name, not its login server: no `.azurecr.io`.

### 6. Check it

```sh
gh api repos/opensoft/openDox-code/environments/acr-qa \
  --jq '{rules: [.protection_rules[].type], policy: .deployment_branch_policy}'
gh api repos/opensoft/openDox-code/environments/acr-qa/deployment-branch-policies \
  --jq '.branch_policies[] | {name, type}'
gh variable list --env acr-qa --repo opensoft/openDox-code
az identity federated-credential list --identity-name <IDENTITY_NAME> \
  --resource-group <IDENTITY_RESOURCE_GROUP> --query '[].{subject: subject, audiences: audiences}'
```

Then dispatch one run (see "How to run it") and approve it.

## When the first push fails

- **`AADSTS70021` / `AADSTS700213`**: the federated credential's subject is
  not the one the token carries. Redo step 1, and compare.
- **`No subscriptions found`** at sign-in: the identity sees no subscription.
  A role assignment on a resource inside the subscription normally makes it
  visible. If it does not, the workflow needs `allow-no-subscriptions: true`
  on `azure/login`. `az acr login` handles a sign-in with no subscription.
- **`unauthorized` / `denied` on `docker push`**: the role assignment has not
  propagated yet (wait a few minutes), or the registry is in ABAC mode and
  holds `AcrPush`, which it ignores (see step 3).
- **The build job stops at the environment check**: `acr-qa` does not exist
  yet, names no reviewer, or has no deployment limit (step 4).

## What the public repository shows

The workflow file names no estate identifier. Variables are not masked, though,
and a public repository's run logs are public. The push job's step headers
therefore show the client, tenant and subscription IDs and the registry name to
anyone who opens a run. They are identifiers, not credentials: knowing them
does not let anyone mint the GitHub token the federated credential accepts.

Microsoft's guide recommends keeping the three IDs as environment secrets
instead, which GitHub masks. Switching means changing `vars.` to `secrets.`
for those three in `image.yml`, and changing the tests that pin `vars.`. That
choice is the owner's.

## Next step: the Opensoft-Tenant digest bump

Not built. The QA overlay
`gitops/azure/opendox/overlays/qa/kustomization.yaml` in `opensoft/Opensoft-Tenant`
does not exist yet. Its design also ties the migration Job's name to the image
digest, so the edit a bump makes cannot be written or tested against anything
real. Until it exists, bump the overlay by hand with the digest this workflow
reports.

The design, for when the overlay lands:

- A third job, `needs: push`, with `if: vars.TENANT_BUMP_CLIENT_ID != ''`
  (a **repository** variable, so a job-level `if` can read it). Until it is
  set, the job is skipped, and GitHub creates no environment for it.
- A GitHub App installed on `opensoft/Opensoft-Tenant` alone, with
  `Contents: write` and `Pull requests: write`.
- The token comes from `actions/create-github-app-token` (pinned by SHA), given:
  - `client-id: ${{ vars.TENANT_BUMP_CLIENT_ID }}` (current releases deprecate
    `app-id` in favour of `client-id`);
  - `private-key: ${{ secrets.TENANT_BUMP_PRIVATE_KEY }}`, an environment
    secret of a separate environment;
  - `owner: opensoft`, `repositories: Opensoft-Tenant`;
  - `permission-contents: write`, `permission-pull-requests: write`.
- The job edits the `opendox-runtime` image's `digest:`, and whatever the
  overlay ties to it. It then opens a pull request in Opensoft-Tenant, whose
  own review and checks gate the merge, and Flux deploys what merges.

## Also not done here

- **Build provenance.** `actions/attest-build-provenance` needs `attestations:
  write`. For a public repository it also writes a permanent entry, naming the
  image, to the public Sigstore transparency log. Both are the owner's call;
  the SBOM is an artifact only.
- **The base image is pinned by tag** (`FROM python:3.12-slim`), not by digest,
  and `deploy/compose/Dockerfile` still says "This image is not built by CI".
  Both belong to `deploy/`, which this change does not touch.
