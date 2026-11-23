"""Compare a fresh three-phase voltage export to an audited copy of the same no-load solution."""
import argparse
import json
import math
import sys
from pathlib import Path

from audit_case import digest, inspect, read_samples


def compare(case, exported, tolerance):
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("voltage tolerance must be finite and nonnegative")
    source = case / "noload_EMF.csv"
    if source.samefile(exported):
        raise ValueError("supply two separately exported files")
    audit = inspect(case, "noload")
    if audit["errors"]:
        raise ValueError("reference case failed audit: " + "; ".join(audit["errors"]))
    ref_headers, reference = read_samples(source, "InducedVoltage", 4, source.name, normalize_voltage=True)
    export_headers, fresh = read_samples(exported, "InducedVoltage", 4, source.name, normalize_voltage=True)
    if len(fresh) != len(reference):
        raise ValueError("sample count differs")
    maximum = [0.0, 0.0, 0.0]
    for index, (a, b) in enumerate(zip(reference, fresh)):
        if abs(a[0] - b[0]) > 1e-12 or (index and b[0] <= fresh[index - 1][0]):
            raise ValueError("time grid differs at sample %d" % index)
        for phase in range(3):
            maximum[phase] = max(maximum[phase], abs(a[phase + 1] - b[phase + 1]))
    return {
        "matches": max(maximum) <= tolerance, "voltage_tolerance_V": tolerance,
        "samples_per_phase": len(fresh), "time_window_s": [fresh[0][0], fresh[-1][0]],
        "max_abs_delta_V": dict(zip("ABC", maximum)), "reference_headers": ref_headers, "export_headers": export_headers,
        "reference_sha256": digest(source), "export_sha256": digest(exported),
        "reference_project_sha256": audit["project_sha256"], "audit_warnings": audit["warnings"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--tolerance-v", type=float, default=1e-6)
    parser.add_argument("--out", type=Path, help="new output JSON, outside the reference case")
    args = parser.parse_args()
    try:
        result = compare(args.case, args.export, args.tolerance_v)
        body = json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        if args.out:
            if args.case.resolve() in args.out.resolve().parents:
                raise ValueError("output must be outside the reference case")
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(body)
        else:
            print(body, end="")
    except (OSError, ValueError) as exc:
        parser.exit(2, "%s\n" % exc)
    return 0 if result["matches"] else 2


if __name__ == "__main__":
    sys.exit(main())
