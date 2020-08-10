#
# This file is part of pySMT.
#
#   Copyright 2014 Andrea Micheli and Marco Gario
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

from pysmt.solvers.solver import Solver
from pysmt.exceptions import PysmtValueError, GoalNotSupportedError
from pysmt.optimization.goal import MinimizationGoal, MaximizationGoal
from pysmt.shortcuts import Symbol, INT, REAL, BVType, Equals
from pysmt.logics import LIA, LRA, BV
from pysmt.oracles import get_logic

class Optimizer(Solver):
    """
    Interface for the optimization
    """

    def optimize(self, goal, **kwargs):
        """Returns a pair `(model, cost)` where `model` is an object
        that obtained according to `goal` while satisfying all
        the formulae asserted in the optimizer, while `cost` is the
        objective function value for the model.

        `goal` must have a term with integer, real or
        bit-vector type whose value has to be minimized
        This function can raise a PysmtUnboundedOptimizationError if
        the solver detects that the optimum value is either positive
        or negative infinite or if there is no optimum value because
        one can move arbitrarily close to the optimum without reching
        it (e.g. "x > 5" has no minimum for x, only an infimum)

        """
        raise NotImplementedError


    def pareto_optimize(self, goals):
        """This function is a generator returning *all* the pareto-optimal
        solutions for the problem of minimizing the `cost_functions`
        keeping the formulae asserted in this optimizer satisfied.

        The solutions are returned as pairs `(model, costs)` where
        model is the pareto-optimal assignment and costs is the list
        of costs, one for each optimization function in
        `cost_functions`.

        `cost_functions` must be a list of terms with integer, real or
        bit-vector types whose values have to be minimized

        This function can raise a PysmtUnboundedOptimizationError if
        the solver detects that the optimum value is either positive
        or negative infinite or if there is no optimum value because
        one can move arbitrarily close to the optimum without reching
        it (e.g. "x > 5" has no minimum for x, only an infimum)

        """
        raise NotImplementedError


    def can_diverge_for_unbounded_cases(self):
        """This function returns True if the algorithm implemented in this
        optimizer can diverge (i.e. not terminate) if the objective is
        unbounded (infinite or infinitesimal).
        """
        raise NotImplementedError


    def _get_symbol_type(self, objective_formula):
        otype = self.environment.stc.get_type(objective_formula)
        if otype.is_int_type():
            return INT
        elif otype.is_real_type():
            return REAL
        elif otype.is_bv_type():
            return BVType(otype.width)
        else:
            raise PysmtValueError("Invalid optimization function type: %s" % otype)

    def _get_or(self, objective_formula):
        otype = self.environment.stc.get_type(objective_formula)
        mgr = self.environment.formula_manager
        if otype.is_int_type():
            return mgr.Or
        elif otype.is_real_type():
            return mgr.Or
        elif otype.is_bv_type():
            return mgr.BVOr
        else:
            raise PysmtValueError("Invalid optimization function type: %s" % otype)


    def _get_le(self, objective_formula):
        otype = self.environment.stc.get_type(objective_formula)
        mgr = self.environment.formula_manager
        if otype.is_int_type():
            return mgr.LE
        elif otype.is_real_type():
            return mgr.LE
        elif otype.is_bv_type():
            return mgr.BVULE
        else:
            raise PysmtValueError("Invalid optimization function type: %s" % otype)


    def _get_lt(self, objective_formula):
        otype = self.environment.stc.get_type(objective_formula)
        mgr = self.environment.formula_manager
        if otype.is_int_type():
            return mgr.LT
        elif otype.is_real_type():
            return mgr.LT
        elif otype.is_bv_type():
            return mgr.BVULT
        else:
            raise PysmtValueError("Invalid optimization function type: %s" % otype)


class OptComparationFunctions:

    def _comparation_functions(self, goal):
        """Internal utility function to get the proper cast, LT and LE
        function for the given objective formula
        """
        mgr = self.environment.formula_manager
        cast_bv = None
        if goal.get_logic() is BV:
            otype = self.environment.stc.get_type(goal.term())
            cast_bv = lambda x: mgr.BV(x, otype.width)
        options = {
            LIA: {
                MinimizationGoal: {
                    True: (mgr.Int, mgr.LT, mgr.LE),
                },
                MaximizationGoal: {
                    True: (mgr.Int, mgr.GT, mgr.GE),
                },
            },
            LRA: {
                MinimizationGoal: {
                    True: (mgr.Real, mgr.LT, mgr.LE),
                },
                MaximizationGoal: {
                    True: (mgr.Real, mgr.GT, mgr.GE),
                },
            },
            BV: {
                MinimizationGoal: {
                    False: (cast_bv, mgr.BVULT, mgr.BVULE),
                    True: (cast_bv, mgr.BVSLT, mgr.BVSLE),
                },
                MaximizationGoal: {
                    False: (cast_bv, mgr.BVUGT, mgr.BVUGE),
                    True: (cast_bv, mgr.BVSGT, mgr.BVSGE),
                },
            },
        }
        return options[goal.get_logic()][goal.opt()][goal.signed()]


