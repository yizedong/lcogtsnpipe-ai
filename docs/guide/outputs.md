# What a reduction produces

## results/&lt;universe&gt;/ — the deliverable

```
<workdir>/results/baseline/
├── report.md                 the standard report (below), with report_lightcurve.png
├── lc_subtracted.csv/.ecsv   template-subtracted light curve — the main product
├── lc_unsubtracted.csv/.ecsv light curve without subtraction (includes host light)
├── review_queue.json         review queues per step (docs/guide/review.md)
├── <step>.json               result of every step: status, counts, per-frame metrics/limits/messages
├── logs/<step>.log           everything each command printed
├── run.json                  per step: command, exit code, status, start, seconds; code version (git commit)
└── record/                   the exact astra.yaml, universe and target.yaml that ran
```

### Light-curve columns

| column | meaning |
|---|---|
| dateobs | UTC date of the exposure |
| jd | Julian date of the start of the exposure (header MJD-OBS + 2400000.5), as the old pipeline |
| mag, dmag | calibrated magnitude and its error (photometric + zero point + colour term) |
| telescope | telescope id (e.g. 1m0-05) |
| filter | U B V g r i (short names) |
| magtype | 1 = detection, −1 = upper limit (verdict `ulim`) |
| filename | the frame the point comes from |
| flag | 1 = outlier against neighbours in time (kept; look at it) |

The ECSV header lists `qa_failed`: frames left out because a check failed, and which checks.
Magnitudes are in the system of the calibration catalogs: B and V in the Landolt (Vega) system via APASS, g r i in
the SDSS (AB) system via SDSS or Pan-STARRS.

### report.md

1. target, reference night/camera, working directory; code version and commit (marked if uncommitted changes);
   the universe (every choice);
2. one line per step: status, frames ok / warn / fail / skipped, seconds;
3. light-curve plot (subtracted and unsubtracted side by side, flagged points circled) and per band: points,
   flagged, first/last MJD, brightest magnitude;
4. every frame left out and why; every flagged point;
5. the review queue (items per step);
6. how to reproduce the run.

## The working directory — products per frame

The layout of the old pipeline's `$LCOSNDIR` is kept, so products can be compared file by file:

```
<workdir>/
├── snpipe.sqlite                     database (photlco table as in the old MySQL schema)
├── data/lsc/YYYYMMDD/                1-m frames of that night (data/0m4/ for 0.4 m)
│   ├── <frame>.fits                  unpacked BANZAI frame
│   ├── <frame>.clean.fits, .mask.fits    cosmic-ray cleaned image and mask
│   ├── <frame>.psf.fits, .sn2.fits   PSF model; star table with zero points (header)
│   ├── <frame>.temp.fits             reference copy (reference night only)
│   ├── <frame>.optimal.<cam>.diff.fits   difference image (+ .ref = registered reference, .zogypsf)
│   ├── <frame>.og/.rs/.sf.fits       transient stamps: original, residual, original − fit
│   └── <frame>.<stage>.qa.json       check result of each stage
├── standard/cat/<field>/             catalogs (apass, sloan, gaia, landolt)
├── qa/<stage>-<time>.json            every stage call's summary (and <stage>-latest.json = the last call)
└── review/                           queues, packets, verdicts.jsonl, redo_params.json
```
