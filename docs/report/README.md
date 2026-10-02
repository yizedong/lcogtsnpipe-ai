# lcogtsnpipe → snpipe: stage-by-stage report on SN 2024pxl

*Status: 2026-10-02. Numbers marked (subset) use the 99 frames of 2024-07-22…28 that both pipelines reduced;
the full new light curve and the `diff_gain=zeropoint` test are added in §6–7 when the running reductions finish.*

## 1. What was done

* **Old pipeline installed without Docker** (README "manual installation", modernised to the Dockerfile's
  Python 3.11 versions): conda env, IRAF built from source (commit d980a65, `make test`: 133 passed), PyRAF 2.2.4,
  HOTPANTS, cdsclient, MySQL 9.7 server in user space, lcogtsnpipe from a copy of the repository. Two local patches,
  both build-system only (a `yacc`→`bison -y` wrapper; `printf` instead of `echo` for `\n` in `irafcl.sh` on RHEL).
* **New pipeline `snpipe`** (this repository): pure Python (numpy, scipy, astropy, photutils, sep, astroscrappy,
  astroquery, reproject; PyZOGY bundled). `pip install` in an empty virtual environment installs it and all
  dependencies from PyPI; the test suite passes (5/5).
* **Data**: 551 BANZAI frames of SN 2024pxl (B g V r i, 1 m Sinistro + 0.4 m QHY, 2024-07-22 → 11-10) and the
  18 pre-explosion 1 m frames of 2018-03-07 used as templates by Singh et al. (2026), from the LCO archive.
* Same catalog files for both pipelines (APASS DR9, SDSS, Gaia DR3 — the ESA Gaia archive timed out, so the same
  DR3 table was taken from VizieR).

## 2. Stage-by-stage comparison (subset unless noted)

| stage | old (IRAF) | new | reproduction (new − old) | speed |
|---|---|---|---|---|
| ingest + funpack | LCOGTingest + funpack | astropy unpacking | pixels identical (all extensions) | I/O bound |
| catalogs | comparecatalogs (vizquery, astroquery) | same queries/cuts/formats | same files | — |
| cosmic | astroscrappy | identical call | masks and clean images **bit-identical** (18/18) | same algorithm |
| wcs | trusts BANZAI; human `checkwcs` | measured vs Gaia for every frame (rms, offset, matches), refit if bad | n/a (new check) | 1 s/frame |
| psf: aperture phot | daophot `phot` | photutils + IRAF centroid/sky rules | magp2/3/4 **identical** (0.000 median & MAD) | |
| psf: model + PSF phot | daophot `psf` gauss+LUT, `group`, `nstar` | GaussianPRF + 2× LUT (DAOPHOT recipe) in ImagePSF, DAOPHOT grouping, PSFPhotometry with fitted sky | aperture correction +0.004 ± 0.009 (78 frames); sn2 PSF mags −0.001, per-frame σ 0.014 | 39–80 s → ~15 s per frame; parallel |
| psfmag (unsubtracted) | lscsn + daophot `allstar` | Legendre background, IRAF `mode` sky, PSFPhotometry | SN psfmag +0.010 ± 0.035; apmag +0.003 ± 0.010 (78 frames) | 20 → 4.3 s/frame |
| zcat | already Python | ported line by line | z1 +0.0004 ± 0.011, z2 +0.001 ± 0.011 | |
| mag (unsubtracted) | calibratemag | ported | +0.014 ± 0.033 (78) | |
| diff (PyZOGY) | lscdiff: geomap+gregister, seepsf, PyZOGY | reproject (flux-conserving), seepsf-equivalent, PyZOGY with exact 60× faster bad-pixel fill | SN aperture mag on difference images +0.005 ± 0.027 (92; 1 m 0.016, 0.4 m 0.034; median error 0.037) | 181 s → 102 s per frame; 2 in parallel (6.9 GB each) |
| psf / psfmag on differences | seepsf + daophot | same recipe | (included in the line below) | 17 → 0.3 s; 28 → 5.3 s per frame |
| zcat / mag on differences | Python | ported | z1 −0.003 ± 0.003; **calibrated mag +0.002 ± 0.031 (92)** | |

