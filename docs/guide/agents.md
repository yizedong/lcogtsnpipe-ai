# Runbook for an AI agent

You are asked to reduce a transient with this pipeline, check the result and hand over a report. Follow these steps;
each links to the page with the details. Do not skip the checks: the pipeline flags problems, it does not hide them,
but only if someone reads the flags.

## 0. Before you start

* Read [install.md](install.md) and make sure `snpipe --help` and `astra validate pipeline/astra.yaml` work.
* Never write credentials (LCO API key) into the repo, a target file or an issue.
* Never delete raw data. `snpipe verdict ... delete` only removes products; `bad` excludes a frame.
* Long runs go to the batch system (`snpipe run ... --sbatch`), not to an interactive session that may end.

## 1. Describe the target ([targets.md](targets.md))

* Coordinates from TNS (not from a frame header: offset pointings exist).
* Science DAY-OBS range: file-name dates, first to last frame you want.
* References: one per telescope class you use (1-m frames need a 1-m reference, 0.4-m a 0.4-m one): a night
  without the transient (before explosion, or > ~1 year after for a supernova), in every filter. Note its DAY-OBS
  and camera prefix. If a class has none, use `survey: ps1` (g r i z) or `survey: sdss` (u g r i z), or leave the
  class out and report its points as unsubtracted (host light included). The 1-m light curve matters most.
* `snpipe init-target ...`, then read the file back.
* Check: `snpipe run TARGET --dry-run` prints every command without errors.

## 2. Run ([running.md](running.md))

```bash
snpipe run targets/<name>           # or: --sbatch > job.sbatch; sbatch job.sbatch
snpipe status targets/<name>
```

After it ends, for every step that is not `ok`, read `results/<universe>/<step>.json` (`counts`, and each frame's
`status`, `messages`) and `logs/<step>.log`:

* exit 1 (`qa_fail`): normal in small numbers; the failed frames are in the review queue.
* exit 2/3/4: the step and everything after it did not run. Fix the cause (target file, missing files, service),
  then run `snpipe run` again (it resumes).
* A step `ok` but with many `skipped` frames: an earlier stage left them out; find which (their messages).

## 3. Check ([checks.md](checks.md), [review.md](review.md))

1. Read `results/<universe>/report.md` top to bottom.
2. Fractions: how many frames failed at psf, psfmag, diff, mag? More than ~10 % at one stage, or all frames of one
   telescope or night, means something systematic: find the common cause before reviewing frame by frame.
3. Review queue: open every warn/fail packet (PNG) and the spot-check ok packets. Answer the packet's question;
   give a verdict with a reason. At most two `redo` rounds per frame, then `bad` and leave it to a person.
4. After verdicts: `snpipe run targets/<name> --from <step>` (the earliest step you changed).
5. The light curve: look at the plot. Flagged points: check their packets. Compare bands (colours should evolve
   smoothly), telescopes (1 m vs 0.4 m on the same night should agree within errors), and subtracted vs
   unsubtracted (subtracted fainter, increasingly so as the transient fades).

## 4. Report back

Hand over `results/<universe>/report.md` (+ its figure), the two light-curve CSVs, and a short summary:

* what was reduced (bands, telescopes, dates, number of points);
* what was left out and why (counts per reason), and your verdicts (`review/verdicts.jsonl`);
* anything systematic you found and did not fix; anything a person must decide;
* the code commit (in the report; say if it had uncommitted changes).

If you found a bug, open an issue (bug template) with the frame, the step result and the packet; do not patch the
code during a reduction (see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
