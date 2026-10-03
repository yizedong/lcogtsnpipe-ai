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
| `--force` | every step that runs redoes its per-frame products |
| `--sbatch` | print a SLURM job script for the run |

**Resuming.** A step that finished (exit 0 or 1) with the same command and the same inputs is not run again, so
after an interruption just run the same command; the stages also skip frames that are already done. When a step's
command, the target's facts (coordinates, nights, frame lists) or an earlier step changed since it last ran, it is
rerun with its per-frame products redone (`SNPIPE_FORCE=1`). After a code update use `--from STEP --force`.

**On a cluster:**

```bash
snpipe run targets/sn2025rbs --sbatch > job.sbatch   # check partition/time/memory, then
mkdir -p $SNPIPE_WORK/sn2025rbs/results/baseline && sbatch job.sbatch
```

A season of a few hundred frames takes hours, mostly difference imaging (~1-3 min per frame per worker).

## The steps

25 steps, from registering the target to the report: science frames (ingest, cosmic rays, PSF, transient
photometry, zero points, magnitudes, unsubtracted light curve), the reference frames (cleaned, marked, PSF, zero
points), the difference images and their photometry (subtracted light curve), then the review queue and the
report. The full list with what each step does and which decisions it uses: [../reference/recipe.md](../reference/recipe.md);
`snpipe run TARGET --dry-run` prints the exact commands. Step ids are `<stage>_<role>`, e.g. `psf_science`,
`psf_reference`, `diff_science`.

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
snpipe psf --target-file targets/sn2025rbs --frames reference --filetype 4
snpipe psf -n 2025rbs -e 20250801-20250810 -T fa              # without a target file (needs SNPIPE_DIR)
```

Frame selection (as the old `lscloop.py`): `-n NAME`, `-e YYYYMMDD-YYYYMMDD` (DAY-OBS), `-f FILTER...`,
`-T STRING` (file-name substring, e.g. a camera), `-d ID`, `--filetype 1|3|4` (science | difference | reference image),
`-b STAGE` (only frames whose STAGE is not done), `--frames-file LIST`. `-j N` frames in parallel. All options:
[../reference/cli.md](../reference/cli.md).

Running a stage by hand does not update `results/`; run `snpipe run ... --from STEP` afterwards so the light
curves and the report include the change.
