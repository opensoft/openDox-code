"""The projection mechanism's seams, openDox's own defaults behind them, and
the verbs routed through them: plan 034's T055.

T055 realizes #1144's 5.5 and 4.3 in part. It gives the snapshot registry and
source, the corpus-root predicate, the snapshot writer and the validator lookup
a declared seam each (`opendox.projection_seams`) with an openDox default each
(`opendox.default_registry`, `opendox.default_projection`), which the entry
points register where no host has (R1Q10 (a), in R1Q3 (a)'s pattern). It
routes `cli.py`'s two generations and the registry's regenerate through
`generator_seam.generate()`, chooses a validator by the snapshot's `kind`, and
retires the `consumer_reach` stand-ins those reaches used. Its falsifier is
F4.1's scan, down by these reaches; the PR body quotes that scan. This file
holds the behaviour behind it:

1. NOTHING REGISTERED REFUSES, naming the seam and its call, at each seam.
2. THE REGISTRATION RULES: names are probed, one registration, a host replaces
   the default only until a consumer has read it, the same one again is a
   no-op, and the validator lookup keeps all of that per kind.
3. THE ENTRY POINTS REGISTER THE DEFAULTS, and keep a host registered first.
4. STANDALONE, with no sibling importable, `generate` writes and a server
   builds and answers `/snapshot.json`, `/capabilities` and `/source/`.
5. openDox's own registry and source: containment, keys, the baked entry, the
   refusals of what only a host's registry offers, and the regenerate through
   the registered generator and writer.
6. openDox's own corpus-root predicate, writer and validator stand-in.
7. The generate verbs: the report, the refusals, and validation by kind.
8. `branch_session`'s routed sites and `workbench.validate_manifest`.
9. No proxy over a seam is read at import time.
10. openDox's own RFC 3339 check.

Every case starts with nothing registered at the four seams or the generator
seam, and puts back every registry it found.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import types
from pathlib import Path

import pytest

from opendox import cli
from opendox import corpus_adapter
from opendox import default_generator
from opendox import default_projection
from opendox import default_registry
from opendox import defaults
from opendox import domain_profile
from opendox import generator_seam as gs
from opendox import projection_seams as ps
from opendox import rfc3339
from opendox import serve
from opendox import workbench
from opendox import branch_session as bs
from opendox import consumer_reach
from opendox.boundary import BoundaryViolation, OutputBoundary

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "opendox"
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"
ANCHOR_DATE = "2026-09-27T12:00:00+00:00"
NEUTRAL = gs.NEUTRAL_SNAPSHOT_KIND
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

SINGLE_SEAMS = {"registry": ps.registry, "corpus_root": ps.corpus_root,
                "writer": ps.writer}


# ---------------------------------------------------------------------------
# isolation, stand-ins and fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_registries():
    """Nothing registered at the four seams or the generator seam, the entry
    points' default home corpus registered, and every registry PUT BACK whole,
    records included, so an entry point's default is never handed back as a
    host's."""
    single = {name: (seam._registered, seam._is_default, seam._default_read)
              for name, seam in SINGLE_SEAMS.items()}
    kinds = (dict(ps.validators._registered), set(ps.validators._default_read))
    generator = (gs._registered, gs._is_default, gs._generated_from_default,
                 gs._default_generations_under_way, gs._registration_serial)
    profile = (domain_profile._registered, domain_profile._is_default,
               domain_profile._built_from_default)
    home = corpus_adapter._home_factory
    for seam in SINGLE_SEAMS.values():
        seam.unregister()
    ps.validators.unregister()
    gs.unregister()
    corpus_adapter.register_home(cli._default_home_factory)
    yield
    for name, seam in SINGLE_SEAMS.items():
        seam._registered, seam._is_default, seam._default_read = single[name]
    ps.validators._registered, ps.validators._default_read = kinds
    (gs._registered, gs._is_default, gs._generated_from_default,
     gs._default_generations_under_way, gs._registration_serial) = generator
    (domain_profile._registered, domain_profile._is_default,
     domain_profile._built_from_default) = profile
    corpus_adapter._home_factory = home


def _stub(seam) -> types.SimpleNamespace:
    """A registration carrying exactly the seam's names."""
    members = {name: (lambda *args, **kwargs: None) for name in seam.callables}
    members.update({name: f"<{name}>" for name in seam.values})
    return types.SimpleNamespace(**members)


class _Validator:
    """A stand-in validator that records its calls and answers `result`."""

    def __init__(self, result=None, remedy=None):
        self.calls = []
        self.result = result or ps.ValidationResult(
            True, 0, "stand-in: 0 error(s)", "", "stand-in")
        self.dependency_remedy = remedy

    def validate(self, path, *, strict=False, search_from=()):
        self.calls.append({"path": Path(path), "strict": strict,
                           "search_from": tuple(search_from)})
        return self.result


def _git(root: Path, *args: str) -> str:
    """`git` in `root` as the fixture's own identity at a fixed date, with no
    inherited `GIT_*` variable and no user or system configuration."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": ANCHOR_DATE, "GIT_COMMITTER_DATE": ANCHOR_DATE,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, env=env).stdout.decode()


def _repository(tmp_path: Path, *, copy: Path | None = PLAIN_DOCUMENTS,
                files: dict[str, str] | None = None,
                name: str = "repository") -> Path:
    """A fresh plain git repository, committed."""
    root = tmp_path / name
    if copy is not None:
        shutil.copytree(copy, root)
    else:
        root.mkdir(parents=True)
    for relative, body in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", "fixture")
    return root


def _generate(repo: Path, out: Path, *extra: str) -> int:
    return cli.main(["generate", "--repo-root", str(repo),
                     "--repository", "garden", "--output", str(out), *extra])


def _get(httpd, path: str) -> tuple[int, dict, bytes]:
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        host, port = httpd.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def _served(tmp_path: Path, **kwargs):
    """A real server over a generated snapshot of a real git checkout."""
    repo = _repository(tmp_path)
    out = tmp_path / "run" / "snapshot.json"
    assert _generate(repo, out, "--no-validate") == 0
    (tmp_path / "web").mkdir(exist_ok=True)
    return repo, out, serve.build_server(tmp_path / "web", out, repo, port=0,
                                         **kwargs)


# ---------------------------------------------------------------------------
# 1 — nothing registered refuses, naming the seam and its call (4.2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SINGLE_SEAMS))
def test_each_seam_refuses_when_nothing_is_registered(name) -> None:
    seam = SINGLE_SEAMS[name]
    with pytest.raises(ps.SeamNotRegistered) as caught:
        seam.current()
    message = str(caught.value)
    for expected in (seam.registration_call, f"opendox.projection_seams.{name}",
                     seam.default, "ENTRY POINT", "cli.build_parser()",
                     "cli.main()", "serve.build_server()", "serve.main()",
                     "R1Q10 (a)", "5850003126", "unregister()"):
        assert expected in message, f"the refusal no longer says {expected!r}"


def test_the_validator_lookup_refuses_a_kind_with_no_validator() -> None:
    """Never another kind's validator: a document is read by its own kind."""
    other = _Validator()
    ps.validators.register("some-kind", other)
    with pytest.raises(ps.ValidatorNotRegistered) as caught:
        ps.validators.for_kind("another-kind")
    message = str(caught.value)
    assert "'another-kind'" in message and "some-kind" in message
    assert ps.validators.registration_call in message
    assert isinstance(caught.value, ps.SeamNotRegistered)


def test_a_proxy_resolves_on_each_read_and_never_on_a_dunder() -> None:
    proxy = ps.registry.proxy
    assert "registry" in repr(proxy), "repr must not resolve the seam"
    with pytest.raises(AttributeError):
        proxy.__wrapped__
    first, second = _stub(ps.registry), _stub(ps.registry)
    first.DEFAULT_REF, second.DEFAULT_REF = "first", "second"
    ps.registry.register(first)
    assert proxy.DEFAULT_REF == "first"
    ps.registry.unregister()
    ps.registry.register(second)
    assert proxy.DEFAULT_REF == "second", "the proxy holds nothing across reads"
    ps.registry.unregister()
    with pytest.raises(ps.SeamNotRegistered):
        proxy.DEFAULT_REF


# ---------------------------------------------------------------------------
# 2 — the registration rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SINGLE_SEAMS))
def test_a_registration_missing_a_name_is_refused_naming_it(name) -> None:
    seam = SINGLE_SEAMS[name]
    for missing in (*seam.callables, *seam.values):
        registration = _stub(seam)
        delattr(registration, missing)
        with pytest.raises(TypeError) as caught:
            seam.register(registration)
        assert f"lacks {missing}." in str(caught.value)
        assert not seam.is_registered()


def test_a_callable_name_that_is_not_callable_is_refused() -> None:
    registration = _stub(ps.writer)
    registration.write_snapshot = "not callable"
    with pytest.raises(TypeError, match="lacks write_snapshot"):
        ps.writer.register(registration)


def test_a_registration_that_cannot_hand_a_name_over_is_refused_with_the_cause() -> None:
    class _Lazy:
        def __getattr__(self, name):
            raise RuntimeError(f"cannot load {name}")

    with pytest.raises(TypeError) as caught:
        ps.corpus_root.register(_Lazy())
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert not ps.corpus_root.is_registered()


@pytest.mark.parametrize("name", sorted(SINGLE_SEAMS))
def test_one_registration_and_a_deliberate_swap(name) -> None:
    seam = SINGLE_SEAMS[name]
    host, other = _stub(seam), _stub(seam)
    assert seam.register(host) is host
    assert seam.register(host) is host, "the same registration again is a no-op"
    with pytest.raises(ps.SeamAlreadyRegistered) as caught:
        seam.register(other)
    assert f"opendox.projection_seams.{name}.unregister()" in str(caught.value)
    assert seam.current() is host
    seam.unregister()
    assert seam.register(other) is other