The frames only one pipeline could reduce: none only-old; 19 only-new in the unsubtracted PSF stage (the old PSF
stage failed: 9 on the aperture-correction gate, 10 other errors; the remediation ladder recovered them).

Figures: `psf_stage.png`, `z1_ft1.png`, `psfmag_ft1.png`, `mag_ft1.png`, `z1_ft3.png`, `apmag_ft3.png`,
`mag_ft3.png`, `lightcurve_vs_paper.png`.

### Visual comparisons (`visual/`)

* `visual/psf_models.png` — old PSF rendered by IRAF `seepsf` vs the new model, their difference (≤ 2 % of the
  peak) and radial profiles, for a 1 m frame, a 0.4 m frame and a template.
* `visual/difference_images.png` — science, old difference, new difference and (new − old)/σ around the SN.
* `visual/sn_psf_fit_stamps.png` — the SN fit stamps (original / residual) of both pipelines.
* `visual/one_to_one.png` — new vs old with residual panels: aperture correction, zero point, SN PSF mag,
  calibrated mag (unsubtracted), SN aperture mag and calibrated mag on difference images.
* `visual/pulls.png` — (new − old) / combined error.
* `visual/lightcurves_by_band.png`, `visual/lightcurves_by_band_subset.png` — per band: paper, old, new, residuals.
* `visual/timing.png` — seconds per frame, old vs new.

## 3. Wall-clock for the subset (99 frames)

| stage | old (serial) | new |
|---|---|---|
| psf | 3616 s | ≈ 15 s/frame compute; 3 workers |
| psfmag | 1968 s | 4.3 s/frame |
| diff (PyZOGY) | 17947 s | 6540 s (2 workers) |
| psf on differences | 1659 s | 0.3 s/frame |
| psfmag on differences | 2744 s | 5.3 s/frame |
| zcat + mag | 129 s (unsub.) + 612 s (diff) | 385 s + 588 s on an isolated copy; disk-bound: both read every full image once for the limiting magnitude, so the time follows the disk load |

Where the speed comes from: no Python+IRAF process per image, no shared scratch files (every stage runs frames in
parallel), one photometry and one PSF-fit pass instead of two, vectorised DAOPHOT lookup table, and the exact fast
PyZOGY bad-pixel fill. Where it does not help: disk-bound steps on this network filesystem, photutils' 20–50 s
import per worker, and PyZOGY's memory (6.9 GB per 4k frame limits parallel subtractions on a 16 GB job).

## 4. Light curve vs Singh et al. (2026) (subset)

| band | old − paper | new − paper |
|---|---|---|
| B | −0.045 ± 0.013 | −0.045 ± 0.020 |
| g | +0.026 ± 0.011 | +0.029 ± 0.031 |
| V | −0.031 ± 0.037 | −0.011 ± 0.029 |
| r | −0.005 ± 0.024 | −0.007 ± 0.032 |
| i | −0.005 ± 0.026 | −0.002 ± 0.049 |

(median ± robust σ of point-by-point differences; points matched within 0.02 d.) Both pipelines are equally close to
the published photometry; the B/V offsets of a few hundredths may reflect the paper's (unstated) B/V calibration
catalog or pipeline-version changes since 2024.

## 5. How agents check the reduction (replacing the interactive `check*` stages)

Unattended, the old pipeline accepts everything (its prompts return '' without a TTY). snpipe gives every stage:

