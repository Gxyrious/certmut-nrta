# CertMut-NRTA

[English](README.md) | 简体中文

CertMut-NRTA在实时自动机网络的组合学习中，利用最小验证证书选择用于一致性测试的时间字。对照方法为均匀随机测试UR、启发式随机测试HRT和变异测试MUT。

## 快速开始

安装 Python 3.12 和 Java 17 后，在仓库根目录执行以下命令，结果会写入 `1_source_code/results/quickstart/learning_runs.json`.

```sh
cd 1_source_code
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python run.py --group G1 --case 1 --method CERTIFICATE --seed 101 --budget 128 --output results/quickstart
```



## 全量复现

在 `1_source_code/` 中运行全部实验，并将结果与归档比对。全量实验通常需要数小时，`--workers` 指定并行进程数。

```sh
python run.py --workers 4 --output results/full
python ../.github/verify_results.py results/full results/verified
```

实验结果写入 `1_source_code/results/full/`，通过校验的结果保存至 `1_source_code/results/verified/`.

## 实验材料

基准包含 100 个目标网络，分为 G1–G10 十组。同一目标的各次运行共用一份评价集，其中包含 2500 条接受时间字和 2500 条拒绝时间字。

- 目标模型：`2_experiment_materials/targets/models`
- 同步拓扑配置：`2_experiment_materials/targets/profiles.json`
- 固定评价集：`2_experiment_materials/targets/evaluation-banks`
- 逐次学习结果：`2_experiment_materials/run_data/learning_runs.json`
- 证书批次计数：`2_experiment_materials/run_data/certificate_counts.json`

## 实验结果

每档预算下，四种方法均在相同的 100 个目标上运行，每个目标使用三个随机种子（101–103）。表中每格对应 300 次运行，依次给出平均行为一致率和严格等价次数。

| 方法 | 预算 128 | 预算 256 | 预算 512 |
| --- | ---: | ---: | ---: |
| UR | 88.81% / 11 | 93.29% / 67 | 97.57% / 146 |
| HRT | 90.01% / 25 | 95.88% / 123 | 98.90% / 233 |
| MUT | 89.68% / 13 | 94.57% / 91 | 98.87% / 247 |
| CERTIFICATE | 92.55% / 33 | 97.07% / 116 | 99.28% / 264 |

在预算 512 下，CERTIFICATE 平均提交 1138.05 个动作，平均累计延时为 1378.39，分别比 MUT 低 60.6% 和 73.4%。

在预算 512、种子 101 的 300 个候选批次上，假定测试结果均与假设一致，最小证书所需的查询数比顺序推断平均少 5.8%。

## 从源码构建

在 `1_source_code/` 中运行 `python build.py` 可从[学习器源码](https://github.com/zeno-98/NRTA_Learning)构建学习器。构建需要 JDK 17、Maven 和 Git。