@pytest.mark.parametrize("name", sorted(SINGLE_SEAMS))
def test_a_host_replaces_the_default_only_until_it_is_read(name) -> None:
    seam = SINGLE_SEAMS[name]
    default, host, late = _stub(seam), _stub(seam), _stub(seam)
    assert seam.register_default(default) is default
    assert seam.register_default(_stub(seam)) is default, (
        "register_default never displaces what is registered")
    assert seam.register(host) is host, "nothing read the default, so it yields"
    seam.unregister()
    seam.register_default(default)
    assert seam.current() is default
    with pytest.raises(ps.SeamAlreadyRegistered) as caught:
        seam.register(late)
    message = str(caught.value)
    for expected in ("openDox's own default", "already read", "R1Q3 (ii)",
                     "5817152735", "RN-1 (a)", "unregister()"):
        assert expected in message, f"the refusal no longer says {expected!r}"
    assert seam.current() is default
    assert seam.register_default(_stub(seam)) is default


@pytest.mark.parametrize("name", sorted(SINGLE_SEAMS))
def test_register_default_never_displaces_a_host(name) -> None:
    seam = SINGLE_SEAMS[name]
    host = _stub(seam)
    seam.register(host)
    assert seam.register_default(_stub(seam)) is host
    assert seam.current() is host


def test_a_default_missing_a_name_is_refused_even_over_a_registration() -> None:
    ps.writer.register(_stub(ps.writer))
    with pytest.raises(TypeError, match="lacks write_snapshot"):
        ps.writer.register_default(types.SimpleNamespace())


def test_the_validator_lookup_keeps_the_rules_per_kind() -> None:
    default, host, late = _Validator(), _Validator(), _Validator()
    ps.validators.register_default(NEUTRAL, default)
    assert ps.validators.register_default(NEUTRAL, _Validator()) is default
    assert ps.validators.register(NEUTRAL, host) is host, (
        "nothing read the kind's default, so it yields")
    with pytest.raises(ps.SeamAlreadyRegistered):
        ps.validators.register(NEUTRAL, late)
    ps.validators.unregister(NEUTRAL)
    ps.validators.register_default(NEUTRAL, default)
    ps.validators.register("host-kind", host)
    assert ps.validators.for_kind(NEUTRAL) is default
    with pytest.raises(ps.SeamAlreadyRegistered, match="already read"):
        ps.validators.register(NEUTRAL, late)
    assert ps.validators.register("host-kind", host) is host
    assert ps.validators.kinds() == ("host-kind", NEUTRAL)
    for bad in ("", " padded ", None, 3):
        with pytest.raises(ValueError):
            ps.validators.register(bad, host)
    with pytest.raises(TypeError, match="lacks validate"):
        ps.validators.register("x-kind", types.SimpleNamespace())
    ps.validators.unregister()
    assert ps.validators.kinds() == ()


def test_register_defaults_registers_openDoxs_own_at_each_seam_and_reads_nothing() -> None:
    ps.register_defaults()
    assert ps.registry._registered is default_registry
    assert ps.corpus_root._registered is default_projection.CORPUS_ROOT
    assert ps.writer._registered is default_projection.WRITER
    for kind in default_projection.OWN_KINDS:
        assert ps.validators._registered[kind] == (default_projection.VALIDATORS[kind], True)
    for seam in SINGLE_SEAMS.values():
        host = _stub(seam)
        assert seam.register(host) is host, (
            "registering the defaults read nothing, so a host still replaces them")


def test_openDoxs_own_kinds_are_the_neutral_snapshot_and_the_workbench_manifest() -> None:
    assert default_projection.OWN_KINDS == (NEUTRAL, "ideation-workbench")
    assert default_projection.WORKBENCH_KIND == workbench.KIND


def test_the_default_registry_carries_openDoxs_own_values() -> None:
    assert default_registry.DEFAULT_INDEX_NAME == defaults.DEFAULT_INDEX_NAME
    assert default_registry.PEEK_TTL_SECONDS == defaults.PEEK_TTL_SECONDS
    assert default_registry.DEFAULT_REF == "main"
    assert (default_registry.BINDING_REFETCH,
            default_registry.BINDING_REGENERATE) == ("refetch", "regenerate")


def test_importing_the_seams_and_defaults_registers_and_resolves_nothing() -> None:
    script = _blocking_siblings() + textwrap.dedent("""
        from opendox import projection_seams as ps
        import opendox.default_registry, opendox.default_projection, opendox.rfc3339
        assert not ps.registry.is_registered()
        assert not ps.corpus_root.is_registered()
        assert not ps.writer.is_registered()
        assert ps.validators.kinds() == ()
        print("clean")
        """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, cwd=ROOT, timeout=120)
    assert done.returncode == 0 and "clean" in done.stdout, done.stderr


# ---------------------------------------------------------------------------
# 3 — the entry points register the defaults, and keep a host's
# ---------------------------------------------------------------------------

def _assert_defaults_registered() -> None:
    assert ps.registry._registered is default_registry
    assert ps.corpus_root._registered is default_projection.CORPUS_ROOT
    assert ps.writer._registered is default_projection.WRITER
    assert set(default_projection.OWN_KINDS) <= set(ps.validators.kinds())


def test_the_cli_entry_points_register_the_projection_defaults() -> None:
    cli.build_parser()
    _assert_defaults_registered()
    for seam in SINGLE_SEAMS.values():
        seam.unregister()
    ps.validators.unregister()
    with pytest.raises(SystemExit) as exited:
        cli.main(["--help"])
    assert exited.value.code == 0
    _assert_defaults_registered()


def test_serve_main_runs_its_help_standalone_over_the_registered_registry(capsys) -> None:
    """`serve.main()` could not run in a lone checkout even to `--help` until
    T055 (research R7): its option defaults read the consumer's registry."""
    with pytest.raises(SystemExit) as exited:
        serve.main(["--help"])
    assert exited.value.code == 0
    _assert_defaults_registered()
    out = " ".join(capsys.readouterr().out.split())
    assert "(default: main" in out
    assert "(default: the source root)" in out


def test_a_host_registered_first_is_kept_by_every_entry_point() -> None:
    hosts = {name: _stub(seam) for name, seam in SINGLE_SEAMS.items()}
    hosts["registry"] = types.SimpleNamespace(**{
        name: getattr(default_registry, name)
        for name in (*ps.REGISTRY_CALLABLES, *ps.REGISTRY_VALUES)})
    for name, seam in SINGLE_SEAMS.items():
        seam.register(hosts[name])
    validator = _Validator()
    ps.validators.register(NEUTRAL, validator)
    cli.build_parser()
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    with pytest.raises(SystemExit):
        serve.main(["--help"])
    for name, seam in SINGLE_SEAMS.items():
        assert seam.current() is hosts[name], name
    assert ps.validators.for_kind(NEUTRAL) is validator


def test_build_server_builds_standalone_over_openDoxs_own_registry(tmp_path) -> None:
    """Research R7's probe, which refused at the snapshot source, now builds."""
    repo, out, httpd = _served(tmp_path)
    try:
        bound = httpd.RequestHandlerClass.func
        assert isinstance(bound.source, default_registry.SnapshotSource)
        assert bound.source.registry.active.repository == "garden"
        assert Path(bound.source.registry.active.source_root).resolve() == repo.resolve()
        assert bound.capabilities["refresh"]["binding"] == "regenerate"
        assert serve._checkout_real(repo) is True
    finally:
        httpd.server_close()
    _assert_defaults_registered()


# ---------------------------------------------------------------------------
# 4 — standalone: no sibling importable
# ---------------------------------------------------------------------------

_STANDALONE = textwrap.dedent("""
    import http.client, json, sys, threading
    from pathlib import Path
    from opendox import cli, serve
    tmp = Path(sys.argv[1])
    out = tmp / "out" / "snapshot.json"
    rc = cli.main(["generate", "--repo-root", str(tmp / "repo"),
                   "--repository", "garden", "--output", str(out)])
    (tmp / "web").mkdir()
    httpd = serve.build_server(tmp / "web", out, tmp / "repo", port=0)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    host, port = httpd.server_address[:2]
    answers = {}
    for path in ("/snapshot.json", "/capabilities",
                 "/source/notes-toolshed-inventory.md", "/source/.git/config"):
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request("GET", path)
        response = connection.getresponse()
        answers[path] = [response.status, response.read().decode("utf-8", "replace")]
    httpd.shutdown(); httpd.server_close()
    loaded = sorted(name for name, module in sys.modules.items()
                    if module is not None and name.split(".")[0] in SIBLINGS)
    print(json.dumps({"rc": rc, "answers": answers, "loaded": loaded,
                      "kind": json.loads(out.read_text())["kind"]}))
    """)


def _blocking_siblings() -> str:
    """A preamble that makes every sibling unimportable, as a lone openDox
    checkout is: a `None` in `sys.modules` fails the import at once."""
    return ("import sys\n" + "".join(
        f"sys.modules[{name!r}] = None\n" for name in SIBLINGS)
        + f"SIBLINGS = {set(SIBLINGS)!r}\n")


