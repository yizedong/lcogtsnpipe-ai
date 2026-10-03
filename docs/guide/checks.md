# What each stage checks, and what to do

Every stage checks every frame and writes `<frame>.<stage>.qa.json` next to the image (status `ok`, `warn`, `fail` or
`skipped`, the measured `metrics`, the `thresholds` they were judged against, and `messages`). The step result in
`results/<universe>/<step>.json` collects them. The limits below are the ones in the code.

**ok**: nothing to do. **warn**: the frame continues; it is put in the review queue ([review.md](review.md)).
**fail**: the frame stops at this stage and is left out of the light curve; it is in the review queue.
**skipped**: already done earlier, or an earlier stage did not produce what this one needs (listed under
`skipped_missing_input` in the step result; if nothing at all could be processed the stage exits 3).

| stage | check | limit | on failure |
|---|---|---|---|
| ingest | every listed frame placed | all | exit 3; the missing file names are in the result |
| catalogs | every catalog found or downloaded | — | exit 4 (service down: rerun later; field outside SDSS: universe `sloan_source: panstarrs`) |
| wcs | Gaia stars matched | ≥ 10 | re-fit; still too few: fail (`wcs=9999`, frame dropped) |
| wcs | rms of the match | ≤ 2″ | re-fit, then fail |
| wcs | median offset | ≤ 1″ | warn |
| cosmic | fraction of pixels flagged | ≤ 1 % | warn (often a bad frame: trails, saturation, clouds) |
| psf | \|aperture correction\| | ≤ 0.1 mag (`max_apercorr`) | automatic retries (below); all fail: fail |
| psf | PSF stars | ≥ 3 | warn |
| psfmag | fitted position vs the transient's position | ≤ max(2 px, FWHM/2) | warn |
| psfmag | same | ≤ 2 FWHM | fail: the fit is on something else; the PSF magnitude is not used |
| psfmag | PSF-fit error | defined | fail (fit did not converge) |
| psfmag | change between background iterations | ≤ 0.05 mag | warn |
| zcat | calibration stars kept after clipping | ≥ 5 | warn |
| diff | noise of the difference / noise expected from science and reference | ≤ 3 (warn above 1.5) | fail: wrong flux scale or misregistration |
| diff | field-star cancellation: fraction of field-star flux left in the difference | ≤ 10 % (warn above 3 %) | fail: flux ratio or registration off |
| diff | flux ratio used vs the field-star ratio | ≤ 3 % | warn |
| diff | masked fraction | ≤ 50 % | warn |
| diff | reference of the frame's telescope class | exists | skipped ("no reference for this telescope class"), not an error |
| mag | difference magnitude − unsubtracted aperture magnitude (SN + host light) | ≥ −0.2 | fail: the difference cannot be brighter than all the light in the aperture |
| getmag | point vs the median of its neighbours (±1.5 d, same band) | 5σ, ≥ 0.1 mag | flagged, kept (look at it) |

Any metric that comes out undefined (NaN) fails its check.

## Automatic retries for a failed PSF (`psf_auto_fix: ladder`)

The manual's advice, applied in order until the aperture-correction check passes (each attempt is recorded in
`metrics.attempts`; at most 600 s per frame):

1. default settings
2. 0.4-m frames: FWHM 5 px, then 7 px
3. FWHM × 1.25, then × 1.5
4. saturation level just below the brightest PSF star
5. 12 PSF stars
6. stars from the APASS catalog, then from the SDSS catalog

## Common situations

| you see | likely cause | what to do |
|---|---|---|
| ingest exit 3, frames missing | files not downloaded or frames.json lists more than the folder has | fetch the files; or reduce the DAY-OBS range |
| catalogs exit 4 | archive or catalog service down | rerun `snpipe run` later (it resumes) |
| most psf frames of one telescope fail | wrong saturation or a defocused/trailed night | look at the packets; `bad` the frames, or redo with `--param fwhm=...` |
| psfmag fails on many frames of a night | the transient is faint/absent, or coordinates wrong | check `ra`/`dec` in target.yaml against the packet stamps |
| zcat warn on a whole filter | few catalog stars in that filter (e.g. B on 0.4 m) | accept, or change `bv_catalog` / `gri_catalog` |
| diff warns/fails on field-star cancellation | flux ratio off (zero point of a cloudy frame?) or registration | look at the packet: stars as dipoles = registration, stars as positive/negative blobs = flux ratio; check the frame's zero point |
| every frame of one class skipped in diff | no reference for that telescope class | add a reference for the class (an LCO night, or `survey: ps1`/`sdss`) or accept unsubtracted points |
| mag fails (difference brighter than total) | bad subtraction or bad unsubtracted measurement | review both packets |
| no difference images for a filter | no reference frame in that filter | expected; the unsubtracted light curve still has it |
