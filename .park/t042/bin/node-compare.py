#!/usr/bin/env python3
"""Compare two junit files node by node: missing, changed outcome, skips, added."""
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def nodes(path):
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        tags = {child.tag for child in case}
        outcome = ("failed" if "failure" in tags else "error" if "error" in tags
                   else "skipped" if "skipped" in tags else "passed")
        if key in out:
            raise SystemExit(f"duplicate node id {key}")
        out[key] = outcome
    return out


base, head = nodes(sys.argv[1]), nodes(sys.argv[2])
missing = sorted(set(base) - set(head))
changed = sorted(k for k in set(base) & set(head) if base[k] != head[k])
added = sorted(set(head) - set(base))
skips_b = {k for k, v in base.items() if v == "skipped"}
skips_h = {k for k, v in head.items() if v == "skipped"}
print(f"baseline nodes {len(base)} {dict(Counter(base.values()))}")
print(f"head nodes     {len(head)} {dict(Counter(head.values()))}")
print(f"missing at head: {len(missing)}")
for k in missing[:20]:
    print("  MISSING", k)
print(f"changed outcome: {len(changed)}")
for k in changed[:20]:
    print("  CHANGED", k, base[k], "->", head[k])
print(f"skipped set identical: {skips_b == skips_h} ({len(skips_b)} vs {len(skips_h)})")
added_out = Counter(head[k] for k in added)
print(f"added: {len(added)} {dict(added_out)}")
by_file = Counter(k.split("::")[0] for k in added)
for f, n in sorted(by_file.items()):
    print(f"  +{n} {f}")
for k in added:
    if "test_health_store" not in k:
        print("  ADDED-OUTSIDE-STORE", k)
