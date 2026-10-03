# The recipe

Generated from [pipeline/astra.yaml](../../pipeline/astra.yaml) by `python tools/docs/recipe_page.py`. 27 steps, 15 decisions. Step ids are `<stage>_<role>` (role: science, reference, difference); the deliverables are named for what they are.

## Steps

| step | stage | needs | decisions | what it does |
|---|---|---|---|---|
| `target_registered` | add-target |  |  | Target (name, aliases, coordinates) in the pipeline database. |
| `ingest_science` | ingest | target_registered |  | Science frames of the DAY-OBS range copied (or downloaded), unpacked and registered. |
| `ingest_reference` | ingest | target_registered |  | Frames of the reference night copied, unpacked and registered (attached to this target whatever their OBJECT). |
| `catalogs` | catalogs | target_registered | sloan_source | Field catalogs (APASS for B/V, SDSS or Pan-STARRS for g/r/i, Gaia for astrometry), with the old pipeline's cuts. |
| `wcs_science` | wcs | ingest_science, catalogs | wcs_check | Astrometry of every science frame checked against Gaia; re-fitted when it fails the check. (only with wcs_check.gaia) |
| `cosmic_science` | cosmic | ingest_science, wcs_science |  | Cosmic rays found and cleaned (astroscrappy, old pipeline settings). |
| `psf_science` | psf | cosmic_science, catalogs | psf_model, psf_auto_fix, max_apercorr, psf_nstars | PSF model, aperture correction and star photometry (sn2 table) of every science frame. |
| `psfmag_science` | psfmag | psf_science |  | PSF and aperture photometry of the transient on the science frames (background fitted around it). |
| `zcat_science_bv` | zcat | psf_science, catalogs | bv_catalog | Zero points and colour terms of the B and V frames. |
| `zcat_science_gri` | zcat | psf_science, catalogs | gri_catalog | Zero points and colour terms of the g, r and i frames. |
| `mag_science` | mag | psfmag_science, zcat_science_bv, zcat_science_gri |  | Calibrated magnitudes of the transient on the science frames (PSF photometry, colour-corrected). |
| `lc_unsubtracted` | getmag | mag_science |  | Light curve without template subtraction (includes host light): dateobs, jd, mag, dmag, telescope, filter, magtype, flag; plus an .ecsv with the frame of every point. Frames that failed a check are left out. |
| `cosmic_reference_night` | cosmic | ingest_reference |  | Cosmic rays cleaned on the reference night's frames of the reference camera, before they become reference images (the reference copy is made from the cleaned frame, as in the 2024pxl validation run). |
| `template_reference` | template | cosmic_reference_night |  | The reference night's frames marked as reference images (filetype 4, copies of the cleaned frames). |
| `cosmic_reference` | cosmic | template_reference |  | Cosmic rays on the reference images themselves (the old manual's step; a second pass over the cleaned frame, kept so that the references are identical to the validated runs). |
| `psf_reference` | psf | cosmic_reference, catalogs | psf_model, psf_auto_fix, max_apercorr, psf_nstars | PSF model and star photometry of the reference images (the difference images need both). |
| `zcat_reference_bv` | zcat | psf_reference, catalogs | bv_catalog | Zero points of the B and V reference images (difference images normalised to the reference use them). |
| `zcat_reference_gri` | zcat | psf_reference, catalogs | gri_catalog | Zero points of the g, r and i reference images. |
| `diff_science` | diff | psf_science, zcat_science_bv, zcat_science_gri, psf_reference, zcat_reference_bv, zcat_reference_gri | diff_reference_class, diff_normalize, diff_register, diff_region, diff_gain | PyZOGY difference images, science minus the reference of the same telescope class (earliest reference frame per filter); frames of a class without a reference are not subtracted. |
| `psf_difference` | psf | diff_science |  | PSF of every difference image (needed by the transient photometry on it). |
| `psfmag_difference` | psfmag | psf_difference | diff_bkg_order | Photometry of the transient on the difference images. |
| `zcat_difference_bv` | zcat | psfmag_difference | bv_catalog, diff_phot_type | Zero points of the B and V difference images (from the star table of the image they are normalised to). |
| `zcat_difference_gri` | zcat | psfmag_difference | gri_catalog, diff_phot_type | Zero points of the g, r and i difference images. |
| `mag_difference` | mag | zcat_difference_bv, zcat_difference_gri, mag_science | diff_phot_type | Calibrated magnitudes of the transient on the difference images (checked against the unsubtracted ones). |
| `lc_subtracted` | getmag | mag_difference |  | Template-subtracted light curve (the main product), same columns as lc_unsubtracted, plus .ecsv. |
| `review_queue` | review-all | lc_subtracted, lc_unsubtracted |  | Frames to look at: every warn/fail plus a random sample of ok frames, with PNG review packets, for an agent or a person to give verdicts (snpipe verdict). Replaces the old interactive check* steps. |
| `report` | report | lc_subtracted, lc_unsubtracted, review_queue |  | The standard report of the reduction: target and choices, per-step quality summary, frames left out and why, light-curve plots and tables, provenance (code version, universe). Written as report.md with figures next to it. |

## Decisions

The baseline universe selects every default.

### `sloan_source`: Catalog for the g, r, i calibration stars

Changes every g/r/i zero point. The old pipeline uses SDSS unless the field is outside it (then Pan-STARRS).

- `sdss` **(default)**: SDSS PhotoPrimary (comparecatalogs default)
- `panstarrs`: Pan-STARRS1 DR1 (comparecatalogs -p); use for fields outside SDSS

### `wcs_check`: Astrometry check

The old pipeline trusts the BANZAI astrometry and a person runs checkwcs when something looks wrong; frames that BANZAI flags (WCSERR != 0) are then skipped. The Gaia check measures every frame and re-fits failed ones, which recovers those frames; it is not yet validated on a full season, so it is not the default.

- `banzai` **(default)**: Trust BANZAI (old pipeline)
- `gaia`: Check every frame against Gaia DR3 and re-fit failures

### `bv_catalog`: Catalog for the B, V zero points

B and V cannot be calibrated to SDSS; APASS is the field catalog the manual uses.

- `apass` **(default)**: APASS DR9
- `landolt`: Local Landolt sequence of the field (needs standard-star nights; U band)

### `gri_catalog`: Catalog for the g, r, i zero points

The old pipeline and the 2024pxl paper calibrate g, r, i to SDSS.

- `sloan` **(default)**: SDSS (or the Pan-STARRS file, see sloan_source)
- `apass`: APASS

### `psf_model`: PSF model

The PSF shape enters every PSF magnitude and the aperture correction.

- `daophot` **(default)**: Gaussian + 2x residual lookup table (DAOPHOT recipe; old pipeline)
- `epsf`: photutils EPSFBuilder empirical PSF

### `psf_auto_fix`: Automatic retries for failed PSFs

The manual tells the user to retry a failed PSF with a larger FWHM, lower saturation level, more stars or another catalog; without retries those frames are lost.

- `ladder` **(default)**: Apply the manual's fixes automatically, re-checking after each
- `off`: Single attempt (unattended old run)

### `psf_nstars`: Number of PSF stars

Old default 6. With a PSF that is constant over the frame, 6 stars leave a 0.02-0.04 mag bias and 0.07-0.10 mag scatter of PSF vs aperture magnitudes on 1-m frames (both pipelines); the manual suggests 12 as a remedy.

- `n6` **(default)**: 6 (old default)
- `n12`: 12
- `n20`: 20

### `max_apercorr`: Largest accepted aperture correction (mag)

Old pipeline default (--max_apercorr 0.1); a larger correction means the PSF does not describe the stars.

- `apco_0p1` **(default)**: 0.1 mag
- `apco_0p2`: 0.2 mag (looser)

### `diff_reference_class`: Which reference a science frame may be subtracted with

The manual chooses "the best one for each camera-filter combination" and lscloop's default reference camera is the science camera. A 1-m reference for 0.4-m frames (used in the SN 2024pxl validation runs; never in the published light curve, which is 1-m only) mixes pixel scales, PSFs and passbands.

- `same` **(default)**: Same telescope class only; a class without a reference is not subtracted
- `any`: Fall back to another class (1 m first); for tests, record why

### `diff_normalize`: Flux scale of the difference image

Old default --normalize t: difference in reference units, calibrated with the reference's stars (and, since bug fix B01, the reference's airmass).

