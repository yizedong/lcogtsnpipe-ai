# Bugs fixed, and why

13 fixed (4 of them inherited from the old pipeline), 11 open, 2 checked and not bugs. Generated from [bugs.json](bugs.json) by `tools/bugs_page.py`; other deliberate differences from the old pipeline are in [decisions.md](decisions.md).

| id | status | origin | stage | bug |
|---|---|---|---|---|
| B01 | fixed | also in the old pipeline | mag | Difference-image magnitudes use the wrong airmass in the extinction correction |
| B02 | fixed | also in the old pipeline | getmag | getmag --type ph reports the PSF-fit error for the aperture magnitude |
| B03 | fixed | also in the old pipeline | getmag | getmag -o x.csv writes a space-separated table |
| B04 | fixed | also in the old pipeline | diff | Difference-image rows keep stale photometry of the science frame |
| B05 | fixed | snpipe only | psfmag / getmag | A failed SN PSF fit was exported as a precise measurement |
| B06 | fixed | snpipe only | qa | QA gates let NaN metrics pass |
| B07 | fixed | snpipe only | psf | Off-image catalog stars were re-centred onto the frame edge |
| B08 | fixed | snpipe only | psf | Aperture sky used a plain sigma clip instead of IRAF's 'mean' algorithm |
| B09 | fixed | snpipe only | catalogs | APASS catalog written in sexagesimal instead of degrees |
| B10 | fixed | snpipe only | catalogs | Pan-STARRS fallback did not run when SDSS returned nothing |
| B11 | fixed | snpipe only | db | Worker processes reused the parent's SQLite connection |
| B12 | fixed | snpipe only | wcs / all | One bad frame aborted the whole stage |
| B13 | fixed | snpipe only | diff | Test variants of a difference image overwrote the default image's QA |
| O01 | open | also in the old pipeline | diff | Template PSF is not transformed to the science pixel grid |
| O02 | open | snpipe only | psf | PSF-fit errors on difference images ignore the subtracted sky and reference noise |
| O03 | open | snpipe only | psf | Grouped PSF fits have one sky per star instead of one per group |
| O04 | open | also in the old pipeline | zcat | Zero point 'succeeds' when every calibration star is clipped |
| O05 | open | snpipe only | wcs | An automatic WCS refit can pass QA without being saved |
| O06 | open | snpipe only | psfmag | --no-recenter does not fix the PSF-fit position |
| O07 | open | also in the old pipeline | psfmag | SN stamp coordinates are wrong when the cutout is trimmed at the image edge |
| O08 | open | snpipe only | psf | Aperture pixel weights differ from IRAF |
| O09 | open | snpipe only | psfmag | Binning ignored when the pixel scale comes from CCDSCALE |
| O10 | open | run scripts | run scripts | Job scripts report success when stages fail, and can delete products after a failed copy |
| O11 | open | documentation | report | Report claims stronger than the evidence |
| N01 | not-a-bug | also in the old pipeline | zcat | zcat 'module-global keep' |
| N02 | not-a-bug | snpipe only | tools | compare.py could pair different stars by row index |

## Fixed: bugs inherited from the old pipeline

These are in lcogtsnpipe too, so old and new agreed while both were wrong. Fixing them makes snpipe differ from the old pipeline on purpose.

