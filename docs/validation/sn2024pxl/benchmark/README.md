# Fair benchmark: old vs new pipeline (SN 2024pxl, 100 science + 18 reference frames)

Jobs 49929684 (old) and 49929687 (new), run one after the other (SLURM dependency), each `-p shared -c 8 --mem=16G
--constraint=cascadelake`, same CPU model (Intel Xeon Platinum 8268 @ 2.90 GHz), all data/DB/scratch on node-local
disk, staging excluded. Raw: bench/results/timing_{old,new}_full.json.

| | old | new | speed-up |
|---|---|---|---|
| all stages | 26,064 s (7.24 h) | 8,859 s (2.46 h) | 2.9x |
| psf (science) | 3,469 | 629 | 5.5x |
| psfmag (science) | 1,292 | 65 | 20x |
| psf (references, both passes) | 1,683 | 185 | 9x |
| diff | 15,655 (1 m 10,062 + 0.4 m 5,593) | 6,458 (2 workers, memory bound) | 2.4x |
| psf + psfmag on differences | 2,808 | 189 | 15x |
| cosmic (science) | 508 (multicore 4) | 611 | 0.8x |

Caveats: nodes not exclusive (other users' jobs recorded at start/end); the old job overlapped an old-pipeline
smoke job (49939699) for ~20 min around 14:00-14:20; code before the 2026-10-02/03 fixes (O01 etc.); both
pipelines subtracted 0.4-m frames with the 1-m reference (since disallowed by default). On a 1 TB node (32 cores,
28 subtraction workers) the new pipeline did 750 SN 2025rbs subtractions in ~50 min.
