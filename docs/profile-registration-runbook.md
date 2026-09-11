# The host profile: what openDox composes from, and who registers it

**The operational contract RULED ASK-2 requires be written down.** Brett Heap
ruled ASK-2 option (2) on `opensoft/openxFactory#656` comment
[`5628886636`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5628886636),
verbatim:

> **RULED (2): LAZY PROXY** — a module in openDox-code resolves the profile at
> first attribute access; openxFactory registers the real module at process
> start; that operational contract is DOCUMENTED in the runbook.

This is that runbook. It is the whole of what a host has to do, and the whole of
what openDox promises in return.

## Why there is a profile at all

openDox is the **neutral** product. Its command line and its server are
assembled from two halves: the CORE verbs and routes openDox owns, and the
CONTRIBUTED ones a host supplies through the § 2.4 extension points
(`subcommand_extension.SubcommandExtension`, `route_extension.RouteBinding`).

Until the carve, the contributed half came from an in-tree file,
`profile_openxfactory.py` — openxFactory's own profile, sitting inside the
neutral product. The § 3 carve files it `not_moved / deleted_at_carve` in
openxFactory's `docs/opendox-carve-manifest.yaml`: *"the one file the § 3 carve
deletes rather than moves — after the carve openXdox declares its own profile
and openDox's core has no line naming any."* `cli.py` went on reading the name,
so `build_parser()` raised `NameError: profile_openxfactory` for every caller
(the finding, comment
[`5633826227`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5633826227)).

The name is now bound to a **lazy proxy** over a registration a host makes.

## The contract

```python
import opendox.domain_profile as domain_profile

domain_profile.register(<the host's profile module or object>)
```

* **ONCE**, at **process start** — before the first `cli.build_parser()` or
  `serve.build_server()`.
* By the **host's own adapter**. Adapter code stays in openxFactory (design
  § D3); nothing in the neutral packages registers a profile for a host, and
  nothing in them ships one.
* A **module** or an **object**. ASK-2's words are "registers the real module";
  § 4.4's form is an object built from a YAML profile (RULED ASK-4 Q1: YAML
  canonical, dataclass the runtime form). Both are accepted.
* **Nothing is type-checked.** openDox cannot name
  `openxdox.domain_profile.DomainProfile` without recreating the back-import the
  carve removed, and it has never heard of openxFactory. It names only the
  attributes it reads.

### What openDox reads off it

| attribute | read by | shape |
| --- | --- | --- |
| `SUBCOMMAND_EXTENSIONS` | `cli.build_parser()` | a tuple of `subcommand_extension.SubcommandExtension` |
| `ROUTE_EXTENSIONS` | `serve.build_server()` | a tuple of `route_extension.RouteExtension` |

Reads happen at **first attribute access**, never at import time. `import
opendox.cli` and `import opendox.profile_proxy` touch no registry and cannot
fail for want of a host, and `serve.py` binds the proxy INSIDE `build_server()`
rather than in its import header.

**Both composition points read the same registration.** `build_parser()` reads
`SUBCOMMAND_EXTENSIONS` where it assembles its subcommands; `build_server()`
reads `ROUTE_EXTENSIONS` where it collects its route bindings, placing the
host's routes **ahead of** the caller's `route_extensions=` tuple — the order
the pre-carve tree had, restored unchanged. `route_extensions` remains the
§ 2.4 seam for whatever a caller adds ON TOP, and its default `()` still means
"add nothing".

### What happens when a host does not

**It refuses, and the refusal names the call.** There is no fallback and no
empty tuple:

```
no host profile is registered, so openDox has no contributed subcommands and no
contributed routes to compose from. openDox is the NEUTRAL product and ships no
profile of its own: the § 3 carve deleted the in-tree `profile_openxfactory.py`
rather than moving it, and the descendant that drives openDox registers its own
profile at process start with

    opendox.domain_profile.register(<the host's profile>)

before it calls `cli.build_parser()` or `serve.build_server()` (RULED ASK-2
option (2), openxFactory#656 comment 5628886636; the operational contract is
docs/profile-registration-runbook.md). This is a REFUSAL, not a missing default:
composing from an empty profile would produce a parser with its contributed
verbs silently absent, which looks exactly like a working one.
```

