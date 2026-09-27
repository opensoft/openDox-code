"""The session notebook's MEMBERSHIP, through the registered home corpus
(`add-neutral-product-standalone-operability` task 4.3; plan 034 task T025,
R1Q9 (a)).

`workbench.session_documents` used to import openxFactory's `doc_health.corpus`
inside its body (`workbench.py:746` at `1e4a57fb`), the last of the four
reaches `workbench.py` made into the publisher. It now lists the home corpus a
host registered with `corpus_adapter.register_home(...)` (4.1, T020), under
the scope a host registered with `workbench.register_session_notebook_scope(...)`,
and `all` where none is. With nothing registered it refuses as 4.2 does.

WHAT IT ASSERTS, AND WHY EACH IS HERE

1. NOTHING REGISTERED REFUSES AS 4.2 DOES (`CorpusRefused`, kind
   `ADAPTER_NOT_REGISTERED`, naming the seam and `register_home`), and the
   session that asked is not blocked by it (FR-042).
2. THE MEMBERSHIP TEST THE PLAN NAMES. With nothing but openDox's default
   registered (a factory over `LocalGitCorpus`, as T022's entry points will
   register it), the notebook lists `all`. With a scope registered, it lists
   that scope and nothing else. openxFactory registers `documents` (T046).
3. A SCOPE THE CORPUS DOES NOT DECLARE IS REFUSED, NEVER WIDENED.
4. THE BYTES ARE THE CORPUS'S, AND THE TEXT IS WHAT IT WAS. The notebook
   takes no snapshot of its own: it carries what the registered corpus serves
   at the worktree, so the host's checkout-reading adapter serves an
   uncommitted edit, and a key is handed back to the adapter, never opened as
   a path. Each document is decoded as the reader this replaced read it from
   disk, which is held against `Path.read_text` itself, and the size bound is
   measured the same way, so no source's content hash moves under the hosted
   notebook.
5. THE REGISTRATION DISCIPLINE for the scope.
6. AN IMPORTABLE `doc_health` IS NOT REACHED, and the static half: nothing
   in `workbench.py` makes a deferred reach into the publisher or the
   consumer any more, read by `ast` the way F4.1's scan reads the package.

`--noconftest` SAFE, like every file `validate` runs today. It imports
`opendox.workbench`, `opendox.corpus_adapter`, `opendox.branch_session` and
`opendox.runtime.local_git_adapter`, which import with no sibling present,
and neither `opendox.serve` nor `opendox.cli` (plan 034, tasks.md § Phase 1:
those two modules do not import in a lone checkout until T011 lands).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from opendox import branch_session
from opendox import corpus_adapter as ca
from opendox import workbench as wb
from opendox.runtime.local_git_adapter import LocalGitCorpus

WORKBENCH_SOURCE = Path(wb.__file__)

#: #1144 task 4.3's F4.1 scan, word for word: the four packages no deferred
#: reach in openDox may name.
FOREIGN = ("openxdox", "ideation_dashboard", "corpus_adapter_openxfactory",
           "doc_health")

#: The seam's own functions, and the reader that resolves through it.
SEAM_FUNCTIONS = ("register_session_notebook_scope",
                  "unregister_session_notebook_scope", "session_notebook_scope",
                  "_document_text", "session_documents")

needs_git = pytest.mark.skipif(shutil.which("git") is None,
                               reason="LocalGitCorpus reads a git repository")


@pytest.fixture(autouse=True)
def _empty_seams():
    """Every test starts with NO home corpus and NO scope registered, and puts
    back what it found. Both registrations are process-global by design.

    Read through `getattr` with a default, so that against a tree WITHOUT the
    scope seam each test fails on its own assertion rather than all of them
    erroring here, which is what makes this file's red run legible."""
    previous_home = ca._home_factory
    previous_scope = getattr(wb, "_session_notebook_scope", None)
    unregister = getattr(wb, "unregister_session_notebook_scope", lambda: None)
    ca._home_factory = ca._UNSET
    unregister()
    yield
    ca._home_factory = previous_home
    unregister()
    if previous_scope is not None:
        wb.register_session_notebook_scope(previous_scope)


# --------------------------------------------------------------------------
# stand-ins
# --------------------------------------------------------------------------

