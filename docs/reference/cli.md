# Command reference

Generated from the code by `python tools/docs/cli_page.py`. Exit codes of every command: 0 ok, 1 some frames failed their checks, 2 configuration error, 3 missing input, 4 external service failed.

## Whole reductions

### snpipe run

run the whole recipe (pipeline/astra.yaml) for a target folder

```
snpipe run [-h] [--universe UNIVERSE] [--from STEP] [--only STEP] [--dry-run] [--keep-going] [--recipe RECIPE] [--sbatch] target_dir

positional arguments:
  target_dir           folder with target.yaml and universes/

options:
  -h, --help           show this help message and exit
  --universe UNIVERSE  universes/<UNIVERSE>.yaml (default baseline)
  --from STEP          rerun STEP and every step after it
  --only STEP          run only STEP
  --dry-run            print the commands without running them
  --keep-going         after a stopped step, still run independent steps
  --recipe RECIPE      another astra.yaml (default: the packaged pipeline/astra.yaml)
  --sbatch             print a SLURM job script for this run instead
```

### snpipe status

what ran for a target: status, exit code and time per step

```
snpipe status [-h] [--universe UNIVERSE] target_dir

positional arguments:
  target_dir

options:
  -h, --help           show this help message and exit
  --universe UNIVERSE
```

### snpipe init-target

create <folder>/target.yaml and universes/baseline.yaml

```
snpipe init-target [-h] --name NAME [--alias [ALIAS ...]] --ra RA --dec DEC --science SCIENCE [--reference REFERENCE] [--camera CAMERA]
                          [--frames FRAMES] [--workdir WORKDIR]
                          target_dir

positional arguments:
  target_dir

options:
  -h, --help            show this help message and exit
  --name NAME           name in the pipeline database, e.g. 2025xyz
  --alias [ALIAS ...]   other names, e.g. the archive OBJECT spellings
  --ra RA               degrees
  --dec DEC             degrees
  --science SCIENCE     DAY-OBS range of the science frames, YYYYMMDD-YYYYMMDD
  --reference REFERENCE, --templates REFERENCE
                        DAY-OBS of the reference night
  --camera CAMERA       camera prefix of the reference frames (fa, fl, sq, ...)
  --frames FRAMES       folder with frames.json + the files, or archive
  --workdir WORKDIR     working directory (default: <folder>/work)
```

### snpipe report

write the standard report of a run (report.md + figures)

```
snpipe report [-h] [--target-file TARGET_FILE] -o OUTPUT

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
  -o OUTPUT, --output OUTPUT
                        results/<universe>/report.md
```

### snpipe review-all

review queues (with pictures) for every step of a run

```
snpipe review-all [-h] [--target-file TARGET_FILE] [--sample SAMPLE] -o OUTPUT

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
  --sample SAMPLE       random ok frames per step for spot checks
  -o OUTPUT, --output OUTPUT
                        results/<universe>/review_queue.json
```

## Setup

### snpipe add-target

register a target (name, coordinates, aliases) in the database

```
snpipe add-target [-h] [--target-file TARGET_FILE] [--ra RA] [--dec DEC] [--alias [ALIAS ...]] [--qa-out QA_OUT] [name]

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        take name, coordinates and aliases from target.yaml
  --ra RA
  --dec DEC
  --alias [ALIAS ...]
  --qa-out QA_OUT       also write the result JSON here
```

### snpipe ingest

copy or download frames, unpack them and register them

```
snpipe ingest [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [--target TARGET] [--start START] [--end END]
                     [--filters [FILTERS ...]] [--tels [TELS ...]] [--frames-json FRAMES_JSON] [--local-dir LOCAL_DIR] [-j JOBS] [--qa-out QA_OUT]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml: ingest its science or reference frames (--frames)
  --frames {science,reference}
  --target TARGET       archive OBJECT name (without --target-file)
  --start START         YYYY-MM-DD (without --target-file)
  --end END             YYYY-MM-DD (without --target-file)
  --filters [FILTERS ...]
  --tels [TELS ...]     1m0 0m4 2m0
  --frames-json FRAMES_JSON
                        a saved archive frame list instead of querying
  --local-dir LOCAL_DIR
                        copy files from here instead of downloading
  -j JOBS, --jobs JOBS
  --qa-out QA_OUT       also write the result JSON here
```

### snpipe catalogs

field catalogs: APASS, SDSS or Pan-STARRS, Gaia

```
snpipe catalogs [-h] [--target-file TARGET_FILE] [--target TARGET] [--fields [FIELDS ...]] [--panstarrs] [--sloan-source {sdss,panstarrs}] [-F]
                       [-o OUTPUT]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
  --target TARGET
  --fields [FIELDS ...]
  --panstarrs           same as --sloan-source panstarrs
  --sloan-source {sdss,panstarrs}
  -F, --force           query again even if a catalog is recorded
  -o OUTPUT, --output OUTPUT
                        also write the result JSON here
```

## Stages

### snpipe wcs

check the astrometry of each frame against Gaia; re-fit when it fails

