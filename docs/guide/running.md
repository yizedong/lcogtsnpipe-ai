# Running a reduction

## The whole thing

```bash
snpipe run targets/sn2025rbs                 # all steps of pipeline/astra.yaml with universes/baseline.yaml
snpipe status targets/sn2025rbs              # what ran: status, exit code and time per step
```

`snpipe run` is the executor of the ASTRA recipe [pipeline/astra.yaml](../../pipeline/astra.yaml). It

1. reads the target file, the universe and the recipe, and checks that every decision has a valid option;
2. orders the steps by their inputs;
3. fills each recipe command (`{inputs.target}` = the target file, `{decisions.X}` = the option chosen,
   `{output}` = the step's result file) and runs it in the working directory;
4. records everything in `<workdir>/results/<universe>/` (see [outputs.md](outputs.md)).

Useful options:

| option | effect |
|---|---|
| `--dry-run` | print every command, run nothing |
| `--universe ID` | use `universes/ID.yaml` (own working directory `<workdir>/universe-ID`) |
| `--from STEP` | rerun STEP and every step after it (e.g. after a verdict, or new frames) |
| `--only STEP` | run one step |
| `--keep-going` | when a step stops, still run the steps that do not depend on it |
| `--sbatch` | print a SLURM job script for the run |

**Resuming.** A step that finished (exit 0 or 1) with the same command and the same inputs is not run again, so
after an interruption just run the same command. The stages themselves also skip frames that are already done.

**On a cluster:**

```bash
snpipe run targets/sn2025rbs --sbatch > job.sbatch   # check partition/time/memory, then
mkdir -p $SNPIPE_WORK/sn2025rbs/results/baseline && sbatch job.sbatch
```

A season of a few hundred frames takes hours, mostly difference imaging (~1-3 min per frame per worker).

## The steps

| step | command (stage) | what it does |
|---|---|---|
| target_registered | `add-target` | target in the database |
| science_frames, reference_frames | `ingest` | copy/download, unpack, register frames |
| catalogs | `catalogs` | APASS, SDSS or Pan-STARRS, Gaia field catalogs |
| wcs_science | `wcs` | astrometry checked against Gaia (only with `wcs_check: gaia`) |
| cosmic_science | `cosmic` | cosmic rays |
| psf_science | `psf` | PSF model, aperture correction, star photometry |
| snphot_science | `psfmag` | photometry of the transient |
| zeropoints_bv, zeropoints_gri | `zcat` | zero points and colour terms |
| mag_science | `mag` | calibrated magnitudes |
| lc_unsubtracted | `getmag` | light curve without subtraction |
| reference_marked, reference_cosmic, reference_psf, reference_zeropoints_* | `cosmic`, `template`, `psf`, `zcat` | prepare the reference frames |
| difference_images | `diff` | PyZOGY difference images |
| psf_difference, snphot_difference, zeropoints_difference_*, mag_difference | `psf`, `psfmag`, `zcat`, `mag` | photometry of the transient on the difference images |
| lc_subtracted | `getmag` | the template-subtracted light curve (main product) |
| review_queue | `review-all` | frames to look at, with pictures |
| report | `report` | report.md |

What each stage checks, and what to do when it complains: [checks.md](checks.md).

## Exit codes

Every stage, and `snpipe run`, ends with an exit code:

| code | meaning | what `snpipe run` does |
|---|---|---|
| 0 | ok (warnings possible) | continue |
| 1 | some frames failed their checks | continue; those frames are left out of the light curve |
| 2 | configuration error (target file, options, unknown target) | stop this branch |
| 3 | missing input (no frames selected, earlier stage not done, files missing) | stop this branch |
| 4 | external service failed (archive, catalog server) | stop this branch; retry later |

The step's log is `results/<universe>/logs/<step>.log`; its JSON result lists every frame with its status,
metrics, limits and messages.

## One stage at a time

Every step is a normal command you can run yourself, e.g. to redo one filter:

```bash
snpipe psf --target-file targets/sn2025rbs -f B -F            # -F: redo frames that are already done
snpipe psf --target-file targets/sn2025rbs --frames templates --filetype 4
snpipe psf -n 2025rbs -e 20250801-20250810 -T fa              # without a target file (needs SNPIPE_DIR)
```

Frame selection (as the old `lscloop.py`): `-n NAME`, `-e YYYYMMDD-YYYYMMDD` (DAY-OBS), `-f FILTER...`,
`-T STRING` (file-name substring, e.g. a camera), `-d ID`, `--filetype 1|3|4` (science | difference | reference),
`-b STAGE` (only frames whose STAGE is not done), `--frames-file LIST`. `-j N` frames in parallel. All options:
[../reference/cli.md](../reference/cli.md).

Running a stage by hand does not update `results/`; run `snpipe run ... --from STEP` afterwards so the light
curves and the report include the change.
