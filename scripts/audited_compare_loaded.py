#!/usr/bin/env python3
"""Evidence-gated comparison for this workspace's generated load cases.

This wrapper independently audits both saved cases, checks the recorded common
source and narrowly normalizes the generated runner's configuration digest,
then delegates numeric processing to an explicitly supplied comparator. It
does not establish physical correctness, convergence, or runner authenticity.
Only the local full-model load-case layout and matching runner templates are
supported. It does not start Maxwell or alter input cases.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_file(path, label):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(label + ' is not an existing file: ' + str(path))
    return path


def check_output(out, cases):
    out = Path(out).resolve()
    if out.exists() or out.is_symlink():
        raise ValueError('output already exists')
    if not out.parent.is_dir():
        raise ValueError('output parent does not exist')
    for case in cases:
        try:
            out.relative_to(Path(case).resolve())
        except ValueError:
            continue
        raise ValueError('output must be outside the input case directories')
    return out


def run_audit(audit, case):
    p = subprocess.run([sys.executable, '-B', str(audit), '--case', str(case), '--kind', 'load'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        result = json.loads(p.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('audit did not return parseable JSON for ' + str(case)) from exc
    if p.returncode != 0 or result.get('status') != 'evidence_consistent_not_physical_validation' or result.get('errors'):
        raise ValueError('case audit failed for %s: %s' % (case, result.get('errors', [])))
    return result


def normalized_runner(case, expected_config_hash):
    path = Path(case) / 'run_case.py'
    runner = path.read_bytes()
    expression = rb"(digest\(os\.path\.join\(case_dir,\s*['\"]configuration\.json['\"]\)\)\s*!=\s*['\"])([a-fA-F0-9]{64})(['\"])"
    matches = list(re.finditer(expression, runner))
    if len(matches) != 1 or matches[0].group(2).decode('ascii').lower() != expected_config_hash.lower():
        raise ValueError('runner does not contain exactly one matching configuration digest: ' + str(path))
    start, end = matches[0].span(2)
    normalized = runner[:start] + b'0' * 64 + runner[end:]
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(runner).hexdigest(),
            'normalized_sha256': hashlib.sha256(normalized).hexdigest()}, normalized


def compare(coarse, fine, comparator, audit, vary, out):
    coarse, fine = Path(coarse).resolve(), Path(fine).resolve()
    if not coarse.is_dir() or not fine.is_dir() or coarse == fine:
        raise ValueError('two distinct existing case directories are required')
    out = check_output(out, (coarse, fine))
    comparator = checked_file(comparator, 'comparator')
    audit = checked_file(audit, 'audit script')
    # The supplied comparator imports these two local helpers by module name.
    # Require explicit sibling files and fingerprint all executable inputs.
    tools = {'audit': audit, 'comparator': comparator,
             'summarize_full_loaded_case': checked_file(comparator.parent / 'summarize_full_loaded_case.py', 'summarizer'),
             'summarize_fixed_geometry_case': checked_file(comparator.parent / 'summarize_fixed_geometry_case.py', 'report reader'),
             'wrapper': Path(__file__).resolve()}
    fingerprints = {k: {'path': str(v), 'sha256': sha256(v)} for k, v in tools.items()}
    audits = {'coarse': run_audit(audit, coarse), 'fine': run_audit(audit, fine)}
    configs = {}
    runners = {}
    normalized = {}
    for name, case in (('coarse', coarse), ('fine', fine)):
        config_path = case / 'configuration.json'
        configs[name] = json.loads(config_path.read_text(encoding='utf-8-sig'))
        config_sha = sha256(config_path)
        if config_sha != audits[name].get('configuration_sha256'):
            raise ValueError(name + ' configuration changed since audit')
        runners[name], normalized[name] = normalized_runner(case, config_sha)
        if runners[name]['sha256'] != audits[name].get('runner_sha256'):
            raise ValueError(name + ' runner changed since audit')
    if normalized['coarse'] != normalized['fine']:
        raise ValueError('runner contents differ beyond the embedded configuration digest')
    # Matching configured paths/hashes alone do not establish the common source;
    # demand the audit's successful independent read/hash for both cases.
    for name in ('coarse', 'fine'):
        c = configs[name]
        if not isinstance(c.get('source_project'), str) or not c['source_project']:
            raise ValueError(name + ' lacks a source project')
        if not isinstance(c.get('source_project_sha256'), str) or not re.fullmatch(r'[a-fA-F0-9]{64}', c['source_project_sha256']):
            raise ValueError(name + ' lacks a source project SHA-256')
        if audits[name].get('source_lineage', {}).get('source_project', {}).get('matches') is not True:
            raise ValueError(name + ' source project is unavailable or not verified')
    p0 = os.path.normcase(os.path.abspath(configs['coarse']['source_project']))
    p1 = os.path.normcase(os.path.abspath(configs['fine']['source_project']))
    if p0 != p1 or configs['coarse']['source_project_sha256'].lower() != configs['fine']['source_project_sha256'].lower():
        raise ValueError('cases do not have the same recorded source project and hash')
    # The original comparator runs in a fresh interpreter. Its temporary JSON is
    # outside both case directories and is removed whether it succeeds or fails.
    with tempfile.TemporaryDirectory(prefix='.maxwell-compare-', dir=str(out.parent)) as temp:
        work_out = Path(temp) / 'comparison.json'
        proc = subprocess.run([sys.executable, '-B', str(comparator), '--coarse', str(coarse),
                               '--fine', str(fine), '--vary', vary, '--out', str(work_out)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode or not work_out.is_file():
            error = proc.stderr.decode('utf-8', 'backslashreplace')[-4000:]
            raise ValueError('numeric comparator failed: ' + error)
        result = json.loads(work_out.read_text(encoding='utf-8-sig'))
    # The helper scripts and case inputs must remain unchanged throughout.
    for name, path in tools.items():
        if sha256(path) != fingerprints[name]['sha256']:
            raise ValueError(name + ' changed during comparison')
    if sha256(configs['coarse']['source_project']) != configs['coarse']['source_project_sha256'].lower():
        raise ValueError('source project changed during comparison')
    for name, case in (('coarse', coarse), ('fine', fine)):
        for filename, key in (('configuration.json', 'configuration_sha256'), ('run_case.py', 'runner_sha256'),
                              ('run_result.txt', 'log_sha256')):
            if sha256(case / filename) != audits[name][key]:
                raise ValueError(name + ' ' + filename + ' changed during comparison')
        for filename, data in audits[name]['files'].items():
            if sha256(case / filename) != data['sha256']:
                raise ValueError(name + ' ' + filename + ' changed during comparison')
        if sha256(case / 'configured_load_EXPLORATORY.aedt') != audits[name]['project_sha256']:
            raise ValueError(name + ' project changed during comparison')
        profile = result['profiles'][name]
        if sha256(profile['profile']) != profile['sha256']:
            raise ValueError(name + ' solver profile changed during comparison')
    report = {'status': 'audited_exploratory_comparison_not_physical_validation',
              'recorded_source_project': configs['coarse']['source_project'],
              'recorded_source_sha256': configs['coarse']['source_project_sha256'].lower(),
              'tools': fingerprints, 'runners': runners, 'audits': audits, 'comparison': result,
              'limits': ['Checks only the local generated full-model load-case layout.',
                         'Current runner templates and source hashes do not prove which code ran.',
                         'Nonempty results directories do not prove usable or matching solver data.',
                         'Same source and configuration do not prove identical model physics or convergence.',
                         'Solver and lineage warnings remain in the two audit records.']}
    with out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write('\n')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--coarse', required=True, type=Path)
    p.add_argument('--fine', required=True, type=Path)
    p.add_argument('--comparator', required=True, type=Path, help='absolute path of trusted local compare_loaded_timestep.py')
    p.add_argument('--audit-script', type=Path, default=Path(__file__).resolve().with_name('audit_case.py'))
    p.add_argument('--vary', choices=('timestep', 'band'), default='timestep')
    p.add_argument('--out', required=True, type=Path, help='new JSON outside both input case directories')
    a = p.parse_args()
    try:
        path = compare(a.coarse, a.fine, a.comparator, a.audit_script, a.vary, a.out)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, subprocess.SubprocessError) as exc:
        print('AUDITED_COMPARISON_FAILED: ' + str(exc), file=sys.stderr)
        return 1
    print(str(path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
