# Compatibility references

`stage1-reference.json` records an accepted-stage-one snapshot, made before
stage two changed source files. It uses `test/data/regression/simple/motor.ric`,
DEFAULT_PREFERENCES and the recorded ENG settings. Hashes cover the exact JSON
channel arrays, CSV, ENG, BurnSim and the project reserialized with saveFile.
CSV configuration exports all channels and grains. These files and calculations
must stay identical across English/Russian/English.

The text-file byte hashes were recorded with Linux LF line endings. Windows
tests first assert native CRLF output for CSV, ENG and YAML, then normalize only
CRLF to LF for comparison with those references. BurnSim XML bytes and numeric
JSON hashes are compared without normalization. Language-to-language exports on
the same host are still compared byte for byte. No reference hashes were changed
for Windows packaging.

`model-reference.json` records all 18 existing .ric fixtures using the original
staging model code (before localization markers). Each SHA-256 is calculated from
UTF-8 JSON with `sort_keys=True, separators=(',', ':')`, covering the motor dict,
simulation success, every channel array and canonical English alert levels,
types, locations and descriptions. The original and localized model snapshots
were compared exactly before recording the fixture. These hashes include full
floating-point values, without rounding or tolerances that could hide changes.

Native build hosts can use `scripts/compatibility_baseline.py` to replay the
pinned pre-localization ancestor `dcc7fd62045d55036451b833f60e16a786f4685d`.
It archives that exact source, verifies the Cython source is unchanged, uses the
same compiled kernel and numerical runtime, regenerates its original Designer
forms and runs its original engine/exporters in an isolated subprocess. The
resulting references include source/runtime provenance. They are not generated
from the current engine and do not replace the committed Linux goldens.

Windows builds use these independent host references for exact channel/model/
alert/export comparisons. This avoids treating platform floating-point/libm
differences as localization regressions while still rejecting any difference
between the original and localized engine on that same Windows host. The
independent replay was also verified against every committed Linux hash.

Do not regenerate references merely to make a failing test pass. First investigate
whether a calculation, file format or stable identity was changed. Deliberate
future physics changes require separate review and corresponding reference updates.
