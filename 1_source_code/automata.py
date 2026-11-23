from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations


def encode(word):
    return [[action, delay.numerator, delay.denominator] for action, delay in word]


def decode(word):
    return tuple((action, Fraction(numerator, denominator)) for action, numerator, denominator in word)


def interval(guard):
    lower, upper = guard[1:-1].split(",")
    return Fraction(lower), None if upper.strip() == "+" else Fraction(upper), guard[0] == "[", guard[-1] == "]"


def inside(value, guard):
    lower, upper, left_closed, right_closed = guard
    return ((value > lower or left_closed and value == lower) and
            (upper is None or value < upper or right_closed and value == upper))


def region(value):
    return value.numerator // value.denominator, value.denominator == 1


def word_cost(word):
    return len(word), sum((delay for _, delay in word), Fraction(0))


@dataclass(frozen=True)
class Edge:
    id: int
    target: str
    guard: tuple


class Component:
    def __init__(self, data):
        clock, = data["clocks"]
        self.actions = frozenset(data["actions"])
        self.accept = {item["name"] for item in data["locations"] if item["accepting"]}
        self.states = tuple(sorted(self.accept))
        self.initial = data["init_location"]
        self.edges = defaultdict(list)
        self.max_constant = 0
        for i, transition in enumerate(data["transitions"]):
            guard = interval(transition["guard"].get(clock, "[0,+)"))
            self.max_constant = max(self.max_constant, *(int(v) for v in guard[:2] if v is not None))
            if transition["source"] in self.accept:
                self.edges[transition["source"], transition["action"]].append(
                    Edge(i, transition["target"], guard)
                )

    def step(self, state, action, clock):
        for edge in self.edges.get((state, action), ()):
            if inside(clock, edge.guard):
                return (edge.target if edge.target in self.accept else None), edge
        return None, None


class Network:
    def __init__(self, components):
        self.components = tuple(Component(part) for part in components)
        self.actions = tuple(sorted(set().union(*(part.actions for part in self.components))))
        self.initial = (tuple(part.initial for part in self.components), (Fraction(0),) * len(components))

    def step(self, state, action, delay):
        locations, clocks = state
        next_locations = list(locations)
        next_clocks = [clock + delay for clock in clocks]
        edges = []
        for i, part in enumerate(self.components):
            if action not in part.actions:
                continue
            successor, edge = part.step(locations[i], action, next_clocks[i])
            if successor is None:
                return None, ()
            edges.append((i, edge.id))
            next_locations[i] = successor
            next_clocks[i] = Fraction(0)
        return (tuple(next_locations), tuple(next_clocks)), tuple(edges)

    def first_reject(self, word):
        state = self.initial
        for i, (action, delay) in enumerate(word, 1):
            state, _ = self.step(state, action, delay)
            if state is None:
                return i
        return len(word) + 1

    def accepts(self, word):
        return self.first_reject(word) > len(word)

    def project(self, word, component):
        actions = self.components[component].actions
        elapsed = Fraction(0)
        projection = []
        for i, (action, delay) in enumerate(word, 1):
            elapsed += delay
            if action in actions:
                projection.append((i, action, elapsed))
                elapsed = Fraction(0)
        return tuple(projection)

    def region_words(self, word):
        return tuple(tuple((action, *region(value)) for _, action, value in self.project(word, i))
                     for i in range(len(self.components)))


@dataclass(frozen=True)
class TimedMutation:
    component: int
    source: str
    action: str
    guard: tuple
    target: str | None

    def reject(self, part, projection, limit):
        state = part.initial
        for i, action, value in projection:
            if i >= limit:
                break
            if state == self.source and action == self.action and inside(value, self.guard):
                state = self.target
            else:
                state, _ = part.step(state, action, value)
            if state is None:
                return i
        return limit


