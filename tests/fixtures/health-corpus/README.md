title: Garden notes, the health-check corpus
summary: The entry document of the document health-check fixture; it links the documents meant to be reachable and says what each planted document is for.

# Garden notes, the health-check corpus

This small corpus exists for the document health check. Every planted document
carries exactly ONE finding, and is named after the old id its finding was
first written under. Nothing else in the corpus should be flagged. This file
is an entry document with no link pointing at it, as is the index in the
garden folder; the exemption for entry documents (README and index) is what
keeps both from being flagged as documents nothing links to.

## Documents that are linked from here

- [broken-link.md](broken-link.md) links to a path that does not exist. Its
  target moved: the same file name exists once, elsewhere, in the garden
  folder. The repair is mechanical (auto-fix).
- [derivable-front-matter.md](derivable-front-matter.md) has no title line at
  all, but it has a heading the title can be taken from (auto-fix).
- [candidate/stage-location-mismatch.md](candidate/stage-location-mismatch.md)
  sits in the candidate folder and declares a different stage. The repair
  edits the stage line and never moves the file (auto-fix).
- [near-duplicate.md](near-duplicate.md) repeats
  [compost-bin-sizing.md](compost-bin-sizing.md) almost word for word
  (assisted).
- [empty-stub.md](empty-stub.md) has its header and no body at all (assisted).
  It keeps a header so that it is flagged for being empty and for nothing else.
- [accepted-finding.md](accepted-finding.md) links to a file that exists
  nowhere in the corpus. The link is deliberate, so its finding is the one a
  run accepts as an exception (human-only).
- [candidate/path-edging-options.md](candidate/path-edging-options.md) sits in
  the candidate folder and declares the candidate stage, so it agrees with its
  folder. It is a control: it must not be flagged.
- [garden/rain-barrel-checklist.md](garden/rain-barrel-checklist.md) is where
  the moved link target of the broken link now lives.

## Documents that are not linked from here

- The file human-only-finding.md is deliberately linked from nowhere, so it is
  the one document nothing links to (human-only).
- The file garden/index.md is the second entry document, an index. It also has
  no link pointing at it, and it is exempt.

## Which document is reported for the near-duplicate pair

The two documents of the pair are compared, and ONE finding is raised. It is
raised on the later document of the pair, which is the one that repeats the
other. The corpus is committed in a single commit, so the commit order gives no
answer, and path order decides: the greater path is the later one.
compost-bin-sizing.md sorts first and is the original. near-duplicate.md sorts
last and is the document the finding is raised on. Renaming either file would
silently move the finding to the other, which is why the names are pinned by a
test.
