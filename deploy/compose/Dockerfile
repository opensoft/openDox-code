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

# Dependency metadata first, so a source-only change does not reinstall the
# dependency tree.
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[runtime]"

# The ordered SQL travels with the image: `opendox-runtime migrate` reads
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
