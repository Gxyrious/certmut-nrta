# CertMut-NRTA

English | [简体中文](README.zh-CN.md)

CertMut-NRTA uses minimum verification certificates to select timed words for conformance testing in compositional active learning of networks of real-time automata (NRTAs). The baselines are uniform random testing (UR), heuristic random testing (HRT), and mutation testing (MUT).

## Quick Start

With Python 3.12 and Java 17 installed, run the following commands from the repository root. Results are written to `1_source_code/results/quickstart/learning_runs.json`.

```sh
cd 1_source_code
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python run.py --group G1 --case 1 --method CERTIFICATE --seed 101 --budget 128 --output results/quickstart
```

## Full Reproduction

Run all experiments from `1_source_code/` and verify the outputs against the archived results. Full reproduction typically takes several hours; use `--workers` to specify the number of parallel processes.

```sh
python run.py --workers 4 --output results/full
python ../.github/verify_results.py results/full results/verified
```

Run outputs are written to `1_source_code/results/full/`, and verified results are saved to `1_source_code/results/verified/`.

## Experimental Materials

The benchmark comprises 100 target networks across 10 groups (G1–G10). All runs for the same target share a fixed evaluation set of 2500 accepted and 2500 rejected timed words.

- Target models: `2_experiment_materials/targets/models`
- Synchronization topology profiles: `2_experiment_materials/targets/profiles.json`
- Fixed evaluation sets: `2_experiment_materials/targets/evaluation-banks`
- Per-run learning results: `2_experiment_materials/run_data/learning_runs.json`
- Certificate batch counts: `2_experiment_materials/run_data/certificate_counts.json`

## Experimental Results

At each query budget, all four methods run on the same 100 targets with three random seeds (101–103). Each cell summarizes 300 runs as mean behavioral agreement and strict language equivalence count.

| Method | Budget 128 | Budget 256 | Budget 512 |
| --- | ---: | ---: | ---: |
| UR | 88.81% / 11 | 93.29% / 67 | 97.57% / 146 |
| HRT | 90.01% / 25 | 95.88% / 123 | 98.90% / 233 |
| MUT | 89.68% / 13 | 94.57% / 91 | 98.87% / 247 |
| CERTIFICATE | 92.55% / 33 | 97.07% / 116 | 99.28% / 264 |

At budget 512, CERTIFICATE submits an average of 1138.05 actions and 1378.39 cumulative delay, reducing actions by 60.6% and delay by 73.4% relative to MUT.

Across 300 candidate batches at budget 512 (seed 101), assuming all test outcomes agree with the hypothesis, minimum certificates require 5.8% fewer queries than sequential inference on average.

## Building from Source

Run `python build.py` in `1_source_code/` to build the learner from the [learner source](https://github.com/zeno-98/NRTA_Learning). Building requires JDK 17, Maven, and Git.