def _local_git_default(root: str):
    """openDox's own default, as T022's entry points register it: a
    `home_corpus`-shaped factory over `LocalGitCorpus`, at its defaults."""
    return LocalGitCorpus(), ca.CorpusRef(name=Path(root).name, location=str(root))


def _git_repository(root: Path, files: dict[str, bytes]) -> Path:
    """A plain git repository holding `files`, committed. `LocalGitCorpus`
    reads a repository through its own history."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, content in files.items():
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=membership test",
                    "-c", "user.email=membership@example.invalid", "-c",
                    "commit.gpgsign=false", "commit", "-q", "-m", "fixture"],
                   check=True)
    return root


class _TwoScopeCorpus:
    """A stand-in host adapter that declares `documents` beside `all`, as
    openxFactory's does, and records which scope it was asked to list."""

    def __init__(self, files: dict[str, bytes], documents: tuple[str, ...],
                 scopes: tuple[str, ...] = (ca.SCOPE_ALL, "documents")) -> None:
        self.files = files
        self.documents = documents
        self.scopes = scopes
        self.listed: list[str] = []

    def resolve(self, ref):
        return ca.ResolvedCorpus(ref=ref, location=ref.location, revision=None,
                                 scopes=self.scopes, write_path=None,
                                 write_path_available=False)

    def list_documents(self, corpus, scope=ca.SCOPE_ALL):
        self.listed.append(scope)
        keys = sorted(self.files) if scope == ca.SCOPE_ALL else sorted(self.documents)
        return tuple(ca.DocumentId(corpus=corpus.ref.name, key=key) for key in keys)

    def read(self, corpus, document, revision=None):
        return ca.Document(id=document, content=self.files[document.key],
                           revision=None)

    def classify(self, corpus, document):          # pragma: no cover - unused
        raise AssertionError("the notebook's membership does not classify")

    def check(self, corpus, subjects=None):        # pragma: no cover - unused
        return ()

    def write_back(self, corpus, document, content, *, actor, basis_revision,
                   reason=""):                     # pragma: no cover - unused
        raise AssertionError("the notebook's membership never writes")


class _CheckoutCorpus:
    """A stand-in with the HOST adapter's read semantics. openxFactory's
    adapter lists the checkout it is pointed at with a glob and reads each
    document with `read_bytes`, whatever HEAD says, so this one does too."""

    def resolve(self, ref):
        return ca.ResolvedCorpus(ref=ref, location=ref.location, revision=None,
                                 scopes=(ca.SCOPE_ALL,), write_path=None,
                                 write_path_available=False)

    def list_documents(self, corpus, scope=ca.SCOPE_ALL):
        root = Path(corpus.location)
        keys = sorted(path.relative_to(root).as_posix()
                      for path in root.rglob("*.md")
                      if ".git" not in path.relative_to(root).parts)
        return tuple(ca.DocumentId(corpus=corpus.ref.name, key=key) for key in keys)

    def read(self, corpus, document, revision=None):
        return ca.Document(id=document,
                           content=(Path(corpus.location) / document.key).read_bytes(),
                           revision=None)


def _register(adapter) -> list[str]:
    """Register a factory over `adapter`; returns the roots it was called on."""
    roots: list[str] = []

    def factory(root: str):
        roots.append(root)
        return adapter, ca.CorpusRef(name=Path(root).name, location=str(root))

    ca.register_home(factory)
    return roots


class _TrapModule(types.ModuleType):
    """A module that records every non-dunder attribute anybody asks it for."""

    def __init__(self, name: str, touched: list[str]) -> None:
        super().__init__(name)
        self.__dict__["_touched"] = touched
        self.__path__ = []          # a package, so its submodules can be imported

    def __getattr__(self, attr: str):
        if not attr.startswith("__"):
            self._touched.append(f"{self.__name__}.{attr}")
        raise AttributeError(attr)


class _Notebook:
    """A session notebook adapter that must never be asked for anything."""

    def create_session(self, alias, documents):     # pragma: no cover - guard
        raise AssertionError("no notebook is created from a refused membership")


