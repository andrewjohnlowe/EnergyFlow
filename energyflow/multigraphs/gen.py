"""Implementation of multigraph Generator class."""

from __future__ import absolute_import, division, print_function

import itertools
import numpy as np

from energyflow.algorithms import *
from energyflow.utils import igraph_import

igraph = igraph_import()

__all__ = ['Generator', 'PrimeGenerator', 'CompositeGenerator']

cols = ['n','e','d','v','k','g','w','c','p']

class Generator:

    def __init__(self, dmax, nmax=None, emax=None, cmax=None, vmax=None, comp_dmaxs=None,
                       verbose=False, ve_alg='numpy', np_optimize='greedy'):

        # setup generator of connected graphs
        self.prime_generator = PrimeGenerator(dmax, nmax, emax, cmax, vmax, verbose, 
                                              ve_alg, np_optimize)

        # get results and store 
        pr = self.prime_generator.results()
        self.c_specs, self.edges, self.weights, self.einstrs, self.einpaths = pr

        # setup generator of disconnected graphs
        self.composite_generator = CompositeGenerator(self.c_specs, comp_dmaxs)

        # get results and store
        self.disc_specs, self.disc_formulae = self.composite_generator.results()

    @property
    def specs(self):
        if not hasattr(self, '_specs'):
            if len(self.disc_specs):
                self._specs = np.concatenate((self.c_specs, self.disc_specs))
            else:
                self._specs = self.c_specs
        return self._specs

    def save(self, filename):
        np.savez(filename, **{'ve_alg':        self.prime_generator.ve.ve_alg,
                              'cols':          cols,
                              'specs':         self.specs,
                              'disc_formulae': self.disc_formulae,
                              'edges':         self.edges,
                              'einstrs':       self.einstrs,
                              'einpaths':      self.einpaths,
                              'weights':       self.weights})

