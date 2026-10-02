# Targets: describing an object to reduce

Each object gets a folder (anywhere; `targets/` in the repo holds maintained examples):

```
targets/sn2025rbs/
├── target.yaml            facts about the object (this page)
└── universes/
    └── baseline.yaml      the choices: one option per decision of pipeline/astra.yaml
```

Create one with

```bash
snpipe init-target ~/reductions/sn2025xyz --name 2025xyz --alias SN2025xyz "SN 2025xyz" \
    --ra 123.456789 --dec -12.345678 \
    --science 20250801-20251231 --reference 20260905 --camera fa \
    --frames /data/raw/2025xyz            # or: --frames archive; leave out --reference/--camera for no subtraction
```

then read and edit `target.yaml`.

## target.yaml

```yaml
schema_version: 1
name: 2025rbs                       # name in the pipeline database; every stage selects frames by it
aliases: [SN2025rbs, SN 2025rbs]    # other names, e.g. the archive OBJECT spellings
ra: 339.265262                      # degrees: where the transient is (TNS); the photometry is forced here
dec: 34.418892
coordinates: TNS                    # optional: where ra/dec come from
workdir: ${SNPIPE_WORK}/sn2025rbs   # working directory: database, frames, products, results
science:
  dayobs: 20250715-20260917         # DAY-OBS range of the frames to reduce
  frames: ${SNPIPE_RAW}/2025rbs     # folder with frames.json and the files, or "archive"
reference:                          # optional: without it there is no subtraction
  dayobs: 20260918                  # DAY-OBS of the reference (template) night: one night or a range
  camera: fa                        # camera prefix of the reference frames
  frames: ${SNPIPE_RAW}/2025rbs     # optional: default = science.frames
resources:
  jobs: 8                           # frames processed in parallel by most stages
  diff_jobs: 2                      # frames in parallel in difference imaging (~7 GB memory each)
```

* **Relative paths** are relative to the target file; `${VAR}` is replaced by the environment variable (an unset
  variable is an error, not an empty string).
* **DAY-OBS** is the LCO observing-night label in the file name (`cpt1m012-fa06-20240723-0133-e91`), which can
  differ by one from the UTC date of the exposure. Use the file-name date.
* The science range must not include the reference night. Unknown keys, impossible dates and reversed ranges
  are errors. `templates:` is accepted as the old name of `reference:`.
* `workdir` and `resources` only say where and how fast to run; changing them never changes results.

### The reference frames

Difference imaging subtracts a reference image (the old pipeline calls it a *template*) taken when the transient
was not there: before explosion, or long after it faded. Without a `reference` section the run stops after the
unsubtracted light curve (host light included) and still writes the review queue and the report.

* `reference.dayobs` and `reference.camera` select the reference frames: every frame of that night taken with that
  camera (`fa` = 1-m Sinistro, `fl` = older 1-m Sinistro, `sq` = 0.4-m QHY, `ep` = MuSCAT). For each filter the
  earliest frame is used for every science frame of that filter, from any telescope.
* Reference frames often belong to another object in the archive (for 2024pxl they were taken for SN 2017drh in the
  same galaxy). That does not matter: the frames listed for this target are attached to it whatever their OBJECT.
* Filters without a reference frame get no difference images (their frames still get unsubtracted magnitudes).
* U band needs Landolt standard-star nights to calibrate (no all-sky U catalog); see the U-band guide when it lands.

### frames.json and local frames

With `frames: archive` the pipeline queries the LCO archive for `name` and every alias over the DAY-OBS range
(`LCO_API_KEY` for proprietary data) and downloads the frames.

With a folder, the folder must contain the BANZAI files (`*-e91.fits.fz`) and a `frames.json`: the list of LCO
archive frame records of those files, as returned by `https://archive-api.lco.global/frames/` (`results`). The
pipeline reads `filename`, `TELID` (e.g. `1m0a`), `INSTRUME` (e.g. `fa06`), `primary_optical_element` (filter) and
`url` from each record. Frames listed but missing from the folder are reported by the ingest step (exit 3).

## Universes: the choices

`universes/baseline.yaml` selects one option for each decision in [pipeline/astra.yaml](../../pipeline/astra.yaml)
(catalogs, PSF model and retries, number of PSF stars, difference-imaging options, ...). The baseline reproduces
the old pipeline's defaults. To try something else, copy it, change the selections and give it a new `id`:

```bash
cp targets/sn2025rbs/universes/baseline.yaml targets/sn2025rbs/universes/psf20.yaml   # set id: psf20, psf_nstars: n20
snpipe run targets/sn2025rbs --universe psf20
```

A universe other than baseline gets its own working directory (`<workdir>/universe-<id>`), so its products never
mix with the baseline's. Every decision, its options and why the default was chosen are in pipeline/astra.yaml.

Universes are for scientifically defensible alternatives. Bug fixes are not universes: they are code changes,
recorded in [../reference/bugs.md](../reference/bugs.md).
