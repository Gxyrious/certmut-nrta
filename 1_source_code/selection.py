from collections import defaultdict, deque
from fractions import Fraction
from random import Random

from automata import mutation_catalog, region, split_mutants, timed_mutants, word_cost
from certificates import Candidate, Certificate, Evidence
from sampling import Sampler


def bits(mask):
    while mask:
        lowest = mask & -mask
        yield lowest.bit_length() - 1
        mask ^= lowest


class MutationSpace:
    def __init__(self, network, config):
        bound = config["clock_ceiling"]
        mutants = timed_mutants(network, bound) + split_mutants(network, config["n_acc"])
        self.catalog = mutation_catalog(network, mutants, bound)
        self.network = network
        self.variants = [1 | sum(1 << (j + 1) for j in local.mutants) for local in self.catalog]
        self.local_outputs = [{} for _ in self.catalog]
        self.word_outputs = {}

    def outputs(self, word):
        if word not in self.word_outputs:
            outputs = []
            for i, local in enumerate(self.catalog):
                projection = self.network.project(word, i)
                key = tuple((action, *region(value)) for _, action, value in projection)
                memo = self.local_outputs[i]
                if key not in memo:
                    limit = len(word) + 1
                    rejection, _, active = local.trace(projection, limit)
                    mask = self.variants[i] if rejection == limit else 0
                    for j in active:
                        bit = 1 << (j + 1)
                        if local.mutants[j].reject(local.part, projection, limit) == limit:
                            mask |= bit
                        else:
                            mask &= ~bit
                    memo[key] = mask
                outputs.append(memo[key])
            self.word_outputs[word] = tuple(outputs)
        return self.word_outputs[word]

    def reset(self, batch):
        self.classes = [[mask] for mask in self.variants]
        self.refined = [set() for _ in self.catalog]
        self.history = {}
        self.quotients = {}
        self.root = None
        for candidate in batch:
            self.refine(self.outputs(candidate.word))

    def refine(self, outputs):
        for i, output in enumerate(outputs):
            if output in self.refined[i]:
                continue
            self.refined[i].add(output)
            classes = [subset for group in self.classes[i] for subset in (group & output, group & ~output) if subset]
            if classes != self.classes[i]:
                self.classes[i] = classes
                self.quotients.clear()

    def quotient(self, outputs):
        if outputs not in self.quotients:
            self.quotients[outputs] = tuple(sum(1 << j for j, group in enumerate(classes) if group & output)
                                            for classes, output in zip(self.classes, outputs))
        return self.quotients[outputs]

    def sync(self, cache):
        if len(self.history) == len(cache):
            return
        for word, result in cache.items():
            if word not in self.history:
                outputs = self.outputs(word)
                self.refine(outputs)
                self.history[word] = result, outputs

        alive = [(1 << len(classes)) - 1 for classes in self.classes]
        negatives = []
        for label, outputs in self.history.values():
            masks = self.quotient(outputs)
            if label:
                alive = [domain & mask for domain, mask in zip(alive, masks)]
            else:
                negatives.append(masks)
        negatives = list(set(masks for masks in negatives if all(a & m for a, m in zip(alive, masks))))
        n = len(alive)
        nodes = [(n, (), 1)]
        memo, shared = {}, {}

        def build(i, pending):
            key = i, pending
            if key in memo:
                return memo[key]
            domain = alive[i]
            edges = defaultdict(int)
            if i == n - 1:
                for j in pending:
                    domain &= ~negatives[j][i]
                if domain:
                    edges[0] = domain
            else:
                for j in bits(domain):
                    current = 1 << j
                    residual = tuple(k for k in pending if negatives[k][i] & current)
                    child = build(i + 1, residual)
                    if child is not None:
                        edges[child] |= current
            answer = None
            if edges:
                arcs = tuple((mask, child) for child, mask in sorted(edges.items()))
                signature = i, arcs
                if signature not in shared:
                    shared[signature] = len(nodes)
                    count = sum(mask.bit_count() * nodes[child][2] for mask, child in arcs)
                    nodes.append((i, arcs, count))
                answer = shared[signature]
            memo[key] = answer
            return answer

        self.root = build(0, tuple(range(len(negatives))))
        self.nodes = nodes
        self.total = nodes[self.root][2]
        self.acceptance_counts = {}

    def disagreement(self, candidate):
        masks = self.quotient(self.outputs(candidate.word))
        if masks not in self.acceptance_counts:
            counts = [1]
            for i, edges, _ in self.nodes[1:]:
                counts.append(sum((mask & masks[i]).bit_count() * counts[child] for mask, child in edges))
            self.acceptance_counts[masks] = counts[self.root]
        accepted = self.acceptance_counts[masks]
        return self.total - accepted if candidate.accepts else accepted