def test_generate_and_serve_run_with_no_sibling_importable(tmp_path) -> None:
    """T055's claim end to end, in a process where `openxdox`,
    `ideation_dashboard`, `doc_health` and `corpus_adapter_openxfactory` cannot
    be imported: `generate` writes the neutral snapshot, and a server builds
    and answers the core routes from openDox's own registry."""
    _repository(tmp_path, name="repo")
    script = _blocking_siblings() + _STANDALONE
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                          capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["rc"] == 0, done.stderr
    assert result["kind"] == NEUTRAL
    assert result["loaded"] == []
    answers = result["answers"]
    assert answers["/snapshot.json"][0] == 200
    assert json.loads(answers["/snapshot.json"][1])["kind"] == NEUTRAL
    assert answers["/capabilities"][0] == 200
    assert answers["/source/notes-toolshed-inventory.md"][0] == 200
    assert answers["/source/.git/config"][0] == 404


# ---------------------------------------------------------------------------
# 5 — openDox's own registry and source
# ---------------------------------------------------------------------------

@pytest.fixture()
def tree(tmp_path) -> Path:
    root = tmp_path / "tree"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("# a\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (root / "changes").mkdir()
    (root / "changes" / ".openspec.yaml").write_text("x: 1\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    (root / "escape.md").symlink_to(outside)
    # Symlinks that stay INSIDE the root: two lead to what no URL may name
    # (a dot-directory, an undocumented dot-file), and two to what it may.
    (root / "link").symlink_to(".git", target_is_directory=True)
    (root / "docs" / "hidden").symlink_to("../.git", target_is_directory=True)
    (root / "alias.md").symlink_to(".env")
    (root / "same.md").symlink_to("docs/a.md")
    (root / "spec.yaml").symlink_to("changes/.openspec.yaml")
    # The writer's temporary sibling, as a crash mid-write would leave it.
    (root / "docs" / ".snapshot.json.0123abcd.tmp").write_text("{", encoding="utf-8")
    return root


@pytest.mark.parametrize("tail,served", [
    ("docs/a.md", True),
    ("docs%2Fa.md", True),
    ("changes/.openspec.yaml", True),
    ("../outside.md", False),
    ("%2e%2e/outside.md", False),
    ("/etc/passwd", False),
    ("docs/a.md\x00", False),
    ("", False),
    (".git/config", False),
    ("%2egit/config", False),
    (".env", False),
    ("docs", False),
    ("escape.md", False),
    ("docs/missing.md", False),
    ("link/config", False),
    ("docs/hidden/config", False),
    ("alias.md", False),
    ("same.md", True),
    ("spec.yaml", True),
    ("docs/.snapshot.json.0123abcd.tmp", False),
])
def test_resolve_within_is_the_containment_source_has_always_had(tree, tail, served) -> None:
    """The rule `/source` has always been confined by, and one place where
    openDox's statement of it is stricter: a symlink inside the root that
    leads into a dot-directory or at an undocumented dot-file is refused as
    its target would be, so `link -> .git` cannot serve `.git/config`."""
    resolved = default_registry.resolve_within(tree, tail)
    if served:
        assert resolved is not None and resolved.is_file()
        assert resolved.is_relative_to(tree.resolve())
    else:
        assert resolved is None


def test_the_keys_default_to_main_and_parse_back() -> None:
    reg = default_registry
    assert reg.snapshot_key("r") == ("r", "main")
    assert reg.snapshot_key("r", "  ") == ("r", "main")
    assert reg.key_id("r", "draft/t") == "r@draft/t"
    assert reg.parse_key_id("r@draft%2Ft") == ("r", "draft/t")
    assert reg.parse_key_id("no-at-sign") is None
    assert reg.parse_key_id("@main") is None
    assert reg.is_publishable_ref(None) and reg.is_publishable_ref("main")
    assert not reg.is_publishable_ref("draft/t")


def test_the_source_registers_the_snapshot_it_was_handed(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "repository": "garden",
        "generation": {"source_revision": "abc123", "generated_at": ANCHOR_DATE},
    }), encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    source = default_registry.SnapshotSource(
        baked_snapshot=snapshot, checkout_root=checkout,
        source_roots={"other@main": tmp_path})
    registry = source.bootstrap()
    entry = registry.active
    assert (entry.repository, entry.ref) == ("garden", "main")
    assert entry.source_root == checkout
    assert (entry.source_revision, entry.generated_at) == ("abc123", ANCHOR_DATE)
    assert source.baked_repository == "garden"
    assert source.refresh_binding == "regenerate"
    assert source.compose_view("garden") is None
    assert source.peek_hints() == {}
    assert source._source_root_for("other", "main") == tmp_path
    assert source._source_root_for("stranger", "main") is None
    assert default_registry.SnapshotSource(
        baked_snapshot=snapshot, checkout_root=tmp_path / "gone").refresh_binding is None


def test_the_source_refuses_what_only_a_hosts_registry_reads(tmp_path) -> None:
    for kwargs in ({"data_source": object()}, {"local_index": tmp_path / "index.json"}):
        with pytest.raises(default_registry.NeutralRegistryRefused) as caught:
            default_registry.SnapshotSource(**kwargs)
        assert ps.registry.registration_call in str(caught.value)
        assert isinstance(caught.value, ps.ProjectionSeamError)
    assert default_registry.data_source_from_options() is None
    for kwargs, flag in (({"directory": tmp_path}, "--data-source-dir"),
                         ({"directory": ""}, "--data-source-dir"),
                         ({"url": "https://example.invalid/x"}, "--data-source-url"),
                         ({"token_env": "SECRET_ENV"}, "--data-source-token-env"),
                         ({"token_env": ""}, "--data-source-token-env")):
        with pytest.raises(default_registry.NeutralRegistryRefused) as caught:
            default_registry.data_source_from_options(**kwargs)
        assert flag in str(caught.value), (
            "a declared option is refused by name, never dropped in silence")
    assert default_registry.github_raw_base_url("o/r") == \
        "https://raw.githubusercontent.com/o/r/main/"
    assert default_registry.github_raw_base_url("o/r", ref="x", path="a/b") == \
        "https://raw.githubusercontent.com/o/r/x/a/b/"
    with pytest.raises(ValueError):
        default_registry.github_raw_base_url("not-a-slug")


def test_serve_main_refuses_a_data_source_openDoxs_registry_cannot_read(
        tmp_path, capsys, monkeypatch) -> None:
    reached = []
    monkeypatch.setattr(serve, "serve", lambda *a, **k: reached.append(a))
    repo = _repository(tmp_path)
    for flags, named in (
            (["--data-source-dir", str(tmp_path)], "--data-source-dir"),
            (["--data-source-token-env", "SECRET_ENV"], "--data-source-token-env"),
            # An explicitly EMPTY option is a declaration too: `serve.main()`
            # hands it over as given, and never drops it for being falsy.
            (["--data-source-url", ""], "--data-source-url"),
            (["--data-source-github", "o/r"],
             "--data-source-github, which composes one"),
            (["--data-source-github", ""],
             "serve refused: --data-source-github: expected OWNER/REPO")):
        rc = serve.main(["--snapshot", str(tmp_path / "s.json"), "--checkout-root",
                         str(repo), *flags])
        assert rc == 1 and not reached, flags
        err = capsys.readouterr().err
        assert "serve refused:" in err and named in err, (flags, err)


def test_serve_main_refuses_an_empty_project_register(tmp_path, capsys, monkeypatch) -> None:
    """The holder's decision of 2026-09-28, at `serve`'s own option: an EMPTY
    `--project-register` is refused before a socket is bound, and never
    dropped, as `SnapshotSource` would drop it by testing it for truth. A
    given one is still handed over as given."""
    reached: list = []
    monkeypatch.setattr(serve, "serve", lambda *a, **k: reached.append(k))
    repo = _repository(tmp_path)
    base = ["--snapshot", str(tmp_path / "s.json"), "--checkout-root", str(repo)]
    assert serve.main([*base, "--project-register", ""]) == 1 and not reached
    assert ("serve refused: --project-register was given an empty path"
            in capsys.readouterr().err)
    assert serve.main([*base, "--project-register", "register.yaml"]) == 0
    assert reached and reached[0]["project_register"] == "register.yaml"


def test_dropping_the_active_entry_clears_the_active_key(tmp_path) -> None:
    """No ref-less request meets a key with nothing behind it, and the next
    entry registered becomes active, as the first one did."""
    reg = default_registry
    registry = reg.SnapshotRegistry()
    first = registry.register(reg.SnapshotEntry("garden", source_root=tmp_path))
    assert registry.active is first
    registry.drop("garden")
    assert registry.active is None and registry.resolve(None) is None
    second = registry.register(reg.SnapshotEntry("orchard", source_root=tmp_path))
    assert registry.active is second
    registry.register(reg.SnapshotEntry("orchard", "draft/t"))
    registry.drop("orchard", "draft/t")
    assert registry.active is second, "dropping another entry leaves the active one"


def test_the_registry_keeps_a_sessions_owner_and_base_and_confines_each_entry(tmp_path) -> None:
    reg = default_registry
    registry = reg.SnapshotRegistry()
    main = registry.register(reg.SnapshotEntry("garden", source_root=tmp_path))
    session = reg.SnapshotEntry("garden", "draft/t", source_root=tmp_path / "wt",
                                session_tile=("staged-topic", "t"),
                                session_base=("main", "abc"),
                                session_base_aliases=("def",))
    registry.register(session)
    assert registry.active is main, "the first entry registered is active"
    rebuilt = registry.register(reg.SnapshotEntry("garden", "draft/t"))
    assert rebuilt.session_tile == ("staged-topic", "t")
    assert rebuilt.session_base == ("main", "abc")
    assert rebuilt.session_base_aliases == ("def",)
    assert registry.resolve(None) is main
    assert registry.resolve("garden", "draft/t") is rebuilt
    assert registry.keys() == [("garden", "draft/t"), ("garden", "main")]
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    assert registry.resolve_source("garden", None, "doc.md") == (tmp_path / "doc.md").resolve()
    assert registry.resolve_source("garden", "draft/t", "doc.md") is None, (
        "an entry with no root serves nothing, never another entry's checkout")
    assert registry.resolve_source("stranger", None, "doc.md") is None
    with registry.atomically() as held:
        assert held is registry
        assert registry.set_active("garden", "draft/t") is rebuilt
    registry.drop("garden", "draft/t")
    assert registry.get("garden", "draft/t") is None and len(registry) == 1


@pytest.mark.parametrize("read,after", [
    ("active", "main"),
    ("resolve", "main"),
    ("get", None),
    ("len", 1),
])
def test_a_read_waits_for_a_held_read_modify_write(read, after, tmp_path) -> None:
    """Every read takes the registry's lock, so none answers from the middle
    of a block `atomically()` holds (Copilot at openDox-code#59 96f18c45,
    r4136863481). Here the block registers a session, promotes it, and then
    puts `main` back and drops the session, as a read-modify-write may. A
    read on another thread starts while the session is promoted. Unheld, it
    saw the session, or two entries. Held, it waits, and it answers the
    registry as the block left it."""
    reg = default_registry
    registry = reg.SnapshotRegistry()
    main = registry.register(reg.SnapshotEntry("garden", source_root=tmp_path))
    session = reg.SnapshotEntry("garden", "draft/t", source_root=tmp_path)
    reads = {
        "active": lambda: registry.active,
        "resolve": lambda: registry.resolve(None),
        "get": lambda: registry.get("garden", "draft/t"),
        "len": lambda: len(registry),
    }
    promoted, reading = threading.Event(), threading.Event()
    answered: list = []

    def reader() -> None:
        promoted.wait(timeout=10)
        reading.set()
        answered.append(reads[read]())

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    with registry.atomically():
        registry.register(session, active=True)
        promoted.set()
        reading.wait(timeout=10)
        # Time to answer, where nothing holds the registry. A read that
        # waits for the lock is still waiting when this runs out.
        worker.join(timeout=0.5)
        registry.set_active("garden")
        registry.drop("garden", "draft/t")
    worker.join(timeout=10)
    expected = {"main": main, None: None, 1: 1}[after]
    assert answered == [expected], (
        f"{read} answered from the middle of a held block: {answered!r}")


def test_the_regenerate_runs_the_registered_generator_and_writer(tmp_path) -> None:
    calls, writes = [], []

    def operation(repo_root, repository, *, source_revision=None, generated_at=None):
        calls.append((repo_root, repository, source_revision))
        return {"schema_version": 1, "kind": "host-snapshot", "repository": repository,
                "generation": {"source_revision": "fresh"}}

    gs.register(gs.SnapshotGenerator(contract="host-snapshot", generate=operation))

    class _Writer:
        def write_snapshot(self, snapshot, path, boundary):
            writes.append(snapshot)
            return boundary.write_output(path, json.dumps(snapshot))

    ps.writer.register(_Writer())
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"repository": "garden",
                                    "generation": {"source_revision": "old"}}),
                        encoding="utf-8")
    source = default_registry.SnapshotSource(baked_snapshot=snapshot,
                                             checkout_root=tmp_path)
    source.bootstrap()
    result = source.refresh(repository="garden")
    assert calls == [(tmp_path, "garden", None)], (
        "the regenerate generates through the registered generator, and an "
        "unset project register asks nothing of it")
    assert writes and writes[0]["generation"]["source_revision"] == "fresh"
    assert result["binding"] == "regenerate" and result["source_revision"] == "fresh"
    assert source.registry.active.source_revision == "fresh"


