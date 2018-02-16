"""Implementation of EFP."""

from __future__ import absolute_import, division

import numpy as np

from energyflow.algorithms import VariableElimination
from energyflow.observables.efpbase import EFPBase, EFPElem
from energyflow.observables.efm import EFM, efp_as_efms, unique_dim_nlows

__all__ = ['EFP']

class EFP(EFPBase):

    """A class for representing and computing a single EFP."""

    def __init__(self, edges, measure='hadr', beta=1, normed=True, check_type=True, 
                              ve_alg='numpy', np_optimize='greedy'):
        """
        Arguments
        ----------
        edges : list
            - Edges of the EFP graph specified by tuple-pairs of vertices.
        measure : {`'hadr'`, `'hadr-dot'`, `'ee'`}
            - See [Measures](/intro/measures) for additional info.
        beta : float
            - The parameter $\\beta$ appearing in the measure. 
            Must be greater than zero.
        normed : bool
            - Controls normalization of the energies in the measure.
        check_type : bool
            - Whether to check the type of the input each time or use 
            the first input type.
        ve_alg : {`'numpy'`, `'ef'`}
            - Which variable elimination algorithm to use.
        np_optimize : {`True`, `False`, `'greedy'`, `'optimal'`}
            - When `ve_alg='numpy'` this is the `optimize` keyword 
            of `numpy.einsum_path`.
        """

        # initialize EFPBase
        super().__init__(measure, beta, normed, check_type)

        # store these edges as an EFPElem
        self.efpelem = EFPElem(edges)

        if self.use_efms:
            self.efm_einstr, self.efm_specs = efp_as_efms(self.graph)
            dim_nlows = unique_dim_nlows(self.efm_specs)
            self.efms = {dim: EFM(dim, nlows) for dim,nlows in dim_nlows.items()}
            self.efm_einpath = np.einsum_path(self.efm_einstr, 
                                              *[np.empty([4]*s[0]) for s in self.efm_specs],
                                              optimize=np_optimize)[0]
            self.pow2 = 2**self.d
        else:

            # get ve instance
            self.ve = VariableElimination(ve_alg, np_optimize)

            # set internals of ve to these edges
            self.ve.run(self.simple_graph, self.n)
            self.efpelem.einstr, self.efpelem.einpath = self.ve.einspecs()
            
    #===============
    # public methods
    #===============

    def compute(self, event=None, zs=None, angles=None):

        if self.use_efms:
            local_efms = self._get_efms(event, zs, angles)
            einsum_args = [local_efms[dim][nlow] for dim,nlow in self.efm_specs]
            return np.einsum(self.efm_einstr, *einsum_args, optimize=self.efm_einpath)*self.pow2
        else:

            # get dictionary of thetas to use for event
            zs, thetas_dict = self._get_zs_thetas_dict(event, zs, angles)

            # call compute on the EFPElem
            return self.efpelem.compute(zs, thetas_dict)

    def batch_compute(self, events=None, zs=None, angles=None, n_jobs=-1):

        return super().batch_compute(events, zs, angles, n_jobs)

    #===========
    # properties
    #===========

    @property
    def _weight_set(self):
        """Set of edge weights for the graph of this EFP."""

        return self.efpelem.weight_set

    @property
    def efms(self):
        """Get items of EFMs."""

        return self._efms

    @efms.setter
    def efms(self, arg):
        """Set items of EFMs."""

        self._efms = arg

    @property
    def graph(self):
        """Graph of this EFP represented by a list of edges."""

        return self.efpelem.edges

    @property
    def simple_graph(self):
        """Simple graph of this EFP (forgetting all multiedges)
        represented by a list of edges."""

        return self.efpelem.simple_edges

    @property
    def n(self):
        """Number of vertices in the graph of this EFP."""

        return self.efpelem.n

    @property
    def d(self):
        """Degree, or number of edges, in the graph of this EFP."""

        return self.efpelem.d

    @property
    def c(self):
        """VE complexity $\\chi$ of this EFP."""

        if hasattr(self.ve, 'chi'):
            return self.ve.chi
        else:
            return None
