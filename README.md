# openDox-code

The **code leg** of the `opendox` project: the implementation and its
tests. The requirements it implements live in
[`opensoft/openDox-spec`](https://github.com/opensoft/openDox-spec).

**Clone the assembly root, not this repository.** This leg is mounted as a
submodule at `code/` inside
[`opensoft/openDox`](https://github.com/opensoft/openDox), which
is what pins the commit of this repository that the project currently is:

```sh
git clone --recurse-submodules https://github.com/opensoft/openDox.git
cd openDox
make bootstrap
```

Working here directly is fine — it is an ordinary repository with an ordinary
branch. What advancing this leg does NOT do is advance the project: that is a
commit in the assembly root moving the gitlink, `contracts/code-pin.yaml` and
any workflow `@<sha>` reference together.

Being the code leg confers no authority over the implementation. The split is
navigation; authority travels in grants, and a project that keeps spec and
code in one repository is reviewed identically.

Topic: `xf-project-opendox`.

## Posture

Contributing guidelines and the code of conduct live in the assembly root,
not here: see
[CONTRIBUTING.md](https://github.com/opensoft/openDox/blob/main/CONTRIBUTING.md)
and
[CODE_OF_CONDUCT.md](https://github.com/opensoft/openDox/blob/main/CODE_OF_CONDUCT.md)
in `opensoft/openDox`. Security reports for this repository go through
[SECURITY.md](SECURITY.md). The `validate` check is a required status check
on `main`, enforced by a repository ruleset — see
[docs/branch-protection.md](docs/branch-protection.md). Until the BUILD arc
(`split-opendox` § 3.5/3.6) inverts the openDox → openXdox dependency,
`validate` runs only the scaffold's shape assertions (RULED Q-L5 (b′),
`opensoft/openxFactory#656`, 2026-09-10).

## Documentation

The doc index for this repository. Everything under `docs/` is listed here,
and a new document is linked from this table in the same pull request that
adds it — the xFactory family's standing rule, levelled across all six
`openDox`/`openXdox` repositories by the OQ-O scaffold pass
(`opensoft/openxFactory#656`).

| document | what it is |
|---|---|
| [docs/branch-protection.md](docs/branch-protection.md) | the repository ruleset that makes `validate` a required status check on `main`, its `evaluate` → `active` history, and the one policy difference between the two families |
