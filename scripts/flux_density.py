"""Prepare Maxwell 2D XY full-machine field probes and reduce native transient B exports (tesla)."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
from tempfile import TemporaryDirectory

from audit_case import inspect

HERE = Path(__file__).resolve().parent

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write_json(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)

def write_rows(path, rows):
    with path.open('x', encoding='utf-8', newline='') as stream:
        w = csv.DictWriter(stream, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def field_times(asol, result_folder, setup):
    text = asol.read_text(encoding='utf-8',errors='replace')
    sections = dict(re.findall(r"\$begin '(SolutionBlock\d+)'(.*?)\$end '\1'",text,re.S))
    setup_ids = [re.search(r'\bSimSetupID=(\d+)',s)[1] for s in sections.values()
                 if "SimSetupName='%s'"%setup in s]
    if len(setup_ids)!=1:
        raise ValueError('Cannot identify unique saved setup '+setup)
    keys = [line for line in text.splitlines() if 'SolutionKey(SimSetup='+setup_ids[0]+',' in line
            and 'SolutionDefinition' in line and 'VersionID=0)' in line]
    if len(keys)!=1:
        raise ValueError('Cannot identify the current solution definition for '+setup)
    section=sections[keys[0].split("='")[-1].rstrip("'")]
    blocks = re.findall(r"\$begin 'Fields'(.*?)\$end 'Fields'", section, re.S)
    blocks = [b for b in blocks if 'Field(DblID=' in b]
    if len(blocks) != 1 or blocks[0].count("Field(DblID=") == 0:
        raise ValueError('Expected one saved field solution. Isolate one setup and variation.')
    block = blocks[0]
    maps = re.findall(r'IDDblMap\(([^)]*)\)', block)
    if len(maps) != 1 or block.count("$begin 'DataMap'") != 1:
        raise ValueError('Ambiguous field time or variation map')
    items = [x.strip() for x in maps[0].split(',')]
    ids = items[::2]
    dirs = re.findall(r"Field\(DblID=(\d+), Dir='([^']+)'\)", block)
    if len(items)%2 or len(set(ids))!=len(ids) or len(dirs)!=len(ids) or set(ids)!={k for k,_ in dirs}:
        raise ValueError('Incomplete field id map')
    for _, name in dirs:
        folder = result_folder / name
        if not any(f.stat().st_size for f in folder.glob('*.fld')):
            raise ValueError('Missing binary field data in '+str(folder))
    times = sorted(items[1::2], key=float)
    values = [float(x) for x in times]
    if not all(math.isfinite(x) and x>=0 for x in values) or len(set(values))!=len(times):
        raise ValueError('Invalid stored field times')
    return times

def make_points(spec):
    rotor, bore, bottom, outer = (spec[k] for k in ('rotor_tip_mm','bore_mm','slot_bottom_mm','outer_mm'))
    slots, poles, count = (spec[k] for k in ('slots','poles','angles'))
    if (not all(math.isfinite(x) for x in (rotor,bore,bottom,outer,spec['slot1_deg']))
            or not 0 < rotor < bore < bottom < outer or not 0 < spec['gap_fraction'] < 1):
        raise ValueError('Check machine radii and the gap sampling fraction')
    if any(type(n) is not int or n<=0 for n in (slots,poles,count)) or poles%2 or count%slots or count<=poles:
        raise ValueError('Require even poles and an angular grid divisible by slots and above pole count')
    if not 0 < spec['tooth_offset_pitch'] < 0.5:
        raise ValueError('Invalid interior tooth offset in slot pitches')
    depths=spec.get('depth_fractions',[.2,.5,.8])
    side_subdivisions=spec.get('tooth_side_subdivisions',1)
    if not depths or sorted(set(depths))!=depths or not all(0<f<1 for f in depths):
        raise ValueError('Depth fractions must be distinct, increasing and inside (0,1)')
    if type(side_subdivisions) is not int or side_subdivisions<1:
        raise ValueError('Require at least one transverse interval on each side of the tooth center')
    pitch = 360./slots
    rows = []
    def add(region, track, angle, radius):
        angle %= 360
        theta = math.radians(angle)
        rows.append(dict(index=len(rows),region=region,track=track,theta_deg=angle,r_mm=radius,
                         x_mm=radius*math.cos(theta),y_mm=radius*math.sin(theta)))
    for j in range(count):
        add('gap','ring',360.*j/count,rotor+(bore-rotor)*spec['gap_fraction'])
    for fraction in depths:
        for s in range(slots):
            for j in range(-side_subdivisions,side_subdivisions+1):
                off=spec['tooth_offset_pitch']*j/side_subdivisions
                add('tooth','depth%g_offset%g'%(fraction,off),spec['slot1_deg']+(s+.5+off)*pitch,
                    bore+(bottom-bore)*fraction)
        for j in range(count):
            add('yoke','depth%g'%fraction,360.*j/count,bottom+(outer-bottom)*fraction)
    return rows

def prepare(args):
    case, out = args.case.absolute(), args.out.absolute()
    if case.resolve()==out.resolve() or case.resolve() in out.resolve().parents:
        raise ValueError('Choose an independent output folder outside the source case')
    audit = inspect(case, args.kind)
    if audit['errors']:
        raise ValueError(audit['errors'])
    spec = read_json(args.geometry)
    points = make_points(spec)
    cfg = read_json(case/'configuration.json')
    src = case/('configured_%s_EXPLORATORY.aedt'%args.kind)
    results = case/(src.name+'results')
    design = cfg.get('design_name') or 'Full_Transient'
    asol = results/(design+'.asol')
    setup={'noload':'Reusable_NoLoad','load':'Reusable_Load'}[args.kind]
    times = field_times(asol, results/(design+'.results'),setup)
    if cfg.get('slots',spec['slots'])!=spec['slots'] or not math.isclose(cfg['frequency_Hz']*120/cfg['speed_rpm'], spec['poles']):
        raise ValueError('Probe geometry and case slot/pole settings differ')
    stop = cfg['cycles']/cfg['frequency_Hz']
    if not math.isclose(float(times[-1]),stop,rel_tol=1e-7,abs_tol=1e-12):
        raise ValueError('Final saved field does not match configured stop time')
    start = stop - 1./cfg['frequency_Hz']
    times = [t for t in times if float(t)>=start-1e-10/cfg['frequency_Hz']]
    cadence=int(cfg.get('save_fields_every',0))
    if cadence:
        per_cycle=round(360/cfg['step_deg'])
        steps=cfg['cycles']*per_cycle
        expected=sorted({i for i in range(0,steps+1,cadence) if i>=steps-per_cycle} | {steps})
        dt=1/(cfg['frequency_Hz']*per_cycle)
        if len(expected)!=len(times) or any(abs(i*dt-float(t))>dt*1e-5 for i,t in zip(expected,times)):
            raise ValueError('Available field times differ from requested save cadence in the last cycle')
    out.mkdir(parents=True,exist_ok=False)
    shutil.copy2(src, out/src.name)
    shutil.copytree(results, out/results.name)
    write_rows(out/'points.csv',points)
    with (out/'points.pts').open('x',encoding='ascii') as f:
        f.write('Unit=mm\n')
        for p in points:
            f.write('%.14g %.14g 0\n'%(p['x_mm'],p['y_mm']))
    shutil.copy2(HERE/'export_flux_density_aedt.py',out/'export_fields.py')
    plan = dict(geometry=spec, case=str(case), project_file=src.name, design=design,
                setup=setup, kind=args.kind,
                stator=spec.get('stator','Stator'),steel_material=spec.get('steel_material','REUSE_STEEL'),
                air_bodies=spec.get('air_bodies',['Region','Band']),air_materials=spec.get('air_materials',['vacuum','air']),point_count=len(points),
                times_s=times,frequency_Hz=cfg['frequency_Hz'],speed_rpm=cfg['speed_rpm'],cycles=cfg['cycles'],
                current_rms_A=cfg.get('current_rms_A',0 if args.kind=='noload' else None),
                hashes={name:digest(path) for name,path in {'project':src,'asol':asol,'config':case/'configuration.json',
                      'points.csv':out/'points.csv','points.pts':out/'points.pts','export_fields.py':out/'export_fields.py'}.items()})
    write_json(out/'plan.json',plan)
    print('%s: %d positions, %d stored field times' % (out,len(points),len(times)))

def field_values(path, points, vector=True):
    with path.open(encoding='utf-8-sig') as stream:
        header = stream.readline().strip()
        if ('Vector data' if vector else 'Scalar data') not in header or 'Bx' not in header or 'By' not in header:
            raise ValueError('Unexpected field header in '+str(path))
        rows = [[float(v) for v in line.split()] for line in stream if line.strip()]
    if len(rows)!=len(points):
        raise ValueError('Field point count mismatch in '+str(path))
    result = []
    for p,row in zip(points,rows):
        if len(row)!=(6 if vector else 4) or not all(map(math.isfinite,row)):
            raise ValueError('Invalid field row in '+str(path))
        expected = (p['x_mm']/1000,p['y_mm']/1000,0.)
        if max(abs(a-b) for a,b in zip(expected,row[:3]))>1e-9:
            raise ValueError('Coordinates or output units mismatch in '+str(path))
        result.append(row[3:])
    return result

def cylindrical(points,vectors):
    for p,(bx,by,bz) in zip(points,vectors):
        theta=math.radians(p['theta_deg'])
        br=bx*math.cos(theta)+by*math.sin(theta)
        bt=-bx*math.sin(theta)+by*math.cos(theta)
        yield p,br,bt,math.hypot(bx,by,bz)

def metrics(points, vectors, poles):
    return frame_metrics(cylindrical(points, vectors), poles)

def frame_metrics(samples, poles):
    groups = {region:[] for region in ('gap','tooth','yoke')}
    for record in samples:
        groups[record[0]['region']].append(record)
    results = {}
    for region,values in groups.items():
        peak = max(values,key=lambda row:row[3])
        mags=sorted(v[3] for v in values)
        data=dict(mean_abs_B_T=statistics.mean(mags),p95_abs_B_T=mags[math.ceil(.95*len(mags))-1],
                  peak_abs_B_T=peak[3], peak_theta_deg=peak[0]['theta_deg'],peak_r_mm=peak[0]['r_mm'])
        comp = 2 if region=='yoke' else 1
        signed=[v[comp] for v in values]
        data.update(component='Bt' if comp==2 else 'Br',mean_abs_component_T=statistics.mean(map(abs,signed)),
                    peak_abs_component_T=max(map(abs,signed)),
                    spatial_rms_component_T=math.sqrt(statistics.fmean(x*x for x in signed)),
                    spatial_rms_Bmag_T=math.sqrt(statistics.fmean(x*x for x in mags)))
        if region=='gap':
            angles=[math.radians(v[0]['theta_deg'])*poles/2 for v in values]
            data['spatial_fundamental_Br_peak_T']=2*math.hypot(sum(b*math.cos(a) for b,a in zip(signed,angles)),
                                                                sum(b*math.sin(a) for b,a in zip(signed,angles)))/len(values)
            data['spatial_fundamental_Br_rms_T']=data['spatial_fundamental_Br_peak_T']/math.sqrt(2)
        results[region]=data
    return results

def cycle_weights(times, frequency):
    """Normalized trapezoid weights for one electrical cycle at the actual saved times."""
    if not times or not all(map(math.isfinite,times)) or not math.isfinite(frequency) or frequency<=0:
        raise ValueError('Invalid time or electrical frequency')
    intervals=[b-a for a,b in zip(times,times[1:])]
    if any(dt<=0 for dt in intervals):
        raise ValueError('Field times must be strictly increasing')
    span=times[-1]-times[0]
    if len(times)<3 or not math.isclose(span,1/frequency,rel_tol=1e-7):
        return None
    return [(before+after)/(2*span) for before,after in zip([0.]+intervals,intervals+[0.])]

def add_mean_squares(squares, frame, weight):
    for sums,(_,br,bt,mag) in zip(squares,frame):
        sums[0]+=weight*br*br
        sums[1]+=weight*bt*bt
        sums[2]+=weight*mag*mag

def cycle_results(points, squares, fundamental_mean_square):
    rows=[dict(p,Br_rms_T=math.sqrt(br),Bt_rms_T=math.sqrt(bt),Bmag_rms_T=math.sqrt(mag))
          for p,(br,bt,mag) in zip(points,squares)]
    regions={}
    for region in ('gap','tooth','yoke'):
        local=[row for row in rows if row['region']==region]
        component='Bt' if region=='yoke' else 'Br'
        strongest=max(local,key=lambda row:row['Bmag_rms_T'])
        regions[region]=dict(component=component,
            component_space_time_rms_T=math.sqrt(statistics.fmean(r[component+'_rms_T']**2 for r in local)),
            Bmag_space_time_rms_T=math.sqrt(statistics.fmean(r['Bmag_rms_T']**2 for r in local)),
            max_point_cycle_Bmag_rms_T=strongest['Bmag_rms_T'],point_index=strongest['index'],
            theta_deg=strongest['theta_deg'],r_mm=strongest['r_mm'])
    regions['gap']['fundamental_Br_space_time_rms_T']=math.sqrt(fundamental_mean_square)
    return rows,regions

def summarize(args):
    root=args.export
    plan=read_json(root/'plan.json')
    if (root/'export.log').read_text(errors='replace').splitlines()[-1:]!=['COMPLETE']:
        raise ValueError('Incomplete native field export')
    for name in ('points.csv','points.pts','export_fields.py'):
        if digest(root/name)!=plan['hashes'][name]:
            raise ValueError('Export input changed: '+name)
    points=make_points(plan['geometry'])
    if len(points)!=plan['point_count']:
        raise ValueError('Plan point count differs')
    times=list(map(float,plan['times_s']))
    weights=cycle_weights(times,plan['frequency_Hz'])
    squares=[[0.,0.,0.] for _ in points] if weights else None
    fundamental_mean_square=0.
    time_rows=[]
    for i,t in enumerate(times):
        vectors=field_values(root/('B_%03d.fld'%i),points)
        frame=list(cylindrical(points,vectors))
        values=frame_metrics(frame,plan['geometry']['poles'])
        if weights:
            add_mean_squares(squares,frame,weights[i])
            fundamental_mean_square+=weights[i]*values['gap']['spatial_fundamental_Br_rms_T']**2
        for region,data in values.items():
            time_rows.append(dict(time_s=float(t),region=region,**data))
    scalars=field_values(root/'Bmag_check.fld',points,False)
    if any(m[0]<0 for m in scalars):
        raise ValueError('Negative magnitude from AEDT')
    comparison={}
    for region in ('gap','tooth','yoke'):
        pairs=[(math.hypot(*v),m[0]) for p,v,m in zip(points,vectors,scalars) if p['region']==region]
        peak_vector=max(v for v,_ in pairs)
        peak_scalar=max(m for _,m in pairs)
        if peak_scalar==0 or peak_vector==0:
            raise ValueError('Empty magnetic field in '+region)
        comparison[region]=dict(max_point_delta_T=max(abs(v-m) for v,m in pairs),
                                vector_peak_T=peak_vector,aedt_scalar_peak_T=peak_scalar,
                                peak_delta_T=abs(peak_vector-peak_scalar))
    peaks = {r:max((row for row in time_rows if row['region']==r),key=lambda row:row['peak_abs_B_T'])
             for r in ('gap','tooth','yoke')}
    for row in time_rows:
        row.setdefault('spatial_fundamental_Br_peak_T',None)
        row.setdefault('spatial_fundamental_Br_rms_T',None)
    # Publish only after all frames and the independent final-field check pass.
    with TemporaryDirectory(dir=root) as tmp:
        staged=Path(tmp)
        regions=None
        if weights:
            point_rows,regions=cycle_results(points,squares,fundamental_mean_square)
            write_rows(staged/'point_cycle_rms.csv',point_rows)
        write_rows(staged/'time_metrics.csv',time_rows)
        write_json(staged/'summary.json',dict(sampled_peaks=peaks,times_s=plan['times_s'],point_count=len(points),
                   cycle_rms=regions,final_time_magnitude_crosscheck=comparison,kind=plan['kind'],
                   last_cycle_span=times[-1]-times[0],project_sha256=plan['hashes']['project']))
        if weights:
            (staged/'point_cycle_rms.csv').replace(root/'point_cycle_rms.csv')
        else:
            (root/'point_cycle_rms.csv').unlink(missing_ok=True)
        for name in ('time_metrics.csv','summary.json'):
            (staged/name).replace(root/name)
    print({r:round(v['peak_abs_B_T'],6) for r,v in peaks.items()})

def waveform(args):
    root=args.export
    plan=read_json(root/'plan.json')
    if not (root/'summary.json').is_file():
        raise ValueError('Run summarize on the completed exports first')
    i=args.time_index
    if i<0:
        i+=len(plan['times_s'])
    if not 0<=i<len(plan['times_s']):
        raise ValueError('Time index outside the stored field window')
    points=make_points(plan['geometry'])
    vectors=field_values(root/('B_%03d.fld'%i),points)
    rows=[dict(p,time_s=float(plan['times_s'][i]),Br_T=br,Bt_T=bt,abs_B_T=mag)
          for p,br,bt,mag in cylindrical(points,vectors)]
    write_rows(args.out,rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    prep=sub.add_parser('prepare')
    for opt in ('case','geometry','out'):
        prep.add_argument('--'+opt,required=True,type=Path)
    prep.add_argument('--kind',choices=('noload','load'),required=True)
    summ=sub.add_parser('summarize')
    summ.add_argument('--export',required=True,type=Path)
    wave=sub.add_parser('waveform')
    wave.add_argument('--export',required=True,type=Path)
    wave.add_argument('--time-index',type=int,default=-1,help='index in the saved field window; -1 selects the final time')
    wave.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    {'prepare':prepare,'summarize':summarize,'waveform':waveform}[a.cmd](a)