class OptSearchInterval(OptComparationFunctions):

    def __init__(self, goal, environment,client_data):
        self._obj = goal
        self._lower = None #-INF where i found this costant?
        self._upper = None #+INF
        self._pivot = None
        self.environment = environment
        self._cast, self.op_strict, self.op_ns = self._comparation_functions(goal)
        self.client_data = client_data

    def linear_search_cut(self):
        """must be called always"""
        if self._obj.is_minimization_goal():
            bound = self._upper
        else:
            bound = self._lower

        return self.op_strict(self._obj.term(), self._cast(bound))

    def _compute_pivot(self):
        if self._lower is None and self._upper is None:
            return 0
        l,u = self._lower, self._upper
        if self._lower is None and self._upper is not None:
            l = self._upper - (abs(self._upper) + 1)
        elif self._lower is not None and self._upper is None:
            u = self._lower + abs(self._lower) + 1
        return (l + u + 1) // 2

    def binary_search_cut(self):
        """may be skipped"""
        self._pivot = self._compute_pivot()
        return self.op_strict(self._obj.term(), self._cast(self._pivot))


    def empty(self):
        """True: remove this unit from optimization search"""
        if self._upper == None or self._lower == None:
            return False
        return self._upper <= self._lower


    def search_is_sat(self, model):
        self._pivot = None
        model_value = model.get_value(self._obj.term()).constant_value()
        if self._obj.is_minimization_goal():
            if self._upper is None:
                self._upper = model_value
            elif self._upper > model_value:
                self._upper = model_value
        elif self._obj.is_maximization_goal():
            if self._lower is None:
                self._lower = model_value
            elif self._lower < model_value:
                self._lower = model_value
        else:
            pass  # this may happen in boxed multi-independent optimization


    def search_is_unsat(self):
        if self._pivot is not None:
            if self._obj.is_minimization_goal():
                self._lower = self._pivot
            else:
                self._upper = self._pivot
        else:
            if self._obj.is_minimization_goal():
                self._lower = self._upper
            else:
                self._upper = self._lower

class OptPareto(OptComparationFunctions):

    def __init__(self, goal, environment):
        self.environment = environment
        self.goal = goal
        self._cast, self.op_strict, self.op_ns = self._comparation_functions(goal)
        self.val = None

    def get_costraint_strict(self):
        if self.val is not None:
            return self.op_strict(self.goal.term(), self.val)
        else:
            return None

    def get_costraint_ns(self):
        if self.val is not None:
            return self.op_ns(self.goal.term(), self.val)
        else:
            return None

class ExternalOptimizerMixin(Optimizer):
    """An optimizer that uses an SMT-Solver externally"""

    def _setup(self):
        raise NotImplementedError

    def _cleanup(self, client_data):
        raise NotImplementedError

    def _pareto_setup(self, client_data):
        raise NotImplementedError

    def _pareto_cleanup(self, client_data):
        raise NotImplementedError

    def _pareto_check_progress(self, client_data, cost_functions,
                               costs_so_far, lts, les):
        raise NotImplementedError

    def _pareto_block_model(self, client_data, cost_functions, last_model, lts, les):
        raise NotImplementedError

    def _optimization_check_progress(self, client_data, formula, strategy):
        raise NotImplementedError

    def optimize(self, goal, strategy='linear',
                 feasible_solution_callback=None,
                 step_size=1, **kwargs):
        """This function performs the optimization as described in
        `Optimizer.optimize()`. However. two additional parameters are
        available:

        `strategy` can be either 'binary' or 'linear'. 'binary' performs a
        binary search to find the optimum, while 'ub' searches among
        the satisfiable models.

        `feasible_solution_callback` is a function with a single
        argument or None. If specified, the function will be called
        each time the algorithm finds a feasible solution. Each call
        is guaranteed to have a better solution quality than the
        previous.

        `step_size` the minimum reolution for finding a solution. The
        optimum will be found in the proximity of `step_size`
        """
        rt = None, None
        if goal.is_maximization_goal() or goal.is_minimization_goal():
            rt = self._optimize(goal, strategy)
        else:
            raise GoalNotSupportedError("ExternalOptimizerMixin", goal)
        return rt

    def boxed_optimization(self, goals, strategy='linear',
                 feasible_solution_callback=None,
                 step_size=1, **kwargs):
        rt = {}
        for goal in goals:
            self._boxed_setup()
            rt[goal] = self.optimize(goal,strategy,
                 feasible_solution_callback,
                 step_size, **kwargs)
            self._boxed_cleanup()
        return rt

    def lexicographic_optimize(self, goals, strategy='linear',
                               feasible_solution_callback=None,
                               step_size=1, **kwargs):
        costraints = []
        rt = []
        for goal in goals:
            next, costraints = self._lexicographic_opt(goal, costraints, strategy)
            rt.append(next)
        return rt

    def _pareto_cleanup(self, client_data):
        pass


    def _optimize(self, goal, strategy):
        model = None
        client_data = self._setup()
        current = OptSearchInterval(goal, self.environment, client_data)
        first_step = True
        while not current.empty():
            if not first_step:
                if strategy == "linear":
                    lin_assertions = current.linear_search_cut()
                elif strategy == "binary":
                    lin_assertions = current.binary_search_cut()
                else:
                    raise PysmtValueError("Unknown optimization strategy '%s'" % strategy)
            else:
                lin_assertions = None
            status = self._optimization_check_progress(client_data, lin_assertions, strategy)
            if status:
                model = self.get_model()
                current.search_is_sat(model)
            else:
                if first_step:
                    return None, None
                current.search_is_unsat()
            first_step = False

        self._cleanup(client_data)

        return model, model.get_value(goal.term())



    def pareto_optimize(self, goals):
        objs = [OptPareto(goal, self.environment) for goal in goals]

        terminated = False
        client_data = self._setup()
        i = 0
        while not terminated:
            i = 0
            last_model = None
            optimum_found = False
            for obj in objs:
                 obj.val = None
            self._pareto_setup(client_data)
            while not optimum_found:
                i = i+1
                optimum_found = self._pareto_check_progress(client_data,objs)
                if not optimum_found:
                    last_model = self.get_model()
                    j = -1
                    for obj in objs:
                        j = j+1
                        obj.val = self.get_value(obj.goal.term())
            self._pareto_cleanup(client_data)
            if last_model is not None:
                yield last_model, [obj.val for obj in objs]
                self._pareto_block_model(client_data, objs)
            else:
                terminated = True
        self._cleanup(client_data)


