# Running and checking a reduction as an agent

The old pipeline needed a human at several points (`checkwcs`, `checkpsf`, `zcat -i`, `checkmag`,
`checkdiff`, `getmag --show`). Run unattended, it silently accepted everything (its prompts return ''
without a TTY). snpipe replaces the human with three layers that an agent (or a human) can use.

## 1. Gates — after every command
* Exit code: 0 ok, 1 at least one frame failed its QA gate, 2 config error, 3 missing input, 4 external
  service (archive, catalog server).
* `qa/<stage>-latest.json`: `status`, `counts`, and per frame `status`, `metrics`, `thresholds`,
  `messages`. Per-frame copies sit next to the images as `<frame>.<stage>.qa.json`.
* Fixed gates come from the old code (|apco| ≤ 0.1 mag, WCS rms ≤ 2″, colour term ≤ 0.3 / > 5 stars).
* A failed fixed gate is not the end: the PSF stage applies the manual's remediation ladder
  (larger FWHM, datamax below the brightest PSF star, 12 stars, other catalog) and records every attempt
  in `metrics.attempts`.

## 2. Review packets — what a human used to look at
```
snpipe review psf --ensemble apco fwhm_psf_x_pix   # flags outliers vs frames of the same filter/telescope
cat review/psf/queue.json                           # warn/fail frames + a random sample of ok frames
```
Each queue item points to `review/<stage>/<frame>.png` (fixed layout) and a JSON sidecar with the
question to answer, the allowed verdicts and the remediation knobs. Look at the PNG:
* psf — PSF stars on the image, PSF model and profile, *data − model* of the PSF stars: residuals should
  be noise-like; a coherent blob means a companion or a bad PSF star.
* psfmag — original / original − fit / residual stamps of the target.
* diff — target / registered reference / difference: field stars should vanish.

## 3. Verdicts — recorded, reversible, bounded
```
snpipe verdict FRAME psf redo --param datamax=45000 --reason "PSF star 1 has a companion 10 px S"
snpipe psf -n TARGET -e EPOCH -b psf          # reruns only the frames reset by the verdict, with the knobs
snpipe verdict FRAME psfmag bad --reason "target on a bad column"
```
Verdicts have the database effect of the old interactive answers (y / n / b / d / u) and are appended to
`review/verdicts.jsonl`. `redo` accepts only the knobs the manual lists for that stage. Give up after
two redo attempts and hand the frame to a human.

## ASTRA
`snpipe astra ...` writes `astra.yaml` + `universes/baseline.yaml`. Each output's recipe is the
command above and its artifact is the stage QA summary; decisions are the choices the old pipeline made
through defaults (catalogs, PSF model, ladder, aperture-correction gate, reference camera, normalisation,
resampling, photometry type on differences). Validate with `astra validate`.
