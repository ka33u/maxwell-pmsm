#!/usr/bin/env python3
"""Offline Park-transform check of existing full-model CSVs; not FEA or an inductance extraction."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_csv(path, headers):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        r = csv.reader(f); h = next(r)
        if h != headers:
            raise ValueError('Unexpected columns/units in '+str(path))
        data = [[float(v) for v in row] for row in r]
    if len(data) < 3 or any(not math.isfinite(v) for row in data for v in row):
        raise ValueError('Nonfinite or insufficient samples')
    if any(len(row)!=len(headers) for row in data): raise ValueError('Inconsistent columns')
    for row in data: row[0] /= 1000.
    dt=(data[-1][0]-data[0][0])/(len(data)-1)
    if dt<=0 or any(abs((data[i][0]-data[i-1][0])-dt)>max(1e-12,dt*1e-5) for i in range(1,len(data))):
        raise ValueError('Time not uniformly sampled')
    return data,dt


def validate_configured_grid(rows, dt, config, label):
    """Require a complete, zero-based grid for this generator's transient case."""
    try:
        raw_cycles = config['cycles']
        if isinstance(raw_cycles, bool):
            raise ValueError('boolean cycle count')
        cycles = float(raw_cycles)
        step_deg = float(config['step_deg'])
        frequency = float(config['frequency_Hz'])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + ': invalid or missing time configuration') from exc
    if (not all(math.isfinite(x) for x in (cycles, step_deg, frequency)) or
            cycles < 1 or not cycles.is_integer() or step_deg <= 0 or frequency <= 0):
        raise ValueError(label + ': invalid or missing time configuration')
    per_cycle = round(360. / step_deg)
    if per_cycle < 1 or not math.isclose(per_cycle * step_deg, 360., rel_tol=0., abs_tol=1e-7):
        raise ValueError(label + ': configured step does not divide one electrical cycle')
    expected_intervals = int(cycles) * per_cycle
    expected_dt = step_deg / (360. * frequency)
    tol = max(1e-12, expected_dt * 1e-5)
    if len(rows) != expected_intervals + 1:
        raise ValueError(label + ': incomplete configured time grid: expected %d samples, got %d' %
                         (expected_intervals + 1, len(rows)))
    if abs(dt - expected_dt) > tol or any(abs(row[0] - k * expected_dt) > tol
                                         for k, row in enumerate(rows)):
        raise ValueError(label + ': configured time grid mismatch')


def transform(values, theta):
    cs=[math.cos(theta-j*2*math.pi/3) for j in range(3)]
    ss=[math.sin(theta-j*2*math.pi/3) for j in range(3)]
    return (2./3*sum(x*c for x,c in zip(values,cs)), -2./3*sum(x*s for x,s in zip(values,ss)), sum(values)/3.)


def fundamental_phases(rows, w):
    n=len(rows)
    phase=[]
    for j in range(1,4):
        s=2./n*sum(row[j]*math.sin(w*row[0]) for row in rows)
        c=2./n*sum(row[j]*math.cos(w*row[0]) for row in rows)
        if math.hypot(s,c)<1e-9:raise ValueError('Fundamental amplitude is too small to infer phase sequence')
        phase.append(math.degrees(math.atan2(c,s)))
    wrap=lambda x:(x+180.)%360.-180.
    relative=[wrap(phase[1]-phase[0]),wrap(phase[2]-phase[0])]
    if abs(wrap(relative[0]+120.))>5. or abs(wrap(relative[1]-120.))>5.:
        raise ValueError('This implementation requires ABC positive phase sequence')
    return phase,relative


def fundamental_sequence_metrics(rows, w):
    """RMS sequence magnitudes of the configured-frequency fundamental only.

    Phasors use sine reference, x = Re(z)*sin(wt) + Im(z)*cos(wt).
    Positive ABC: B=A*exp(-j*120deg), C=A*exp(+j*120deg).
    """
    n = len(rows)
    phasors = []
    for j in range(1, 4):
        s = 2. / n * sum(row[j] * math.sin(w * row[0]) for row in rows)
        c = 2. / n * sum(row[j] * math.cos(w * row[0]) for row in rows)
        phasors.append(complex(s, c))
    a = complex(-0.5, math.sqrt(3.) / 2.)
    zero = sum(phasors) / 3.
    positive = (phasors[0] + a * phasors[1] + a * a * phasors[2]) / 3.
    negative = (phasors[0] + a * a * phasors[1] + a * phasors[2]) / 3.
    pos_abs = abs(positive)
    return {'phase_rms': {phase: abs(value) / math.sqrt(2.) for phase, value in zip('ABC', phasors)},
            'positive_sequence_rms': pos_abs / math.sqrt(2.),
            'negative_sequence_rms': abs(negative) / math.sqrt(2.),
            'zero_sequence_rms': abs(zero) / math.sqrt(2.),
            'negative_over_positive': abs(negative) / pos_abs if pos_abs > 1e-12 else None,
            'zero_over_positive': abs(zero) / pos_abs if pos_abs > 1e-12 else None}