class SUAOptimizerMixin(ExternalOptimizerMixin):
    """Optimizer mixin using solving under assumptions"""

    def _setup(self):
        return []

    def _cleanup(self, client_data):
        pass

    def _optimization_check_progress(self, client_data, formula, strategy):
        if formula is not None:
            rt = self.solve(assumptions=[formula])
        else:
            rt = self.solve()
        return rt

    def _pareto_setup(self, client_data):
        pass

    def _pareto_cleanup(self, client_data):
        pass

    def _boxed_setup(self):
        self.push()

    def _boxed_cleanup(self):
        self.pop()

    def _lexicographic_opt(self, current_goal, costraints, strategy):
        self.push()
        if costraints is not None:
            for f in costraints:
                self.add_assertion(f)
        else:
            costraints = []
        model, val = self.optimize(current_goal, strategy)
        self.pop()
        costraints.append(Equals(current_goal.term(), val))
        return val, costraints



    def _pareto_check_progress(self, client_data, objs):
        mgr = self.environment.formula_manager
        k = []
        if objs[0].val is not None:
            k = [obj.get_costraint_ns() for obj in objs]
            k.append(mgr.Or(obj.get_costraint_strict()for obj in objs ))
            print(k)
        return not self.solve(assumptions=client_data + k)


    def _pareto_block_model(self, client_data, objs):
        mgr = self.environment.formula_manager
        client_data.append(mgr.Or(obj.get_costraint_strict() for obj in objs))

    def can_diverge_for_unbounded_cases(self):
        return True


class IncrementalOptimizerMixin(ExternalOptimizerMixin):
    """Optimizer mixin using the incremental interface"""

    def _setup(self):
        self.push()
        return None

    def _cleanup(self, client_data):
        self.pop()

    def _optimization_check_progress(self, client_data, formula, strategy):
        if strategy == 'linear':
            if formula is not None:
                self.add_assertion(formula)
            rt = self.solve()
        elif strategy == 'binary':
            self.push()
            if formula is not None:
                self.add_assertion(formula)
            rt = self.solve()
            self.pop()
        return rt

    def _pareto_setup(self, client_data):
        self.push()

    def _pareto_cleanup(self, client_data):
        self.pop()

    def _boxed_setup(self):
        self.push()

    def _boxed_cleanup(self):
        self.pop()

    def _lexicographic_opt(self, current_goal, costraints, strategy):
        self.push()
        if costraints is not None:
            for f in costraints:
                self.add_assertion(f)
        else:
            costraints = []
        model, val = self.optimize(current_goal, strategy)
        self.pop()
        costraints.append(Equals(current_goal.term(), val))
        return val, costraints

    def _pareto_check_progress(self, client_data, objs):
        mgr = self.environment.formula_manager
        if objs[0].val is not None:
            for obj in objs:
                self.add_assertion(obj.get_costraint_ns())
            self.add_assertion(mgr.Or(obj.get_costraint_strict() for obj in objs))
        return not self.solve()

    def _pareto_block_model(self, client_data, objs):
        mgr = self.environment.formula_manager
        self.add_assertion(mgr.Or(obj.get_costraint_strict() for obj in objs))

    def can_diverge_for_unbounded_cases(self):
        return True