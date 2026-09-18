# The runtime image. One stage, no build step: this package is pure Python and
# its only compiled dependency arrives as a binary wheel (`psycopg[binary]`),
# which is why the runtime extra asks for that variant.
FROM python:3.12-slim

ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/opensoft/openDox-code" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="openDox runtime" \
      org.opencontainers.image.description="Identity and coordination (RULING Q1); documents live in repositories"

# `git` is a RUNTIME dependency and not a build one: RULING C3's repository
# creation act runs `git` as a subprocess to create and commit to a project's
# plain local repository. The runtime refuses at the act rather than at start
# if it is absent, but an image that shipped without it would fail the one
# thing § 3.6 exists to do.
RUN apt-get update \
 && apt-get install --no-install-recommends -y git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# THE DEPENDENCY TREE IS REINSTALLED ON ANY SOURCE CHANGE, and this comment
# used to claim the opposite. `pip install ".[runtime]"` below needs the
# package's own source to build it, so `COPY src` has to precede it, and the
# install layer's cache key therefore includes every file under `src/`
# (Copilot review of openDox-code#25 — the comment was the defect, not the
# order). Stated rather than papered over: an image build after a one-line
# source edit re-resolves and reinstalls FastAPI, psycopg and the rest.
#
# Splitting it — install the pinned dependency set first, then `--no-deps .` —
# is the `--require-hashes` LOCKFILE act `pyproject.toml` already names as a
# separate act with a real owner. Without a lockfile the "dependency set" would
# have to be re-derived from `pyproject.toml` inside the build, which is a
# second resolver nobody would maintain. This image is not built by CI, so the
# cost is a developer's minutes and it is recorded here rather than traded for
# an invented pin.
COPY pyproject.toml README.md ./
# The lock travels with the sources it pins, and BEFORE the install that reads
# it: an image built from an unlocked resolve is a supply chain that can change
# without a commit (SonarCloud `docker:S8544`, "using dependencies without
# locking resolved versions is security-sensitive" — advisory on this
# repository, registered on openDox-code#26 and built in the follow-up).
COPY constraints-cpython312-linux.txt ./
COPY src ./src
# `--only-binary :all:` so pip never builds a dependency from an sdist —
# which would run that project's `setup.py` inside the image build. Every
# package in the `runtime` extra publishes wheels for cpython 3.12 on
# linux, `psycopg[binary]` by name, so the flag costs nothing.
RUN python -m pip install --no-cache-dir --only-binary :all: \
      -c constraints-cpython312-linux.txt ".[runtime]"

# The ordered SQL travels with the image: `opendox-runtime runtime migrate` reads
# `migrations/` relative to the working directory, and an image whose migration
# job had to mount the repository would be a migration job that could run
# against SQL the image had never seen.
COPY migrations ./migrations

# A non-root user, and the per-project repository root it owns.
RUN useradd --system --create-home --uid 10001 opendox \
 && mkdir -p /var/lib/opendox/projects \
 && chown -R opendox:opendox /var/lib/opendox
USER opendox

EXPOSE 8080
CMD ["opendox-runtime", "runtime", "serve"]
