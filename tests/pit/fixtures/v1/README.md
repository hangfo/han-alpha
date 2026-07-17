# Frozen PIT fixture v1

`raw/` contains the only publishable synthetic fixture inputs. `manifest.json`
pins every byte by SHA-256. `invalid/` contains non-publishable contract examples
used to exercise timestamp and referential-integrity failures; they are not inputs
to the valid snapshot.
