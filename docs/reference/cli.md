# Command reference

Generated from the code by `python tools/docs/cli_page.py`. Exit codes of every command: 0 ok, 1 some frames failed their checks, 2 configuration error, 3 missing input, 4 external service failed.

## Whole reductions

### snpipe run

run the whole recipe (pipeline/astra.yaml) for a target folder

```
snpipe run [-h] [--universe UNIVERSE] [--from START] [--only ONLY] [--dry-run] [--keep-going] [--recipe RECIPE] [--sbatch] target_dir

positional arguments:
  target_dir

options:
  -h, --help           show this help message and exit
  --universe UNIVERSE
  --from START         rerun this step and every step after it
  --only ONLY          run only this step
  --dry-run            print the commands without running them
  --keep-going         after a stopped step, still run independent steps
  --recipe RECIPE      another astra.yaml (default: the packaged pipeline/astra.yaml)
  --sbatch             print a SLURM job script for this run instead
```

### snpipe status

what ran for a target, with status and time per step

```
snpipe status [-h] [--universe UNIVERSE] target_dir

positional arguments:
  target_dir

options:
  -h, --help           show this help message and exit
  --universe UNIVERSE
```

### snpipe init-target

create targets/<name>/target.yaml + universes/baseline.yaml

```
snpipe init-target [-h] --name NAME --ra RA --dec DEC [--alias [ALIAS ...]] --science SCIENCE --templates TEMPLATES --camera CAMERA
                          [--frames FRAMES] [--workdir WORKDIR]
                          target_dir

positional arguments:
  target_dir

options:
  -h, --help            show this help message and exit
  --name NAME
  --ra RA
  --dec DEC
  --alias [ALIAS ...]
  --science SCIENCE     DAY-OBS range YYYYMMDD-YYYYMMDD
  --templates TEMPLATES
                        DAY-OBS of the reference night
  --camera CAMERA       camera prefix of the reference frames (fa, fl, sq, ...)
  --frames FRAMES       folder with frames.json + the files, or archive
  --workdir WORKDIR
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

review queues for every step of a run

```
snpipe review-all [-h] [--target-file TARGET_FILE] [--sample SAMPLE] -o OUTPUT

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
  --sample SAMPLE
  -o OUTPUT, --output OUTPUT
                        results/<universe>/review_queue.json
```

## Setup

### snpipe add-target



```
snpipe add-target [-h] [--target-file TARGET_FILE] [--ra RA] [--dec DEC] [--alias [ALIAS ...]] [--qa-out QA_OUT] [name]

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml: name, coordinates and aliases from the file
  --ra RA
  --dec DEC
  --alias [ALIAS ...]
  --qa-out QA_OUT       also write the result JSON here
```

### snpipe ingest



```
snpipe ingest [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--target TARGET] [--start START] [--end END]
                     [--filters [FILTERS ...]] [--tels [TELS ...]] [--frames-json FRAMES_JSON] [--local-dir LOCAL_DIR] [-j JOBS] [--qa-out QA_OUT]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml: ingest its science or template frames (see --frames)
  --frames {science,templates}
  --target TARGET       archive OBJECT name (without --target-file)
  --start START
  --end END
  --filters [FILTERS ...]
  --tels [TELS ...]     1m0 0m4 2m0
  --frames-json FRAMES_JSON
                        use a saved archive frame list instead of querying
  --local-dir LOCAL_DIR
                        copy files from here instead of downloading
  -j JOBS, --jobs JOBS
  --qa-out QA_OUT       also write the result JSON here
```

### snpipe catalogs



```
snpipe catalogs [-h] [--target-file TARGET_FILE] [--target TARGET] [--fields [FIELDS ...]] [--panstarrs] [--sloan-source {sdss,panstarrs}] [-F]
                       [-o OUTPUT]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
  --target TARGET
  --fields [FIELDS ...]
  --panstarrs
  --sloan-source {sdss,panstarrs}
  -F, --force
  -o OUTPUT, --output OUTPUT
                        also write the result JSON here