- `t` **(default)**: reference (template)
- `i`: science image

### `diff_register`: Resampling of the reference onto the science pixels

The old default was IRAF gregister drizzle (flux conserving); the manual warns the bilinear --no_iraf path may be worse.

- `adaptive` **(default)**: reproject_adaptive, flux conserving (closest to drizzle)
- `exact`: reproject_exact (area overlap) x pixel-area ratio; slow
- `bilinear`: reproject_interp bilinear x pixel-area ratio

### `diff_region`: Part of the frame that is subtracted

The old pipeline subtracts the full frame. A 2048x2048 cutout around the target is about 4x cheaper but moved SN magnitudes by up to 0.2 mag on 2024pxl (the flux-ratio fit then uses fewer stars).

- `full` **(default)**: Full frame (old pipeline)
- `cutout`: 2048x2048 px around the target

### `diff_gain`: Flux ratio between science and reference

The ratio from the two images' zero points matches the ratio measured on the field stars within 2% (SN 2025rbs). PyZOGY's iterative fit, the old default, is biased low: by 10-30% on 0.4-m frames when the reference PSF was not resampled (bug O01), and by 1-6% even on 1-m frames; with a bright host this leaves uncancelled host light (0.4-1.6 mag on 2025rbs). The field-star ratio is measured on every frame as a check (warn above 3%).

- `zeropoint` **(default)**: From the photometric zero points (field stars if a zero point is missing)
- `fit`: PyZOGY iterative fit (old pipeline; biased)

### `diff_bkg_order`: Order of the background surface fitted around the transient on difference images

The old reductions (manual and 2024pxl paper runs) use -x 1 -y 1 on difference images, where the host has been subtracted; unsubtracted frames keep the default order 3.

- `order1` **(default)**: First order (plane)
- `order3`: Third order

### `diff_phot_type`: Photometry of the transient on difference images

The old pipeline uses aperture photometry on difference images (the PyZOGY PSF is neither the science nor the reference PSF).

- `ph` **(default)**: Aperture (3 FWHM)
- `fit`: PSF fit
