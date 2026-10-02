# Using snpipe

## Setup

```bash
pip install git+https://github.com/yizedong/lcogtsnpipe-ai     # or: pip install -e . in a clone
export SNPIPE_DIR=/path/to/workdir      # data, database and products live here (like $LCOSNDIR)
export LCO_API_KEY=...                  # only needed to download proprietary LCO data
export SNPIPE_SCRATCH=/local/fast/disk  # optional: scratch for difference imaging
```

## Stages (old `lscloop.py -s …` → `snpipe …`)

Every stage takes the frame selection of lscloop: `-n NAME -e YYYYMMDD-YYYYMMDD [-f FILTER…] [-T TEL] [-d ID]
[--filetype 1|3|4] [-b STAGE] [-F] [-j JOBS]`.

| stage | command | what it does | agent gate |
|---|---|---|---|
| ingest | `snpipe ingest --target NAME --start … --end …` | LCO archive query (or local files), unpacking, database rows | frames placed == queried |
| catalogs | `snpipe catalogs --target NAME` | APASS DR9, SDSS (or PS1), Gaia DR3 | catalog found |
| wcs | `snpipe wcs …` | check the BANZAI WCS against Gaia, refit if bad | rms ≤ 2″, ≥ 10 matches |
| cosmic | `snpipe cosmic …` | astroscrappy (sigclip 4.5, sigfrac 0.2, objlim 4) | CR fraction |
| psf | `snpipe psf …` | PSF model, aperture correction, field-star table; remediation ladder | \|apco\| ≤ 0.1 |
| psfmag | `snpipe psfmag …` | target PSF + aperture photometry | fit stayed on target |
| zcat | `snpipe zcat -f landolt --field apass …` and `-f sloan …` | zero point + colour term | ≥ 5 stars kept |
| mag | `snpipe mag …` | calibrated magnitudes | diff not brighter than unsubtracted |
| template | `snpipe template …` | mark reference frames (filetype 4) | |
| diff | `snpipe diff --tempdate … --temptel fl …` | PyZOGY difference images | difference noise vs reference |
| getmag | `snpipe getmag … -o lc.csv` | light curve (CSV + ECSV with frame names, outlier flags) | running-median outliers |
| review | `snpipe review psf --ensemble apco` | review queue + PNG packets | |
| verdict | `snpipe verdict FRAME psf redo --param fwhm=7 --reason …` | record a review decision | |
| astra | `snpipe astra NAME --ra … --dec … --epoch … --tempdate …` | write the ASTRA record | `astra validate` |

Exit codes: 0 ok · 1 at least one frame failed its QA gate · 2 configuration error · 3 missing input ·
4 external service failure.

## Full recipe: difference-imaging light curve (as Singh et al. 2026 for SN 2024pxl)

```bash
snpipe add-target 2024pxl --ra 263.113958 --dec 7.062411 --alias SN2024pxl
snpipe ingest   --target SN2024pxl --start 2024-07-22 --end 2024-11-10
snpipe catalogs --target 2024pxl
E="-n 2024pxl -e 20240722-20241110"
snpipe cosmic $E && snpipe psf $E
# references taken 2018-03-07
snpipe template -n 2024pxl -e 20180306
snpipe cosmic   -n 2024pxl -e 20180306 --filetype 4
snpipe psf      -n 2024pxl -e 20180306 --filetype 4
snpipe diff   $E --tempdate 20180306 --temptel fl -j 2
snpipe psf    $E --filetype 3
snpipe psfmag $E --filetype 3 -x 1 -y 1
snpipe zcat   $E --filetype 3 -f landolt --field apass --type ph
snpipe zcat   $E --filetype 3 -f sloan --type ph
snpipe mag    $E --filetype 3 --type ph
snpipe getmag $E --filetype 3 --type mag -o lc.csv
```

Memory: PyZOGY needs ~7 GB per 4k frame, so use `-j 2` for `diff` on a 16 GB machine.
