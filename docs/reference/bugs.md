# Bugs fixed, and why

32 fixed (5 of them inherited from the old pipeline), 12 open, 2 checked and not bugs. Generated from [bugs.json](bugs.json) by `tools/docs/bugs_page.py`; other deliberate differences from the old pipeline are in [compatibility.md](compatibility.md).

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
| B14 | fixed | snpipe only | review | A 'delete' verdict on a difference image could delete the raw science frame |
| B15 | fixed | snpipe only | run / stages | A changed choice or target re-ran a step, but its stages reused their cached products |
| B16 | fixed | snpipe only | add-target | A corrected target position never reached the database |
| B17 | fixed | snpipe only | survey | Survey reference noise header in the wrong units |
| B18 | fixed | snpipe only | recipe | A target with only survey references stopped at the B/V reference zero points |
| B19 | fixed | snpipe only | selection / recipe | Chosen subtraction variants were invisible to the later steps |
| B20 | fixed | snpipe only | ingest | Per-class reference folders collapsed into the last one |
| B21 | fixed | snpipe only | ingest | A failed survey reference was ignored when LCO references were also present |
| B22 | fixed | snpipe only | mag | Missing star table of a difference image silently brought back the wrong extinction (B01) |
| B23 | fixed | snpipe only | diff | The subtraction noise check disappeared when no flux ratio was known |
| B24 | fixed | snpipe only | psfmag | Difference-image apertures from the reference's seeing only |
| B25 | fixed | snpipe only | ingest | Ingesting reference frames crashed with per-class references |
| B26 | fixed | snpipe only | qa | 'Missing input' when only some frames lacked inputs |
| B27 | fixed | snpipe only | diff | Reference saturation not scaled by the registration's pixel-area ratio |
| B28 | fixed | snpipe only | diff | One unfillable masked cluster turned the whole difference image into NaN |
| B29 | fixed | snpipe only | survey | PS1 reference saturation level was the image maximum |
| B30 | fixed | snpipe only | diff | Frames in a filter the survey does not have were reported as failures |
| B31 | fixed | snpipe only | mag | The "difference cannot be brighter than the total" check compared with the PSF magnitude |
| O01 | fixed | also in the old pipeline | diff | Template PSF is not transformed to the science pixel grid |
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
| O12 | open | also in the old pipeline | zcat | Cloudy frames are not flagged: no check on the zero point itself |
| O13 | open | snpipe only | diff (survey references) | With PS1 references the field stars are over-subtracted by 2-7% |
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