def delay_cells(network, state, action, upper):
    _, clocks = state
    cuts = {Fraction(0), Fraction(upper)}
    for i, part in enumerate(network.components):
        if action in part.actions:
            first, last = clocks[i].__ceil__(), (clocks[i] + upper).__floor__()
            cuts.update(Fraction(k) - clocks[i] for k in range(first, last + 1))
    points = sorted(cuts)
    return sorted(cuts | {(a + b) / 2 for a, b in zip(points, points[1:])})


class CertificateSearch:
    def __init__(self, network, config, seed, round_number):
        self.network, self.config = network, config
        self.sampler = Sampler(network, config, Random(seed * 1000003 + round_number))
        seed = seed * 104729 + round_number
        self.prefix_rng, self.order_rng = Random(seed), Random(seed ^ 0x5A17)
        self.used, self.pending = set(), {}
        self.prefix_queue = deque()
        self.space = MutationSpace(network, config)

    def prefixes(self, cache, previous):
        maximum = self.sampler.max_length - 1
        size = self.config["support_prefixes"]
        sources = {(): None}
        for word, label in cache.items():
            if label:
                sources.update(dict.fromkeys(word[:i] for i in range(min(maximum, len(word)) + 1)))
        for _ in range(self.config["support_prefix_attempts"]):
            word = self.sampler.heuristic(previous)
            length = min(maximum, self.network.first_reject(word) - 1)
            sources.update(dict.fromkeys(word[:i] for i in range(length + 1)))
            if len(sources.keys() - self.used) >= 4 * size:
                break
        fresh = [prefix for prefix in sources if prefix not in self.used and prefix not in self.pending
                 and self.network.accepts(prefix)]
        self.prefix_rng.shuffle(fresh)
        self.pending.update(dict.fromkeys(fresh))
        self.prefix_queue.extend(fresh)
        chosen = sorted(self.pending, key=lambda p: (word_cost(p), p))[:size // 2]
        for prefix in chosen:
            del self.pending[prefix]
        while self.prefix_queue and len(chosen) < size:
            prefix = self.prefix_queue.popleft()
            if prefix in self.pending:
                chosen.append(prefix)
                del self.pending[prefix]
        self.used.update(chosen)
        return chosen

    def candidates(self, cache, previous):
        network = self.network
        words = {}
        for prefix in self.prefixes(cache, previous):
            state = network.initial
            for action, delay in prefix:
                state, _ = network.step(state, action, delay)
            for action in network.actions:
                for delay in delay_cells(network, state, action, self.config["delay_upper"]):
                    word = prefix + ((action, delay),)
                    if word in cache or word in words:
                        continue
                    successor, _ = network.step(state, action, delay)
                    words[word] = Candidate(word, network.region_words(word), successor is not None, word_cost(word))
        batch = list(words.values())
        self.order_rng.shuffle(batch)
        return batch

    def tests(self, cache, previous, contexts, round_number):
        network = self.network
        while True:
            batch = self.candidates(cache, previous)
            if not batch:
                continue
            if contexts is not None and round_number not in contexts:
                observations = [(network.region_words(word), label) for word, label in cache.items()]
                contexts[round_number] = batch, observations
            self.space.reset(batch)
            while True:
                observations = ((network.region_words(word), label) for word, label in cache.items())
                evidence = Evidence(len(network.components), observations)
                certificate = Certificate(batch, evidence)
                if not certificate.possible:
                    break
                self.space.sync(cache)

                def priority(index):
                    test = batch[index]
                    opposite = self.space.disagreement(test)
                    return -Fraction(opposite, len(test.word)), test.cost, index

                eligible = sorted(certificate.possible, key=priority)
                index = next(i for i in eligible if certificate.allows(i))
                yield batch[index].word
