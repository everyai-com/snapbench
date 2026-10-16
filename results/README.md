# results

Contributed snapbench results, one JSON file per run, at
`results/<soc part>/<device>/<date>-<id>.json`. Everything in this folder is
released under [CC0 1.0](../LICENSE-DATA).

Only real runs (`"provenance": "measured"`) on Snapdragon hardware belong
here. CI checks every file with `python3 -m snapbench validate --accept`.

To add one, run snapbench on your device and use
`python3 -m snapbench submit FILE` (see the [README](../README.md#contribute-a-run)).
