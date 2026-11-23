from dataclasses import dataclass
from itertools import product

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, maximum_bipartite_matching


@dataclass(frozen=True)
class Candidate:
    word: tuple
    projections: tuple
    accepts: bool
    cost: tuple


def add_prefixes(positive, projections):
    for known, word in zip(positive, projections):
        known.update(word[:i] for i in range(1, len(word) + 1))


def residual(projections, positive):
    return tuple((i, word) for i, word in enumerate(projections) if word not in positive[i])


def reduce_clause(clause, positive):
    return tuple((i, word) for i, word in clause if word not in positive[i])


def implies_rejection(clause, projections):
    return all(projections[i][:len(word)] == word for i, word in clause)


class Evidence:
    def __init__(self, size, observations):
        self.positive = [{()} for _ in range(size)]
        rejected = []
        for projections, label in observations:
            if label:
                add_prefixes(self.positive, projections)
            else:
                rejected.append(projections)
        self.negative = {residual(word, self.positive) for word in rejected}

    def observe(self, projections, label):
        if label:
            add_prefixes(self.positive, projections)
            self.negative = {reduce_clause(clause, self.positive) for clause in self.negative}
        else:
            self.negative.add(residual(projections, self.positive))

    def label(self, projections):
        if all(word in known for word, known in zip(projections, self.positive)):
            return True
        if any(implies_rejection(clause, projections) for clause in self.negative):
            return False
        return None


def rejection_classes(batch, evidence, positives):
    closure = [known.copy() for known in evidence.positive]
    for index in positives:
        add_prefixes(closure, batch[index].projections)
    historical = {reduce_clause(clause, closure) for clause in evidence.negative}
    classes = {}
    for i, candidate in enumerate(batch):
        if not candidate.accepts and not any(implies_rejection(clause, candidate.projections) for clause in historical):
            classes.setdefault(residual(candidate.projections, closure), []).append(i)

    if len(closure) == 2:
        for clause, members in classes.items():
            prefixes = [[None] + [(i, word[:k]) for k in range(1, len(word) + 1)] for i, word in clause]
            predecessors = (tuple(pair for pair in terms if pair is not None) for terms in product(*prefixes))
            if not any(p != clause and p in classes for p in predecessors):
                yield members
    else:
        for clause, members in classes.items():
            projections = batch[members[0]].projections
            if not any(other != clause and implies_rejection(other, projections) for other in classes):
                yield members


def positive_obligations(batch, evidence, positives):
    vertices = []
    for i, known in enumerate(evidence.positive):
        words = {batch[j].projections[i] for j in positives} - known
        proper_prefixes = {word[:k] for word in words for k in range(len(word))}
        vertices.extend((i, word) for word in sorted(words - proper_prefixes))
    ids = {vertex: i for i, vertex in enumerate(vertices)}
    edges = {}
    for i in positives:
        edge = tuple(ids[j, word] for j, word in enumerate(batch[i].projections) if (j, word) in ids)
        if edge:
            edges[i] = edge
    return vertices, edges


def reachable(graph, start):
    visited = set(start)
    pending = list(visited)
    while pending:
        for vertex in graph[pending.pop()]:
            if vertex not in visited:
                visited.add(vertex)
                pending.append(vertex)
    return visited


def bipartite_cover(vertices, edges):
    left_size = sum(side == 0 for side, _ in vertices)
    right_size = len(vertices) - left_size
    pairs = sorted({edge for edge in edges.values() if len(edge) == 2})
    rows = [u for u, _ in pairs]
    cols = [v - left_size for _, v in pairs]
    matrix = csr_matrix((np.ones(len(pairs)), (rows, cols)), shape=(left_size, right_size))
    matching = {(u, v + left_size) for u, v in enumerate(
        maximum_bipartite_matching(matrix, perm_type="column")
    ) if v >= 0}
    matched = {v for edge in matching for v in edge}

    graph, reverse = ([[] for _ in vertices] for _ in range(2))
    for u, v in pairs:
        start, end = (v, u) if (u, v) in matching else (u, v)
        graph[start].append(end)
        reverse[end].append(start)
    left, right = set(range(left_size)), set(range(left_size, len(vertices)))
    from_free_left = reachable(graph, left - matched)
    to_free_right = reachable(reverse, right - matched)
    rows = [u for u, neighbors in enumerate(graph) for _ in neighbors]
    cols = [v for neighbors in graph for v in neighbors]
    directed = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(vertices), len(vertices)))
    _, components = connected_components(directed, connection="strong")
    allowed = {edge for edge in pairs if edge in matching or edge[0] in from_free_left or
               edge[1] in to_free_right or components[edge[0]] == components[edge[1]]}
    exposed = (left & from_free_left) | (right & to_free_right)
    eligible = {i for i, edge in edges.items()
                if edge in allowed or len(edge) == 1 and edge[0] in exposed}
    return len(vertices) - len(matching), eligible


def integer_cover(vertices, edges):
    if not vertices:
        return set()
    rows = {vertex: i for i, vertex in enumerate(sorted(vertices))}
    useful = [(i, vertices.intersection(edge)) for i, edge in edges.items()]
    useful = [(i, edge) for i, edge in useful if edge]
    row_ids = [rows[v] for _, edge in useful for v in edge]
    columns = [j for j, (_, edge) in enumerate(useful) for _ in edge]
    matrix = csc_matrix((np.ones(len(row_ids)), (row_ids, columns)), shape=(len(rows), len(useful)))
    ones = np.ones(len(useful))
    result = milp(ones, integrality=ones, bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, 1, np.inf), options={"mip_rel_gap": 0.0})
    if not result.success:
        raise RuntimeError(result.message)
    return {i for (i, _), selected in zip(useful, result.x) if selected > .5}


class Certificate:
    def __init__(self, batch, evidence):
        positives = [i for i, candidate in enumerate(batch) if candidate.accepts]
        vertices, self.edges = positive_obligations(batch, evidence, positives)
        self.vertices = set(range(len(vertices)))
        classes = list(rejection_classes(batch, evidence, positives))
        self.rejecting_count = len(classes)
        rejecting = {i for members in classes for i in members}
        self.exact_matching = len(evidence.positive) == 2
        if self.exact_matching:
            self.positive_count, eligible = bipartite_cover(vertices, self.edges)
            self.possible = eligible | rejecting
        else:
            self.cover = integer_cover(self.vertices, self.edges)
            self.positive_count = len(self.cover)
            self.possible = self.edges.keys() | rejecting

    def allows(self, index):
        if self.exact_matching or index not in self.edges or index in self.cover:
            return True
        remaining = self.vertices.difference(self.edges[index])
        return 1 + len(integer_cover(remaining, self.edges)) == self.positive_count


def batch_counts(batch, observations):
    evidence = Evidence(len(batch[0].projections), observations)
    certificate = Certificate(batch, evidence)
    undetermined = sum(evidence.label(candidate.projections) is None for candidate in batch)
    sequential = 0
    for candidate in sorted(batch, key=lambda candidate: candidate.cost):
        if evidence.label(candidate.projections) is None:
            evidence.observe(candidate.projections, candidate.accepts)
            sequential += 1
    return dict(undetermined_tests=undetermined, sequential_queries=sequential,
                positive_queries=certificate.positive_count, rejecting_queries=certificate.rejecting_count)
