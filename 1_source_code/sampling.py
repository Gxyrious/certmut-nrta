from collections import defaultdict, deque
from fractions import Fraction
from math import prod

from automata import mutation_catalog, split_mutants, timed_mutants, word_cost


class Sampler:
    def __init__(self, network, config, rng):
        self.network, self.config, self.rng = network, config, rng
        self.max_length = min(config["max_length"], max(2, 2 * sum(len(p.states) for p in network.components)))
        self.upper = config["delay_upper"]
        self.precision = config["delay_precision"]
        self.cells = {}
        self.suffixes = {}

    def uniform(self):
        return tuple((self.rng.choice(self.network.actions),
                      Fraction(self.rng.randrange(self.upper * self.precision + 1), self.precision))
                     for _ in range(self.rng.randint(1, self.max_length)))

    def transition_groups(self, state):
        if state in self.cells:
            return self.cells[state]
        locations, clocks = state
        groups = {}
        for action in self.network.actions:
            cuts = {Fraction(0), Fraction(self.upper)}
            for i, part in enumerate(self.network.components):
                for edge in part.edges.get((locations[i], action), ()):
                    for endpoint in edge.guard[:2]:
                        if endpoint is not None and 0 <= endpoint - clocks[i] <= self.upper:
                            cuts.add(endpoint - clocks[i])
            cuts = sorted(cuts)
            ranges = []
            for delay in cuts:
                tick = delay * self.precision
                if tick.denominator == 1:
                    ranges.append((int(tick), int(tick)))
            for lower, upper in zip(cuts, cuts[1:]):
                first = (lower * self.precision).__floor__() + 1
                last = (upper * self.precision).__ceil__() - 1
                if first <= last:
                    ranges.append((first, last))
            for first, last in sorted(ranges):
                delay = Fraction((first + last) // 2, self.precision)
                successor, edges = self.network.step(state, action, delay)
                key = (action, edges if successor is not None else None)
                groups.setdefault(key, []).append((first, last))
        good = [(action, ranges) for (action, edges), ranges in groups.items() if edges is not None]
        bad = [(action, ranges) for (action, edges), ranges in groups.items() if edges is None]
        self.cells[state] = good, bad
        return good, bad

    def draw(self, state, group):
        action, ranges = group
        offset = self.rng.randrange(sum(last - first + 1 for first, last in ranges))
        for first, last in ranges:
            if offset <= last - first:
                delay = Fraction(first + offset, self.precision)
                successor, _ = self.network.step(state, action, delay)
                return action, delay, successor
            offset -= last - first + 1

    def access_suffix(self, state, seen):
        key = state, frozenset(seen)
        if key in self.suffixes:
            return self.suffixes[key]
        queue = deque([(state, ())])
        visited = {state}
        result = ()
        for _ in range(self.config["suffix_nodes"]):
            if not queue:
                break
            current, path = queue.popleft()
            if current[0] not in seen:
                result = path
                break
            if len(path) >= self.config["suffix_depth"]:
                continue
            good, _ = self.transition_groups(current)
            options = [(action, Fraction(tick, self.precision))
                       for action, ranges in good for first, last in ranges
                       for tick in sorted({first, (first + last) // 2, last})]
            self.rng.shuffle(options)
            for action, delay in options:
                successor, _ = self.network.step(current, action, delay)
                if successor not in visited:
                    visited.add(successor)
                    queue.append((successor, path + ((action, delay),)))
        if len(self.suffixes) < 2048:
            self.suffixes[key] = result
        return result

    def heuristic(self, previous):
        network, rng = self.network, self.rng
        state = network.initial
        word, seen = [], {state[0]}
        if previous and rng.random() < self.config["p_start"]:
            reusable = min(self.max_length, network.first_reject(previous) - 1)
            for action, delay in previous[:reusable]:
                word.append((action, delay))
                state, _ = network.step(state, action, delay)
                seen.add(state[0])
        while len(word) < self.max_length:
            good, bad = self.transition_groups(state)
            preferred, fallback = (good, bad) if rng.random() < self.config["p_valid"] else (bad, good)
            groups = preferred or fallback
            if not groups:
                break
            action, delay, state = self.draw(state, rng.choice(groups))
            word.append((action, delay))
            if state is None:
                return tuple(word)
            seen.add(state[0])
            if rng.random() < self.config["p_stop"]:
                break
        if len(seen) < prod(len(part.states) for part in network.components):
            word.extend(self.access_suffix(state, seen))
        return tuple(word) if word else self.uniform()


def normalized(values):
    low, high = min(values), max(values)
    return [float((value - low) / (high - low)) if low != high else 0.0 for value in values]


def mutation_suite(network, pool, catalog):
    words, coverage, transition_counts = [], [], []
    cache = [{} for _ in catalog]
    for word in pool:
        limit = len(word) + 1
        projections = [network.project(word, i) for i in range(len(catalog))]
        traces = [local.trace(projection, limit) for local, projection in zip(catalog, projections)]
        rejections = [first_reject for first_reject, _, _ in traces]
        first_reject = min(rejections)
        hits = set()
        for i, (local, projection, (_, _, active)) in enumerate(zip(catalog, projections, traces)):
            cap = min(rejections[:i] + rejections[i + 1:] + [limit])
            key = projection, cap
            if key not in cache[i]:
                cache[i][key] = {j for j in active
                                 if local.mutants[j].reject(local.part, projection, cap) != first_reject}
            hits.update(cache[i][key])
        if hits:
            words.append(word)
            coverage.append(hits)
            transition_counts.append(
                sum(len({edge for position, edge in transitions if position <= first_reject})
                    for _, transitions, _ in traces)
            )
    if not words:
        return []
    by_mutant = defaultdict(list)
    for i, hits in enumerate(coverage):
        for mutant in hits:
            by_mutant[mutant].append(i)
    waits = normalized([word_cost(word)[1] for word in words])
    lengths = normalized([len(word) for word in words])
    kills = normalized([len(hits) for hits in coverage])
    transitions = normalized(transition_counts)
    scores = [.4 * (1 - a) + .4 * (1 - b) + .6 * c + .2 * d
              for a, b, c, d in zip(waits, lengths, kills, transitions)]
    covered, suite = set(), []
    for mutant in sorted(by_mutant, key=lambda i: (len(by_mutant[i]), i)):
        if mutant in covered:
            continue
        best = max(by_mutant[mutant], key=lambda i: (scores[i], -i))
        suite.append(words[best])
        covered.update(coverage[best])
    return suite


def mutation_tests(network, sampler, config, cache, previous):
    bound = config["clock_ceiling"]
    size = config["mutation_batch_coefficient"] * bound * sum(
        len(part.states) * len(part.actions) for part in network.components
    )
    catalogs = {}
    while True:
        pool = {}
        for _ in range(size):
            word = sampler.heuristic(previous)
            if word not in cache:
                pool[word] = None
        for stage, generate, parameter in (("timed", timed_mutants, bound),
                                           ("split", split_mutants, config["n_acc"])):
            if stage not in catalogs:
                catalogs[stage] = mutation_catalog(network, generate(network, parameter), bound)
            fresh = [word for word in pool if word not in cache]
            yield from mutation_suite(network, fresh, catalogs[stage])