class PrimeGenerator:

    def __init__(self, dmax, nmax=None, emax=None, cmax=None, vmax=None, 
                       verbose=False, ve_alg='numpy', np_optimize='greedy'):

        if not igraph:
            raise NotImplementedError('cannot use PrimeGenerator without igraph')
        
        self.ve = VariableElimination(ve_alg, np_optimize)

        # store parameters
        self.dmax = dmax
        self.nmax = nmax if nmax is not None else self.dmax+1
        self.emax = emax if emax is not None else self.dmax
        self.cmax = cmax if cmax is not None else self.nmax
        self.vmax = vmax if vmax is not None else self.dmax
        self.verbose = verbose

        # setup N and e values to be used
        self.ns = list(range(2, self.nmax+1))
        self.emaxs = {n: min(self.emax, int(n/2*(n-1))) for n in self.ns}
        self.esbyn = {n: list(range(n-1, self.emaxs[n]+1)) for n in self.ns}

        # this could be more complicated than the same max for all (n,e)
        self.dmaxs = {(n,e): self.dmax for n in self.ns for e in self.esbyn[n]}

        # setup storage containers
        quantities = ['simple_graphs_d', 'edges_d', 'chis_d', 'vs_d', 'einpaths_d',
                      'einstrs_d', 'weights_d']
        for q in quantities:
            setattr(self, q, {(n,e): [] for n in self.ns for e in self.esbyn[n]})

        # get simple connected graphs
        self.generate_simple()

        # get weighted connected graphs
        self.generate_weights()

    # generates simple graphs subject to constraints
    def generate_simple(self):

        self.base_edges = {n: list(itertools.combinations(range(n), 2)) for n in self.ns}

        self._add_if_new(igraph.Graph.Full(2, directed=False), (2,1))

        # iterate over all combinations of n>2 and d
        for n in self.ns[1:]:
            for e in self.esbyn[n]:

                # consider adding new vertex
                if e-1 in self.esbyn[n-1]:

                    # iterate over all graphs with n-1, e-1
                    for seed_graph in self.simple_graphs_d[(n-1,e-1)]:

                        # iterate over vertices to attach to
                        for v in range(n-1):
                            new_graph = seed_graph.copy()
                            new_graph.add_vertices(1)
                            new_graph.add_edges([(v,n-1)])
                            self._add_if_new(new_graph, (n,e))

                # consider adding new edge to existing set of vertices
                if e-1 in self.esbyn[n]:

                    # iterate over all graphs with n, d-1
                    for seed_graph, seed_edges in zip(self.simple_graphs_d[(n,e-1)], 
                                                      self.edges_d[(n,e-1)]):

                        # iterate over edges that don't exist in graph
                        for new_edge in self._edge_filter(n, seed_edges):
                            new_graph = seed_graph.copy()
                            new_graph.add_edges([new_edge])
                            self._add_if_new(new_graph, (n,e))

        if self.verbose: 
            print('# of simple graphs by n:', self._count_simple_by_n())
            print('# of simple graphs by e:', self._count_simple_by_e())

    # adds simple graph if it is non-isomorphic to existing graphs and has a valid metric
    def _add_if_new(self, new_graph, ne):

        # check for isomorphism with existing graphs
        for graph in self.simple_graphs_d[ne]:
            if new_graph.isomorphic(graph): 
                return

        # check that ve complexity for this graph is valid
        new_edges = new_graph.get_edgelist()
        self.ve.run(new_edges, ne[0])
        if self.ve.chi > self.cmax: 
            return

        # check that the maximum valency isn't exceeded
        maxv = new_graph.maxdegree()
        if maxv > self.vmax:
            return
        
        # append graph and ve complexity to containers
        self.simple_graphs_d[ne].append(new_graph)
        self.edges_d[ne].append(new_edges)
        self.chis_d[ne].append(self.ve.chi)
        self.vs_d[ne].append(maxv)

        einstr, einpath = self.ve.einspecs()
        self.einstrs_d[ne].append(einstr)
        self.einpaths_d[ne].append(einpath)

    # generator for edges not already in list
    def _edge_filter(self, n, edges):
        for edge in self.base_edges[n]:
            if edge not in edges:
                yield edge

    # generates non-isomorphic graph weights subject to constraints
    def generate_weights(self):

        # take care of the n=2 case:
        self.weights_d[(2,1)].append([(d,) for d in range(1, self.dmaxs[(2,1)]+1)])

        # get ordered integer partitions of d of length e for relevant values
        parts = {}
        for n in self.ns[1:]:
            for e in self.esbyn[n]:
                for d in range(e, self.dmaxs[(n,e)]+1):
                    if (d,e) not in parts:
                        parts[(d,e)] = list(int_partition_ordered(d, e))

        # iterate over the rest of ns
        for n in self.ns[1:]:

            # iterate over es for which there are simple graphs
            for e in self.esbyn[n]:

                # iterate over simple graphs
                for graph in self.simple_graphs_d[(n,e)]:
                    weightings = []

                    # iterate over valid d for this graph
                    for d in range(e, self.dmaxs[(n,e)]+1):

                        # iterate over int partitions
                        for part in parts[(d,e)]:

                            # check that maximum valency is not exceeded 
                            if (self.vmax < self.dmax and 
                                max(graph.strength(weights=part)) > self.vmax):
                                continue

                            # check if isomorphic to existing
                            iso = False
                            for weighting in weightings:
                                if graph.isomorphic_vf2(other=graph, 
                                                        edge_color1=weighting, 
                                                        edge_color2=part): 
                                    iso = True
                                    break
                            if not iso: 
                                weightings.append(part)
                    self.weights_d[(n,e)].append(weightings)

        if self.verbose: 
            print('# of weightings by n:', self._count_weighted_by_n())
            print('# of weightings by d:', self._count_weighted_by_d())

    def results(self):
        """
        Column descriptions:
        n - number of vertices in graph
        e - number of edges in (underlying) simple graph
        d - number of edges in multigraph
        k - unique index for graphs with a fixed (n,d)
        g - index of simple edges in edges
        w - index of weights in weights
        c - complexity, with respect to some VE algorithm
        p - number of prime factors for this EFP
        """

        c_specs, edges, weights, einstrs, einpaths = [], [], [], [], []
        ks = {}
        g = w = 0
        for ne in sorted(self.edges_d.keys()):
            n, e = ne
            z = zip(self.edges_d[ne], self.weights_d[ne], self.chis_d[ne], self.vs_d[ne],
                    self.einstrs_d[ne], self.einpaths_d[ne])
            for edgs, wghts, chi, v, es, ep in z:
                for weighting in wghts:
                    d = sum(weighting)
                    k = ks.setdefault((n,d), 0)
                    ks[(n,d)] += 1
                    c_specs.append([n, e, d, v, k, g, w, chi, 1])
                    weights.append(weighting)
                    w += 1
                edges.append(edgs)
                einstrs.append(es)
                einpaths.append(ep)
                g += 1
        return np.asarray(c_specs), edges, weights, einstrs, einpaths

    def _count_simple_by_n(self):
        return {n: np.sum([len(self.edges_d[(n,e)]) for e in self.esbyn[n]]) for n in self.ns}

    def _count_simple_by_e(self):
        return {e: np.sum([len(self.edges_d[(n,e)]) for n in self.ns if (n,e) in self.edges_d]) \
                           for e in range(1,self.emax+1)}

    def _count_weighted_by_n(self):
        return {n: np.sum([len(weights) for e in self.esbyn[n] \
                           for weights in self.weights_d[(n,e)]]) for n in self.ns}

    def _count_weighted_by_d(self):
        counts = {d: 0 for d in range(1,self.dmax+1)}
        for n in self.ns:
            for e in self.esbyn[n]:
                for weights in self.weights_d[(n,e)]:
                    for weighting in weights: counts[sum(weighting)] += 1
        return counts