### O01 — Template PSF is not transformed to the science pixel grid
*diff · also in the old pipeline · fix [`1a03262`](https://github.com/yizedong/lcogtsnpipe-ai/commit/1a03262) · found by: Codex review (review_1.md #5); confirmed and measured by the SN 2025rbs diagnosis (reviews/diag_2025rbs_diff.md)*

- **Where:** diff.py (old: lscdiff.py)
- **What was wrong:** The template is resampled onto the science grid, but PyZOGY gets the template PSF in native template pixels.
- **Why it matters:** PyZOGY receives a reference PSF 1.9x too wide when a 1-m reference (0.389"/px) is subtracted from 0.4-m science (0.74"/px). Its flux-ratio (gain) fit then comes out 10-30% low (rerun on 2025rbs frames: 0.187 vs 0.229 true), so the transient is too bright by 0.06-0.36 mag and an uncancelled fraction of the host is added (up to 1-2 mag late for the bright 2025rbs host). Even on 1-m frames the iterative fit is 1-6% low.
- **Fix:** Resample the reference PSF to the science pixel scale before PyZOGY; set the flux ratio from the zero points (matches the field-star ratio within 2%) or flag |fit/zero-point - 1| > 3% (choice pending). Note: this reverses the reading of the earlier diff_gain=zeropoint test (the zero-point ratio was right, the fit biased).
- **Effect on SN 2024pxl:** 2025rbs: 0.4-m difference magnitudes 0.4-1.6 mag brighter than the unsubtracted ones (impossible); 1-m non-tfn sites -0.02..-0.08. 2024pxl: same bias, smaller host; the published light curve (old pipeline, same bug) probably carries it on 0.4-m points. Not yet re-measured after a fix.


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

### B14 — A 'delete' verdict on a difference image could delete the raw science frame
*review · snpipe only · 2026-10-02 · fix [`0db02f3`](https://github.com/yizedong/lcogtsnpipe-ai/commit/0db02f3) · found by: cold-start handover test (fresh agent reading only the repo), verified*

- **Where:** review.py verdict()
- **What was wrong:** The diff QA and review queue are keyed by the science frame name. 'snpipe verdict <science frame> diff delete' globbed '<science stem>*' and removed the raw science image, its star table, all its difference images, and its database row.
- **Why it matters:** Irreversible loss of raw data and every product of that frame, triggered by the natural command an agent would type from the review queue.
- **Fix:** Delete accepts only a .diff. file name (otherwise an error) and removes only files of that difference image.
- **Effect on SN 2024pxl:** None: no delete verdict was ever given on 2024pxl. Tested on dummy files: the science frame is refused; deleting the diff keeps the science image and other variants.

### B15 — A changed choice or target re-ran a step, but its stages reused their cached products
*run / stages · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** run.py, cli.py, catalogs.py
- **What was wrong:** Stages skip frames whose products exist ('psf already calculated'); the recipe never forces, so after changing e.g. the number of PSF stars or the reference night the executor re-ran the step and recorded the new configuration over the old products. catalogs --force only retried empty catalogs.
- **Why it matters:** Results that do not match their recorded configuration.
- **Fix:** A step whose signature changed since it last ran (command, target facts incl. the frames.json contents, input steps) runs with SNPIPE_FORCE=1 and its stages redo their products; snpipe run --force forces everything; catalogs --force re-queries.
- **Effect on SN 2024pxl:** None on the runs so far (no configuration was changed in place).

### B16 — A corrected target position never reached the database
*add-target · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** ingest.add_target, cli.py
- **What was wrong:** An existing target kept its old coordinates; add-target still reported the new ones.
- **Why it matters:** Forced photometry at the wrong position after a coordinate correction.
- **Fix:** Coordinates are updated (and the move reported); the changed target facts make snpipe run redo the position-dependent steps.
- **Effect on SN 2024pxl:** None so far.

### B17 — Survey reference noise header in the wrong units
*survey · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** survey.py
- **What was wrong:** RDNOISE held the sky RMS in image units, but the psf noise model reads it in electrons (variance = data/GAIN + (RDNOISE/GAIN)^2).
- **Why it matters:** Wrong weights in the PSF fits of survey references (background noise 1/GAIN too small).
- **Fix:** RDNOISE = GAIN x sky RMS.
- **Effect on SN 2024pxl:** Found before any production use of survey references.

### B18 — A target with only survey references stopped at the B/V reference zero points
*recipe · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** cli.py cmd_stage
- **What was wrong:** PS1/SDSS have no B or V; the B/V reference zcat selected nothing and exited 3 (missing input), blocking the subtraction.
- **Why it matters:** Survey-reference runs could not finish.
- **Fix:** A stage with no frames because the filter was not observed reports 'nothing to do' (exit 0); missing products still exit 3.
- **Effect on SN 2024pxl:** Found before production use.

### B19 — Chosen subtraction variants were invisible to the later steps
*selection / recipe · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** selection.py, astra.yaml
- **What was wrong:** Variants (.fit = PyZOGY gain fit, .cut = cutout) and cross-class differences were never selected downstream, even when the universe chose them.
- **Why it matters:** A universe with diff_gain=fit or diff_reference_class=any stopped after the subtraction.
- **Fix:** The recipe passes --diff-variant gain:region:reference_class (from the universe) to every step after the subtraction; selection keeps exactly the chosen variant.
- **Effect on SN 2024pxl:** None on baseline runs.

### B20 — Per-class reference folders collapsed into the last one
*ingest · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** target.frames_for, ingest.run
- **What was wrong:** frames_for concatenated all classes' frame records but returned only the last folder.
- **Why it matters:** 1-m reference frames looked up in the 0.4-m folder (or downloaded instead of copied).
- **Fix:** Every record carries its own source folder.
- **Effect on SN 2024pxl:** None (both examples have one reference class).

### B21 — A failed survey reference was ignored when LCO references were also present
*ingest · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** cli.py cmd_ingest
- **What was wrong:** The exit code only considered survey errors when there were no LCO reference frames.
- **Why it matters:** A run continued with a class silently unsubtracted.
- **Fix:** Any failed survey reference makes the step exit 4 (external service).
- **Effect on SN 2024pxl:** None so far.

### B22 — Missing star table of a difference image silently brought back the wrong extinction (B01)
*mag · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** mag.py
- **What was wrong:** Without the difference image's sn2 header, mag fell back to the science frame's site and airmass.
- **Why it matters:** Up to the B01 error (0.15 mag) on such frames, without a warning.
- **Fix:** A difference image without a readable sn2 header fails its mag check ('rerun diff').
- **Effect on SN 2024pxl:** None (all sn2 files present).

### B23 — The subtraction noise check disappeared when no flux ratio was known
*diff · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** diff.py
- **What was wrong:** With no zero points and no field-star ratio, the expected noise was undefined and the check was skipped silently.
- **Why it matters:** A bad subtraction passing without a noise verdict.
- **Fix:** The frame gets a warning 'noise check not evaluated'.
- **Effect on SN 2024pxl:** None observed.

### B24 — Difference-image apertures from the reference's seeing only
*psfmag · snpipe only · 2026-10-03 · fix [`9333d84`](https://github.com/yizedong/lcogtsnpipe-ai/commit/9333d84) · found by: Codex review (reviews/codex/review_5_pipeline.md), verified*

- **Where:** psfmag.py
- **What was wrong:** The aperture radius used the reference's FWHM; a difference image's PSF is about the broader of the two images' (a sharp survey reference with a 2.5" science frame: 3 x 1.2" = 1.4 science FWHM, a few % of the flux lost).
- **Why it matters:** Faint bias of the transient on differences with a much sharper reference.
- **Fix:** Radius from the larger of the reference and science FWHM, so the transient's aperture encloses its flux like the reference stars' magp3 does for the zero point.
- **Effect on SN 2024pxl:** Small for LCO references (similar seeing); matters for survey references.

### B25 — Ingesting reference frames crashed with per-class references
*ingest · snpipe only · 2026-10-03 · fix [`2500a01`](https://github.com/yizedong/lcogtsnpipe-ai/commit/2500a01) · found by: end-to-end runs of 2025rbs*

- **Where:** cli.py cmd_ingest
- **What was wrong:** The result line read reference.dayobs, which no longer exists with one reference per class (KeyError).
- **Why it matters:** The step failed after the frames had been ingested (2025rbs finishing run).
- **Fix:** Fixed with the survey-reference change (2500a01).
- **Effect on SN 2024pxl:** None (frames were ingested).

### B26 — 'Missing input' when only some frames lacked inputs
*qa · snpipe only · 2026-10-03 · fix [`7306d30`](https://github.com/yizedong/lcogtsnpipe-ai/commit/7306d30) · found by: end-to-end runs of 2025rbs*

- **Where:** qa.exit_code
- **What was wrong:** A stage with 746 frames already done and 3 without a PSF exited 3 and stopped the run.
- **Why it matters:** Runs stopped on normal partial results.
- **Fix:** Exit 3 only when every skipped frame lacked its inputs (7306d30).
- **Effect on SN 2024pxl:** Stopped the 2025rbs finishing run once.

### B27 — Reference saturation not scaled by the registration's pixel-area ratio
*diff · snpipe only · 2026-10-03 · fix [`e2086d6`](https://github.com/yizedong/lcogtsnpipe-ai/commit/e2086d6) · found by: SN 2025rbs PS1-reference test run*

- **Where:** diff.py
- **What was wrong:** Flux-conserving registration multiplies the reference's pixel values by the pixel-area ratio (x2.4 for a 0.25"/px PS1 reference on 0.39"/px science) but PyZOGY got the unscaled saturation level: 132,452 pixels of a PS1 i reference were masked as saturated.
- **Why it matters:** Large masked clusters, then an all-NaN difference image (r and i of the 2025rbs PS1 test).
- **Fix:** Saturation level x pixel-area ratio.
- **Effect on SN 2024pxl:** Every PS1 r/i subtraction of the first 2025rbs test failed; none for LCO 1-m references (ratio ~1).

### B28 — One unfillable masked cluster turned the whole difference image into NaN
*diff · snpipe only · 2026-10-03 · fix [`e2086d6`](https://github.com/yizedong/lcogtsnpipe-ai/commit/e2086d6) · found by: SN 2025rbs PS1-reference test run*

- **Where:** diff.fast_interpolate_bad_pixels
- **What was wrong:** PyZOGY's bad-pixel interpolation (49x49 Gaussian) leaves clusters wider than the kernel as NaN, and one NaN makes the FFT-based difference NaN everywhere (the original PyZOGY behaves the same).
- **Why it matters:** A whole frame lost for a local masking problem.
- **Fix:** Pixels still NaN after the interpolation get the median of the valid pixels (identical to PyZOGY elsewhere, test to 1e-14).
- **Effect on SN 2024pxl:** As B27.

### B29 — PS1 reference saturation level was the image maximum
*survey · snpipe only · 2026-10-03 · fix [`e2086d6`](https://github.com/yizedong/lcogtsnpipe-ai/commit/e2086d6) · found by: SN 2025rbs PS1-reference test run*

- **Where:** survey.py
- **What was wrong:** SATURATE = 1.01 x the brightest pixel; the psf stage then picked saturated stars (aperture correction 0.83 mag off for r, rescued only by the ladder's 'datamax below the brightest star').
- **Why it matters:** Bad PSFs of survey references.
- **Fix:** SATURATE = 5th percentile of the pixels PS1 flags SAT or STARCORE.
- **Effect on SN 2024pxl:** 2025rbs PS1 test.

### B30 — Frames in a filter the survey does not have were reported as failures
*diff · snpipe only · 2026-10-03 · fix [`e2086d6`](https://github.com/yizedong/lcogtsnpipe-ai/commit/e2086d6) · found by: SN 2025rbs PS1-reference test run*

- **Where:** diff.py, qa.py
- **What was wrong:** B, V, U frames of a class with a PS1 reference ended as 'template not found' (fail).
- **Why it matters:** Misleading QA for agents.
- **Fix:** Skipped with 'no reference in this filter' (counts as done, not as missing input).
- **Effect on SN 2024pxl:** 99 frames of the 2025rbs PS1 test.

### B31 — The "difference cannot be brighter than the total" check compared with the PSF magnitude
*mag · snpipe only · 2026-10-03 · fix [`85618ba`](https://github.com/yizedong/lcogtsnpipe-ai/commit/85618ba) · found by: SN 2025rbs gain comparison (frames where the subtraction looked brighter than the total)*

- **Where:** mag.py
- **What was wrong:** The bound used the unsubtracted PSF magnitude; on a bright host or a faded transient that fit fails (2025rbs at +400 d: PSF minus aperture +4 to +5.6 mag), so good subtractions failed the check.
- **Why it matters:** Good points dropped from the light curve; misleading QA.
- **Fix:** The bound is the total light in the aperture on the unsubtracted frame: its calibrated magnitude moved from the PSF to the aperture magnitude (same zero point and colour).
- **Effect on SN 2024pxl:** 2025rbs 1 m (field-star gain): 13 of 232 subtracted points failed the old check, 0 the new one.


## Open: verified, not fixed yet

Checked to be real; effect on SN 2024pxl given.

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
- **Why it matters:** Not identical to IRAF, as docs/reference/compatibility.md claims.
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

- **Where:** docs/reference/compatibility.md, docs/report/README.md, README.md, docs/index.html, tools/compare.py, tools/stage_report.py
- **What was wrong:** 'Identical' aperture photometry (9 of 1,230 stars differ by > 0.01 mag, chip edge); headline diff agreement includes a QA-failed -3.94 mag point; '8.1 h -> 2.5 h' is a sum of stage timings with 2 stages estimated; 'WCS checked for every frame' (only 18 templates); paper comparison not reproducible (45 vs 113 matches now); ladder recoveries 19 vs 21 and inferred.
- **Why it matters:** Readers would trust numbers that are not what they say.
- **Proposed fix:** Reword with the real statistics, save frame manifests, plot the exported light curve.
- **Effect on SN 2024pxl:** Documentation only.

### O12 — Cloudy frames are not flagged: no check on the zero point itself
*zcat · also in the old pipeline · found by: end-to-end test of snpipe run (night 2024-07-30 of SN 2024pxl)*

- **Where:** zcat.py (old: none; a person noticed clouds in zcat -i / checkmag)
- **What was wrong:** On 2024-07-30 the lsc 1-m B zero point was 19.5-19.8 against 23.8 the night before (same exposure and airmass): about 4 mag of cloud. Nothing flagged it; the frames were calibrated and the subtractions failed later with noise ratios 9-25.
- **Why it matters:** Thick-cloud frames give poor photometry and failed subtractions; the cause should be named at the zero-point step, not discovered downstream.
- **Proposed fix:** Compare each zero point with the robust median of the same telescope class and filter (ensemble check, as review --ensemble does for the PSF); warn beyond ~0.5 mag, fail beyond ~1.5 mag (thresholds to be set from the 2024pxl season).
- **Effect on SN 2024pxl:** Not yet measured on the season; on this night 6 frames, all with failed or warned subtractions.

### O13 — With PS1 references the field stars are over-subtracted by 2-7%
*diff (survey references) · snpipe only · found by: SN 2025rbs PS1-reference test run*

- **Where:** diff.py star_flux_ratio / survey references
- **What was wrong:** On 1-m LCO frames subtracted with a PS1 stack (flux ratio from the field stars, noise as expected), the field stars leave -2% to -7% of their flux (aperture 4 x the broader FWHM); with LCO 1-m references the same check gives ~0 to +3%.
- **Why it matters:** The transient and the host are then scaled a few % wrong; survey references are not validated until this is understood.
- **Proposed fix:** To find: passband mismatch PS1 vs LCO (colour-dependent ratio; fit the ratio vs colour), PSF mismatch between the 1.2" stack and 2" LCO frames, or the ratio estimate (aperture magnitudes). Measure on the full 2025rbs 1-m set.
- **Effect on SN 2024pxl:** Not yet measured on light curves.


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