def test_the_regenerate_refuses_an_input_the_generator_does_not_declare(tmp_path) -> None:
    gs.register_default(default_generator.GENERATOR)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")
    source = default_registry.SnapshotSource(
        baked_snapshot=snapshot, checkout_root=tmp_path,
        project_register=tmp_path / "register.yaml")
    source.bootstrap()
    with pytest.raises(gs.GeneratorInputRefused):
        source.refresh()
    assert snapshot.read_text(encoding="utf-8") == "{}", "nothing was written"


def test_an_injected_generator_is_used_and_a_session_ref_is_never_promoted(tmp_path) -> None:
    ps.register_defaults()
    used = []

    def generator(root, repository, *, project_register_source=None):
        used.append(repository)
        return {"schema_version": 1, "kind": NEUTRAL, "repository": repository,
                "generation": {"source_revision": "s1"}}

    source = default_registry.SnapshotSource(checkout_root=tmp_path, generator=generator)
    registry = source.registry
    main = registry.register(default_registry.SnapshotEntry(
        "garden", snapshot_path=tmp_path / "main.json", source_root=tmp_path))
    registry.register(default_registry.SnapshotEntry(
        "garden", "draft/t", snapshot_path=tmp_path / "session.json",
        source_root=tmp_path))
    source.refresh(repository="garden", ref="draft/t")
    assert used == ["garden"]
    assert registry.active.key == main.key, "FR-014a: main stays active"
    assert json.loads((tmp_path / "session.json").read_text())["generation"] == \
        {"source_revision": "s1"}


def test_a_regenerate_promotes_no_session_and_moves_no_active_key(tmp_path) -> None:
    """FR-014a at the source boundary: a regenerated session never becomes
    active while `main` is, and one that was ALREADY active, set there on
    purpose, stays so, since moving the key off it is a change nobody asked
    the regenerate for (Copilot at openDox-code#59 183b40fc, r4146370161, is
    answered by this case)."""
    ps.register_defaults()

    def generator(root, repository):
        return {"schema_version": 1, "kind": NEUTRAL, "repository": repository,
                "generation": {"source_revision": "s1"}}

    source = default_registry.SnapshotSource(checkout_root=tmp_path, generator=generator)
    registry = source.registry
    main = registry.register(default_registry.SnapshotEntry(
        "garden", snapshot_path=tmp_path / "main.json", source_root=tmp_path))
    registry.register(default_registry.SnapshotEntry(
        "garden", "draft/t", snapshot_path=tmp_path / "session.json",
        source_root=tmp_path))
    source.refresh(repository="garden", ref="draft/t")
    assert registry.active.key == main.key, "a regenerated session is not promoted"
    registry.set_active("garden", "draft/t")
    source.refresh(repository="garden", ref="draft/t")
    assert registry.active.key == ("garden", "draft/t"), (
        "an entry active already stays active: nothing was promoted")


def test_an_injected_generator_is_handed_the_register_only_when_one_is_set(tmp_path) -> None:
    """An unset project register is not passed to an injected generator, as
    the generator seam omits an unset input, so one that takes only the core
    arguments regenerates. A set register is still handed over (Copilot at
    openDox-code#59 c2a8ad9f, r4146219833)."""
    ps.register_defaults()
    calls = []

    def core_only(root, repository):
        calls.append(("core", repository))
        return {"schema_version": 1, "kind": NEUTRAL, "repository": repository,
                "generation": {"source_revision": "s1"}}

    def with_register(root, repository, *, project_register_source):
        calls.append(("register", project_register_source))
        return core_only(root, repository)

    register = tmp_path / "register.yaml"
    for generator, project_register in ((core_only, None), (with_register, register)):
        source = default_registry.SnapshotSource(
            checkout_root=tmp_path, generator=generator,
            project_register=project_register)
        source.registry.register(default_registry.SnapshotEntry(
            "garden", snapshot_path=tmp_path / "main.json", source_root=tmp_path))
        source.refresh(repository="garden")
    assert calls == [("core", "garden"), ("register", register),
                     ("core", "garden")]


# ---------------------------------------------------------------------------
# 5b — the core `/snapshot.json` arm, answered from the registered source
# ---------------------------------------------------------------------------

def test_the_snapshot_arm_serves_the_active_and_the_named_entry(tmp_path) -> None:
    _repo, out, httpd = _served(tmp_path)
    status, headers, body = _get(httpd, "/snapshot.json")
    assert status == 200 and json.loads(body)["kind"] == NEUTRAL
    assert headers["X-Snapshot-Repository"] == "garden"
    _repo2, _out2, httpd = _served(tmp_path / "second")
    status, _headers, body = _get(httpd, "/snapshot.json?repository=garden&ref=main")
    assert status == 200 and json.loads(body)["repository"] == "garden"
    _repo3, _out3, httpd = _served(tmp_path / "third")
    status, _headers, _body = _get(httpd, "/snapshot.json?repository=nobody")
    assert status == 404, "an unknown pair, and no aggregate composes"


def test_the_hosted_plane_refuses_a_session_ref_named_or_active(tmp_path) -> None:
    _repo, _out, httpd = _served(tmp_path)
    bound = httpd.RequestHandlerClass.func
    bound.loopback = False
    status, _headers, body = _get(httpd, "/snapshot.json?repository=garden&ref=draft/t")
    assert status == 403 and json.loads(body)["error"] == "session_unavailable"
    _repo, _out, httpd = _served(tmp_path / "again")
    bound = httpd.RequestHandlerClass.func
    bound.loopback = False
    registry = bound.source.registry
    registry.register(default_registry.SnapshotEntry(
        "garden", "draft/t", snapshot_path=bound.snapshot_path), active=True)
    status, _headers, body = _get(httpd, "/snapshot.json")
    assert status == 403, "the refusal follows the entry the request resolved to"


