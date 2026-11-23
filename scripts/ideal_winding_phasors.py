#!/usr/bin/env python3
"""Screen a complete two-layer winding table using ideal fundamental phasors.

This does not establish physical winding, branch connections or circulating currents.
"""
import argparse
import cmath
import csv
import hashlib
import io
import json
import math
from pathlib import Path

FIELDS = ('coil', 'phase', 'parallel_branch', 'upper_slot', 'upper_polarity',
          'lower_slot', 'lower_polarity', 'series_turns_per_coil')
EPS_REL = 1e-12


def diagnose(path, slots, poles, pitch, branches):
    for name, value in [('slots', slots), ('poles', poles), ('pitch', pitch), ('branches', branches)]:
        if type(value) is not int or value < 1:
            raise ValueError(name + ' must be a positive integer')
    if poles % 2 or pitch >= slots:
        raise ValueError('poles must be even and pitch less than slots')
    raw = Path(path).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError('CSV headers must match the documented coil-side format')
    values = {(p, b): 0j for p in 'ABC' for b in range(1, branches + 1)}
    counts = {(p, b): 0 for p in 'ABC' for b in range(1, branches + 1)}
    turns = {(p, b): 0 for p in 'ABC' for b in range(1, branches + 1)}
    coils, upper, lower = set(), set(), set()
    for line, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError('invalid column count at line %d' % line)
        try:
            coil, branch, u, l, n = (int(row[k].strip()) for k in ('coil', 'parallel_branch', 'upper_slot', 'lower_slot', 'series_turns_per_coil'))
        except ValueError as exc:
            raise ValueError('invalid integer at line %d' % line) from exc
        phase, su, sl = (row[k].strip() for k in ('phase', 'upper_polarity', 'lower_polarity'))
        if phase not in ('A', 'B', 'C') or su not in ('+', '-') or sl not in ('+', '-') or su == sl:
            raise ValueError('invalid phase or side polarities at line %d' % line)
        if not (1 <= coil <= slots and 1 <= u <= slots and 1 <= l <= slots and 1 <= branch <= branches and n > 0):
            raise ValueError('coil/slot/branch/turn outside allowed range at line %d' % line)
        if coil in coils or u in upper or l in lower or (l-u) % slots != pitch:
            raise ValueError('duplicate coil/slot layer or incorrect pitch at line %d' % line)
        coils.add(coil); upper.add(u); lower.add(l)
        theta_u = 2*math.pi*(poles//2)*(u-1)/slots
        theta_l = 2*math.pi*(poles//2)*(l-1)/slots
        sign_u = 1 if su == '+' else -1
        sign_l = 1 if sl == '+' else -1
        values[phase, branch] += n * (sign_u*cmath.exp(1j*theta_u) + sign_l*cmath.exp(1j*theta_l))
        counts[phase, branch] += 1; turns[phase, branch] += n
    expected = set(range(1, slots+1))
    if coils != expected or upper != expected or lower != expected:
        raise ValueError('requires one coil per slot and one side in each slot/layer')
    if any(count == 0 for count in counts.values()):
        raise ValueError('every phase/branch must contain at least one coil')
    phases = {}
    for phase in 'ABC':
        vals = [values[phase, b] for b in range(1, branches+1)]
        mean = sum(vals) / branches
        scale = max(abs(x) for x in vals)
        max_diff = max(abs(x-mean) for x in vals)
        ratio = max_diff / abs(mean) if scale > 0 and abs(mean) > EPS_REL*scale else None
        phases[phase] = {'mean': {'real': mean.real, 'imag': mean.imag, 'magnitude': abs(mean),
                                  'angle_deg': math.degrees(cmath.phase(mean)) if ratio is not None else None},
                         'max_absolute_deviation': max_diff, 'max_deviation_over_mean': ratio,
                         'relative_deviation_note': None if ratio is not None else 'undefined: mean is zero or negligible relative to branch magnitudes',
                         'branches': [{'branch': b, 'coils': counts[phase,b], 'series_turns': turns[phase,b],
                                       'real': values[phase,b].real, 'imag': values[phase,b].imag,
                                       'magnitude': abs(values[phase,b]),
                                       'angle_deg': math.degrees(cmath.phase(values[phase,b])) if abs(values[phase,b]) > EPS_REL*scale and scale > 0 else None}
                                      for b in range(1, branches+1)]}
    phase_angles = {}
    for first, second in (('A', 'B'), ('B', 'C'), ('C', 'A')):
        a, b = phases[first]['mean']['angle_deg'], phases[second]['mean']['angle_deg']
        phase_angles[first+'_to_'+second+'_deg'] = ((b-a+180) % 360 - 180) if a is not None and b is not None else None
    return {'status': 'ideal_fundamental_diagnostic_not_wiring_or_FEA_validation',
            'input_sha256': hashlib.sha256(raw).hexdigest(),
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'parameters': {'slots': slots, 'poles': poles, 'pole_pairs': poles//2, 'pitch_slots': pitch, 'branches_per_phase': branches},
            'convention': 'theta(slot)=2*pi*(poles/2)*(slot-1)/slots; K_branch=sum N*(s_upper*exp(j*theta_upper)+s_lower*exp(j*theta_lower)). With psi(t)=Re(K*exp(j*omega*t)), e=dpsi/dt=j*omega*K under the same sign convention. Slot 1 and t=0 are arbitrary shared references; K is not volts.',
            'limits': ['Uniform slot spacing and common sinusoidal fundamental field are assumed; mixed turns are weighted.',
                       'The table must encode each coil orientation consistently with its assumed series branch terminal orientation; order and real routing are not established.',
                       'No field solve, actual wiring, magnet direction, end winding, branch impedance, current or circulating current is verified.',
                       'No automatic pass/fail tolerance is applied; interpret deviations with model and source assumptions.'],
            'phases': phases, 'phase_mean_relative_angles_deg': phase_angles}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', type=Path, required=True)
    p.add_argument('--slots', type=int, required=True); p.add_argument('--poles', type=int, required=True)
    p.add_argument('--pitch', type=int, required=True); p.add_argument('--branches', type=int, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); result = diagnose(a.csv, a.slots, a.poles, a.pitch, a.branches)
    with a.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n')
    print(a.out)

if __name__ == '__main__': main()