def _outcome(call):
    """What `call()` raised, or None: taken whole, so that what it TOUCHED is
    asserted first and a reach shows as the reach rather than as its crash."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the caller asserts on it
        return exc
    return None


# --------------------------------------------------------------------------
# 1 — nothing registered refuses as 4.2 does, and blocks no session
# --------------------------------------------------------------------------

def test_with_no_home_corpus_registered_the_notebook_refuses_as_4_2_does(tmp_path):
    with pytest.raises(ca.CorpusRefused) as refused:
        wb.session_documents(tmp_path)
    refusal = refused.value.refusal
    assert refusal.kind == ca.ADAPTER_NOT_REGISTERED
    assert refusal.subject == "opendox.corpus_adapter"
    assert "register_home" in refusal.detail


def test_the_refusal_is_the_sessions_notice_and_never_blocks_it(tmp_path):
    """`open_session_notebook` is the caller that opens a session's notebook,
    and FR-042 says a notebook never blocks a session: the refusal arrives as
    the notice, naming its remedy, and no notebook is created."""
    created, notice = branch_session.open_session_notebook(
        _Notebook(), alias="xf-session-plain-a-k0123456789ab", branch="a",
        worktree=tmp_path, repository="plain")
    assert created is False
    assert "is OPEN and fully usable" in notice
    assert "register_home" in notice


# --------------------------------------------------------------------------
# 2 — the membership test: `all` by default, the registered scope when one is
# --------------------------------------------------------------------------

@needs_git
def test_with_only_the_default_registered_the_notebook_lists_all(tmp_path):
    """openDox's default carries no host rule: no governed roots, no `Status:`
    header. Every document the corpus lists is a member."""
    worktree = _git_repository(tmp_path / "plain", {
        "README.md": b"# A plain repository\n",
        "notes/a.md": b"Status: draft\n\n# A note with a header\n",
        "notes/b.md": b"# A note with none\n",
        "ideas/c.txt": b"an idea, in plain text\n",
    })
    ca.register_home(_local_git_default)
    assert wb.session_notebook_scope() == ca.SCOPE_ALL == "all"

    assert wb.session_documents(worktree) == [
        ("README.md", "# A plain repository\n"),
        ("ideas/c.txt", "an idea, in plain text\n"),
        ("notes/a.md", "Status: draft\n\n# A note with a header\n"),
        ("notes/b.md", "# A note with none\n"),
    ]


def test_with_no_scope_registered_a_two_scope_corpus_lists_all(tmp_path):
    adapter = _TwoScopeCorpus({"docs/a.md": b"a\n", "code/b.py": b"b\n"},
                              documents=("docs/a.md",))
    roots = _register(adapter)
    assert wb.session_documents(tmp_path) == [("code/b.py", "b\n"),
                                              ("docs/a.md", "a\n")]
    assert adapter.listed == [ca.SCOPE_ALL]
    assert roots == [str(tmp_path)], "the factory is called on the worktree"


def test_a_registered_scope_is_the_one_the_notebook_lists(tmp_path):
    """The hosted case: openxFactory registers its adapter's `documents`
    scope (T046), and the notebook lists that scope and nothing else."""
    adapter = _TwoScopeCorpus(
        {"docs/a.md": b"Status: draft\n\na\n", "docs/b.md": b"Status: record\n\nb\n",
         "code/c.py": b"c\n"},
        documents=("docs/a.md", "docs/b.md"))
    _register(adapter)
    assert wb.register_session_notebook_scope("documents") == "documents"
    assert wb.session_notebook_scope() == "documents"

    assert wb.session_documents(tmp_path, repository="hosted") == [
        ("docs/a.md", "Status: draft\n\na\n"),
        ("docs/b.md", "Status: record\n\nb\n"),
    ]
    assert adapter.listed == ["documents"]


# --------------------------------------------------------------------------
# 3 — a scope the corpus does not declare is refused, never widened
# --------------------------------------------------------------------------

@needs_git
def test_a_registered_scope_the_default_corpus_does_not_declare_is_refused(tmp_path):
    worktree = _git_repository(tmp_path / "plain", {"README.md": b"# r\n"})
    ca.register_home(_local_git_default)
    wb.register_session_notebook_scope("documents")
    with pytest.raises(ca.CorpusRefused) as refused:
        wb.session_documents(worktree)
    refusal = refused.value.refusal
    assert refusal.kind == ca.SCOPE_UNKNOWN
    assert refusal.subject == "documents"
    assert "opendox.workbench.register_session_notebook_scope(" in refusal.detail
    assert "never widened" in refusal.detail


def test_an_undeclared_scope_is_refused_before_anything_is_listed(tmp_path):
    adapter = _TwoScopeCorpus({"docs/a.md": b"a\n"}, documents=("docs/a.md",),
                              scopes=(ca.SCOPE_ALL,))
    _register(adapter)
    wb.register_session_notebook_scope("documents")
    with pytest.raises(ca.CorpusRefused) as refused:
        wb.session_documents(tmp_path)
    assert refused.value.refusal.kind == ca.SCOPE_UNKNOWN
    assert adapter.listed == [], "an undeclared scope must not reach the listing"


# --------------------------------------------------------------------------
# 4 — the text is what it was
# --------------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    b"Status: draft\r\n\r\nwindows line endings\r\n",
    b"old mac\rline endings\r",
    b"mixed\r\nendings\rand\nnewlines\n",
    b"\xef\xbb\xbfa byte-order mark\n",
    b"invalid \xff\xfe utf-8 \xc3\n",
    "unicode é—中\n".encode("utf-8"),
    b"",
], ids=["crlf", "cr", "mixed", "bom", "invalid-utf8", "unicode", "empty"])
def test_documents_are_decoded_as_the_replaced_reader_read_them(tmp_path, content):
    """`doc_health.corpus.load_docs` read each document with
    `Path.read_text(encoding="utf-8", errors="replace")`. The adapter hands
    over BYTES, so the text is held to that exact call on the same bytes."""
    on_disk = tmp_path / "document.md"
    on_disk.write_bytes(content)
    expected = on_disk.read_text(encoding="utf-8", errors="replace")

    _register(_TwoScopeCorpus({"document.md": content}, documents=()))
    assert wb.session_documents(tmp_path / "worktree") == [("document.md", expected)]


@needs_git
def test_the_notebook_carries_what_the_corpus_serves_at_the_worktree(tmp_path):
    """The notebook takes NO SNAPSHOT OF ITS OWN: it carries what the
    registered corpus serves at the worktree. A corpus that reads the checkout
    it is pointed at (the host's) serves an UNCOMMITTED edit and an untracked
    draft, as the reader this replaced did. A corpus that serves a revision
    (`LocalGitCorpus`) serves the worktree's HEAD, which is its own answer
    and not one this function imposes."""
    worktree = _git_repository(tmp_path / "session", {"notes/a.md": b"committed\n"})
    (worktree / "notes" / "a.md").write_bytes(b"edited, not committed\n")
    (worktree / "notes" / "b.md").write_bytes(b"a new draft\n")

    ca.register_home(lambda root: (
        _CheckoutCorpus(), ca.CorpusRef(name=Path(root).name, location=str(root))))
    assert wb.session_documents(worktree) == [
        ("notes/a.md", "edited, not committed\n"),
        ("notes/b.md", "a new draft\n"),
    ]

    ca.register_home(_local_git_default)
    assert wb.session_documents(worktree) == [("notes/a.md", "committed\n")]


def test_a_key_is_handed_back_and_never_opened(tmp_path):
    """A `DocumentId.key` is OPAQUE (a consumer may compare, sort and hand it
    back, and may not parse it), so every byte comes from the adapter's
    `read` and none from `<worktree>/<key>`. Row-id keys, over a worktree
    that holds no file at all, are read in full."""
    assert list(tmp_path.iterdir()) == []
    _register(_TwoScopeCorpus({"row-0017": b"Status: draft\n\nfrom a row\n",
                               "row-0042": b"another row\n"}, documents=()))
    assert wb.session_documents(tmp_path) == [
        ("row-0017", "Status: draft\n\nfrom a row\n"),
        ("row-0042", "another row\n"),
    ]


def test_the_size_bound_is_measured_on_the_text_as_before(tmp_path):
    """`len(text.encode("utf-8")) <= max_bytes`, on the decoded text, as the
    reach this replaced measured it: a document AT the bound is kept, and one
    byte over it is skipped."""
    at_bound = "x" * 9 + "\n"
    over = "y" * 10 + "\n"
    _register(_TwoScopeCorpus({"at.md": at_bound.encode(), "over.md": over.encode()},
                              documents=()))
    assert wb.session_documents(tmp_path, max_bytes=10) == [("at.md", at_bound)]


# --------------------------------------------------------------------------
# 5 — one scope registration
# --------------------------------------------------------------------------

@pytest.mark.parametrize("not_a_scope", [None, "", "   ", 3, ("documents",)])
def test_only_a_scope_name_can_be_registered(not_a_scope):
    with pytest.raises(TypeError, match="takes the NAME of a scope"):
        wb.register_session_notebook_scope(not_a_scope)
    assert wb.session_notebook_scope() == ca.SCOPE_ALL


def test_registering_the_same_scope_again_is_a_no_op():
    """Compared by VALUE: a host that builds the name at run time registers
    the same scope, not a different one."""
    wb.register_session_notebook_scope("documents")
    same = "".join(["docu", "ments"])
    assert wb.register_session_notebook_scope(same) == "documents"
    assert wb.session_notebook_scope() == "documents"


def test_a_different_scope_is_refused_and_the_first_stays():
    wb.register_session_notebook_scope("documents")
    with pytest.raises(wb.WorkbenchError) as refused:
        wb.register_session_notebook_scope("lifecycle")
    assert "opendox.workbench.unregister_session_notebook_scope()" in str(
        refused.value)
    assert wb.session_notebook_scope() == "documents"


def test_unregistering_returns_the_notebook_to_all(tmp_path):
    adapter = _TwoScopeCorpus({"docs/a.md": b"a\n", "code/b.py": b"b\n"},
                              documents=("docs/a.md",))
    _register(adapter)
    wb.register_session_notebook_scope("documents")
    wb.unregister_session_notebook_scope()
    assert wb.session_notebook_scope() == ca.SCOPE_ALL
    assert [key for key, _ in wb.session_documents(tmp_path)] == ["code/b.py",
                                                                 "docs/a.md"]


# --------------------------------------------------------------------------
# 6 — no reach: an importable `doc_health` is not touched, and the static half
# --------------------------------------------------------------------------

def test_an_importable_doc_health_is_never_reached(tmp_path, monkeypatch):
    touched: list[str] = []
    for name in ("doc_health", "doc_health.corpus"):
        monkeypatch.setitem(sys.modules, name, _TrapModule(name, touched))

    unregistered = _outcome(lambda: wb.session_documents(tmp_path))
    _register(_TwoScopeCorpus({"docs/a.md": b"a\n"}, documents=()))
    registered = _outcome(lambda: wb.session_documents(tmp_path))

    assert touched == [], f"the notebook reached the publisher's package: {touched}"
    assert isinstance(unregistered, ca.CorpusRefused)
    assert registered is None


def _named(node: ast.AST) -> list[str]:
    """F4.1's `named()`, word for word: every import, and every
    `import_module`/`__import__` call with a literal name."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
            and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__"):
        return [node.args[0].value] if isinstance(node.args[0].value, str) else []
    return []


def _deferred_foreign_reaches(tree: ast.AST) -> list[str]:
    """F4.1's `deferred()`, filtered as its scan filters: every reach written
    inside a function body that names one of `FOREIGN`."""
    return sorted({
        f"{WORKBENCH_SOURCE.name}:{node.lineno}: {name}"
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        for node in ast.walk(fn)
        for name in _named(node)
        if any(name == f or name.startswith(f + ".") for f in FOREIGN)})


def test_the_seam_is_in_workbench_py():
    tree = ast.parse(WORKBENCH_SOURCE.read_text(encoding="utf-8"),
                     str(WORKBENCH_SOURCE))
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert [name for name in SEAM_FUNCTIONS if name not in defined] == []


def test_workbench_py_makes_no_deferred_reach_into_the_publisher_or_the_consumer():
    """`session_documents` was the last of `workbench.py`'s four reaches, so
    F4.1's scan now finds none anywhere in the module."""
    tree = ast.parse(WORKBENCH_SOURCE.read_text(encoding="utf-8"),
                     str(WORKBENCH_SOURCE))
    hits = _deferred_foreign_reaches(tree)
    assert hits == [], "a deferred reach into the publisher or the consumer:\n  " \
        + "\n  ".join(hits)


def test_the_static_check_would_catch_the_reach_it_replaced():
    """The negative control, because the assertion above proves an ABSENCE."""
    replaced = (
        "def session_documents(worktree, *, repository=None, max_bytes=0):\n"
        "    from doc_health import corpus            # lazy\n"
        "    return corpus.load_docs(repository, worktree)\n"
    )
    assert _deferred_foreign_reaches(ast.parse(replaced)) == [
        "workbench.py:2: doc_health"]