An empty tuple was refused because it is the failure that cannot be seen. A CLI
missing its contributed verbs and a server missing its contributed routes both
look exactly like working ones, until someone types the missing command.

The other two refusals:

| raised | when | what it means |
| --- | --- | --- |
| `domain_profile.ProfileNotRegistered` | nothing registered | the host's process-start hook did not run |
| `profile_proxy.ProfileFacetMissing` | registered, facet absent | the hook ran; the PROFILE is missing an attribute. An `AttributeError` subclass, so `hasattr` / `getattr(..., default)` keep their meaning |
| `domain_profile.AlreadyRegistered` | a second, DIFFERENT profile | one registration is the contract. Re-registering the same object is a no-op, so an idempotent start-up is not punished; a deliberate swap calls `unregister()` first |

## One registration, two accessors (RULED ASK-4 Q5)

Q5 — comment
[`5634195861`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5634195861)
— ruled **one registration, two accessors**: `openxdox.domain_profile.current()`
rides the same registration as this proxy. It is realized as:

**This leg's registry is the shared seam.**

```
                  the host's ONE call, at process start
                  opendox.domain_profile.register(profile)
                                 |
                 +---------------+----------------+
                 |                                |
    opendox.profile_proxy              openxdox.domain_profile.current()
     .profile_openxfactory              (its own registry empty ->
      -> reads it directly                _upstream() imports
                                          "opendox.domain_profile" LATE and
                                          consults is_registered() / current())
```

openXdox **pins** openDox (`contracts/opendox-pin.yaml`, § 4.2, RULED OQ-2), so
openXdox reaching openDox is the lawful direction, and it is the only one used.
**No import is added between the two legs in the forbidden direction**: nothing
in openDox names, imports or requires `openxdox`, which
`tests/test_consumer_reach.py` measures at 0 import-time reaches.

The delegation is not a shape invented here: openXdox-code #14 already declares
`_UPSTREAM_REGISTRY = "opendox.domain_profile"` and duck-types this module on
`is_registered()` / `current()`. **The module path is therefore part of the
contract** — renaming `opendox/domain_profile.py` breaks Q5's one registration
silently, and `tests/test_profile_registration.py` pins it for that reason.

**One object, two readers.** Each reader names only what it reads: openDox
reaches `SUBCOMMAND_EXTENSIONS` / `ROUTE_EXTENSIONS` and type-checks nothing;
openXdox type-checks its own `DomainProfile` and treats anything else as "not
here", leaving its own refusal standing. A host that wants one registration to
serve both therefore registers a profile that satisfies both readers — for
example an `openxdox.domain_profile.DomainProfile` carrying the two extension
tuples. **That composition is the host's.** openDox refusing an object for
lacking a facet it does not itself read would be the neutral leg legislating for
the other one.

**The alternative rejected:** *the host calls BOTH legs' `register()` in one
documented process-start hook.* Simpler to write down; refused because (1) it is
two registrations wearing one hook's name, and two states that can disagree is
exactly the failure `AlreadyRegistered` exists to refuse — Q5's words are "one
registration" — and (2) openXdox-code #14 has already built the delegation to
this module, so the two-call hook would have left that code dead and owed a
second leg's PR to remove it. The one-call shape also survives a host that
installs only openDox.

## How a future `<Domainx>Dox` host does the same

Identically, and that is the point of the shape. A `MedxDox` registers its own
profile with the same one call:

```python
import opendox.domain_profile as domain_profile
from medxdox import profile as medx_profile      # the descendant's OWN adapter

domain_profile.register(medx_profile)
```

openDox learns nothing about Medx by doing so — no name, no import, no branch.
ASK-2 notes option (3), a plugin package the host publishes, as *"the shape
every future `<Domainx>Dox` profile may want; not now"*: when it arrives it
changes how a host's profile is DISTRIBUTED, not this contract, because a plugin
still ends in one `register()` call at process start.

## What a host that only ever built a server must now do

