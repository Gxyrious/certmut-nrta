from argparse import ArgumentParser
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from itertools import product
import json
from pathlib import Path
from random import Random
from subprocess import PIPE, Popen, run
from tempfile import TemporaryDirectory

from automata import Network, decode, encode, word_cost
from certificates import batch_counts
from sampling import Sampler, mutation_tests
from selection import CertificateSearch

SOURCE = Path(__file__).resolve().parent
TARGETS = SOURCE.parent / "2_experiment_materials/targets"
JAVA = ("java", "-Xms128m", "-Xmx2g", "-cp", str(SOURCE / "lib/learner.jar"), "Driver")
METHODS = ("UR", "HRT", "MUT", "CERTIFICATE")
GROUPS = {f"G{i}": settings for i, settings in enumerate(
    [(2, 3, 12), (3, 5, 12), (4, 6, 16), (5, 8, 12), (10, 15, 12)] + [(2, 3, 12)] * 5, 1
)}
CASES = range(1, 11)
SEEDS = (101, 102, 103)
BUDGETS = (128, 256, 512)


def settings(group):
    ceiling, delay, length = GROUPS[group]
    return dict(clock_ceiling=ceiling, delay_upper=delay, max_length=length,
                delay_precision=4, p_start=.4, p_valid=.8, p_stop=.05,
                suffix_depth=4, suffix_nodes=300, n_acc=8, mutation_batch_coefficient=30,
                support_prefixes=32, support_prefix_attempts=256)


def messages(lines):
    for line in lines:
        if line.startswith("@@BRIDGE "):
            yield json.loads(line.removeprefix("@@BRIDGE "))


class BudgetExhausted(Exception):
    pass


class LearningRun:
    def __init__(self, config, method, seed, budget):
        self.config, self.method, self.seed, self.budget = config, method, seed, budget
        self.rng = Random(seed)
        self.cache = {(): True}
        self.words = self.actions = self.round_number = 0
        self.delay = Fraction(0)
        self.previous = ()
        self.contexts = {} if (method, seed, budget) == ("CERTIFICATE", 101, 512) else None

    def send(self, **message):
        self.learner.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.learner.stdin.flush()

    def reply(self):
        return next(self.events)

    def submit(self, timed_word, **request):
        if self.words == self.budget:
            raise BudgetExhausted
        self.send(**request)
        label = self.reply()["label"]
        self.cache[timed_word] = label
        self.words += 1
        length, delay = word_cost(timed_word)
        self.actions += length
        self.delay += delay
        return label

    def ask(self, word):
        if word in self.cache:
            return self.cache[word]
        return self.submit(word, op="mq", word=encode(word))

    def probe(self, word, network):
        rejection = network.first_reject(word)
        expected = rejection > len(word)
        label = self.ask(word)
        if label != expected:
            return word, label
        if not expected:
            before = word[:rejection - 1]
            if not self.ask(before):
                return before, False
            at = word[:rejection]
            if self.ask(at):
                return at, True
        return None

    def counterexample(self, word, positive):
        if not positive:
            low, high = 0, len(word)
            while high - low > 1:
                middle = (low + high) // 2
                if self.ask(word[:middle]):
                    low = middle
                else:
                    high = middle
            word = word[:high]
        self.previous = word
        self.send(op="ce", word=encode(word), positive=positive)

    def tests(self, network):
        if self.method == "CERTIFICATE":
            search = CertificateSearch(network, self.config, self.seed, self.round_number)
            return search.tests(self.cache, self.previous, self.contexts, self.round_number)
        sampler = Sampler(network, self.config, self.rng)
        if self.method == "MUT":
            return mutation_tests(network, sampler, self.config, self.cache, self.previous)
        draw = sampler.uniform if self.method == "UR" else lambda: sampler.heuristic(self.previous)
        return iter(draw, None)

    def search(self, components):
        self.hypothesis = components
        self.round_number += 1
        if self.words == self.budget:
            raise BudgetExhausted
        network = Network(components)
        for word in sorted(self.cache, key=lambda w: (*word_cost(w), w)):
            if network.accepts(word) != self.cache[word]:
                self.counterexample(word, self.cache[word])
                return
        tests = self.tests(network)
        while self.words < self.budget:
            word = next(tests)
            if word not in self.cache:
                result = self.probe(word, network)
                if result is not None:
                    self.counterexample(*result)
                    return
        raise BudgetExhausted

    def learn(self, model):
        with Popen([*JAVA, "learn", str(model)], stdin=PIPE, stdout=PIPE, text=True) as learner:
            self.learner, self.events = learner, messages(learner.stdout)
            try:
                for message in self.events:
                    if "hypothesis" in message:
                        self.search(message["hypothesis"])
                    else:
                        word = decode(message["word"])
                        if word in self.cache:
                            self.send(op="cached", label=self.cache[word])
                        else:
                            self.submit(word, op="execute")
                raise RuntimeError(f"Learner exited before using its query budget for {model}")
            except BudgetExhausted:
                self.send(op="stop")
                learner.wait()
                return self.hypothesis
            finally:
                learner.terminate()

    def certificate_counts(self, group, case):
        if self.contexts is None:
            return []
        rounds = list(self.contexts)
        selected = [rounds[0], rounds[(len(rounds) - 1) // 2], rounds[-1]]
        return [dict(group=group, case=case, round=i, **batch_counts(*self.contexts[i]))
                for i in selected]


def trial(job):
    group, case, method, seed, budget = job
    case = f"case{case}"
    model = TARGETS / "models" / group / case
    bank = TARGETS / "evaluation-banks" / group / f"{case}.jsonl"
    experiment = LearningRun(settings(group), method, seed, budget)
    hypothesis = experiment.learn(model)
    with TemporaryDirectory() as directory:
        for i, component in enumerate(hypothesis, 1):
            (Path(directory) / f"H{i}.json").write_text(json.dumps(component))
        evaluation = run([*JAVA, "evaluate", str(model), directory, str(bank)],
                         stdout=PIPE, text=True, check=True)
        quality = next(messages(evaluation.stdout.splitlines()))
    return (
        dict(group=group, case=case, seed=seed, word_budget=budget, method=method,
             **quality, total_actions=experiment.actions, cumulative_delay=float(experiment.delay)),
        experiment.certificate_counts(group, case),
    )


def main():
    parser = ArgumentParser(description="Reproduce the NRTA learning experiments.")
    parser.add_argument("--group", choices=GROUPS)
    parser.add_argument("--case", type=int, choices=CASES)
    parser.add_argument("--method", choices=METHODS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--budget", type=int, choices=BUDGETS)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, default=SOURCE / "results")
    args = parser.parse_args()
    jobs = product(
        (args.group,) if args.group else GROUPS,
        (args.case,) if args.case else CASES,
        (args.method,) if args.method else METHODS,
        (args.seed,) if args.seed else SEEDS,
        (args.budget,) if args.budget else BUDGETS,
    )
    learning, certificates = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row, batches in pool.map(trial, jobs):
            print(json.dumps(row), flush=True)
            learning.append(row)
            certificates.extend(batches)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("learning_runs", learning), ("certificate_counts", certificates)):
        (args.output / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