def test_one_request_serves_the_entry_its_refusal_checked(tmp_path, monkeypatch) -> None:
    """FR-048 against a concurrent refresh. The active entry is resolved ONCE
    for the refusal, the body and the headers: a refresh that makes a session
    active right after the refusal passed `main` cannot put the session's bytes
    in that response."""
    _repo, _out, httpd = _served(tmp_path)
    bound = httpd.RequestHandlerClass.func
    bound.loopback = False
    main = bound.source.registry.active
    session_path = tmp_path / "session.json"
    session_path.write_text('{"kind": "a-session-snapshot"}', encoding="utf-8")
    session = default_registry.SnapshotEntry("garden", "draft/t",
                                             snapshot_path=session_path)
    landed = []

    class _Registry(default_registry.SnapshotRegistry):
        @property
        def active(self):
            return session if landed else main

    registry = _Registry()
    registry.register(main)
    registry.register(session)
    bound.source.registry = registry
    checked = bound._hosted_entry_refused

    def refusal_then_a_refresh_lands(self, entry):
        answered = checked(self, entry)
        landed.append(True)
        return answered

    monkeypatch.setattr(bound, "_hosted_entry_refused", refusal_then_a_refresh_lands)
    status, headers, body = _get(httpd, "/snapshot.json")
    assert status == 200 and landed, "the refusal ran, and a refresh landed after it"
    assert json.loads(body)["kind"] == NEUTRAL, "the body is the entry the refusal checked"
    assert headers["X-Snapshot-Ref"] == "main"


def test_the_source_arm_confines_to_the_entry_its_refusal_checked(tmp_path) -> None:
    """FR-048 on `/source/`, against a concurrent refresh. The unkeyed form
    resolves the ACTIVE entry once, and asks for the path by that entry's own
    pair. Here the active entry is a session until the first path lookup and
    `main` after it. Read twice, the path came from the session's worktree and
    the refusal passed `main`, so a hosted plane served the session's file."""
    _repo, _out, httpd = _served(tmp_path)
    bound = httpd.RequestHandlerClass.func
    bound.loopback = False
    main = bound.source.registry.active
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "secret.md").write_text("SESSION-ONLY BYTES\n", encoding="utf-8")
    session = default_registry.SnapshotEntry("garden", "draft/t", source_root=worktree)

    class _Registry(default_registry.SnapshotRegistry):
        looked_up = False

        @property
        def active(self):
            return main if self.looked_up else session

        def resolve_source(self, repository, ref, tail):
            try:
                return super().resolve_source(repository, ref, tail)
            finally:
                self.looked_up = True

    registry = _Registry()
    registry.register(main)
    registry.register(session)
    bound.source.registry = registry
    status, _headers, body = _get(httpd, "/source/secret.md")
    assert b"SESSION-ONLY" not in body, "a hosted plane served a session's file"
    assert status == 403 and json.loads(body)["error"] == "session_unavailable"


@pytest.mark.parametrize("query", ["", "?repository=garden&ref=main"],
                         ids=["unkeyed", "keyed"])
def test_a_refresh_that_replaces_the_key_cannot_move_the_source_arms_root(
        tmp_path, query) -> None:
    """FR-048 on `/source/`, against a refresh that REPLACES the key. Here a
    refresh on another thread re-registers `garden@main`, with another root,
    right after the arm's one resolution. When the path was asked for by the
    entry's pair, `resolve_source` looked the pair up again, and the path
    came from the replacement's root under the first entry's refusal and
    headers (Copilot at openDox-code#59 687d37bf, r4136585695). Confined to
    the root of the entry in hand, it comes from the entry the refusal
    checked, and the refresh lands as it would."""
    repo, _out, httpd = _served(tmp_path)
    bound = httpd.RequestHandlerClass.func
    first = bound.source.registry.active
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "notes-toolshed-inventory.md").write_text(
        "THE REPLACEMENT'S BYTES\n", encoding="utf-8")
    replacement = dataclasses.replace(first, source_root=elsewhere,
                                      source_revision="replaced")
    attempting = threading.Event()

    def refresh() -> None:
        attempting.set()
        registry.register(replacement)

    refresher = threading.Thread(target=refresh, daemon=True)
    landed_before_the_path: list[bool] = []

    class _Registry(default_registry.SnapshotRegistry):
        def resolve(self, repository, ref=None):
            entry = super().resolve(repository, ref)
            if entry is first and refresher.ident is None:
                refresher.start()
                attempting.wait(timeout=10)
                refresher.join(timeout=10)
                landed_before_the_path.append(
                    self.get(*first.key) is replacement)
            return entry

    registry = _Registry()
    registry.register(first)
    bound.source.registry = registry
    status, _headers, body = _get(
        httpd, f"/source/notes-toolshed-inventory.md{query}")
    assert landed_before_the_path == [True], (
        "the refresh landed after the arm's one resolution, and before its "
        "path was confined")
    assert b"THE REPLACEMENT'S BYTES" not in body, (
        "the path was looked up again, and came from the replacement's root")
    assert status == 200
    assert body == (repo / "notes-toolshed-inventory.md").read_bytes()


def test_hosted_ref_refused_asks_the_registered_registry() -> None:
    ps.register_defaults()
    assert serve.hosted_ref_refused(True, "draft/t") is False
    assert serve.hosted_ref_refused(False, None) is False
    assert serve.hosted_ref_refused(False, "main") is False
    assert serve.hosted_ref_refused(False, "draft/t") is True
    ps.registry.unregister()
    host = types.SimpleNamespace(**{
        name: getattr(default_registry, name)
        for name in (*ps.REGISTRY_CALLABLES, *ps.REGISTRY_VALUES)})
    host.is_publishable_ref = lambda ref: ref in (None, "main", "release")
    ps.registry.register(host)
    assert serve.hosted_ref_refused(False, "release") is False, (
        "the rule is the registered registry's, not a second spelling of it")


# ---------------------------------------------------------------------------
# 6 — openDox's own corpus-root predicate, writer and validator stand-in
# ---------------------------------------------------------------------------

def test_the_corpus_root_predicate_asks_for_a_git_repositorys_root(tmp_path) -> None:
    predicate = default_projection.CORPUS_ROOT
    assert predicate.corpus_scan_defect(tmp_path / "gone") == "the path does not exist"
    (tmp_path / "file").write_text("x", encoding="utf-8")
    assert predicate.corpus_scan_defect(tmp_path / "file") == "the path is not a directory"
    (tmp_path / "plain").mkdir()
    assert "not the root of a git repository" in predicate.corpus_scan_defect(tmp_path / "plain")
    repo = _repository(tmp_path, copy=None, files={"a.md": "# a\n"})
    assert predicate.corpus_scan_defect(repo) is None
    assert predicate.corpus_scan_defect(repo / "a.md") == "the path is not a directory"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert predicate.corpus_scan_defect(worktree) is None, "a worktree's .git is a file"
    assert predicate.SCANNED_ROOTS == ()
    assert predicate.change_rows(repo) == ()


def test_the_corpus_root_refusal_names_the_path_what_it_wanted_and_a_shape(tmp_path) -> None:
    predicate = default_projection.CORPUS_ROOT
    refusal = predicate.corpus_root_refusal(tmp_path / "gone", flag="--checkout-root",
                                            shape="a\n  b")
    assert refusal.startswith("--checkout-root is not a corpus checkout: the path does not exist")
    assert str((tmp_path / "gone").resolve()) in refusal
    assert predicate.LOOKED_FOR in refusal
    for expected in ("SERVED CHECKOUT", "namespace", "a correct invocation has this shape:",
                     "    a", "      b"):
        assert expected in refusal
    assert predicate.corpus_root_refusal(_repository(tmp_path)) is None


def test_the_writer_is_canonical_and_writes_only_through_the_boundary(tmp_path) -> None:
    writer = default_projection.WRITER
    snapshot = {"b": 1, "a": {"d": "é", "c": [2, 1]}}
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    written = writer.write_snapshot(snapshot, tmp_path / "snapshot.json", boundary)
    text = written.read_text(encoding="utf-8")
    assert text == writer.canonical_json(snapshot)
    assert text == ('{\n  "a": {\n    "c": [\n      2,\n      1\n    ],\n    '
                    '"d": "\\u00e9"\n  },\n  "b": 1\n}\n')
    with pytest.raises(BoundaryViolation):
        writer.write_snapshot(snapshot, tmp_path / "elsewhere.json", boundary)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snapshot.json"], (
        "the boundary refused the destination before anything was created")


def test_the_writer_replaces_the_snapshot_atomically(tmp_path) -> None:
    """A request mid-read while a refresh rewrites the snapshot sees the
    whole old snapshot, never a truncated one: the new bytes arrive by one
    rename over the target, not by a rewrite in place."""
    writer = default_projection.WRITER
    target = tmp_path / "snapshot.json"
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    writer.write_snapshot({"kind": NEUTRAL, "n": 1}, target, boundary)
    before = os.stat(target).st_ino
    with open(target, "rb") as reader:
        writer.write_snapshot({"kind": NEUTRAL, "n": 2}, target, boundary)
        assert json.loads(reader.read()) == {"kind": NEUTRAL, "n": 1}
    assert json.loads(target.read_text(encoding="utf-8")) == {"kind": NEUTRAL, "n": 2}
    assert os.stat(target).st_ino != before, "the bytes arrived by a rename"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snapshot.json"], (
        "no temporary sibling is left behind")


