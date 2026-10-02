# Where snpipe differs from lcogtsnpipe, and why

Rule followed: reproduce the old pipeline; change behaviour only for (a) things IRAF/MySQL/Docker-specific
that have no meaning in Python, (b) verified bugs, (c) speed changes that do not change numbers.
Every item says whether its numerical effect was measured.

## Reproduced exactly (verified bit-identical or to IRAF's printed precision)
| item | check |
|---|---|
| funpack of BANZAI `.fz` (SCI → primary, CAT, BPM) | pixels identical in all extensions (astropy vs cfitsio funpack) |
| cosmic (astroscrappy call, datamin→saturation replacement, mask dtypes) | 18/18 frames: masks and clean images identical |
| aperture photometry (IRAF phot: marginal centroid, mean sky with 3σ clipping, apertures 2/3/4 FWHM) | magp2/3/4 identical to 0.000 mag (median and MAD) on 1,230 stars; same recentered positions |
| PSF star selection (pstselect rules) | same 6 stars, same a2 magnitudes |
| phot sky, salgorithm=mean, incl. IRAF's first-pass cut min(mean−dmin, dmax−mean, 3σ) | frame lsc1m004-fa03-20240818-0142 (annulus reaching off-chip rows): same 6 PSF stars, star 16 a2 −8.260 vs IRAF −8.261, apco −0.078±0.091 vs −0.073±0.095. A plain astropy sigma clip gave −9.55 and apco −4.4 |
| catalog files and their queries/cuts | same files used by both pipelines |
| zcat / mag / getmag arithmetic | ported line by line |

## Reproduced with an equivalent algorithm (measured differences)
| item | old | new | measured effect |
|---|---|---|---|
| PSF model | DAOPHOT `psf` gauss + LUT | Gaussian (photutils GaussianPRF) + 2× LUT built with the DAOPHOT recipe, in a photutils ImagePSF | sn2 PSF mags new−old: median ≤0.016, MAD 0.011–0.03 mag (BVgri), 18 frames |
| grouping for PSF fits | DAOPHOT `group` (link r ≤ fitrad+1, or overlap S/N ≥ critsnratio within psfrad+fitrad+1) + nstar maxgroup 60 | same rule (union-find), groups passed to photutils; groups > 60 not fitted | same results on the test frame; 10–20× faster on bad-seeing 0.4-m frames (plain distance grouping gave groups of 56+) |
| PSF photometry | DAOPHOT `nstar` (fitsky=yes) | photutils PSFPhotometry + fitted constant sky | included above; fixed sky would give −0.020 / 0.025 |
| psfmag background | IRAF imsurfit | astropy Legendre2D, same orders, full cross terms, same sections | — |
| psfmag sky | apphot `mode` | port of apmode.x | — |
| alignment for diff | IRAF geomap + gregister (drizzle, fluxconserve) | reproject_adaptive(conserve_flux=True) on the WCS (reproject_exact took >25 min per 4k frame) | — |
| diff masks | registered CR mask; outside the template footprint data=0, unmasked (IRAF path) | same (masking the footprint, as the old --no_iraf path does, makes PyZOGY's gain fit fail with NaNs) | — |
| PyZOGY difference images (full frame) | lscdiff difftype 1 | same call, exact fast bad-pixel fill, parallel | SN aperture mag on the difference images, 92 frames: new−old median +0.005, robust σ 0.027 (1 m 0.016, 0.4 m 0.034; median error 0.037); 6540 s with 2 workers vs 17947 s serial |
| Gaia catalog | ESA archive | ESA archive, VizieR copy of DR3 as fallback (same columns and cuts); ESA archive times out ahead of DR4 | identical source table |

## Speed changes that do not change numbers
| item | verification |
|---|---|
| PyZOGY `interpolate_bad_pixels`: astropy direct 49×49 convolution → separable scipy Gaussian with the same kernel, truncation, NaN and edge handling (SLIDE's idea, but keeping PyZOGY's background subtraction, which SLIDE drops) | max relative difference 1e-14; 60× faster |
| one phot pass and one PSF-fit pass on all catalog stars (old: phot+nstar twice on overlapping lists) | aperture correction unchanged (−0.0232 both ways on the test frame) |
| frames in parallel, per-frame scratch directories | — |
| one DB connection per process, parameterised SQL | — |

## Bugs fixed
Moved to **[bugs.md](bugs.md)** (generated from [bugs.json](bugs.json)): every bug found, fixed or open, including the
ones inherited from the old pipeline, with the reason and the measured effect on SN 2024pxl.

## Behaviour kept although questionable (decide later; listed so it is not silent)
| item | note |
|---|---|
| PS1 catalog query drops the bright limit (duplicate dict key) | kept, ASTRA decision `sloan_source` only switches SDSS/PS1 |
| APASS V transformed with the B colour term (`BBV`) in transform2natural | kept (affects only `zn`, not z1/z2) |
| PSF stars are not checked against the BANZAI bad-pixel mask (a star on a flagged strip near the frame edge can be a PSF star; example lsc1m004-fa03-20240818-0142 star 16) | kept; same in IRAF |
| pstselect accepts a PSF star with a fainter close companion | kept; caught by the review packet (example: elp1m008-fl05-20180306-0087, star 1) |
| template = earliest reference frame per filter | kept |

## Tried and rejected
| option | result |
|---|---|
| PyZOGY on a 2048² cutout around the SN (4× cheaper) | SN difference mags moved by up to 0.2 mag vs full frame (PyZOGY's flux-scale/gain fit depends on the star set) → kept only as a non-default ASTRA option `diff_region=cutout`, documented as not equivalent |
| `--gain zeropoint` (flux scale from zcat zero points, no iterative PyZOGY fit; 4× faster PyZOGY step) | SN mags +0.04–0.06 mag fainter than the iterative fit and the old pipeline (up to +0.2 on 0.4 m g/r/i), 27 subset frames → kept as non-default ASTRA option `diff_gain=zeropoint`, a fallback when the fit fails (fixed 1 of 7 failed frames) |

## Added (no old equivalent)
* remediation ladder for failed PSFs (the manual's advice applied automatically; ASTRA decision `psf_auto_fix`)
* WCS verification against Gaia for every frame (old: human `checkwcs`)
* per-frame QA files, review packets, verdict log, ASTRA record