**Register, or `build_server()` refuses.** Between BUILD slice 2b and this slice
a server composed from exactly what its caller handed it: 2b removed `serve.py`'s
`ROUTE_EXTENSIONS` reach outright rather than repairing it, because repairing it
needed a ruling it did not have. Brett Heap RULED **ASK-6 → 1** on comment
[`5635150678`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5635150678)
— *"the routes half of § 4.3 — serve.py reads the proxy too ... the same author
adds the server-side binding in the same PR (one mechanism, one registration,
under ASK-2)"* — and the reach is back, through this proxy.

So a process that builds a server now registers a profile first, exactly as one
that builds a parser does. This is the same **REFUSAL, NOT A DEFAULT** stance,
applied for the same reason: a server silently missing its contributed routes
looks exactly like a working one. It also makes
`domain_profile.current()`'s message true of both readers rather than one — that
text has always said "before it calls `cli.build_parser()` or
`serve.build_server()`".

The edit is **declared**: openxFactory's carve manifest declares carve lines
`:1371` (the deferred profile import) and `:1380-1381` (the `collect_bindings`
reach) on the `scripts/ideation_dashboard/serve.py` row, the second under the
row annotation RULED Q-L1 ([`5628560136`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5628560136))
that landed with PR-2 #940. The restored expression is **byte-identical to the
carve commit's own two lines**; only the module the name is bound to changed.

## Owed, and deliberately not taken here

* **The docstring corrections.** `cli.build_parser()`'s docstring and
  `serve.py`'s at `:166` / `:755` / `:1368` still describe the in-tree profile
  ("the one line the § 3 carve deletes rather than moves"). Those lines are not
  ones openxFactory's carve manifest declares for their rows, and an edit
  outside the declared lines is an undeclared movement the arrival verifier
  refuses (RULED OQ-1). **RULED ASK-7 → 1**
  ([`5635150678`](https://github.com/opensoft/openxFactory/issues/656#issuecomment-5635150678))
  leaves all four standing and fixes them "at the next declared-edit window",
  with no manifest rows for prose. In-tree comments carry the correction until
  then — the posture BUILD slice 2b took at the same docstrings, and the one
  this slice takes beside its own two edits.
* **The openxFactory half.** The real profile (the two tuples) and the
  process-start hook that calls `register()` are adapter code, and adapter code
  stays in openxFactory (design § D3). PR-2 (#940) has landed at `cc4ae9d3`;
  the adapter is the act after it.

## Where this is executed rather than described

`tests/test_profile_registration.py`, which `validate` runs. Thirty cases:
import-time inertness (in a subprocess), the unregistered refusal and its text,
both facets resolving, the double-registration refusal and the idempotent no-op,
the missing-facet refusal and its `AttributeError`-ness, the dunder and `repr`
probing rules, how a refusal NAMES a profile (two opaque instances of one class
told apart; a hostile `repr` that neither raises nor runs long) and which reader
it names per facet, the duck type openXdox delegates to — module path included
— and **both composition points, executed**.

That last group has to be got at sideways. **Neither `opendox.cli` nor
`opendox.serve` can be imported in this repository at all**: `serve.py:181` still
reaches `ideation_dashboard`, openxFactory's pre-carve package, which exists at
neither carve destination, and `cli.py` imports `serve` and inherits the block.
Both are recorded by name, with the blocker named, in
`tests/test_consumer_reach.py`'s `STILL_REACHING`, and both are owed to a later
act of the BUILD arc.

So the suite lifts each composition point out of its own file **by AST** — the
binding of the proxy, wherever that module puts it, plus the statement that reads
a facet off it — and executes those statements against stand-ins for the two
§ 2.4 seams. What runs is the tree's own lines, so a deleted binding, a renamed
import or a deleted read all fail here, including the original defect
(`NameError: profile_openxfactory` at `build_parser()`) that a unit test of the
proxy alone could never see. It pins the host-ahead-of-caller order, it proves
the unregistered refusal at BOTH readers, it holds `cli.py` to its module-scope
binding and `serve.py` to its deferred one, and none of it is pinned to a line
number that the next declared edit would move — or has to change the day the two
modules become importable.

---

*Status: record. Authored under `split-opendox-two-layer-product` § 4.3, lane
`openxfactory-4-opendox-extraction`. A CREATED file: no carve-manifest row
(RULED OQ-C).*
