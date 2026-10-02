# Reviewing frames and giving verdicts

The old pipeline stopped at `checkpsf`, `checkmag`, `checkdiff`... for a person to look at each frame (and, run
unattended, silently accepted everything). snpipe writes what that person looked at to files instead, so an agent or
a person can review them at any time.

## The review queue

The `review_queue` step (`snpipe review-all`) makes one queue per step that has per-frame results:

```
<workdir>/review/<step>/queue.json      every warn/fail frame + 5 random ok frames (spot check)
<workdir>/review/<stage>/<frame>.png    the picture to look at
<workdir>/review/<stage>/<frame>.json   the question, the allowed verdicts, the metrics, the remediation knobs
```

`results/<universe>/review_queue.json` lists the queues; the report shows how many items each has.
For one stage summary by hand: `snpipe review psf` (uses `qa/psf-latest.json`, i.e. the last psf call only).

## What to look at

| stage | picture | question |
|---|---|---|
| psf | PSF stars on the image, PSF model and profile, data − model of each PSF star | Are the PSF stars isolated, unsaturated single stars, with noise-like residuals? A coherent blob in a residual = a companion or a bad PSF star. |
| psfmag | the transient: original / original − fit / residual | Is the transient well fitted, with no neighbour or edge problem? |
| diff | target / registered reference / difference around the transient | Do the field stars vanish, leaving the transient as the only real residual? |
| zcat | the zero-point numbers | Is the zero-point fit sensible? |

## Verdicts

```bash
snpipe verdict FRAME STAGE accept|redo|bad|delete|ulim --reason "what you saw" [--param key=value ...] [--who name]
```

| verdict | effect | undo |
|---|---|---|
| accept | nothing changes; the verdict is logged | — |
| redo | resets the stage for that frame and stores the knobs given with `--param` (only those the manual lists for the stage, e.g. psf: `fwhm`, `datamax`, `nstars`, `field`) | run the stage again |
| bad | `quality=1`: the frame is excluded from every later selection | not from the command line yet (database edit) |
| delete | diff: removes that difference image (give the `.diff.fits` name); psfmag/getmag: clears the magnitudes | rerun the stage |
| ulim | marks the point as an upper limit | — |

Every verdict is appended to `<workdir>/review/verdicts.jsonl` (time, who, frame, stage, verdict, reason, knobs).

## After verdicts: rerun what depends on them

```bash
snpipe verdict cpt1m012-fa06-20240723-0133-e91.fits psf redo --param datamax=45000 --reason "PSF star 1 saturated"
snpipe run targets/sn2024pxl --from psf_science     # psf redoes the reset frame with the knobs, then everything after
```

Use `--from` with the step of the stage you changed (psf_science, snphot_science, difference_images, ...); the
later steps recompute the light curves and the report.

Give a frame at most two `redo` rounds; if it still fails, mark it `bad` with the reason and leave it for a person.