def test_a_failed_move_leaves_the_old_snapshot_and_no_sibling(tmp_path, monkeypatch) -> None:
    writer = default_projection.WRITER
    target = tmp_path / "snapshot.json"
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    writer.write_snapshot({"kind": NEUTRAL, "n": 1}, target, boundary)

    def the_move_fails(source, destination):
        raise OSError("the move failed")

    monkeypatch.setattr(default_projection.os, "replace", the_move_fails)
    with pytest.raises(OSError, match="the move failed"):
        writer.write_snapshot({"kind": NEUTRAL, "n": 2}, target, boundary)
    assert json.loads(target.read_text(encoding="utf-8")) == {"kind": NEUTRAL, "n": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snapshot.json"]


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o444])
def test_a_refresh_keeps_the_snapshots_permissions(tmp_path, mode) -> None:
    """Copilot at d7aa9d8c (r4136439187). `os.replace` carries the sibling's
    mode over the target, and the sibling had a new file's ordinary mode, so
    a snapshot kept restricted was widened by every refresh. Its permission
    bits now carry over. A new snapshot gets an ordinary new file's mode."""
    writer = default_projection.WRITER
    target = tmp_path / "snapshot.json"
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    writer.write_snapshot({"kind": NEUTRAL, "n": 1}, target, boundary)
    ordinary = tmp_path / "ordinary"
    ordinary.write_bytes(b"")
    assert (stat.S_IMODE(os.stat(target).st_mode)
            == stat.S_IMODE(os.stat(ordinary).st_mode)), "a new snapshot is ordinary"
    os.chmod(target, mode)
    writer.write_snapshot({"kind": NEUTRAL, "n": 2}, target, boundary)
    assert stat.S_IMODE(os.stat(target).st_mode) == mode
    assert json.loads(target.read_text(encoding="utf-8")) == {"kind": NEUTRAL, "n": 2}


def test_a_mode_that_cannot_be_kept_fails_the_write_and_widens_nothing(
        tmp_path, monkeypatch) -> None:
    writer = default_projection.WRITER
    target = tmp_path / "snapshot.json"
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    writer.write_snapshot({"kind": NEUTRAL, "n": 1}, target, boundary)
    os.chmod(target, 0o600)

    def the_mode_cannot_be_set(descriptor, mode):
        raise OSError("fchmod is not permitted here")

    monkeypatch.setattr(default_projection.os, "fchmod", the_mode_cannot_be_set)
    with pytest.raises(OSError, match="fchmod is not permitted here"):
        writer.write_snapshot({"kind": NEUTRAL, "n": 2}, target, boundary)
    assert json.loads(target.read_text(encoding="utf-8")) == {"kind": NEUTRAL, "n": 1}
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snapshot.json"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"),
                                   Path("not-json"), {"a": {1, 2}}])
def test_the_writer_refuses_what_json_cannot_carry(tmp_path, value) -> None:
    """Never the `NaN`/`Infinity` that `json` would otherwise write, which no
    JSON reader parses; and nothing is written."""
    boundary = OutputBoundary(tmp_path, ["snapshot.json"])
    with pytest.raises(default_projection.SnapshotNotWritable) as caught:
        default_projection.WRITER.write_snapshot(
            {"kind": NEUTRAL, "value": value}, tmp_path / "snapshot.json", boundary)
    assert isinstance(caught.value, ps.ProjectionSeamError)
    assert "JSON cannot carry" in str(caught.value)
    assert not (tmp_path / "snapshot.json").exists()


def test_generate_refuses_a_snapshot_json_cannot_carry(tmp_path, capsys) -> None:
    def operation(repo_root, repository, *, source_revision=None, generated_at=None):
        return {"schema_version": 1, "kind": "host-snapshot", "repository": repository,
                "generation": {"source_revision": "r"}, "score": float("nan")}

    gs.register(gs.SnapshotGenerator(contract="host-snapshot", generate=operation))
    out = tmp_path / "out" / "snapshot.json"
    assert _generate(_repository(tmp_path), out, "--no-validate") == 1
    err = capsys.readouterr().err
    assert "generate refused:" in err and "JSON cannot carry" in err
    assert not out.exists()


@pytest.mark.parametrize("extra", [
    {},
    {"generation": "r1", "documents": 7, "keyword_index": "k"},
], ids=["only-what-the-seam-requires", "other-shapes"])
def test_generate_reports_a_snapshot_whatever_else_its_contract_carries(
        extra, tmp_path, capsys) -> None:
    """A registered generator owes the seam only its declared `kind` and an
    integer `schema_version`. Its snapshot is written and reported, with
    what it lacks shown as `<absent>`, and the verb goes on to the validator
    for its kind. The report indexed `repository` and `generation` as if
    every contract carried them, so such a snapshot failed with a `KeyError`
    after it was written (Copilot at openDox-code#59 96f18c45,
    r4136863311)."""
    snapshot = {"schema_version": 1, "kind": "host-snapshot", **extra}

    def operation(repo_root, repository, *, source_revision=None, generated_at=None):
        return dict(snapshot)

    gs.register(gs.SnapshotGenerator(contract="host-snapshot", generate=operation))
    validator = _Validator()
    ps.validators.register("host-snapshot", validator)
    out = tmp_path / "out" / "snapshot.json"
    assert _generate(_repository(tmp_path), out) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == snapshot
    lines = capsys.readouterr().out.splitlines()
    for line in ("  repository=<absent> project=<ungrouped> project_group=<none>",
                 "  source_revision=<absent>", "  generated_at=<absent>",
                 "  documents=0 clusters=0 possibles=0 staged_topics=0 "
                 "changes=0 keywords=0"):
        assert line in lines, lines
    assert [call["path"].resolve() for call in validator.calls] == [out.resolve()], (
        "the verb goes on to the validator registered for the snapshot's kind")


def test_openDoxs_own_validator_is_bound_to_each_own_kind(tmp_path) -> None:
    """T058: the stand-in is gone, and openDox's own validator is registered
    per kind. The seam hands a validator only a path, so each is bound to the
    kind it is registered under, and reads its document as that kind is
    written. It runs no subprocess, so it declares no remedy."""
    validators = default_projection.VALIDATORS
    assert tuple(validators) == default_projection.OWN_KINDS
    assert {kind: v.kind for kind, v in validators.items()} == {
        kind: kind for kind in default_projection.OWN_KINDS}
    assert (validators[NEUTRAL].syntax, validators[workbench.KIND].syntax) == ("JSON", "YAML")
    assert all(v.dependency_remedy is None for v in validators.values())
    assert not hasattr(default_projection, "OwnValidatorNotBuilt")
    assert not hasattr(default_projection, "VALIDATOR")
    with pytest.raises(ValueError, match="openDox's own kinds"):
        default_projection.OwnValidator("ideation-dashboard-snapshot")


def test_a_validation_results_outcome_follows_ok_unless_given() -> None:
    assert ps.ValidationResult(True, 0, "", "", "v").outcome == ps.VALIDATED
    assert ps.ValidationResult(False, 1, "", "", "v").outcome == ps.NOT_CONFORMANT
    unavailable = ps.ValidationResult(False, -1, "", "", None, ps.VALIDATOR_UNAVAILABLE, "why")
    assert not unavailable.available and "why" in unavailable.summary()
    assert ps.ValidationResult(True, 0, "a\nlast line\n", "", "v").summary() == "last line"


# ---------------------------------------------------------------------------
# 7 — the generate verbs through the seams
# ---------------------------------------------------------------------------

