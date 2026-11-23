#!/usr/bin/env python3
"""Compare the last two sampled mechanical turns; this does not prove convergence.

Input must be a uniformly sampled CSV with a time column headed e.g. ``Time [ms]``
or ``Time [s]`` and the selected signal column. If the time header has no unit,
``--time-unit`` is required. All reported quantities retain the signal column's
unit. End time is always given in seconds. No extrapolation or interpolation
across missing samples is permitted.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

TIME_UNITS = {'s': 1.0, 'ms': 1e-3, 'us': 1e-6, 'µs': 1e-6, 'μs': 1e-6}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _time_factor(header, supplied):
    # An explicit but unsupported header unit must never be mistaken for a
    # unitless header: an override could otherwise reinterpret ns as seconds.
    match = re.search(r'\[\s*([^\[\]]*?)\s*\]\s*$', header)
    inferred = match.group(1).lower() if match else None
    if match and inferred not in TIME_UNITS:
        raise ValueError('unsupported time unit in time-column header: %r; convert the CSV to a supported unit' % match.group(1))
    if not match and ('[' in header or ']' in header):
        raise ValueError('malformed time-column unit header')
    if supplied is not None and supplied not in TIME_UNITS:
        raise ValueError('unsupported supplied time unit: %r' % supplied)
    if supplied and inferred and TIME_UNITS[supplied] != TIME_UNITS[inferred]:
        raise ValueError('time unit conflicts with the time-column header')
    unit = supplied or inferred
    if unit is None:
        raise ValueError('time column has no recognized unit; specify --time-unit')
    return TIME_UNITS[unit], unit


def read_samples(path, column, time_column=None, time_unit=None):
    with Path(path).open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError('empty CSV')
        if len(set(headers)) != len(headers):
            raise ValueError('duplicate column names')
        if time_column is None:
            candidates = [h for h in headers if re.match(r'^\s*time(?:\s*\[.*\])?\s*$', h, re.I)]
            if len(candidates) != 1:
                raise ValueError('expected one Time column; specify --time-column')
            time_column = candidates[0]
        if time_column not in headers or column not in headers or time_column == column:
            raise ValueError('time and signal columns must be distinct and present')
        factor, unit = _time_factor(time_column, time_unit)
        ti, vi = headers.index(time_column), headers.index(column)
        rows = []
        for line, fields in enumerate(reader, 2):
            if len(fields) != len(headers):
                raise ValueError('wrong number of columns at line %d' % line)
            try:
                t, v = float(fields[ti]) * factor, float(fields[vi])
            except (TypeError, ValueError):
                raise ValueError('non-numeric time or signal at line %d' % line)
            if not math.isfinite(t) or not math.isfinite(v):
                raise ValueError('non-finite time or signal at line %d' % line)
            rows.append((t, v))
    if len(rows) < 3:
        raise ValueError('at least three samples are required')
    intervals = [b[0] - a[0] for a, b in zip(rows, rows[1:])]
    if any(dt <= 0 for dt in intervals):
        raise ValueError('time must be strictly increasing, without duplicates')
    # Estimate from the endpoints to avoid bias from rounded first-step values.
    step = (rows[-1][0] - rows[0][0]) / (len(rows) - 1)
    tolerance = max(1e-12, step * 1e-6)
    if any(abs(dt - step) > tolerance for dt in intervals):
        raise ValueError('time samples are not uniformly continuous; missing or irregular samples')
    return rows, time_column, unit, step, tolerance


def linear_mean(values, times):
    duration = times[-1] - times[0]
    return sum((times[i+1]-times[i]) * (values[i]+values[i+1]) / 2.0
               for i in range(len(values)-1)) / duration


def compare(path, column, poles, frequency_hz, end_time_s, time_column=None, time_unit=None):
    if isinstance(poles, bool) or not isinstance(poles, int) or poles <= 0 or poles % 2:
        raise ValueError('poles must be a positive even integer')
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError('frequency must be finite and positive')
    if not math.isfinite(end_time_s):
        raise ValueError('end time must be finite')
    source = Path(path).resolve(strict=True)
    source_hash = sha256(source)
    rows, time_column, unit, step, tolerance = read_samples(source, column, time_column, time_unit)
    if sha256(source) != source_hash:
        raise ValueError('source CSV changed during reading')
    period = (poles / 2.0) / frequency_hz
    count = int(round(period / step))
    if count < 1 or abs(count * step - period) > max(1e-10, period * 1e-7):
        raise ValueError('mechanical period is not an integer number of sampling intervals')
    index = int(round((end_time_s - rows[0][0]) / step))
    if index < 0 or index >= len(rows) or abs(rows[index][0] - end_time_s) > tolerance:
        raise ValueError('end time is not an available sample')
    if index < 2 * count:
        available = rows[index][0] - rows[0][0]
        required = 2.0 * period
        missing = max(0.0, required - available)
        raise ValueError('insufficient data for two complete mechanical periods; '
                         'available coverage %.12g s, required %.12g s, shortfall %.12g s '
                         '(assuming electrical frequency and pole count imply synchronous mechanical speed)'
                         % (available, required, missing))
    start = index - 2 * count
    first = rows[start:start+count+1]
    second = rows[start+count:index+1]
    if len(first) != count+1 or len(second) != count+1:
        raise ValueError('incomplete mechanical-period windows')
    if any(abs((b[0]-a[0])-period) > max(tolerance, period*1e-7) for a, b in zip(first, second)):
        raise ValueError('periods cannot be aligned at the same mechanical angle')
    times = [r[0] - first[0][0] for r in first]
    a = [r[1] for r in first]
    b = [r[1] for r in second]
    delta = [y-x for x, y in zip(a, b)]
    duration = times[-1] - times[0]
    rms = math.sqrt(sum((times[i+1]-times[i]) *
                        (delta[i]**2 + delta[i]*delta[i+1] + delta[i+1]**2) / 3.0
                        for i in range(count)) / duration)
    mean_a = linear_mean(a, times)
    mean_b = linear_mean(b, times)
    return {
        'status': 'sampled_period_comparison_not_convergence',
        'source_csv': str(source), 'source_sha256': source_hash,
        'script_sha256': sha256(__file__), 'time_column': time_column,
        'time_unit_in_csv': unit, 'signal_column': column,
        'poles': poles, 'frequency_hz': frequency_hz,
        'mechanical_period_s': period, 'sample_step_s': step,
        'samples_per_period_including_endpoints': count+1,
        'windows_s': [[first[0][0], first[-1][0]], [second[0][0], second[-1][0]]],
        'first_mean': mean_a, 'second_mean': mean_b,
        'second_minus_first_mean': mean_b - mean_a,
        'difference_rms': rms,
        'difference_sample_min': min(delta), 'difference_sample_max': max(delta),
        'difference_max_abs_sampled': max(abs(x) for x in delta),
        'method': 'Time-weighted piecewise-linear integration; differences pair samples one mechanical period apart.',
        'limitations': ['No proof of physical correctness, mesh or time-step convergence, or future steady state.',
                        'Difference extrema are sampled values; peaks between samples are not established.',
                        'The frequency and pole count must correspond to synchronous mechanical speed.']
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--column', required=True, help='exact signal column header')
    parser.add_argument('--time-column', help='exact time column header; defaults to unique Time header')
    # Keep argparse help ASCII for Windows consoles using a GBK code page;
    # still accept both Unicode micro signs in supplied values and CSV headers.
    parser.add_argument('--time-unit', type=lambda value: value.replace('µ', 'u').replace('μ', 'u'),
                        choices=('s', 'ms', 'us'), help='required if time header has no unit')
    parser.add_argument('--poles', type=int, required=True)
    parser.add_argument('--frequency-hz', type=float, required=True)
    parser.add_argument('--end-time-s', type=float, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.csv, args.column, args.poles, args.frequency_hz, args.end_time_s,
                     args.time_column, args.time_unit)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    encoding = sys.stdout.encoding or 'utf-8'
    print(str(args.out).encode(encoding, errors='backslashreplace').decode(encoding))


if __name__ == '__main__':
    main()