```

## Stages

### snpipe wcs



```
snpipe wcs [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                  [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
```

### snpipe cosmic



```
snpipe cosmic [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                     [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
```

### snpipe psf



```
snpipe psf [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                  [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--fwhm FWHM] [--nstars NSTARS]
                  [--datamax DATAMAX] [--datamin DATAMIN] [--max-apercorr MAX_APERCORR] [--field FIELD] [--model {daophot,epsf}] [--no-auto-fix]
                  [--auto-fix {ladder,off}]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  --fwhm FWHM
  --nstars NSTARS       number of PSF stars (also accepts the ASTRA option ids n6, n12, n20)
  --datamax DATAMAX
  --datamin DATAMIN
  --max-apercorr MAX_APERCORR
                        mag (also accepts the ASTRA option ids apco_0p1, apco_0p2)
  --field FIELD
  --model {daophot,epsf}
  --no-auto-fix         do not run the remediation ladder
  --auto-fix {ladder,off}
```

### snpipe psfmag



```
snpipe psfmag [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                     [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [-x XORD] [-y YORD] [--bkg BKG]
                     [--size SIZE] [-c] [--datamax DATAMAX] [--datamin DATAMIN] [--RA RA] [--DEC DEC]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  -x XORD, --xord XORD
  -y YORD, --yord YORD
  --bkg BKG
  --size SIZE
  -c, --no-recenter
  --datamax DATAMAX
  --datamin DATAMIN
  --RA RA
  --DEC DEC
```

### snpipe zcat



```
snpipe zcat [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                   [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--field FIELD]
                   [--catalogue CATALOGUE] [--unfix] [--type {fit,ph}] [--sigma-clip SIGMA_CLIP] [--match-by-site]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  --field FIELD
  --catalogue CATALOGUE
  --unfix
  --type {fit,ph}
  --sigma-clip SIGMA_CLIP
  --match-by-site
```

### snpipe template



```
snpipe template [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                       [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
```

### snpipe diff



```
snpipe diff [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                   [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--tempdate TEMPDATE]
                   [--temptel TEMPTEL] [--normalize {t,i}] [--unmask] [--register REGISTER] [--region {full,cutout}] [--gain {fit,zeropoint}]
                   [--cutout-size CUTOUT_SIZE]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  --tempdate TEMPDATE   DAY-OBS (range) of the reference frames
  --temptel TEMPTEL     camera prefix of the reference frames (fa, fl, sq...)
  --normalize {t,i}
  --unmask
  --register REGISTER   adaptive | exact | bilinear | bicubic
  --region {full,cutout}
  --gain {fit,zeropoint}
                        PyZOGY flux ratio: iterative fit (old default) or from zcat zero points
  --cutout-size CUTOUT_SIZE
```

### snpipe mag



```
snpipe mag [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                  [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--type {fit,ph,mag}]
                  [--match-by-site] [-o OUTPUT] [--combine COMBINE]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  --type {fit,ph,mag}
  --match-by-site
  -o OUTPUT, --output OUTPUT
  --combine COMBINE
```

### snpipe getmag



```
snpipe getmag [-h] [--target-file TARGET_FILE] [--frames {science,templates}] [--qa-out QA_OUT] [-n NAME] [-e EPOCH] [-f FILTER [FILTER ...]]
                     [-T TELESCOPE] [-d ID] [-b BAD] [--filetype FILETYPE] [--frames-file FRAMES_FILE] [-F] [-j JOBS] [--type {fit,ph,mag}]
                     [--match-by-site] [-o OUTPUT] [--combine COMBINE] [--keep-failed]

options:
  -h, --help            show this help message and exit
  --target-file TARGET_FILE
                        target.yaml (or its folder): fills -n, -e, --tempdate, --temptel, -j
  --frames {science,templates}
                        with --target-file: which nights -e selects
  --qa-out QA_OUT       also write the stage summary JSON here
  -n NAME, --name NAME
  -e EPOCH, --epoch EPOCH
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
  -T TELESCOPE, --telescope TELESCOPE
  -d ID, --id ID
  -b BAD, --bad BAD
  --filetype FILETYPE
  --frames-file FRAMES_FILE
                        restrict to the frame names listed in this file
  -F, --force
  -j JOBS, --jobs JOBS  parallel frames (default 8, diff 2)
  --type {fit,ph,mag}
  --match-by-site
  -o OUTPUT, --output OUTPUT
  --combine COMBINE
  --keep-failed         keep points whose mag/diff QA failed (dropped by default)
```

## Review

### snpipe review

build review packets/queue for a stage

```
snpipe review [-h] [--frame FRAME] [--sample SAMPLE] [--ensemble [ENSEMBLE ...]] stage

positional arguments:
  stage

options:
  -h, --help            show this help message and exit
  --frame FRAME
  --sample SAMPLE
  --ensemble [ENSEMBLE ...]
                        metrics to compare against peer frames
```

### snpipe verdict

record a review verdict (agent or human)

```
snpipe verdict [-h] --reason REASON [--param [PARAM ...]] [--who WHO] frame stage {accept,redo,bad,delete,ulim}

positional arguments:
  frame
  stage
  {accept,redo,bad,delete,ulim}

options:
  -h, --help            show this help message and exit
  --reason REASON
  --param [PARAM ...]   k=v remediation knobs for redo
  --who WHO
```