### B01 — Difference-image magnitudes use the wrong airmass in the extinction correction
*mag · also in the old pipeline · 2026-10-02 · fix [`1c2af5c`](https://github.com/yizedong/lcogtsnpipe-ai/commit/1c2af5c) · found by: Codex review (reviews/codex/review_1.md #2), verified*

- **Where:** mag.py image_table (old: lscdiff.py copies the science row; calibratemag.py uses its airmass)
- **What was wrong:** A difference image normalized to the template (PHOTNORM=t, the default) is in the template's flux scale. Its zero point is measured on the template's stars (the template sn2 header: template airmass and site), but the extinction correction of the SN used the science frame's airmass and site, copied into the diff's database row.
- **Why it matters:** The atmosphere term only cancels when both steps use the same image. Otherwise every point is off by k_template*X_template - k_science*X_science, e.g. ogg0m455-sq30-20240725-0178 (B): 0.23*1.617 - 0.21*1.049 = +0.15 mag too faint.
- **Fix:** mag reads airmass and site from the sn2 header that zcat used, so both steps always refer to the same image. Unsubtracted frames are unaffected (their header and row agree).
- **Effect on SN 2024pxl:** Applied to the 2024pxl run (new_run, 2026-10-02): difference light curve points move -0.150 to +0.120 mag (median -0.022), 54 of 151 by more than 0.05 mag; unsubtracted 499/499 identical. Check against the unsubtracted magnitude of the same frame (calibrated correctly): before the fix the residual tracks the predicted error k_t*X_t - k_s*X_s (slope +0.62), after the fix it does not (slope -0.25); the correlation is weak (0.23) and the overall scatter is unchanged (0.037 -> 0.038), so the case rests mainly on the derivation. Because the old pipeline has the same bug, the published 2024pxl light curve probably carries it too.

### B02 — getmag --type ph reports the PSF-fit error for the aperture magnitude
*getmag · also in the old pipeline · 2026-10-01 · fix [`cb5e1d5`](https://github.com/yizedong/lcogtsnpipe-ai/commit/cb5e1d5) · found by: code survey (notes/survey_stages_B.md bug 9)*

- **Where:** getmag.py (old: myloopdef.run_getmag)
- **What was wrong:** With --type ph the old code paired apmag with psfdmag.
- **Why it matters:** The error belongs to a different measurement.
- **Fix:** Uses dapmag.
- **Effect on SN 2024pxl:** Errors only; magnitudes unchanged.

### B03 — getmag -o x.csv writes a space-separated table
*getmag · also in the old pipeline · 2026-10-01 · fix [`cb5e1d5`](https://github.com/yizedong/lcogtsnpipe-ai/commit/cb5e1d5) · found by: code survey*

- **Where:** getmag.py (old: myloopdef.run_getmag)
- **What was wrong:** The file named .csv was not CSV.
- **Why it matters:** Tools reading it as CSV get one column.
- **Fix:** Real CSV, plus an ECSV with the frame name of every point.
- **Effect on SN 2024pxl:** Format only.

### B04 — Difference-image rows keep stale photometry of the science frame
*diff · also in the old pipeline · 2026-10-01 · fix [`cb5e1d5`](https://github.com/yizedong/lcogtsnpipe-ai/commit/cb5e1d5) · found by: code survey*

- **Where:** diff.py (old: lscdiff.py)
- **What was wrong:** The new row for the difference image is a copy of the science row, including its psfmag/mag/zero-point columns.
- **Why it matters:** A later stage that skips a frame could report the unsubtracted value as the difference value.
- **Fix:** All photometry columns are reset on the difference row.
- **Effect on SN 2024pxl:** None on 2024pxl (all columns were recomputed).


## Fixed: bugs in the new code

Mistakes made while porting, found by comparing with the old pipeline/IRAF, by tests on real data, or by review.

### B05 — A failed SN PSF fit was exported as a precise measurement
*psfmag / getmag · snpipe only · 2026-10-02 · fix [`1c2af5c`](https://github.com/yizedong/lcogtsnpipe-ai/commit/1c2af5c) · found by: Codex review (review_1.md #1), verified*

- **Where:** psfmag.py, getmag.py
- **What was wrong:** When the fit did not converge its error was NaN, and max(0, NaN) stored it as 0. A fit that drifted far from the SN only raised a warning, and getmag did not look at psfmag QA.
- **Why it matters:** A fit 57-10000 px from the SN measures something else; a zero error makes it look like the best point of the night.
- **Fix:** An undefined error is stored as missing (9999); a fit more than 2 FWHM from the SN position fails QA (good fits: median 0.9 px, 90th percentile 1.8 px); getmag drops points whose PSF fit failed when the magnitude comes from the PSF fit. Aperture magnitudes are measured at the aperture centroid and are not affected.
- **Effect on SN 2024pxl:** Applied to 2024pxl: the 16 frames re-fitted and all 16 now fail psfmag QA (fits 15-318 px off the SN, 2.5-42 FWHM); they are no longer in lc_2024pxl_nodiff.csv (515 -> 499 points; the other 499 unchanged). They included two unflagged g points, lsc1m005-fa15-20241003-0063 (19.99 +- 0.005) and -0062 (19.34 +- 0.008), neighbours ~18.86, and one with dmag 8.3e7.

### B06 — QA gates let NaN metrics pass
*qa · snpipe only · 2026-10-02 · fix [`1c2af5c`](https://github.com/yizedong/lcogtsnpipe-ai/commit/1c2af5c) · found by: Codex review (review_1.md #12), verified*

- **Where:** qa.py FrameQA.check
- **What was wrong:** NaN compares False with every bound, so check('noise', NaN, hi=10) returned ok.
- **Why it matters:** An undefined metric means the check could not be made.
- **Fix:** Non-finite metrics fail the gate.
- **Effect on SN 2024pxl:** None found on 2024pxl (no gated metric was NaN).

### B07 — Off-image catalog stars were re-centred onto the frame edge
*psf · snpipe only · 2026-10-02 · fix [`6c111e6`](https://github.com/yizedong/lcogtsnpipe-ai/commit/6c111e6) · found by: agent, investigating slow PSF frames*

- **Where:** psf.py centroiding
- **What was wrong:** IRAF keeps the input position of a star outside the image (OffImage); the port re-centred it onto the nearest edge pixels.
- **Why it matters:** Hundreds of stars piled up in one place, formed one huge PSF-fit group and left junk rows in the star table.
- **Fix:** IRAF rule ported in both centroid functions.
- **Effect on SN 2024pxl:** 247 of 566 frames had off-image stars; they were redone. Worst frames 900 s -> 60 s.

### B08 — Aperture sky used a plain sigma clip instead of IRAF's 'mean' algorithm
*psf · snpipe only · 2026-10-02 · fix [`38a1a21`](https://github.com/yizedong/lcogtsnpipe-ai/commit/38a1a21) · found by: agent, comparing with IRAF on an edge frame*

- **Where:** psf.py phot sky
- **What was wrong:** IRAF first cuts the data range to min(mean-dmin, dmax-mean, 3 sigma); the port skipped that first pass.
- **Why it matters:** Annuli reaching off-chip rows got a badly wrong sky.
- **Fix:** Exact IRAF first-pass rule.
- **Effect on SN 2024pxl:** lsc1m004-fa03-20240818-0142: aperture correction -4.4 -> -0.078 (IRAF -0.073). PSF stage rerun on all frames.

### B09 — APASS catalog written in sexagesimal instead of degrees
*catalogs · snpipe only · 2026-10-02 · fix [`73c4fcc`](https://github.com/yizedong/lcogtsnpipe-ai/commit/73c4fcc) · found by: agent, smoke test of the old pipeline on SN 2025rbs*

- **Where:** catalogs.py apass()
- **What was wrong:** The port converted the coordinates in the wrong direction (old deg2HMS converts to degrees).
- **Why it matters:** zcat cannot match stars; the old pipeline crashed on the file.
- **Fix:** Degrees, verified identical to the old-code APASS file of 2024pxl.
- **Effect on SN 2024pxl:** None on 2024pxl (its catalog was made by the old code); would have broken every new target.

### B10 — Pan-STARRS fallback did not run when SDSS returned nothing
*catalogs · snpipe only · 2026-10-02 · fix [`c7dd431`](https://github.com/yizedong/lcogtsnpipe-ai/commit/c7dd431) · found by: Codex review (review_3.md #9), verified*

- **Where:** catalogs.py run()
- **What was wrong:** An empty SDSS result is stored as '' and the fallback call treated '' as 'already done'.
- **Why it matters:** Fields outside SDSS ended up with no g/r/i catalog.
- **Fix:** '' is retried with --force, or for the sloan field when Pan-STARRS is requested.
- **Effect on SN 2024pxl:** None on 2024pxl or 2025rbs (both inside SDSS).

### B11 — Worker processes reused the parent's SQLite connection
*db · snpipe only · 2026-10-02 · fix [`c7dd431`](https://github.com/yizedong/lcogtsnpipe-ai/commit/c7dd431) · found by: Codex review (review_3.md #2), verified*

- **Where:** db.py connect()
- **What was wrong:** The connection cache was copied into forked workers.
- **Why it matters:** SQLite connections must not cross fork(); concurrent writers can corrupt state or lock.
- **Fix:** A forked process opens its own connection (cache keyed on the process id).
- **Effect on SN 2024pxl:** No corruption seen on 2024pxl.

### B12 — One bad frame aborted the whole stage
*wcs / all · snpipe only · 2026-10-01 · fix [`b688a65`](https://github.com/yizedong/lcogtsnpipe-ai/commit/b688a65) · found by: agent (wcs stage crashed during the run)*

- **Where:** cli.py stage runner, wcs.py
- **What was wrong:** An exception in one frame (sep pixel-buffer overflow) stopped the stage for all frames.
- **Why it matters:** One frame must not stop a reduction.
- **Fix:** Per-frame exceptions become a 'fail' QA record; sep pixstack raised.
- **Effect on SN 2024pxl:** The wcs stage on the 2024 science frames still has to be rerun (only the 18 templates were checked).

### B13 — Test variants of a difference image overwrote the default image's QA
*diff · snpipe only · 2026-10-02 · fix [`e82d4a3`](https://github.com/yizedong/lcogtsnpipe-ai/commit/e82d4a3) · found by: agent*

- **Where:** diff.py, cli.py
- **What was wrong:** The zero-point-gain test run (.zp) wrote its QA file over the default diff's QA.
- **Why it matters:** Light-curve filtering read the wrong verdict.
- **Fix:** Variants keep their own QA file; default selection skips .zp/.cut products.
- **Effect on SN 2024pxl:** 27 QA files overwritten, restored from the summaries.


## Open: verified, not fixed yet

Checked to be real; effect on SN 2024pxl given.

### O01 — Template PSF is not transformed to the science pixel grid
*diff · also in the old pipeline · found by: Codex review (review_1.md #5), verified*

- **Where:** diff.py (old: lscdiff.py)
- **What was wrong:** The template is resampled onto the science grid, but PyZOGY gets the template PSF in native template pixels.
- **Why it matters:** Different pixel scale (0.387 vs 0.74 "/px for 0.4 m science with a 1 m template) or rotation changes the effective PSF.
- **Proposed fix:** Measure the PSF on the registered template (or transform it through the same registration).
- **Effect on SN 2024pxl:** Not measured. Could matter for the 47 difference points from 0.4 m cameras.

### O02 — PSF-fit errors on difference images ignore the subtracted sky and reference noise
*psf · snpipe only · found by: Codex review (review_1.md #3), verified*

- **Where:** psf.py fit weights
- **What was wrong:** Pixel variance = max(data,0)/gain + ron^2; on a sky-subtracted difference image that misses most of the noise. DAOPHOT's chi scaling is also missing.
- **Why it matters:** PSF errors on difference images are underestimated.
- **Proposed fix:** Pass the propagated difference variance, or scale errors by the reduced chi.
- **Effect on SN 2024pxl:** Small: the difference light curve uses aperture magnitudes; unsubtracted PSF errors somewhat underestimated.

### O03 — Grouped PSF fits have one sky per star instead of one per group
*psf · snpipe only · found by: Codex review (review_1.md #4), verified*

- **Where:** psf.py _with_sky
- **What was wrong:** photutils sums the per-star sky terms of a group, so they are degenerate (DAOPHOT fits one group sky).
- **Why it matters:** Rank-deficient fit; covariances of grouped stars are less reliable.
- **Proposed fix:** One shared background parameter per group.
- **Effect on SN 2024pxl:** None or small (the SN fit is a single source).

### O04 — Zero point 'succeeds' when every calibration star is clipped
*zcat · also in the old pipeline · found by: Codex review (review_1.md #6), verified*

- **Where:** zcat.py _calcZC (old: lscabsphotdef.py)
- **What was wrong:** With no stars left, the initial guess is returned with zero error.
- **Why it matters:** A made-up zero point looks exact.
- **Proposed fix:** Fail when no calibrators are kept.
- **Effect on SN 2024pxl:** None on 2024pxl (no zero point with zero error).

### O05 — An automatic WCS refit can pass QA without being saved
*wcs · snpipe only · found by: Codex review (review_1.md #7), verified*

- **Where:** wcs.py
- **What was wrong:** Frames that start as good are opened read-only; a later refit is not written.
- **Why it matters:** Downstream stages read the old WCS.
- **Proposed fix:** Reopen in update mode when a refit is needed.
- **Effect on SN 2024pxl:** None (no refits happened in this run).

### O06 — --no-recenter does not fix the PSF-fit position
*psfmag · snpipe only · found by: Codex review (review_1.md #8), verified*

- **Where:** psfmag.py, psf.py
- **What was wrong:** Only the starting position changes; x0/y0 stay free.
- **Why it matters:** Forced photometry can drift to a neighbour.
- **Proposed fix:** Fix x0/y0 in the fit when recentering is off.
- **Effect on SN 2024pxl:** None (option not used).

### O07 — SN stamp coordinates are wrong when the cutout is trimmed at the image edge
*psfmag · also in the old pipeline · found by: Codex review (review_1.md #9), verified*

- **Where:** psfmag.py (old: lscsn.py)
- **What was wrong:** The stamp origin is computed from the requested size, not the actual cutout origin.
- **Why it matters:** Background exclusion and reported psfx/psfy are offset near edges.
- **Proposed fix:** Use the cutout's own origin in both directions.
- **Effect on SN 2024pxl:** No magnitude effect found; psfx/psfy off by ~1-2 px.

### O08 — Aperture pixel weights differ from IRAF
*psf · snpipe only · found by: Codex review (review_1.md #10), verified*

- **Where:** psf.py (method='exact' vs IRAF's clip(r + 0.5 - d, 0, 1))
- **What was wrong:** Geometric overlap instead of IRAF's linear ramp.
- **Why it matters:** Not identical to IRAF, as docs/decisions.md claims.
- **Proposed fix:** Port the IRAF ramp, or document the difference.
- **Effect on SN 2024pxl:** < 1e-5 mag at the pipeline's 2-4 FWHM apertures.

### O09 — Binning ignored when the pixel scale comes from CCDSCALE
*psfmag · snpipe only · found by: Codex review (review_1.md #11), verified*

- **Where:** psfmag.py
- **What was wrong:** The fallback ignores CCDSUM, unlike psf.pixscale().
- **Why it matters:** Binned frames would get apertures twice too large.
- **Proposed fix:** Use psf.pixscale().
- **Effect on SN 2024pxl:** None (LCO frames have PIXSCALE).

### O10 — Job scripts report success when stages fail, and can delete products after a failed copy
*run scripts · run scripts · found by: Codex review (review_3.md #3-#5), verified*

- **Where:** rawdata/fetch_2025rbs.sbatch, bench/common.sh, new_run_2025rbs/*.sbatch, old_run_2025rbs/*.sbatch
- **What was wrong:** Scripts end with a logging command, so SLURM sees success; the old 2025rbs job marks the export done before copying and then removes scratch.
- **Why it matters:** A dependent job can start on missing data; a 40 h run can lose its products.
- **Proposed fix:** Check expected products, return non-zero on failure, keep scratch if the export fails.
- **Effect on SN 2024pxl:** None so far (all 836 2025rbs frames are valid FITS).

### O11 — Report claims stronger than the evidence
*report · documentation · found by: Codex review (review_2.md), verified (reviews/codex/verify_2.md)*

- **Where:** docs/decisions.md, docs/report/README.md, README.md, docs/index.html, tools/compare.py, tools/stage_report.py
- **What was wrong:** 'Identical' aperture photometry (9 of 1,230 stars differ by > 0.01 mag, chip edge); headline diff agreement includes a QA-failed -3.94 mag point; '8.1 h -> 2.5 h' is a sum of stage timings with 2 stages estimated; 'WCS checked for every frame' (only 18 templates); paper comparison not reproducible (45 vs 113 matches now); ladder recoveries 19 vs 21 and inferred.
- **Why it matters:** Readers would trust numbers that are not what they say.
- **Proposed fix:** Reword with the real statistics, save frame manifests, plot the exported light curve.
- **Effect on SN 2024pxl:** Documentation only.


## Checked and not bugs

Reported as possible bugs; checked and found to be fine.

### N01 — zcat 'module-global keep'
*zcat · also in the old pipeline · found by: code survey*

- **Where:** lscabsphotdef.py
- **What was wrong:** A global statement inside an if.
- **Why it matters:** In Python the global statement applies to the whole function, so it works as intended.

### N02 — compare.py could pair different stars by row index
*tools · snpipe only · found by: Codex review (review_2.md, suspected)*

- **Where:** tools/compare.py
- **What was wrong:** Old and new star tables are paired by row.
- **Why it matters:** Checked: rows at the same index are the same star (positions agree to < 0.001 deg).
- **Proposed fix:** Optional assertion on positions.
