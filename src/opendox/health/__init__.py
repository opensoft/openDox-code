"""openDox's document health: its own neutral families (plan 038 T044) and, as
later tasks land, the engine that runs them and the packs a manifest pins
(#1144 requirements 14 and 15).

This package file imports nothing, so importing any module under it costs only
that module's own imports: the CLI's health verbs reach it through the default
profile, and must stay standard-library light (T046).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""
