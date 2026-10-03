# Install

## The package

```bash
python -m venv ~/envs/snpipe && source ~/envs/snpipe/bin/activate      # or a conda env, Python >= 3.10
pip install "lcogtsnpipe-ai[astra,test] @ git+https://github.com/yizedong/lcogtsnpipe-ai"
#   developers: git clone https://github.com/yizedong/lcogtsnpipe-ai && pip install -e "lcogtsnpipe-ai[astra,test]"
snpipe --help
```

PyZOGY is bundled; IRAF and MySQL are not needed. The `astra` extra installs `astra-tools` (the `astra validate`
command, see [running.md](running.md)).

On a shared filesystem (NFS), pip may fail with "Directory not empty": set `TMPDIR` to a local disk first.

## Environment variables

| variable | needed for | meaning |
|---|---|---|
| `SNPIPE_RAW` | the example targets | folder that holds the raw-frame folders (`targets/*/target.yaml` refer to `${SNPIPE_RAW}/...`) |
| `SNPIPE_WORK` | the example targets | folder under which each target gets its working directory |
| `LCO_API_KEY` | downloading proprietary frames | LCO archive token (never commit it) |
| `SNPIPE_SCRATCH` | optional | folder for the per-frame temporary files of difference imaging (default: `<workdir>/tmp`). On a cluster use the shared scratch filesystem (e.g. netscratch), not a node's small local disk |
| `SNPIPE_DIR` | single stages without a target file | the working directory (database, frames, products); `snpipe run` sets it |
| `OMP_NUM_THREADS=1` | recommended | the pipeline parallelises over frames; threaded numpy on top only slows it down |

## Resources

* Disk: several times the compressed raw data (frames are unpacked; cleaned frames, masks, reference copies and
  difference images are added). Put raw frames, working directories and temporary files on a large shared
  filesystem (on FASRC: netscratch), never on a compute node's small local disk; netscratch is not backed up and
  purges old files, so keep the small results (light curves, reports, databases) elsewhere.
* Memory: PyZOGY needs about 7 GB per 4k x 4k frame, so `diff_jobs` (target file) x 7 GB must fit; the other stages
  need much less; lower `jobs` if a run is killed for memory.
* Network: catalogs (APASS, SDSS or Pan-STARRS, Gaia via VizieR) and the LCO archive, once per target.

## Check the installation

```bash
pytest tests                                            # in a clone: numerical equivalence + recipe tests
astra validate pipeline/astra.yaml                      # in a clone: the recipe is a valid ASTRA record
```
