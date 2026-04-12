from __future__ import annotations

import json

from anim import Verdict
from examples.python.families.crystal_field import study
from examples.python.families.crystal_field.check import MeasurementResult
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    ShapeConfig,
    range_spectrum,
)


def _params(outcome: str = "glass") -> Params:
    grid = GridConfig(rows=3, cols=4, spacing=0.30, offset_rows=False, hole_fraction=0.0)
    shape = ShapeConfig(
        kind="circle" if outcome == "glass" else "polygon",
        size=0.08,
        n_sides=0 if outcome == "glass" else 5,
        corner_radius=0.0,
        rotation=None,
    )
    material = MaterialConfig(
        outcome=outcome,  # type: ignore[arg-type]
        albedo=0.85,
        fill=0.10,
        ior=1.50 if outcome == "glass" else 0.0,
        cauchy_b=20_000.0 if outcome == "glass" else 0.0,
        absorption=1.0 if outcome == "glass" else 0.0,
        color_names=[],
    )
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.3),
        speed=0.12,
        moving_intensity=0.7,
        spectrum=range_spectrum(380.0, 780.0),
    )
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        look=LookConfig(exposure=-5.0),
        build_seed=123,
    )


def _result(ok: bool, summary: str) -> MeasurementResult:
    return MeasurementResult(
        metrics={
            "mean": 79.0 if ok else 81.0,
            "contrast_spread": 60.0,
            "moving_radius_mean": 0.014,
            "ambient_radius_mean": 0.009,
            "moving_to_ambient_radius_ratio": 1.55,
            "analysis_frame": 4.0,
            "analysis_fps": 4.0,
            "analysis_time": 1.0,
        },
        verdict=Verdict(ok, summary),
        analysis_frame=4,
        analysis_fps=4,
        analysis_time=1.0,
    )


def test_measured_record_extracts_tags_features_and_reason():
    p = _params()
    rec = study._measured_record(
        seed=7,
        trial=3,
        p=p,
        result=_result(False, "moving_mean=0.014 brightness=81.0 (too bright)"),
        elapsed_ms=12.0,
    )

    assert rec["schema"] == 1
    assert rec["record"] == "measured_probe"
    assert rec["status"] == "rejected"
    assert rec["tags"]["outcome"] == "glass"
    assert rec["features"]["look_exposure"] == -5.0
    assert rec["features"]["object_count"] == 12
    assert rec["verdict"]["reason"] == "brightness_high"
    assert rec["probe"]["width"] == study.PROBE_W
    assert rec["params"]["material"]["outcome"] == "glass"


def test_measured_features_count_only_real_material_colors():
    p = _params("brushed_metal")
    p.material.color_names = ["red", None]

    features = study._flat_features(p)
    tags = study._tags(p)

    assert features["material_color_count"] == 1
    assert tags["material_color_mode"] == "mixed"


def test_scan_jsonl_repairs_partial_tail(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_bytes(
        b'{"trial":0,"status":"accepted"}\n'
        b'{"trial":1,"status":"rejected"}\n'
        b'{"trial":'
    )

    rows, next_trial = study._scan_jsonl(path, repair=True)

    assert rows == 2
    assert next_trial == 2
    assert path.read_text().endswith('{"trial":1,"status":"rejected"}\n')


def test_measure_command_resumes_existing_jsonl(tmp_path, monkeypatch):
    out = tmp_path / "dataset.jsonl"
    p = _params()

    monkeypatch.setattr(study, "sample", lambda _rng: p)
    monkeypatch.setattr(study, "build", lambda _p: object())
    monkeypatch.setattr(
        study,
        "_measure_and_verdict",
        lambda _p, _animate: _result(True, "synthetic pass"),
    )

    study.run_measure(["--out", str(out), "--n", "2", "--seed", "5", "--progress-every", "0"])
    study.run_measure(["--out", str(out), "--n", "3", "--seed", "5", "--progress-every", "0"])

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["trial"] for row in rows] == [0, 1, 2]
    assert all(row["status"] == "accepted" for row in rows)