@dataclass(frozen=True)
class SplitMutation:
    component: int
    trigger: int
    suffix: tuple
    target: str | None

    def reject(self, part, projection, limit):
        state = part.initial
        progress = 0 if self.trigger == -1 else -1
        for i, action, value in projection:
            if i >= limit:
                break
            state, edge = part.step(state, action, value)
            transition = edge.id if edge else None
            if progress >= 0:
                if transition == self.suffix[progress]:
                    progress += 1
                    if progress == len(self.suffix):
                        state = self.target
                        progress = -1
                else:
                    progress = -1
            elif transition == self.trigger:
                progress = 0
            if state is None:
                return i
        return limit


def timed_mutants(network, bound):
    mutants = []
    for i, part in enumerate(network.components):
        ceiling = max(bound, part.max_constant)
        guards = [(Fraction(k), Fraction(k), True, True) for k in range(ceiling + 1)]
        guards += [(Fraction(k), Fraction(k + 1), False, False) for k in range(ceiling)]
        guards.append((Fraction(ceiling), None, False, False))
        for state in part.states:
            for action in sorted(part.actions):
                for guard in guards:
                    lower, upper, _, _ = guard
                    value = lower if lower == upper else lower + Fraction(1, 2)
                    current, _ = part.step(state, action, value)
                    for target in (*part.states, None):
                        if target != current:
                            mutants.append(TimedMutation(i, state, action, guard, target))
    return mutants


def split_mutants(network, access_limit):
    mutants = set()
    for i, part in enumerate(network.components):
        accesses = defaultdict(list)
        queue = deque([(part.initial, (), {part.initial: 1})])
        while queue:
            state, path, visits = queue.popleft()
            if len(accesses[state]) >= access_limit:
                continue
            accesses[state].append(path)
            for action in sorted(part.actions):
                for edge in part.edges.get((state, action), ()):
                    if edge.target in part.accept and visits.get(edge.target, 0) < 2:
                        counts = visits | {edge.target: visits.get(edge.target, 0) + 1}
                        queue.append((edge.target, path + (edge.id,), counts))
        for state, paths in accesses.items():
            for left, right in combinations(paths, 2):
                common = 0
                for u, v in zip(reversed(left), reversed(right)):
                    if u != v:
                        break
                    common += 1
                for path in (left, right):
                    trigger = path[-common - 1] if common < len(path) else -1
                    suffix = path[-common:] if common else ()
                    for action in sorted(part.actions):
                        for edge in part.edges.get((state, action), ()):
                            target = None if edge.target in part.accept else part.initial
                            mutants.add(SplitMutation(i, trigger, suffix + (edge.id,), target))
    return sorted(mutants, key=repr)


def timed_guard(value, ceiling):
    if value > ceiling:
        return Fraction(ceiling), None, False, False
    lower, exact = region(value)
    if exact:
        return value, value, True, True
    return Fraction(lower), Fraction(lower + 1), False, False


class LocalMutations:
    def __init__(self, part, ceiling, mutants):
        self.part, self.ceiling, self.mutants = part, ceiling, mutants
        self.timed, self.split = defaultdict(list), defaultdict(list)
        for index, mutant in mutants.items():
            if isinstance(mutant, TimedMutation):
                self.timed[mutant.source, mutant.action, mutant.guard].append(index)
            else:
                self.split[mutant.trigger].append(index)

    def trace(self, projection, limit):
        state = self.part.initial
        active = set(self.split[-1])
        transitions = []
        for i, action, value in projection:
            if i >= limit:
                break
            active.update(self.timed.get((state, action, timed_guard(value, self.ceiling)), ()))
            state, edge = self.part.step(state, action, value)
            if edge:
                active.update(self.split.get(edge.id, ()))
                transitions.append((i, edge.id))
            if state is None:
                return i, transitions, active
        return limit, transitions, active


def mutation_catalog(network, mutants, bound):
    by_component = [{} for _ in network.components]
    for index, mutant in enumerate(mutants):
        by_component[mutant.component][index] = mutant
    return [LocalMutations(part, max(bound, part.max_constant), local)
            for part, local in zip(network.components, by_component)]