def test_generate_writes_the_neutral_snapshot_and_names_its_kind(tmp_path, capsys) -> None:
    repo = _repository(tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    assert _generate(repo, out, "--no-validate") == 0
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    assert snapshot["kind"] == NEUTRAL and snapshot["documents"]
    assert out.read_text(encoding="utf-8") == default_projection.WRITER.canonical_json(snapshot)
    captured = capsys.readouterr()
    assert "  repository=garden kind=opendox-snapshot" in captured.out
    assert "project=" not in captured.out, "the neutral contract carries no project"


def test_the_report_keeps_every_other_kinds_line(capsys, tmp_path) -> None:
    ps.register_defaults()
    cli._report({"kind": "ideation-dashboard-snapshot", "repository": "r",
                 "generation": {"source_revision": "x"}, "documents": [{}]},
                tmp_path / "s.json", tmp_path)
    assert "  repository=r project=<ungrouped> project_group=<none>" in capsys.readouterr().out


def test_an_input_the_generator_does_not_declare_is_refused_before_a_write(tmp_path, capsys) -> None:
    repo = _repository(tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    assert _generate(repo, out, "--project-register", str(tmp_path / "r.yaml")) == 1
    err = capsys.readouterr().err
    assert "generate refused:" in err and "project_register_source" in err
    assert not out.exists()


def _declaring_generator(calls: list) -> None:
    """Register a host generator that DECLARES both source inputs, so that a
    refusal of an empty option is the option's own, not the seam's
    `GeneratorInputRefused` for an input the generator does not take."""
    def operation(repo_root, repository, *, source_revision=None, generated_at=None,
                  project_register_source=None, possibles_source=None):
        calls.append((project_register_source, possibles_source))
        return {"schema_version": 1, "kind": "host-snapshot",
                "repository": repository, "generation": {"source_revision": "s"},
                "documents": []}

    gs.register(gs.SnapshotGenerator(
        contract="host-snapshot", generate=operation,
        inputs=("project_register_source", "possibles_source")))


@pytest.mark.parametrize("flag", ["--project-register", "--possibles"])
def test_an_empty_source_option_is_refused_before_anything_is_generated(
        flag, tmp_path, capsys) -> None:
    """The holder's decision of 2026-09-28: an EMPTY `--project-register` or
    `--possibles` is refused, fail closed. It is not dropped, as testing the
    value for truth used to drop it. And it is not `Path("").resolve()`, which
    is the current directory. The generator declares the input, so nothing
    else refuses it."""
    calls: list = []
    _declaring_generator(calls)
    repo = _repository(tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    assert _generate(repo, out, flag, "") == 1
    err = capsys.readouterr().err
    assert f"generate refused: {flag} was given an empty path" in err, err
    assert calls == [] and not out.exists()


@pytest.mark.parametrize("attr, flag", [("project_register", "--project-register"),
                                        ("possibles", "--possibles")])
def test_the_gate_snapshot_refuses_an_empty_source_option(attr, flag, tmp_path) -> None:
    calls: list = []
    _declaring_generator(calls)
    args = argparse.Namespace(repo_root=str(tmp_path), repository="garden",
                              source_revision="abc", project_register=None,
                              possibles=None)
    setattr(args, attr, "")
    with pytest.raises(cli.SourceOptionRefused, match=f"{flag} was given an empty path"):
        cli._gate_snapshot(args)
    assert calls == []


def test_a_given_source_option_is_resolved_and_an_unset_one_is_not_passed(
        tmp_path, monkeypatch) -> None:
    calls: list = []
    _declaring_generator(calls)
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(repo_root=str(tmp_path), repository="garden",
                              source_revision="abc", project_register="register.yaml",
                              possibles=None)
    cli._gate_snapshot(args)
    assert calls == [(tmp_path.resolve() / "register.yaml", None)]


def test_generate_and_open_refuses_an_empty_source_option_before_its_run_dir(
        tmp_path, capsys, monkeypatch) -> None:
    """And before the local install's bundled server (plan 034 T072): a
    refused option costs no database start. A tripwire stands in for the
    server, so a regression neither starts one nor passes."""
    started: list = []

    class _Tripwire:
        def __init__(self, settings) -> None:
            started.append(settings)

        def start(self):
            raise AssertionError("the bundled server was started for a "
                                 "refused source option")

        def stop(self) -> None:
            pass

    monkeypatch.setattr(cli.bundle_mod, "BundledServer", _Tripwire)
    calls: list = []
    _declaring_generator(calls)
    repo = _repository(tmp_path)
    run_dir = tmp_path / "run"
    # `--local`: the single-user install. Since plan 034 T070 an unflagged run
    # is HOSTED, and its issuer refusal would come first.
    rc = cli.main(["generate-and-open", "--local", "--repo-root", str(repo),
                   "--repository", "garden", "--run-dir", str(run_dir),
                   "--no-open", "--no-serve", "--possibles", ""])
    assert rc == 1
    assert ("generate-and-open refused: --possibles was given an empty path"
            in capsys.readouterr().err)
    assert calls == [] and not run_dir.exists()
    assert started == [], "a bundled server was built for a refused option"


def test_a_root_openDoxs_predicate_refuses_is_refused_with_its_message(tmp_path, capsys) -> None:
    (tmp_path / "plain").mkdir()
    assert _generate(tmp_path / "plain", tmp_path / "out.json") == 1
    err = capsys.readouterr().err
    assert "--repo-root is not a corpus checkout" in err
    assert default_projection.CorpusRoot.LOOKED_FOR in err
    assert "python3 src/opendox/cli.py generate-and-open" in err
    assert not (tmp_path / "out.json").exists()


def test_a_malformed_generated_at_is_refused_by_openDoxs_own_rule(tmp_path, capsys) -> None:
    repo = _repository(tmp_path)
    assert _generate(repo, tmp_path / "out.json", "--generated-at", "2026-02-30T00:00:00Z") == 1
    assert "--generated-at is not an RFC 3339 date-time" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_an_empty_projection_warns_in_the_predicates_own_terms(tmp_path, capsys) -> None:
    repo = _repository(tmp_path, copy=None)
    assert _generate(repo, tmp_path / "out.json", "--no-validate") == 0
    err = capsys.readouterr().err
    assert "ZERO documents" in err
    assert "accepted as a corpus checkout, but nothing in it was read as a document" in err
    assert "because it holds" not in err


def test_the_empty_projection_warning_names_a_predicates_roots(tmp_path, capsys) -> None:
    predicate = _stub(ps.corpus_root)
    predicate.SCANNED_ROOTS = ("ideation", "openspec")
    ps.corpus_root.register(predicate)
    (tmp_path / "ideation").mkdir()
    cli._warn_on_empty_projection({"documents": 0}, tmp_path)
    assert "because it holds ideation/," in capsys.readouterr().err


def test_the_gate_snapshot_generates_through_the_seam(tmp_path) -> None:
    calls = []

    def operation(repo_root, repository, *, source_revision=None, generated_at=None,
                  project_register_source=None, possibles_source=None):
        calls.append((repository, source_revision, project_register_source))
        return {"schema_version": 1, "kind": "host-snapshot"}

    gs.register(gs.SnapshotGenerator(
        contract="host-snapshot", generate=operation,
        inputs=("project_register_source", "possibles_source")))
    args = argparse.Namespace(repo_root=str(tmp_path), repository="garden",
                              source_revision="abc", project_register=None,
                              possibles=None)
    root, snapshot = cli._gate_snapshot(args)
    assert root == tmp_path.resolve() and snapshot["kind"] == "host-snapshot"
    assert calls == [("garden", "abc", None)]


def test_a_cli_session_registry_is_the_registered_registrys(tmp_path) -> None:
    class _HostRegistry(default_registry.SnapshotRegistry):
        pass

    host = types.SimpleNamespace(**{
        name: getattr(default_registry, name)
        for name in (*ps.REGISTRY_CALLABLES, *ps.REGISTRY_VALUES)})
    host.SnapshotRegistry = _HostRegistry
    ps.registry.register(host)
    registry = cli._session_registry(_repository(tmp_path), "garden")
    assert type(registry) is _HostRegistry


def _validate_args(repo: Path, *extra: str) -> argparse.Namespace:
    return argparse.Namespace(repo_root=str(repo), no_validate=False,
                              strict="--strict" in extra)


def _written(tmp_path: Path, kind: str | None = NEUTRAL) -> Path:
    path = tmp_path / "out" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 1, "repository": "garden"}
    if kind is not None:
        document["kind"] = kind
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_validation_is_by_the_written_snapshots_kind(tmp_path, capsys) -> None:
    ps.register_defaults()
    host_validator = _Validator()
    ps.validators.register("host-snapshot", host_validator)
    written = _written(tmp_path, "host-snapshot")
    assert cli._validate(written, _validate_args(tmp_path)) == 0
    assert host_validator.calls == [{"path": written, "strict": False,
                                     "search_from": (written.parent, tmp_path.resolve())}]
    assert ps.validators.for_kind(NEUTRAL) is default_projection.VALIDATORS[NEUTRAL], (
        "the host's kind took nothing from openDox's own")
    assert "validation: stand-in: 0 error(s)" in capsys.readouterr().out


def test_openDoxs_own_kind_meets_openDoxs_own_validator(tmp_path, capsys) -> None:
    """T058: a snapshot of openDox's own kind is judged by openDox's own
    validator. This one lacks most of the contract, so it is NOT CONFORMANT:
    the verb fails, blames the snapshot, and names each broken rule."""
    ps.register_defaults()
    written = _written(tmp_path)
    assert cli._validate(written, _validate_args(tmp_path)) == 1
    err = capsys.readouterr().err
    assert "REJECTED" in err and "This is the SNAPSHOT" in err
    # ONE line per broken rule, with its count (T084; RULED 5920216845 item
    # 3), and each further place it is broken beneath it, so every missing
    # key is still named.
    assert "6 × [envelope-keys] <root>: " in err, err
    assert err.count("[envelope-keys]") == 1, err
    assert "<root>: 'documents' is required" in err, err
    assert "6 violation(s) of the opendox-snapshot contract, by opendox.validator" in err
    assert "validation SKIPPED" not in err


def test_openDoxs_own_validator_unavailable_is_skipped_and_strict_makes_it_fatal(
        tmp_path, capsys, monkeypatch) -> None:
    """T058: `ValidatorUnavailable` (here a packaged copy that fails its
    identity check) is VALIDATOR UNAVAILABLE, never a pass. The verb warns and
    goes on, and `--strict` makes it fatal."""
    from opendox import contracts

    def refused(copy_id):
        raise contracts.CopyRefused(f"the packaged copy {copy_id} differs from its digest")

    monkeypatch.setattr(contracts, "verified_bytes", refused)
    ps.register_defaults()
    written = _written(tmp_path)
    assert cli._validate(written, _validate_args(tmp_path)) == 0
    err = capsys.readouterr().err
    assert "validation SKIPPED" in err
    assert ("the validator was found (opendox.validator) but could not run: the "
            "packaged copy opendox-snapshot differs from its digest") in err
    assert "the ENVIRONMENT, not the snapshot" in err and "pip install" not in err
    assert cli._validate(written, _validate_args(tmp_path, "--strict")) == 1
    assert "--strict was given" in capsys.readouterr().err


def test_a_kind_with_no_validator_is_unavailable_not_another_kinds(tmp_path, capsys) -> None:
    ps.register_defaults()
    assert cli._validate(_written(tmp_path, "stranger"), _validate_args(tmp_path)) == 0
    err = capsys.readouterr().err
    assert "no validator is registered for kind 'stranger'" in err
    assert ps.validators.registration_call in err, (
        "the lookup's refusal is given whole: it ends with the call that registers one")
    assert "to search from" not in err and str(tmp_path / "out") not in err, (
        "the lookup is the process's registry: no path could make a validator "
        "reachable, so the warning names none")


def test_a_rejection_fails_and_blames_the_snapshot(tmp_path, capsys) -> None:
    rejecting = _Validator(ps.ValidationResult(
        False, 1, "ERROR rule-x: broken\n1 error(s)", "", "stand-in"))
    ps.validators.register(NEUTRAL, rejecting)
    assert cli._validate(_written(tmp_path), _validate_args(tmp_path)) == 1
    err = capsys.readouterr().err
    assert "REJECTED" in err and "rule-x" in err and "pip install" not in err


def test_a_validator_that_could_not_run_warns_with_its_own_remedy(tmp_path, capsys) -> None:
    stuck = _Validator(ps.ValidationResult(
        False, 2, "", "ERROR a library is missing", "stand-in",
        ps.VALIDATOR_UNAVAILABLE, "it exited 2"), remedy="pip install something")
    ps.validators.register(NEUTRAL, stuck)
    assert cli._validate(_written(tmp_path), _validate_args(tmp_path)) == 0
    err = capsys.readouterr().err
    for expected in ("could not run: it exited 2", "ERROR a library is missing",
                     "-m pip install something", "the ENVIRONMENT, not the snapshot"):
        assert expected in err
    assert cli._validate(_written(tmp_path), _validate_args(tmp_path, "--strict")) == 1


def test_a_snapshot_that_declares_no_kind_fails(tmp_path, capsys) -> None:
    ps.register_defaults()
    assert cli._validate(_written(tmp_path, None), _validate_args(tmp_path)) == 1
    assert "declares no kind" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 8 — `branch_session`'s routed sites, and the workbench manifest
# ---------------------------------------------------------------------------

def _host_registry_with_entry(entry_type) -> types.SimpleNamespace:
    host = types.SimpleNamespace(**{
        name: getattr(default_registry, name)
        for name in (*ps.REGISTRY_CALLABLES, *ps.REGISTRY_VALUES)})
    host.SnapshotEntry = entry_type
    return host


def test_a_session_entry_is_the_registered_registrys_entry(tmp_path) -> None:
    class _HostEntry(default_registry.SnapshotEntry):
        pass

    ps.registry.register(_host_registry_with_entry(_HostEntry))
    entry = bs.session_entry("garden", "draft/t", tmp_path)
    assert type(entry) is _HostEntry
    assert (entry.repository, entry.ref, entry.source_root) == ("garden", "draft/t", tmp_path)


def test_a_registered_session_reads_its_snapshot_through_the_registry(tmp_path) -> None:
    ps.register_defaults()
    checkout = tmp_path / "garden"
    checkout.mkdir()
    branch = "draft/t"
    snapshot = bs.session_snapshot_path(checkout, branch)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps({"repository": "garden",
                                    "generation": {"source_revision": "s"}}),
                        encoding="utf-8")
    registry = default_registry.SnapshotRegistry()
    entry = bs.register_session_entry(registry, repository="garden", branch=branch,
                                      worktree=tmp_path / "wt", checkout_root=checkout,
                                      regenerate=False)
    assert isinstance(entry, default_registry.SnapshotEntry)
    assert entry.source_revision == "s" and registry.get("garden", branch) is entry


def test_a_session_snapshot_and_the_main_view_regenerate_through_the_seams(tmp_path) -> None:
    ps.register_defaults()
    gs.register_default(default_generator.GENERATOR)
    repo = _repository(tmp_path)
    registry = default_registry.SnapshotRegistry()
    main = registry.register(default_registry.SnapshotEntry(
        "garden", snapshot_path=tmp_path / "main.json", source_root=repo))
    registry.register(default_registry.SnapshotEntry(
        "garden", "draft/t", snapshot_path=tmp_path / "session.json",
        source_root=repo))
    result = bs.refresh_session_snapshot(registry, repository="garden",
                                         branch="draft/t", worktree=repo)
    assert result["binding"] == "regenerate"
    assert json.loads((tmp_path / "session.json").read_text())["kind"] == NEUTRAL
    assert registry.active.key == main.key, "FR-014a: main stays active"
    view = bs.refresh_main_view(registry, repository="garden", checkout_root=repo)
    assert view["binding"] == "regenerate"
    assert json.loads((tmp_path / "main.json").read_text())["kind"] == NEUTRAL


def test_the_change_rows_are_the_registered_predicates(tmp_path) -> None:
    ps.register_defaults()
    assert bs._change_rows(tmp_path) == ()
    ps.corpus_root.unregister()
    predicate = _stub(ps.corpus_root)
    predicate.change_rows = lambda root: [("c-1", "active", Path(root), "absent", None)]
    ps.corpus_root.register(predicate)
    assert bs._change_rows(tmp_path) == (("c-1", "active", tmp_path, "absent", None),)


def test_a_manifest_is_validated_by_the_validator_for_its_kind(tmp_path) -> None:
    manifest = tmp_path / "set.yaml"
    manifest.write_text("kind: ideation-workbench\n", encoding="utf-8")
    ruling = _Validator()
    ps.validators.register(workbench.KIND, ruling)
    result = workbench.validate_manifest(manifest)
    assert result.ok and result.validator == "stand-in"
    assert ruling.calls == [{"path": manifest.resolve(), "strict": False,
                             "search_from": (manifest.resolve().parent,)}]
    ps.validators.unregister()
    ps.register_defaults()
    judged = workbench.validate_manifest(manifest, search_from=tmp_path)
    assert not judged.ok and judged.returncode == 1
    assert str(judged.validator).startswith("opendox.validator, over its packaged copy "
                                            "ideation-workbench")
    assert "[required] <root>:" in judged.stdout, judged.stdout
    ps.validators.unregister()
    refused = workbench.validate_manifest(manifest)
    assert not refused.ok and "ideation-workbench" in refused.stderr


def test_an_explicit_manifest_validator_script_still_runs(tmp_path) -> None:
    script = tmp_path / "validator.py"
    script.write_text("import sys\nprint('explicit: ok', sys.argv[1:])\n", encoding="utf-8")
    manifest = tmp_path / "set.yaml"
    manifest.write_text("kind: ideation-workbench\n", encoding="utf-8")
    result = workbench.validate_manifest(manifest, validator=script, strict=True)
    assert result.ok and result.validator == script
    assert "--strict" in result.stdout and str(manifest.resolve()) in result.stdout


# ---------------------------------------------------------------------------
# 9 — no proxy over a seam is read at import time
# ---------------------------------------------------------------------------

def _proxy_bindings(tree: ast.Module) -> set[str]:
    """Module-level names bound to `projection_seams.<seam>.proxy`."""
    bound = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute) \
                and node.value.attr == "proxy" \
                and isinstance(node.value.value, ast.Attribute) \
                and isinstance(node.value.value.value, ast.Name) \
                and node.value.value.value.id == "projection_seams":
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return bound


