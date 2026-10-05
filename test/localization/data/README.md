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

Do not regenerate references merely to make a failing test pass. First investigate
whether a calculation, file format or stable identity was changed. Deliberate
future physics changes require separate review and corresponding reference updates.