class CompositeGenerator:

    def __init__(self, c_specs, dmaxs=None):

        self.c_specs = c_specs
        self.__dict__.update({col+'_ind': i for i,col in enumerate(cols)})

        if isinstance(dmaxs, dict):
            self.dmaxs = dmaxs
        else:
            if dmaxs is None:
                dmaxs = np.max(self.c_specs[:,self.d_ind])
            elif not isinstance(dmaxs, int):
                raise TypeError('dmaxs cannot be type {}'.format(type(dmaxs)))
            self.dmaxs = {n: dmaxs for n in range(4, 2*dmaxs+1)}
        self.ns = sorted(self.dmaxs.keys())

        self.ks, self.ndk2w = {}, {}
        for spec in self.c_specs:
            n, d, k, w = spec[[self.n_ind, self.d_ind, self.k_ind, self.w_ind]]
            self.ks.setdefault((n,d), 0)
            self.ks[(n,d)] += 1
            self.ndk2w[(n,d,k)] = w

        self.nmax_avail = np.max(self.c_specs[:,self.n_ind])

        self.generate_disconnected()

    def generate_disconnected(self):
        
        disc_formulae, disc_specs = [], []

        for n in self.ns:

            # partitions with no 1s, no numbers > self.nmax_avail, and not the trivial partition
            good_part = lambda x: (1 not in x and max(x) <= self.nmax_avail and len(x) > 1)
            n_parts = [tuple(x) for x in int_partition_unordered(n) if good_part(x)]
            n_parts.sort(key=len)

            # iterate over all ds
            for d in range(int((n-1)/2)+1, self.dmaxs[n]+1):

                # iterate over all n_parts
                for n_part in n_parts:
                    n_part_len = len(n_part)

                    # get d_parts of the right length
                    d_parts = [x for x in int_partition_unordered(d) if len(x) == n_part_len]

                    # ensure that we found some
                    if len(d_parts) == 0: continue

                    # usage of set and sorting is important to avoid duplicates
                    specs = set()

                    # iterate over all orderings of the n_part
                    for n_part_ord in set([x for x in itertools.permutations(n_part)]):

                        # iterate over all d_parts
                        for d_part in d_parts:

                            # construct spec. sorting ensures we don't get duplicates in specs
                            spec = tuple(sorted([(npo,dp) for npo,dp in zip(n_part_ord,d_part)]))

                            # check that we have the proper primes to calculate this spec
                            good = True
                            for pair in spec:
                                if pair not in self.ks:
                                    good = False
                                    break
                            if good:
                                specs.add(spec)

                    # iterate over all specs that we found
                    for spec in specs:

                        # keep track of how many we added
                        kcount = 0 if (n,d) not in self.ks else self.ks[(n,d)]

                        # iterate over all possible formula implementations with the different ndk
                        for kspec in itertools.product(*[range(self.ks[factor]) for factor in spec]):

                            # iterate over factors
                            formula = []
                            cmax = emax = vmax = 0 
                            for (nn,dd),kk in zip(spec,kspec):

                                # add (n,d,k) of factor to formula
                                ndk = (nn,dd,kk)
                                formula.append(ndk)

                                # select original simple graph
                                ind = self.ndk2w[ndk]
                                cmax = max(cmax, self.c_specs[ind, self.c_ind])
                                emax = max(emax, self.c_specs[ind, self.e_ind])
                                vmax = max(vmax, self.c_specs[ind, self.v_ind])

                            # append to stored array
                            disc_formulae.append(tuple(sorted(formula)))
                            disc_specs.append([n, emax, d, vmax, kcount, -1, -1, cmax, len(kspec)])
                            kcount += 1

        # ensure unique formulae (deals with possible degeneracy in selection of factors)
        disc_form_set = set()
        mask = [not(form in disc_form_set or disc_form_set.add(form)) for form in disc_formulae]

        # store as numpy arrays
        self.disc_formulae = np.asarray(disc_formulae)[mask]
        self.disc_specs = np.asarray(disc_specs)[mask]

    def results(self):
        return self.disc_specs, self.disc_formulae