def test_analyze_command_writes_summary_tables(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    accepted = study._measured_record(
        seed=0,
        trial=0,
        p=_params("glass"),
        result=_result(True, "synthetic pass"),
        elapsed_ms=10.0,
    )
    rejected = study._measured_record(
        seed=0,
        trial=1,
        p=_params("black_diffuse"),
        result=_result(False, "moving_mean=0.014 brightness=81.0 (too bright)"),
        elapsed_ms=11.0,
    )
    dataset.write_text(json.dumps(accepted) + "\n" + json.dumps(rejected) + "\n")
    out = tmp_path / "analysis"

    study.run_analyze(["--in", str(dataset), "--out", str(out)])

    summary = json.loads((out / "summary.json").read_text())
    assert summary["record_count"] == 2
    assert summary["accepted_count"] == 1
    assert summary["failure_reasons"]["brightness_high"] == 1
    assert (out / "groups.csv").exists()
    assert (out / "failure_reasons.csv").exists()
    assert (out / "feature_stats.csv").exists()
    assert (out / "reason_groups.csv").exists()
    assert (out / "feature_deltas.csv").exists()
    assert (out / "numeric_bins.csv").exists()
    assert (out / "conditional_numeric_bins.csv").exists()
    assert (out / "numeric_interactions.csv").exists()
    assert (out / "index.html").exists()


def test_conditional_numeric_bins_are_grouped_by_scenario():
    records = []
    for trial in range(20):
        outcome = "glass" if trial < 10 else "black_diffuse"
        ok = trial in {2, 3, 14}
        rec = study._measured_record(
            seed=0,
            trial=trial,
            p=_params(outcome),
            result=_result(ok, "synthetic pass" if ok else "brightness=81.0 (too bright)"),
            elapsed_ms=1.0,
        )
        rec["features"]["look_exposure"] = float(trial)
        records.append(rec)

    rows = study._conditional_numeric_bin_rows(
        records,
        bins=2,
        group_keys=["tags.outcome"],
    )

    glass_rows = [
        row
        for row in rows
        if row["group"] == "tags.outcome"
        and row["value"] == "glass"
        and row["feature"] == "look_exposure"
    ]
    black_rows = [
        row
        for row in rows
        if row["group"] == "tags.outcome"
        and row["value"] == "black_diffuse"
        and row["feature"] == "look_exposure"
    ]

    assert len(glass_rows) == 2
    assert len(black_rows) == 2
    assert [row["total"] for row in glass_rows] == [5, 5]
    assert [row["total"] for row in black_rows] == [5, 5]


def test_numeric_interactions_bin_two_parameters():
    records = []
    for trial in range(16):
        rec = study._measured_record(
            seed=0,
            trial=trial,
            p=_params("black_diffuse"),
            result=_result(trial in {5, 10}, "synthetic pass"),
            elapsed_ms=1.0,
        )
        rec["features"]["look_exposure"] = float(trial % 4)
        rec["features"]["ambient_intensity"] = float(trial // 4)
        records.append(rec)

    rows = study._numeric_interaction_rows(
        records,
        features=["look_exposure", "ambient_intensity"],
        bins=2,
    )

    selected = [
        row
        for row in rows
        if row["x_feature"] == "look_exposure"
        and row["y_feature"] == "ambient_intensity"
    ]

    assert len(selected) == 4
    assert sum(row["total"] for row in selected) == 16


def test_numeric_interactions_include_probe_metrics():
    records = []
    for trial in range(16):
        rec = study._measured_record(
            seed=0,
            trial=trial,
            p=_params("black_diffuse"),
            result=_result(trial in {5, 10}, "synthetic pass"),
            elapsed_ms=1.0,
        )
        rec["features"]["ambient_intensity"] = float(trial % 4)
        rec["metrics"]["ambient_radius_mean"] = float(trial // 4)
        records.append(rec)

    rows = study._numeric_interaction_rows(
        records,
        features=["ambient_intensity"],
        bins=2,
    )

    selected = [
        row
        for row in rows
        if row["x_feature"] == "ambient_intensity"
        and row["y_feature"] == "metric_ambient_radius_mean"
    ]

    assert len(selected) == 4
    assert sum(row["total"] for row in selected) == 16
