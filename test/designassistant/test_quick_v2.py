"""From-scratch Quick generation with unchanged engine and material snapshots."""

import ast
import copy
import dataclasses
import unittest
from pathlib import Path
from unittest.mock import patch

from designassistant import CandidateGenerator, CandidateProposal, LibraryEntry, MetricConstraint, Snapshot
from designassistant.quick import (
    QuickCriterion,
    QuickDesignProblemBuilder,
    QuickDesignRequirements,
    QuickDesignRequirementsValidator,
)
from designassistant.quick_generation import (
    QuickDesignGeometryFactory,
    QuickDesignNozzleFactory,
    QuickDimensions,
)
from motorlib.grains import grainTypes
from motorlib.motor import Motor
from motorlib.properties import FloatProperty
from motorlib.simResult import SimAlertLevel, SimulationResult
from test.designassistant.support import fixture_snapshot


def requirements(*optional, **settings):
    return QuickDesignRequirements(
        (
            QuickCriterion("diameter", "maximum", 0.1),
            QuickCriterion("length", "maximum", 0.8),
            QuickCriterion("burn_time", "target", 15),
        )
        + optional,
        **settings,
    )


def empty_motor():
    result = Motor().getDict()
    result["config"] = fixture_snapshot()["config"]
    return result


def build(req=None, baseline=None, entries=None):
    return QuickDesignProblemBuilder().build(
        empty_motor() if baseline is None else baseline,
        requirements() if req is None else req,
        (LibraryEntry.from_dict(fixture_snapshot()["propellant"]),) if entries is None else entries,
    )


