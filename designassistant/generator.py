"""Isolated candidate construction and mandatory setter read-back validation."""

from copy import deepcopy

from motorlib.motor import Motor
from motorlib.properties import IntProperty

from .models import CandidateRequest, DesignRequirements, Snapshot, diagnostic
from .paths import PropertyValidationError


class CandidateGenerator:
    def __init__(self, baseline_snapshot: dict, requirements: DesignRequirements):
        # Preserve the input shape, including PolygonProperty nested structures.
        self._baseline = deepcopy(baseline_snapshot)
        self.requirements = requirements
        self.baseline_digest = Snapshot.from_dict(self._baseline).digest
        self.requirements_digest = requirements.digest
        probe = Motor(deepcopy(self._baseline))
        for variable in requirements.variables:
            prop = variable.path.validate_numeric_variable(probe)
            if variable.range.minimum < prop.min or variable.range.maximum > prop.max:
                raise PropertyValidationError("out_of_bounds", "Variable range exceeds the engine bounds.")
            if isinstance(prop, IntProperty) and not variable.range.integer:
                raise PropertyValidationError("invalid_value", "Integer engine properties require integer ranges.")
        self._variables = {v.path: v for v in requirements.variables}

    @property
    def baseline_snapshot(self):
        return deepcopy(self._baseline)

    def generate(self, proposal):
        """Even an invalid proposal receives its own fresh Motor; never simulate here."""
        motor = Motor(deepcopy(self._baseline))
        diagnostics = []
        seen = set()
        for assignment in proposal.assignments:
            try:
                if assignment.path in seen:
                    raise PropertyValidationError("duplicate_assignment", "A property was assigned twice.")
                seen.add(assignment.path)
                variable = self._variables.get(assignment.path)
                if variable is None:
                    # Resolve first to distinguish an unknown property from a fixed property.
                    assignment.path.resolve(motor)
                    raise PropertyValidationError("undeclared_variable", "Property is not a declared design variable.")
                if not variable.range.contains(assignment.value):
                    raise PropertyValidationError("out_of_range", "Assignment is outside the declared parameter range.")
                assignment.path.write_validated(motor, assignment.value)
            except Exception as error:
                diagnostics.append(
                    diagnostic(
                        getattr(error, "code", "invalid_value"),
                        "Invalid assignment for {path}: {reason}",
                        path=assignment.path.value,
                        reason=str(error),
                    )
                )
        # A proposal is a complete point in the search space, not an implicit patch.
        for variable in self.requirements.variables:
            if variable.path not in seen:
                diagnostics.append(
                    diagnostic("missing_assignment", "Missing assignment for {path}.", path=variable.path.value)
                )
        snapshot = None if diagnostics else Snapshot.from_dict(deepcopy(motor.getDict()))
        return CandidateRequest(proposal, snapshot, self.baseline_digest, self.requirements_digest, tuple(diagnostics))
