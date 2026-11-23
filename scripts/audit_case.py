#!/usr/bin/env python3
"""Check saved Maxwell case evidence and summarize sampled waveforms, read only.

This is intentionally restricted to the case layout produced by this workspace's
full-model 2021 R1 generators; it is not a general AEDT result validator. It
does not open or solve an AEDT project and cannot prove physical correctness,
convergence, or that logs were not altered. Output status is evidence-level only.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

FILES = {
    'noload': {'noload_EMF.csv': ('InducedVoltage', 4)},
    'load': {'Torque.csv': ('Torque', 2), 'Current.csv': ('InputCurrent', 4),
             'Flux.csv': ('FluxLinkage', 4), 'Voltage.csv': ('InducedVoltage', 4),
             'SolidLoss.csv': ('SolidLoss', 2)},
    'loss': {'Torque.csv': ('Torque', 2), 'Current.csv': ('InputCurrent', 4),
             'Flux.csv': ('FluxLinkage', 4), 'Voltage.csv': ('InducedVoltage', 4),
             'SolidLoss.csv': ('SolidLoss', 2), 'core_loss.csv': ('CoreLoss', 4)},
}
TIME_SCALE = {'s': 1., 'ms': 1e-3, 'us': 1e-6, 'ns': 1e-9}
EXPORTS = {'noload': ('exported EMF',), 'load': ('exported Torque', 'exported Current', 'exported Flux', 'exported Voltage', 'exported SolidLoss'),
           'loss': ('exported steel core loss', 'exported Torque', 'exported Current', 'exported Flux', 'exported Voltage', 'exported SolidLoss')}
HEADERS = {
    'noload_EMF.csv': [r'InducedVoltage\(Phase_' + p + r'\) \[V\]' for p in 'ABC'],
    'Voltage.csv': [r'InducedVoltage\(Phase_' + p + r'\) \[V\]' for p in 'ABC'],
    'Current.csv': [r'InputCurrent\(Phase_' + p + r'\) \[A\]' for p in 'ABC'],
    'Flux.csv': [r'FluxLinkage\(Phase_' + p + r'\) \[Wb\]' for p in 'ABC'],
    'Torque.csv': [r'Moving1\.Torque \[NewtonMeter\]'],
    'SolidLoss.csv': [r'SolidLoss \[(?:fW|pW|nW|uW|µW|mW|W|kW)\]'],
    'core_loss.csv': [r'CoreLoss \[W\]', r'CoreLoss\(Stator\) \[W\]', r'CoreLoss\(Rotor\) \[W\]'],
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_samples(path, marker, count, schema_name, normalize_voltage=False, normalize_current=False):
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    if not rows or len(rows[0]) != count or not all(marker in h for h in rows[0][1:]):
        raise ValueError('unexpected CSV columns for ' + path.name)
    scales = [1.] * (count - 1)
    if normalize_voltage or normalize_current:
        if normalize_current and schema_name != 'Current.csv' or normalize_voltage and schema_name not in ('noload_EMF.csv','Voltage.csv'):
            raise ValueError('Unexpected schema for phase unit conversion')
        quantity,unit,unit_name = ('InputCurrent','A','current') if normalize_current else ('InducedVoltage','V','voltage')
        prefixes = {'u':1e-6,'µ':1e-6,'m':1e-3,'':1.,'k':1e3}
        for i, phase in enumerate('ABC'):
            column = re.fullmatch(quantity+r'\(Phase_' + phase + r'\) \[([uµmk]?)'+unit+r'\]', rows[0][i+1].strip())
            if not column:
                raise ValueError('unexpected CSV column order or '+unit_name+' unit in ' + path.name)
            scales[i] = prefixes[column.group(1)]
    elif any(not re.fullmatch(pattern, value.strip()) for pattern, value in zip(HEADERS[schema_name], rows[0][1:])):
        raise ValueError('unexpected CSV column order or value units in ' + path.name)
    match = re.fullmatch(r'Time\s*\[(s|ms|us|ns)\]', rows[0][0].strip())
    if not match:
        raise ValueError('unknown time units in ' + path.name)
    scale = TIME_SCALE[match.group(1)]
    values = []
    for index, row in enumerate(rows[1:], 2):
        if len(row) != count:
            raise ValueError('%s row %d has wrong column count' % (path.name, index))
        nums = [float(v) for v in row]
        if normalize_voltage or normalize_current:
            for i, factor in enumerate(scales, 1):
                nums[i] *= factor
        if not all(math.isfinite(v) for v in nums):
            raise ValueError('%s row %d has non-finite data' % (path.name, index))
        nums[0] *= scale
        values.append(nums)
    return rows[0], values

def read_csv(path, marker, count, config):
    is_voltage = path.name in ('noload_EMF.csv','Voltage.csv')
    is_current = path.name == 'Current.csv'
    headers, values = read_samples(path, marker, count, path.name, normalize_voltage=is_voltage,normalize_current=is_current)
    f = float(config['frequency_Hz']); raw_cycles = config['cycles']; deg = float(config['step_deg'])
    if isinstance(raw_cycles, bool):
        raise ValueError('invalid integer cycle count in configuration')
    count_cycles = float(raw_cycles)
    if not math.isfinite(count_cycles) or not count_cycles.is_integer():
        raise ValueError('invalid integer cycle count in configuration')
    cycles = int(count_cycles)
    if f <= 0 or cycles <= 0 or deg <= 0 or not all(math.isfinite(x) for x in (f, deg)):
        raise ValueError('invalid time settings in configuration')
    n = round(cycles * 360 / deg)
    if not math.isclose(n * deg, cycles * 360, abs_tol=1e-7) or len(values) != n + 1:
        raise ValueError('%s incomplete sample count: got %d expected %d' % (path.name, len(values), n + 1))
    dt = deg / (360. * f)
    tol = max(1e-12, dt * 1e-5)
    for i, row in enumerate(values):
        if abs(row[0] - i * dt) > tol or (i and row[0] <= values[i-1][0]):
            raise ValueError('%s time sequence mismatch at row %d' % (path.name, i + 2))
    per = round(360. / deg)
    if per * deg != 360. and not math.isclose(per * deg, 360., abs_tol=1e-7):
        raise ValueError('time step does not divide an electric cycle')
    last = values[-per-1:]
    # Trapezoidal integral for mean; exact square integral for linearly interpolated samples.
    means = []; rms = []
    for j in range(1, count):
        means.append(sum((last[i][j] + last[i+1][j]) / 2 for i in range(per)) / per)
        rms.append(math.sqrt(sum((last[i][j]**2 + last[i][j]*last[i+1][j] + last[i+1][j]**2)/3 for i in range(per)) / per))
    return {'sha256': digest(path), 'headers': headers, 'samples': len(values),
            'start_s': values[0][0], 'end_s': values[-1][0], 'last_cycle_mean': means,
            'last_cycle_rms': rms, 'value_units': 'V' if is_voltage else ('A' if is_current else 'as specified in CSV headers'),
            'integration_method': 'Last-cycle mean: trapezoidal integration of samples. RMS: exact integral of the square of the piecewise-linear interpolation between samples; divide by duration and take square root. Both assume the validated uniform time step.'}

def inspect(case, kind):
    case = Path(case).resolve()
    result = {'case': str(case), 'kind': kind, 'status': 'not_complete', 'errors': [],
              'warnings': [], 'files': {}, 'limits': [
              'Evidence consistency is not proof of simulation correctness, physical validity, convergence or provenance authenticity.',
              'RMS and means cover the last electric cycle. Phase voltages and currents are normalized to V and A; other quantities use the CSV header units.',
              'This checker recognizes only this workspace\'s generated full-model 2021 R1 case layout.']}
    errors = result['errors']
    try:
        cp = case / 'configuration.json'; rp = case / 'run_case.py'; lp = case / 'run_result.txt'
        config = json.loads(cp.read_text(encoding='utf-8-sig'))
        runner = rp.read_text(encoding='utf-8-sig'); log = lp.read_text(encoding='utf-8-sig', errors='replace')
        result['configuration_sha256'] = digest(cp); result['runner_sha256'] = digest(rp); result['log_sha256'] = digest(lp)
        expected = re.findall(r"digest\(os\.path\.join\(case_dir,\s*['\"]configuration\.json['\"]\)\)\s*!=\s*['\"]([a-fA-F0-9]{64})['\"]", runner)
        if len(expected) != 1 or expected[0].lower() != result['configuration_sha256']:
            errors.append('configuration hash missing, ambiguous, or mismatched in runner')
        manifest = case / 'coreloss_manifest.json'
        if manifest.exists():
            man = json.loads(manifest.read_text(encoding='utf-8-sig'))
            if man.get('configuration_sha256') != result['configuration_sha256'] or man.get('runner_sha256') != result['runner_sha256']:
                errors.append('coreloss manifest hashes mismatch')
        else:
            result['warnings'].append('No independent runner hash manifest: current runner integrity at solve time is not established.')
        for marker in ('Validation=1', 'Analyze returned', 'Saved solution before reports', 'Normal completion of simulation', 'CLOSED; solution saved') + EXPORTS[kind]:
            if marker not in log: errors.append('log missing completion marker: ' + marker)
        if 'FATAL' in log or '[error]' in log.lower(): errors.append('log contains FATAL or solver error')
        result['source_lineage'] = {}
        groups = [('source_project', ('source_sha256', 'source_project_sha256')),
                  ('parameters_source', ('parameters_sha256',)), ('materials_source', ('materials_sha256',)),
                  ('source_configuration', ('source_configuration_sha256',)), ('source_runner', ('source_runner_sha256',)),
                  ('source_log', ('source_log_sha256',))]
        for path_key, hash_keys in groups:
            present_hashes = [key for key in hash_keys if key in config]
            if path_key not in config and not present_hashes:
                continue
            if path_key not in config or not present_hashes:
                errors.append('source lineage path/hash pair incomplete: ' + path_key)
                continue
            source_value = config[path_key]
            if not isinstance(source_value, str) or not source_value.strip():
                errors.append('invalid source lineage path: ' + path_key)
                continue
            hashes = [config[key] for key in present_hashes]
            if any(not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value) for value in hashes):
                errors.append('invalid source lineage SHA-256: ' + path_key)
                continue
            source = Path(source_value)
            try:
                got = digest(source)
                matches = all(got.lower() == value.lower() for value in hashes)
                result['source_lineage'][path_key] = {'expected_sha256': hashes[0], 'observed_sha256': got, 'matches': matches}
                if len(present_hashes) > 1:
                    result['source_lineage'][path_key]['expected_sha256_by_field'] = dict(zip(present_hashes, hashes))
                if not matches: errors.append('source lineage hash mismatch: ' + path_key)
            except OSError:
                result['source_lineage'][path_key] = {'expected_sha256': hashes[0], 'observed_sha256': None, 'matches': None}
                if len(present_hashes) > 1:
                    result['source_lineage'][path_key]['expected_sha256_by_field'] = dict(zip(present_hashes, hashes))
                result['warnings'].append('Referenced source unavailable for hash check: ' + path_key)
        if not result['source_lineage']:
            result['warnings'].append('No recognized source lineage pairs were checked.')
        result['solver_warnings'] = [line.strip() for line in log.splitlines() if '[warning]' in line.lower()]
        if result['solver_warnings']:
            result['warnings'].append('Solver warnings present; review solver_warnings before interpreting results.')
        project = case / ('configured_noload_EXPLORATORY.aedt' if kind == 'noload' else 'configured_load_EXPLORATORY.aedt')
        if not project.is_file() or project.stat().st_size == 0: errors.append('saved AEDT project is missing or empty')
        else: result['project_sha256'] = digest(project)
        results_dir = case / (project.name + 'results')
        if not results_dir.is_dir():
            errors.append('AEDT results directory is missing')
        elif not any(p.is_file() and not p.is_symlink() and p.stat().st_size > 0 for p in results_dir.rglob('*')):
            errors.append('AEDT results directory contains no nonempty regular files')
        if (case / (project.name + '.lock')).exists(): errors.append('saved project is still locked')
        for name, (marker, count) in FILES[kind].items():
            try: result['files'][name] = read_csv(case / name, marker, count, config)
            except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc: errors.append('CSV invalid: ' + str(exc))
        result['settings'] = {k: config.get(k) for k in ('frequency_Hz', 'speed_rpm', 'cycles', 'step_deg', 'current_rms_A', 'current_angle_deg')}
        result['status'] = 'evidence_consistent_not_physical_validation' if not errors else 'evidence_incomplete_or_conflicting'
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        errors.append('cannot read or parse case: ' + str(exc))
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path); parser.add_argument('--kind', choices=FILES, required=True)
    parser.add_argument('--out', type=Path, help='new JSON output path; must not already exist')
    args = parser.parse_args(); result = inspect(args.case, args.kind)
    body = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        try:
            args.out.resolve().relative_to(args.case.resolve())
        except ValueError:
            pass
        else:
            parser.error('output must be outside the input case directory')
        with args.out.open('x', encoding='utf-8') as f: f.write(body)
    else:
        # Some Windows terminals use GBK/cp936, which cannot encode all file
        # paths or solver warnings. ASCII-escaped JSON preserves Unicode safely.
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False), end='\n')
    return 0 if result['status'] == 'evidence_consistent_not_physical_validation' else 2

if __name__ == '__main__': sys.exit(main())