class QuickFromScratchTests(unittest.TestCase):
    def test_empty_motor_and_unconfigured_nozzle_need_only_three_requirements(self):
        baseline = empty_motor()
        original = copy.deepcopy(baseline)
        with patch.object(Motor, "runSimulation") as simulation:
            problem = build(baseline=baseline)
        simulation.assert_not_called()
        self.assertTrue(problem.plan.variants)
        self.assertEqual(baseline, original)
        self.assertEqual(problem.plan.baseline, Snapshot.from_dict(original))
        for variant in problem.plan.variants:
            motor = Motor(variant.baseline.to_dict())
            self.assertTrue(motor.grains)
            self.assertGreater(motor.nozzle.getProperty("throat"), 0)
            self.assertGreater(motor.nozzle.getProperty("efficiency"), 0)

    def test_raw_motor_default_configuration_is_supported(self):
        problem = build(baseline=Motor().getDict())
        self.assertEqual(problem.plan.variants[0].baseline.to_dict()["config"], Motor().config.getProperties())

    def test_absent_configuration_uses_engine_defaults(self):
        problem = build(baseline={})
        self.assertEqual(problem.plan.variants[0].baseline.to_dict()["config"], Motor().config.getProperties())

    def test_source_geometry_and_nozzle_are_never_used(self):
        bad = empty_motor()
        bad["grains"] = [{"type": "unknown-source-type", "properties": {"points": [[1, 2]]}}]
        bad["nozzle"] = {"throat": "unconfigured"}
        first = build()
        second = build(baseline=bad)
        self.assertEqual([v.baseline for v in first.plan.variants], [v.baseline for v in second.plan.variants])
        self.assertEqual(second.plan.baseline, Snapshot.from_dict(bad))

    def test_no_thrust_or_impulse_goal_is_invented(self):
        self.assertEqual([t.metric for t in build().plan.requirements.targets], ["burn_time"])
        self.assertFalse(build().inferred_targets)

    def test_optional_thrust_only(self):
        p = build(requirements(QuickCriterion("average_thrust", "target", 50)))
        self.assertEqual([t.metric for t in p.plan.requirements.targets], ["burn_time", "average_thrust"])

    def test_optional_impulse_only(self):
        p = build(requirements(QuickCriterion("total_impulse", "target", 750)))
        self.assertEqual([t.metric for t in p.plan.requirements.targets], ["burn_time", "total_impulse"])

    def test_optional_thrust_and_impulse(self):
        p = build(
            requirements(QuickCriterion("average_thrust", "target", 50), QuickCriterion("total_impulse", "target", 750))
        )
        self.assertEqual(
            [t.metric for t in p.plan.requirements.targets], ["burn_time", "average_thrust", "total_impulse"]
        )
        self.assertFalse(p.diagnostics)

    def test_inconsistent_goals_warn_before_simulation_without_changing_targets(self):
        req = requirements(
            QuickCriterion("average_thrust", "target", 50), QuickCriterion("total_impulse", "target", 100)
        )
        with patch.object(Motor, "runSimulation") as simulation:
            p = build(req)
        simulation.assert_not_called()
        self.assertTrue(any("may conflict" in d.source for d in p.diagnostics))
        self.assertEqual([t.value for t in p.plan.requirements.targets], [15, 50, 100])

    def test_each_required_field_is_mandatory(self):
        for omitted in ("diameter", "length", "burn_time"):
            req = dataclasses.replace(
                requirements(), criteria=tuple(c for c in requirements().criteria if c.field != omitted)
            )
            with self.subTest(field=omitted), patch.object(Motor, "runSimulation") as simulation:
                validation = QuickDesignRequirementsValidator().validate(
                    empty_motor(), req, (LibraryEntry.from_dict(fixture_snapshot()["propellant"]),)
                )
            self.assertFalse(validation.valid)
            simulation.assert_not_called()

    def test_mandatory_and_optional_field_modes_are_explicit(self):
        for index, mode in ((0, "target"), (1, "minimum"), (2, "maximum")):
            criteria = list(requirements().criteria)
            criteria[index] = dataclasses.replace(criteria[index], mode=mode)
            with self.assertRaises(ValueError):
                build(dataclasses.replace(requirements(), criteria=tuple(criteria)))
        with self.assertRaises(ValueError):
            build(requirements(QuickCriterion("average_thrust", "minimum", 50)))

    def test_all_current_geometry_types_have_independent_profiles(self):
        factory = QuickDesignGeometryFactory()
        self.assertEqual(set(factory.PROFILES), set(grainTypes))
        for name in sorted(grainTypes):
            with self.subTest(geometry=name):
                template = factory.create(name, QuickDimensions(0.1, 0.8))
                grain = grainTypes[name]()
                grain.setProperties(template.properties.to_dict())
                self.assertFalse([a for a in grain.getGeometryErrors() if a.level == SimAlertLevel.ERROR])
                self.assertEqual(set(template.properties.to_dict()), set(grain.props))

    def test_numerical_geometries_initialize_nonempty_ports_using_existing_api(self):
        # Exercise geometry setup, including the actual Custom polygon. No new
        # area formula or simulation is needed to verify usable core topology.
        for name in sorted(set(grainTypes) - {"End Burner"}):
            with self.subTest(geometry=name):
                template = QuickDesignGeometryFactory().create(name, QuickDimensions(0.1, 0.8))
                grain = grainTypes[name]()
                grain.setProperties(template.properties.to_dict())
                grain.simulationSetup(Motor().config)
                self.assertGreater(grain.getPortArea(0), 0)

    def test_geometry_specific_properties_do_not_come_from_bates(self):
        factory = QuickDesignGeometryFactory()
        star = factory.create("Star Grain", QuickDimensions(0.1, 0.8)).properties.to_dict()
        conical = factory.create("Conical", QuickDimensions(0.1, 0.8)).properties.to_dict()
        rod = factory.create("Rod and Tube", QuickDimensions(0.1, 0.8)).properties.to_dict()
        self.assertNotIn("coreDiameter", star)
        self.assertGreater(star["numPoints"], 0)
        self.assertNotEqual(conical["forwardCoreDiameter"], conical["aftCoreDiameter"])
        self.assertLess(rod["supportDiameter"], rod["rodDiameter"])
        self.assertLess(rod["rodDiameter"], rod["coreDiameter"])

    def test_custom_polygon_is_independent_and_fixed_while_numeric_dimensions_vary(self):
        template = QuickDesignGeometryFactory().create("Custom Grain", QuickDimensions(0.1, 0.8))
        points = template.properties.to_dict()["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(len(points[0]), 4)
        points[0].clear()
        self.assertEqual(len(template.properties.to_dict()["points"][0]), 4)
        self.assertEqual(template.properties.to_dict()["dxfUnit"], "m")
        self.assertEqual({key for key, _ in template.ranges}, {"diameter", "length"})

    def test_nozzle_is_created_with_valid_bounds_and_stock_property_set(self):
        factory = QuickDesignNozzleFactory()
        from motorlib.nozzle import Nozzle

        data, ranges = factory.create(QuickDimensions(0.1, 0.8))
        nozzle = Nozzle()
        nozzle.setProperties(data.to_dict())
        self.assertFalse(nozzle.getGeometryErrors())
        self.assertEqual(set(data.to_dict()), set(nozzle.props))
        bounds = dict(ranges)
        self.assertLess(bounds["throat"].maximum, bounds["exit"].minimum)
        self.assertLessEqual(bounds["exit"].maximum, 0.1)

    def test_joint_candidates_never_optimize_empirical_nozzle_parameters(self):
        from motorlib.nozzle import Nozzle

        stock = Nozzle().getProperties()
        problem = build()
        for variant in problem.plan.variants:
            paths = {variable.path.value for variable in variant.requirements.variables}
            self.assertEqual({p for p in paths if p.startswith("nozzle.")}, {"nozzle.throat", "nozzle.exit"})
            self.assertTrue(any(p.startswith("grains.") for p in paths))
            nozzle = variant.baseline.to_dict()["nozzle"]
            for key in set(stock) - {"throat", "exit"}:
                expected = QuickDesignNozzleFactory.FIXED_INITIAL_PROPERTIES.get(key, stock[key])
                self.assertEqual(nozzle[key], expected)
            generator = CandidateGenerator(variant.baseline.to_dict(), variant.requirements)
            for endpoint in ("minimum", "maximum"):
                request = generator.generate(
                    CandidateProposal.from_values(
                        endpoint, {v.path.value: getattr(v.range, endpoint) for v in variant.requirements.variables}
                    )
                )
                motor = Motor(request.snapshot.to_dict())
                self.assertFalse(motor.nozzle.getGeometryErrors())
                self.assertGreater(motor.nozzle.calcExpansion(), 1)
                self.assertEqual(
                    {k: motor.nozzle.getProperty(k) for k in set(stock) - {"throat", "exit"}},
                    {k: nozzle[k] for k in set(stock) - {"throat", "exit"}},
                )

    def test_every_generated_geometry_reaches_the_real_simulation_api(self):
        from designassistant import EngineAdapter, MetricRegistry, OutcomeStatus
        from test.designassistant.test_quick import inputs

        problem = build(inputs())
        adapter = EngineAdapter(MetricRegistry(problem.plan.requirements.metric_definitions))
        seen = set()
        simulate = Motor.runSimulation

        def record_simulation(motor, callback=None):
            seen.add(tuple(g.geomName for g in motor.grains))
            return simulate(motor, callback)

        with patch.object(Motor, "runSimulation", record_simulation):
            for variant in problem.plan.variants:
                request = CandidateGenerator(variant.baseline.to_dict(), variant.requirements).generate(
                    CandidateProposal.from_values(
                        variant.key,
                        {
                            v.path.value: value
                            for v, value in zip(variant.requirements.variables, variant.initial_values)
                        },
                    )
                )
                outcome = adapter.run(request)
                self.assertNotIn(outcome.status, (OutcomeStatus.INVALID_REQUEST, OutcomeStatus.EXCEPTION))
        self.assertEqual({g[0] for g in seen}, set(grainTypes))

    def test_grain_counts_follow_dimensions_and_are_explored(self):
        factory = QuickDesignGeometryFactory()
        self.assertEqual(factory.grain_counts(QuickDimensions(0.1, 0.8)), (1, 2, 3, 4, 5, 6))
        self.assertEqual(factory.grain_counts(QuickDimensions(0.1, 0.01)), (1,))
        self.assertEqual({len(v.geometries) for v in build().plan.variants}, {1, 2, 3, 4, 5, 6})

    def test_end_burner_count_respects_existing_engine_restriction(self):
        p = build()
        self.assertTrue(any(v.geometries == ("End Burner",) for v in p.plan.variants))
        self.assertFalse(any("End Burner" in v.geometries and len(v.geometries) > 1 for v in p.plan.variants))
        with self.assertRaisesRegex(ValueError, "forward-most"):
            QuickDesignGeometryFactory().create("End Burner", QuickDimensions(0.1, 0.8), 2)

    def test_invalid_geometry_and_count_fail_explicitly(self):
        for name, count in (("new-type", 1), ("BATES", 0), ("BATES", True), ("BATES", 7)):
            with self.assertRaises(ValueError):
                QuickDesignGeometryFactory().create(name, QuickDimensions(0.1, 0.8), count)

    def test_rectangular_bounds_fit_total_length_for_all_counts(self):
        for variant in build().plan.variants:
            gen = CandidateGenerator(variant.baseline.to_dict(), variant.requirements)
            for label in ("minimum", "maximum"):
                request = gen.generate(
                    CandidateProposal.from_values(
                        label, {v.path.value: getattr(v.range, label) for v in variant.requirements.variables}
                    )
                )
                self.assertTrue(request.valid)
                result = SimulationResult(Motor(request.snapshot.to_dict()))
                self.assertLessEqual(result.getPropellantLength(), 0.8)
                self.assertLessEqual(result.getMaxPropellantDiameter(), 0.1)

    def test_ranges_are_dimension_driven_instead_of_baseline_relative(self):
        base = fixture_snapshot()
        another = copy.deepcopy(base)
        another["grains"].clear()
        another["nozzle"] = Motor().nozzle.getProperties()
        first, second = build(baseline=base), build(baseline=another)
        self.assertEqual(
            [(v.baseline, v.requirements.variables) for v in first.plan.variants],
            [(v.baseline, v.requirements.variables) for v in second.plan.variants],
        )

    def test_project_configuration_is_preserved_exactly(self):
        baseline = empty_motor()
        for variant in build(baseline=baseline).plan.variants:
            self.assertEqual(variant.baseline.to_dict()["config"], baseline["config"])

    def test_library_order_and_same_seed_produce_identical_plan(self):
        original = fixture_snapshot()["propellant"]
        second = copy.deepcopy(original)
        second["name"] += " copy"
        entries = tuple(map(LibraryEntry.from_dict, (original, second)))
        self.assertEqual(build(entries=entries), build(entries=entries[::-1]))

    def test_seeded_budget_covers_libraries_geometries_counts_without_full_cartesian_search(self):
        from uilib.defaults import DEFAULT_PROPELLANTS

        # Material snapshots are consumed verbatim; no recipes are generated.
        entries = tuple(LibraryEntry.from_dict(p) for p in DEFAULT_PROPELLANTS)
        p = build(entries=entries)
        self.assertEqual({v.library_key for v in p.plan.variants}, {e.key for e in entries})
        self.assertEqual({v.geometries[0] for v in p.plan.variants}, set(grainTypes))
        self.assertEqual({len(v.geometries) for v in p.plan.variants}, {1, 2, 3, 4, 5, 6})
        self.assertLess(len(p.plan.variants), p.total_combinations)
        self.assertLessEqual(len(p.plan.variants), p.requirements.simulation_budget)

    def test_setter_rejection_is_explicit_and_prevents_any_simulation(self):
        original = FloatProperty.setValue

        def reject(prop, value):
            if prop.dispName == "Throat Diameter":
                return
            original(prop, value)

        with patch.object(FloatProperty, "setValue", reject), patch.object(Motor, "runSimulation") as simulation:
            validation = QuickDesignRequirementsValidator().validate(
                empty_motor(), requirements(), (LibraryEntry.from_dict(fixture_snapshot()["propellant"]),)
            )
        self.assertFalse(validation.valid)
        self.assertIn("setter read-back", validation.diagnostics[0].arguments_json)
        simulation.assert_not_called()

    def test_dimensional_constraints_precede_scoring(self):
        constraints = build().plan.requirements.constraints
        self.assertIn(MetricConstraint("maximum_diameter", maximum=0.1), constraints)
        self.assertIn(MetricConstraint("propellant_length", maximum=0.8), constraints)

    def test_peak_thrust_uses_only_existing_force_channel_getter(self):
        from designassistant.metrics import ChannelMetricDefinition, MetricRegistry

        definition = ChannelMetricDefinition("peak_thrust", "Peak Thrust", "N", "getMax", "force")
        registry = MetricRegistry((definition,))
        result = SimulationResult(Motor())
        for value in (0, 20, 50, 15):
            result.channels["force"].addData(value)
        self.assertEqual(registry.extract(result)[0].value, result.channels["force"].getMax())
        with self.assertRaises(ValueError):
            MetricRegistry((ChannelMetricDefinition("bad", "Bad", "", "getMax", "unknown"),))
        with self.assertRaises(ValueError):
            MetricRegistry((ChannelMetricDefinition("bad", "Bad", "", "inventPhysics", "force"),))

    def test_engine_numpy_alert_arguments_keep_numeric_formatting(self):
        import json

        import numpy as np

        from designassistant.models import TextRecord
        from motorlib.localization import QT_TRANSLATE_NOOP

        text = QT_TRANSLATE_NOOP("SimulationAlerts", "Initial port/throat ratio of {:.3f} was less than {:.3f}")
        record = TextRecord.from_engine(text.format(np.float64(1.25), np.float32(2)))
        arguments = json.loads(record.arguments_json)["args"]
        self.assertEqual(arguments, [1.25, 2.0])
        self.assertEqual(record.source.format(*arguments), str(text.format(1.25, 2)))
        integer = TextRecord.from_engine(QT_TRANSLATE_NOOP("Test", "{:d}").format(np.int64(3)))
        self.assertEqual(integer.source.format(*json.loads(integer.arguments_json)["args"]), "3")

    def test_generation_module_is_qt_free_and_never_calls_simulation(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / "designassistant/quick_generation.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith(("PyQt", "uilib")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, "runSimulation")

    def test_real_headless_search_from_empty_motor_returns_ranked_actual_metrics(self):
        from test.designassistant.test_quick import inputs, run

        baseline = empty_motor()
        original = copy.deepcopy(baseline)
        problem = build(inputs(), baseline=baseline)
        strategy, trace = run(problem)
        ranked = strategy.results.ranked()
        self.assertTrue(trace)
        self.assertGreaterEqual(len(ranked), 2)
        self.assertTrue(all(record.evaluation.outcome.valid for record in ranked))
        for record in ranked:
            self.assertGreater(record.evaluation.outcome.metric("peak_thrust"), 0)
            self.assertLessEqual(record.evaluation.outcome.metric("maximum_diameter"), 0.05)
            self.assertLessEqual(record.evaluation.outcome.metric("propellant_length"), 0.02)
            self.assertEqual([target.metric for target in record.analysis.targets], ["burn_time"])
        self.assertEqual(baseline, original)


if __name__ == "__main__":
    unittest.main()