def validated_poles(value, label):
    """Reject fractional and boolean poles before deriving speed or torque."""
    if isinstance(value, bool):
        raise ValueError(label + ': poles must be a positive even integer')
    try:
        poles = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + ': poles must be a positive even integer') from exc
    if not math.isfinite(poles) or poles <= 0 or not poles.is_integer() or int(poles) % 2:
        raise ValueError(label + ': poles must be a positive even integer')
    return int(poles)


def eval_case(noload,load):
    noload=Path(noload);load=Path(load);config=json.loads((load/'configuration.json').read_text(encoding='utf-8'))
    seed=json.loads((noload/'configuration.json').read_text(encoding='utf-8'))
    seed_project=noload/'configured_noload_EXPLORATORY.aedt'
    if Path(config['source_project']).resolve()!=seed_project.resolve() or sha(seed_project)!=config['source_project_sha256']:
        raise ValueError('Load is not traced to this no-load project')
    if sha(noload/'configuration.json')!=config['source_configuration_sha256']:
        raise ValueError('No-load configuration hash does not match load source')
    load_poles = validated_poles(config['poles'], 'load')
    seed_poles = validated_poles(seed['poles'], 'no-load')
    if load_poles != seed_poles or any(config[k]!=seed[k] for k in ('frequency_Hz','speed_rpm')):
        raise ValueError('No-load and load configuration disagree')
    for folder in (noload,load):
        log=(folder/'run_result.txt').read_text(encoding='utf-8')
        if any(x not in log for x in ('Validation=1','Normal completion of simulation','CLOSED; solution saved')) or 'FATAL' in log:
            raise ValueError('No completed-solve evidence: '+str(folder))
    f=float(config['frequency_Hz']);p=load_poles//2
    if f<=0: raise ValueError('Invalid frequency')
    if not math.isclose(float(config['speed_rpm']),120.*f/load_poles,rel_tol=1e-8,abs_tol=1e-8):
        raise ValueError('This implementation requires positive synchronous speed')
    w=2*math.pi*f
    paths={'emf': noload/'noload_EMF.csv','i':load/'Current.csv','flux':load/'Flux.csv','u':load/'Voltage.csv','torque':load/'Torque.csv'}
    expected={'emf':['Time [ms]']+['InducedVoltage(Phase_%s) [V]'%x for x in 'ABC'],
              'i':['Time [ms]']+['InputCurrent(Phase_%s) [A]'%x for x in 'ABC'],
              'flux':['Time [ms]']+['FluxLinkage(Phase_%s) [Wb]'%x for x in 'ABC'],
              'u':['Time [ms]']+['InducedVoltage(Phase_%s) [V]'%x for x in 'ABC'],
              'torque':['Time [ms]','Moving1.Torque [NewtonMeter]']}
    data={};steps={}
    for k,v in paths.items():data[k],steps[k]=read_csv(v,expected[k])
    validate_configured_grid(data['emf'],steps['emf'],seed,'no-load EMF')
    for k in ('i','flux','u','torque'):
        validate_configured_grid(data[k],steps[k],config,'load '+k)
    dt=steps['i'];n=round(1/f/dt)
    if n<4 or abs(n*dt-1/f)>1e-9:raise ValueError('Nonintegral electric period')
    for k in ('flux','u','torque'):
        if len(data[k])!=len(data['i']) or abs(steps[k]-dt)>1e-10:raise ValueError('Load reports misaligned')
        if any(abs(a[0]-b[0])>1e-10 for a,b in zip(data[k],data['i'])):raise ValueError('Report times misaligned')
    if abs(steps['emf']-dt)>1e-10 or len(data['emf'])<n+1:raise ValueError('No-load grid incomplete')
    # Last period fundamental sine fit: equally spaced whole cycle excluding duplicate endpoint.
    nldata=data['emf'][-n-1:-1]
    nl_phases,nl_rel=fundamental_phases(nldata,w)
    noload_fundamental = fundamental_sequence_metrics(nldata, w)
    coef_s=2./n*sum(row[1]*math.sin(w*row[0]) for row in nldata)
    coef_c=2./n*sum(row[1]*math.cos(w*row[0]) for row in nldata)
    phi=math.atan2(coef_c,coef_s)
    # Voltage sign convention checked independently below. e= d(lambda)/dt;
    # lambda_pm ~= cos(wt+phi+pi) * E_peak/omega for a sine-phase voltage.
    phase=phi+math.pi
    indices=range(len(data['i'])-n-1,len(data['i'])-1)
    if min(indices)<1:raise ValueError('Load last cycle does not have preceding flux samples')
    current_window = [data['i'][k] for k in indices]
    i_phases,i_rel=fundamental_phases(current_window,w)
    current_fundamental = fundamental_sequence_metrics(current_window, w)
    records=[]
    for k in indices:
        t=data['i'][k][0];theta=w*t+phase
        a=data['i'][k][1:];b=data['flux'][k][1:];e=data['u'][k][1:]
        id_,iq,i0=transform(a,theta);ld,lq,l0=transform(b,theta);ed,eq,e0=transform(e,theta)
        pabc=sum(x*y for x,y in zip(a,e));pdq=1.5*(id_*ed+iq*eq)+3*i0*e0
        t_est=1.5*p*(ld*iq-lq*id_)
        dflux=[(data['flux'][k][j]-data['flux'][k-1][j])/dt for j in range(1,4)]
        records.append({'id':id_,'iq':iq,'psid':ld,'psiq':lq,'pabc':pabc,'pdq':pdq,'t_est':t_est,
                        'torque':data['torque'][k][1], 'e_a':e[0], 'dflux_a':dflux[0]})
    mean=lambda name:sum(x[name] for x in records)/n
    rms=lambda name:math.sqrt(sum(x[name]**2 for x in records)/n)
    emfrms=math.hypot(coef_s,coef_c)/math.sqrt(2.)
    derivative_rms=math.sqrt(sum((x['e_a']-x['dflux_a'])**2 for x in records)/n)
    power_err=max(abs(x['pabc']-x['pdq']) for x in records)
    report={'status':'offline_transform_exploratory_not_Ld_Lq', 'source_sha256':{k:sha(v) for k,v in paths.items()},
       'config_sha256':sha(load/'configuration.json'),'script_sha256':sha(__file__),'frequency_Hz':f,'pole_pairs':p,
       'window_s':[data['i'][-n-1][0],data['i'][-1][0]],'samples_excluding_period_endpoint':n,
       'phase_convention':'amplitude-invariant d=2/3 sum(xk*cos(theta-2pi*k/3)), q=-2/3 sum(xk*sin(theta-2pi*k/3)), zero=sum(xk)/3; theta=omega*t+emf_A_sine_phase+pi',
       'noload_BC_relative_phase_deg':nl_rel,'load_current_BC_relative_phase_deg':i_rel,
       'fundamental_sequence_convention':'RMS fundamental; ABC positive B=A*exp(-j*120deg), C=A*exp(+j*120deg); sequence ratios are dimensionless',
       'noload_emf_fundamental_V':noload_fundamental,'load_current_fundamental_A':current_fundamental,
       'pm_axis_inferred_from_noload_emf_assuming_e_equals_dflux_dt':True,'emf_sine_phase_deg':math.degrees(phi),
       'theta_offset_deg_wrapped':(math.degrees(phase)+180)%360-180,'noload_phase_A_fundamental_rms_V':emfrms,
       'noload_PM_flux_fundamental_peak_Wb_estimate':math.sqrt(2)*emfrms/w,
       'mean_id_peak_A':mean('id'),'mean_iq_peak_A':mean('iq'),'mean_flux_d_Wb':mean('psid'),'mean_flux_q_Wb':mean('psiq'),
       'mean_torque_cross_product_Nm':mean('t_est'),'mean_maxwell_torque_Nm':mean('torque'),
       'torque_cross_minus_maxwell_sample_rms_Nm':math.sqrt(sum((x['t_est']-x['torque'])**2 for x in records)/n),
       'power_abc_mean_W':mean('pabc'),'power_dq0_mean_W':mean('pdq'),'power_transform_max_abs_difference_W':power_err,
       'voltage_A_rms_V':rms('e_a'),'voltage_minus_backward_flux_derivative_A_rms_V':derivative_rms,
       'limits':['Derived offline from existing CSVs; neither an independent Maxwell solve nor validation of actual rotor-axis sign.',
                 'Each waveform is checked against its own case configuration, not a substitute for audit_case or solver provenance verification.',
                 'Sequence magnitudes and ratios cover only the configured-frequency fundamental; phase-angle acceptance alone does not establish balanced phases or low harmonics, and no balance acceptance criterion is applied.',
                 'EMF-derived d-axis uses dFlux/dt sign, fundamental and one no-load electrical period; initial-position offset and actual PM axis require independent field/geometry validation.',
                 'Power inner product and flux-current cross product are invariant to a common dq-axis rotation; agreement cannot validate axis offset or the physical meaning of individual dq components.',
                 'dq flux/current are at one forced-current point; cannot identify Ld/Lq or incremental inductances without additional independent perturbations or Maxwell inductance matrix.',
                 'Cross-product torque ignores cogging and harmonics outside the sinusoidal dq model; do not treat its agreement as independent proof of physical correctness.',
                 'No-load has %s electrical cycles and load has %s; this check does not establish mesh, time-step, full-turn or material convergence.' % (seed['cycles'],config['cycles'])]}
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--noload',type=Path,required=True);p.add_argument('--load',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();report=eval_case(a.noload,a.load)
    with a.out.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=True,indent=2,allow_nan=False);f.write('\n')
    print(str(a.out).encode('ascii','backslashreplace').decode('ascii'))


if __name__=='__main__': main()