def _import_time_reads(tree: ast.Module, names: set[str]) -> list[int]:
    """Lines where `names` are read when the module is IMPORTED: module-level
    statements, class bodies, and a function's defaults, annotations and
    decorators. Only a function's body defers."""
    hits = []

    def reads(node):
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in names \
                    and isinstance(inner.ctx, ast.Load):
                hits.append(inner.lineno)

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                for part in [*node.decorator_list, *args.defaults,
                             *(d for d in args.kw_defaults if d),
                             *(a.annotation for a in [*args.posonlyargs, *args.args,
                                                      *args.kwonlyargs, args.vararg,
                                                      args.kwarg]
                               if a is not None and a.annotation is not None),
                             *([node.returns] if node.returns else [])]:
                    reads(part)
                continue
            if isinstance(node, ast.ClassDef):
                for part in [*node.bases, *node.keywords, *node.decorator_list]:
                    reads(part)
                walk(node.body)
                continue
            nested = []
            for _field, value in ast.iter_fields(node):
                for item in value if isinstance(value, list) else [value]:
                    if isinstance(item, ast.stmt):
                        nested.append(item)
                    elif isinstance(item, ast.AST):
                        reads(item)
            walk(nested)

    walk(tree.body)
    return sorted(hits)


def test_no_proxy_over_a_seam_is_read_at_import_time() -> None:
    """A proxy read at import time would resolve the seam before any entry
    point registered anything, so the import would refuse."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _proxy_bindings(tree)
        if names:
            found[path.relative_to(PACKAGE).as_posix()] = (
                sorted(names), _import_time_reads(tree, names))
    assert found == {"serve.py": (["registry_mod"], []),
                     "serve_workbench.py": (["registry_mod"], [])}, found


def test_the_retired_stand_ins_are_gone_from_consumer_reach() -> None:
    for name in ("snapshot", "snapshot_registry", "corpus_root", "generator",
                 "find_validator", "corpus_root_refusal", "generate_snapshot",
                 "is_rfc3339_datetime", "hosted_ref_refused", "scanned_roots",
                 "function", "constant"):
        assert not hasattr(consumer_reach, name), name
        assert name not in consumer_reach.__all__, name
    assert consumer_reach.LateProjectionRoutes.LATE_COLUMN[2] == ("_serve_index",)


# ---------------------------------------------------------------------------
# 10 — openDox's own RFC 3339 check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,admitted", [
    ("2026-09-04T01:23:45Z", True),
    ("2026-09-04t01:23:45.500z", True),
    ("2026-09-04T01:23:45+05:30", True),
    ("2024-02-29T00:00:00-00:00", True),
    ("2026-02-30T00:00:00Z", False),
    ("2025-02-29T00:00:00Z", False),
    ("2026-09-04T01:23:45+24:00", False),
    ("2026-09-04T01:23:60Z", False),
    ("0000-01-01T00:00:00Z", False),
    ("2026-09-04T01:23:45", False),
    ("2026-09-04", False),
    ("2026-09-04 01:23:45Z", False),
    ("2026-09-04T01:23:45Z\n", False),
    (" 2026-09-04T01:23:45Z", False),
    ("\u0662\u0660\u0662\u0666-09-04T01:23:45Z", False),
    (None, False),
    (20260904, False),
])
def test_the_rfc3339_check_is_the_neutral_contracts_rule(value, admitted) -> None:
    assert rfc3339.is_rfc3339_datetime(value) is admitted