1. **Gates** in per-frame `*.<stage>.qa.json` + `qa/<stage>-latest.json`, exit codes (0 ok / 1 QA fail / 2 config /
   3 missing input / 4 external). Fixed limits come from the old code (|apco| ≤ 0.1, WCS rms ≤ 2″); physical ones
   were added where validation showed silent failures: a difference magnitude cannot be brighter than the
   unsubtracted one; difference noise ≫ reference noise means a failed PyZOGY flux-scale fit.
2. **Remediation ladder**: a failed PSF is retried with the manual's fixes (larger FWHM, datamax below the brightest
   PSF star, 12 stars, APASS/SDSS instead of Gaia), within a 10-minute budget; all attempts are logged. It recovered
   the two U templates the old pipeline lost and 19 science frames.
3. **Review packets** (PNG + JSON with the question and allowed verdicts) and `snpipe verdict` (the old y/n/b/d/u
   effects, logged). Examples found during this work:
   * `packets/psf_companion_0087.png` — PSF star 1 has a companion 10 px S; its light enters the lookup table as a
     ghost (aperture correction 0.090, just under the gate; the old pipeline builds the same PSF).
   * `packets/psf_0m4_galaxy_stars_0180.png` — two of the six PSF stars lie on NGC 6384.
   * `packets/diff_0133.png` — target / registered template / difference: SN clean, field-star dipoles show a
     ~0.6 px registration offset (see §8).
4. **ASTRA record** (`examples/sn2024pxl/astra.yaml`, validated with `astra validate`): every stage is an output
   whose recipe is the `snpipe` command; 13 decisions expose the old defaults (catalogs, PSF model, number of PSF
   stars, ladder, apco gate, template camera, normalisation, resampling, region, gain, photometry type).

## 6. Problems found in my port during validation (and fixed)

Each was found by comparing with IRAF on real frames, which is why the comparison was done stage by stage:

* sky estimator: astropy sigma clipping ≠ IRAF `mean` (first-pass cut limited by the data range); annuli touching
  off-chip rows gave apco −4.4 instead of IRAF's −0.07;
* off-image catalog stars were recentred onto the frame edge (IRAF keeps the input position): 15× slower, junk rows;
* grouping by distance only (DAOPHOT uses an overlap S/N test and maxgroup 60): groups of 56 stars on bad-seeing
  0.4 m frames;
* footprint masking in the difference imaging (the IRAF path masks only cosmic rays) made PyZOGY fail;
* `reproject_exact` too slow for 4k frames → `reproject_adaptive(conserve_flux=True)`.

## 7. Rejected option

* PyZOGY on a 2048² cutout around the SN (4× cheaper): SN magnitudes moved by up to 0.2 mag vs full frame —
  PyZOGY's iterative flux-scale fit depends on the star set. Kept only as a non-default option.

## 8. Known limitations and next steps

* Constant PSF over the frame (as DAOPHOT `varorder=0`): 6 PSF stars leave a 0.02–0.04 mag bias and 0.07–0.10 mag
  scatter of PSF vs aperture magnitudes on 1 m frames, in both pipelines. Options: more stars (`psf_nstars`),
  a spatially varying PSF.
* Registration on the WCS leaves ~0.6 px offsets between the 2018 templates and 2024 frames; the old pipeline fits
  the mapping to matched stars (geomap). A star-based refinement is the next improvement for `diff`.
* PSF stars are not checked against the BANZAI bad-pixel mask (neither pipeline).
* Not yet reduced: the remaining full-frame differences (resumable: `new_run/run_diff_priority.sh` without
  `--frames-file`), SNEx2 upload.

## Credits

This pipeline, the IRAF/DAOPHOT source analysis it is based on, the old-pipeline installation, the validation runs
and this report were produced by **Claude (Anthropic, model Claude Opus 5.5) working in Claude Code**, directed and
reviewed by Yize Dong. It builds on lcogtsnpipe (S. Valenti and contributors, MIT), PyZOGY (D. Guevel, MIT) and the
SLIDE package's PyZOGY speed-up idea (Y. Dong, MIT).
