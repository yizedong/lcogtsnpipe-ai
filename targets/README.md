# Example targets

Maintained examples of the target folder format ([docs/guide/targets.md](../docs/guide/targets.md)). Your own
reductions can live anywhere (`snpipe init-target ~/reductions/<name> ...`).

| target | why it is here |
|---|---|
| [sn2024pxl](sn2024pxl/target.yaml) | the validation object: reduced with the old and the new pipeline ([docs/validation/sn2024pxl](../docs/validation/sn2024pxl/README.md)); reference frames from another object (SN 2017drh) |
| [sn2025rbs](sn2025rbs/target.yaml) | reference frames taken a year after the supernova (after it faded); old-vs-new comparison in progress |

Both use `${SNPIPE_RAW}` (raw-frame folders) and `${SNPIPE_WORK}` (working directories); set them before running.