```
snpipe wcs [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE] [-d ID]
                  [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe cosmic

find and clean cosmic rays

```
snpipe cosmic [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE]
                     [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe psf

PSF model, aperture correction and star photometry of each frame

```
snpipe psf [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE] [-d ID]
                  [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [--fwhm FWHM] [--nstars NSTARS]
                  [--datamax DATAMAX] [--datamin DATAMIN] [--max-apercorr MAX_APERCORR] [--field FIELD] [--model {daophot,epsf}]
                  [--auto-fix {ladder,off}]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  --fwhm FWHM
  --nstars NSTARS       number of PSF stars (also accepts the recipe option ids n6, n12, n20)
  --datamax DATAMAX
  --datamin DATAMIN
  --max-apercorr MAX_APERCORR
                        mag (also accepts the recipe option ids apco_0p1, apco_0p2)
  --field FIELD         catalog for the star list
  --model {daophot,epsf}
  --auto-fix {ladder,off}
                        retry failed PSFs with the manual's fixes

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe psfmag

photometry of the transient (PSF fit and aperture)

```
snpipe psfmag [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE]
                     [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [-x XORD] [-y YORD]
                     [--bkg BKG] [--size SIZE] [-c] [--datamax DATAMAX] [--datamin DATAMIN] [--RA RA] [--DEC DEC]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  -x XORD, --xord XORD  background order in x (or order1, order3)
  -y YORD, --yord YORD  background order in y
  --bkg BKG
  --size SIZE
  -c, --no-recenter
  --datamax DATAMAX
  --datamin DATAMIN
  --RA RA
  --DEC DEC

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe zcat

fit zero points and colour terms against a field catalog

```
snpipe zcat [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE] [-d ID]
                   [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [--field FIELD] [--catalogue CATALOGUE]
                   [--unfix] [--type {fit,ph}] [--sigma-clip SIGMA_CLIP] [--match-by-site]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  --field FIELD         catalog system: apass, sloan, landolt
  --catalogue CATALOGUE
  --unfix               fit the colour term instead of fixing it
  --type {fit,ph}       star magnitudes: PSF or aperture
  --sigma-clip SIGMA_CLIP
  --match-by-site

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe template

mark frames of the reference night as reference images (filetype 4)

```
snpipe template [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE]
                       [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe diff

difference images: science minus reference (PyZOGY)

```
snpipe diff [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE] [-d ID]
                   [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [--tempdate TEMPDATE]
                   [--temptel TEMPTEL] [--normalize {t,i}] [--unmask] [--register REGISTER] [--region {full,cutout}] [--gain {zeropoint,fit}]
                   [--cutout-size CUTOUT_SIZE]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  --tempdate TEMPDATE   DAY-OBS (range) of the reference frames
  --temptel TEMPTEL     camera prefix of the reference frames (fa, fl, sq ...)
  --normalize {t,i}     flux scale: reference (t) or science (i)
  --unmask
  --register REGISTER   adaptive | exact | bilinear | bicubic
  --region {full,cutout}
  --gain {zeropoint,fit}
                        flux ratio science/reference: from the zero points (default) or the PyZOGY fit (old default, biased low: bug O01)
  --cutout-size CUTOUT_SIZE

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe mag

calibrated magnitudes of the transient

```
snpipe mag [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE] [-d ID]
                  [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [--type {fit,ph,mag}] [--match-by-site]
                  [-o OUTPUT] [--combine COMBINE]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  --type {fit,ph,mag}   fit = PSF, ph = aperture, mag = calibrated (getmag)
  --match-by-site
  -o OUTPUT, --output OUTPUT
                        getmag: light-curve CSV (an ECSV is written next to it)
  --combine COMBINE     getmag: average points closer than this (days)

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

### snpipe getmag

export the light curve (CSV + ECSV)

```
snpipe getmag [-h] [--target-file TARGET_FILE] [--frames {science,reference}] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]] [-T TELESCOPE]
                     [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--qa-out QA_OUT] [--type {fit,ph,mag}]
                     [--match-by-site] [-o OUTPUT] [--combine COMBINE] [--keep-failed]

options:
  -h, --help            show this help message and exit
  -F, --force           redo frames that are already done
  -j JOBS, --jobs JOBS  frames in parallel (default 8, diff 2)
  --qa-out QA_OUT       also write the stage summary JSON here
  --type {fit,ph,mag}   fit = PSF, ph = aperture, mag = calibrated (getmag)
  --match-by-site
  -o OUTPUT, --output OUTPUT
                        getmag: light-curve CSV (an ECSV is written next to it)
  --combine COMBINE     getmag: average points closer than this (days)
  --keep-failed         keep points whose checks failed

frame selection:
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,reference}
                        with --target-file: the science nights or the reference night
  -n NAME, --name NAME  target name
  -e EPOCH, --epoch EPOCH
                        DAY-OBS range YYYYMMDD-YYYYMMDD
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        filters (landolt, sloan, or B V g ...)
  -T TELESCOPE, --telescope TELESCOPE
                        file-name substring, e.g. a camera (fa) or site (lsc)
  -d ID, --id ID        frame number
  -b BAD, --bad BAD     only frames where this stage is not done (psf, zcat, mag, psfmag, wcs)
  --filetype FILETYPE   1 science, 3 difference, 4 reference
  --frames-file FRAMES_FILE
                        only the frame names listed in this file
```

## Review

### snpipe review

review queue and pictures for one stage (last call of that stage)

```
snpipe review [-h] [--frame FRAME] [--sample SAMPLE] [--ensemble [ENSEMBLE ...]] stage

positional arguments:
  stage

options:
  -h, --help            show this help message and exit
  --frame FRAME         make the picture of one frame
  --sample SAMPLE
  --ensemble [ENSEMBLE ...]
                        metrics to compare against peer frames
```

### snpipe verdict

record a review verdict (agent or person) and apply its effect

```
snpipe verdict [-h] --reason REASON [--param [PARAM ...]] [--who WHO] frame stage {accept,redo,bad,delete,ulim}

positional arguments:
  frame
  stage
  {accept,redo,bad,delete,ulim}

options:
  -h, --help            show this help message and exit
  --reason REASON
  --param [PARAM ...]   key=value remediation knobs for redo
  --who WHO
```
