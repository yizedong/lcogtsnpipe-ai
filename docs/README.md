# Documentation

## Guide — using the pipeline
1. [install.md](guide/install.md) — install, environment variables, resources
2. [targets.md](guide/targets.md) — describe an object: `target.yaml`, reference frames, `frames.json`, universes
3. [running.md](guide/running.md) — `snpipe run`, resuming, the steps, exit codes, single stages, SLURM
4. [outputs.md](guide/outputs.md) — the results folder, light-curve columns, the report, per-frame products
5. [checks.md](guide/checks.md) — what every stage checks (limits), what to do when it warns or fails
6. [review.md](guide/review.md) — review queues, pictures, verdicts, rerunning after verdicts
7. [agents.md](guide/agents.md) — the runbook for an AI agent: run, check, report

## Reference
* [../pipeline/astra.yaml](../pipeline/astra.yaml) — the recipe: every step and every decision, with the reasons for the defaults
* [reference/cli.md](reference/cli.md) — every command and option
* [reference/compatibility.md](reference/compatibility.md) — where and why snpipe differs from lcogtsnpipe (and what is identical)
* [reference/bugs.md](reference/bugs.md) — every bug found (fixed and open), why it mattered, its effect ([web](bugs.html))

## Validation
* [validation/sn2024pxl/](validation/sn2024pxl/README.md) — SN 2024pxl reduced with the old and the new pipeline,
  stage by stage ([web](stages.html)), and compared with the published light curve
