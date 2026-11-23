"""Write an independent Maxwell three-phase no-load CSV in milliseconds and volts."""
import argparse
import csv
from pathlib import Path

from audit_case import read_samples


def write_volts(raw, output):
    _, rows = read_samples(raw, "InducedVoltage", 4, "noload_EMF.csv", normalize_voltage=True)
    if len(rows) < 2 or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("expected at least two strictly increasing sample times")
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Time [ms]"] + ["InducedVoltage(Phase_%s) [V]" % phase for phase in "ABC"])
        for t, a, b, c in rows:
            writer.writerow([1000*t, a, b, c])
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new file; preserve the original")
    args = parser.parse_args()
    try:
        print("%d rows written in ms and V" % write_volts(args.csv, args.out))
    except (ValueError, OSError) as error:
        parser.exit(2, "%s\n" % error)
