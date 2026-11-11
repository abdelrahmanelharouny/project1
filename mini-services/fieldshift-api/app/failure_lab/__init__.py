"""P2 package: Rotation Failure Lab (workstream D).

Deterministic stress-testing of candidate rotations under named stress packs
(`contracts`: pack specs + provenance, `metrics`: robustness math on the
candidate×pack matrix, `engine`: the pure evaluation core, `service`: run
orchestration + persistence). Honesty rules carry over from the rotation
core: missing evidence is never zero, every approximation carries its basis
string, and no composite score crosses units.
"""
