import math
import tempfile
import unittest
import csv
import json
from pathlib import Path
import offline_dq as d

ROOT=next((p for p in Path(__file__).resolve().parents
           if (p/'two_motor_simulation_20261119').is_dir()),None)

class DqTests(unittest.TestCase):
    def write_fixture(self, root):
        no=root/'nol';load=root/'loaded';no.mkdir();load.mkdir()
        project=no/'configured_noload_EXPLORATORY.aedt';project.write_bytes(b'synthetic test project')
        seed={'frequency_Hz':50.,'poles':4,'speed_rpm':1500.,'cycles':1,'step_deg':3.}
        cp=no/'configuration.json';cp.write_text(json.dumps(seed),encoding='utf-8')
        cfg=dict(seed);cfg.update(cycles=2,source_project=str(project.resolve()),source_project_sha256=d.sha(project),source_configuration_sha256=d.sha(cp))
        (load/'configuration.json').write_text(json.dumps(cfg),encoding='utf-8')
        for folder in (no,load):
            (folder/'run_result.txt').write_text('Validation=1\nNormal completion of simulation\nCLOSED; solution saved\n',encoding='utf-8')
        dt=1/50/120;omega=2*math.pi*50;id_,iq,psid,psiq=-2.,5.,.18,.04
        phases=lambda x,y,theta:[x*math.cos(theta-j*2*math.pi/3)-y*math.sin(theta-j*2*math.pi/3) for j in range(3)]
        def write(p,head,rows):
            with p.open('w',encoding='utf-8',newline='') as f:
                writer=csv.writer(f);writer.writerow(head);writer.writerows(rows)
        time=[k*dt for k in range(241)]
        current=[phases(id_,iq,omega*t) for t in time]
        flux=[phases(psid,psiq,omega*t) for t in time]
        emf=[[0.,0.,0.]]+[[(flux[k][j]-flux[k-1][j])/dt for j in range(3)] for k in range(1,len(time))]
        m=lambda expr,unit:['Time [ms]']+['%s(Phase_%s) [%s]'%(expr,x,unit) for x in 'ABC']
        write(no/'noload_EMF.csv',m('InducedVoltage','V'),[[t*1000]+phases(0, .2*omega,omega*t) for t in time[:121]])
        write(load/'Current.csv',m('InputCurrent','A'),[[t*1000]+v for t,v in zip(time,current)])
        write(load/'Flux.csv',m('FluxLinkage','Wb'),[[t*1000]+v for t,v in zip(time,flux)])
        write(load/'Voltage.csv',m('InducedVoltage','V'),[[t*1000]+v for t,v in zip(time,emf)])
        torque=1.5*2*(psid*iq-psiq*id_)
        write(load/'Torque.csv',['Time [ms]','Moving1.Torque [NewtonMeter]'],[[t*1000,torque] for t in time])
        return no,load,torque

    def test_known_balanced_phase_values(self):
        theta=.73
        phase=[6*math.cos(theta-k*2*math.pi/3)-4*math.sin(theta-k*2*math.pi/3)+2 for k in range(3)]
        x,y,z=d.transform(phase,theta)
        self.assertAlmostEqual(x,6);self.assertAlmostEqual(y,4);self.assertAlmostEqual(z,2)

    def test_power_invariance_including_zero_sequence(self):
        v=[2.,-1.,4.];i=[5.,6.,-3.]
        vd,vq,v0=d.transform(v,1.6);id_,iq,i0=d.transform(i,1.6)
        self.assertAlmostEqual(sum(a*b for a,b in zip(v,i)),1.5*(vd*id_+vq*iq)+3*v0*i0)

    def test_common_dq_axis_rotation_does_not_verify_axis(self):
        current=[5.,6.,-3.];flux=[.18,-.11,.04];voltage=[2.,-1.,4.]
        def evaluate(theta):
            id_,iq,i0=d.transform(current,theta)
            psid,psiq,_=d.transform(flux,theta)
            vd,vq,v0=d.transform(voltage,theta)
            return id_,iq,psid,psiq,psid*iq-psiq*id_,1.5*(vd*id_+vq*iq)+3*v0*i0
        baseline=evaluate(.73)
        for degrees in (17,90,180):
            rotated=evaluate(.73+math.radians(degrees))
            self.assertAlmostEqual(baseline[4],rotated[4],places=12)
            self.assertAlmostEqual(baseline[5],rotated[5],places=12)
            self.assertGreater(abs(baseline[0]-rotated[0])+abs(baseline[1]-rotated[1]),.1)
            self.assertGreater(abs(baseline[2]-rotated[2])+abs(baseline[3]-rotated[3]),.001)

    def test_incomplete_or_bad_units_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.csv';p.write_text('Time [s],Wrong [A]\n0,1\n',encoding='utf-8')
            with self.assertRaises(ValueError):d.read_csv(p,['Time [ms]','Wrong [A]'])

    def test_reject_reverse_phase_sequence(self):
        samples=[]
        for k in range(120):
            t=k/120.; a=2*math.pi*t
            samples.append([t,math.sin(a),math.sin(a+2*math.pi/3),math.sin(a-2*math.pi/3)])
        with self.assertRaisesRegex(ValueError,'ABC'): d.fundamental_phases(samples,2*math.pi)

    def test_analytic_fundamental_sequence_components(self):
        # Exact sine-reference ABC phasors, including a known negative and zero sequence.
        a=complex(-.5,math.sqrt(3)/2.)
        positive=complex(5.,2.); negative=complex(.7,-.3); zero=complex(.2,.1)
        phases=[positive+negative+zero, positive*a*a+negative*a+zero,
                positive*a+negative*a*a+zero]
        rows=[]
        for k in range(120):
            t=k/(120.*50.); theta=2*math.pi*50*t
            rows.append([t]+[z.real*math.sin(theta)+z.imag*math.cos(theta) for z in phases])
        q=d.fundamental_sequence_metrics(rows,2*math.pi*50.)
        self.assertAlmostEqual(q['positive_sequence_rms'],abs(positive)/math.sqrt(2),places=12)
        self.assertAlmostEqual(q['negative_sequence_rms'],abs(negative)/math.sqrt(2),places=12)
        self.assertAlmostEqual(q['zero_sequence_rms'],abs(zero)/math.sqrt(2),places=12)
        self.assertAlmostEqual(q['negative_over_positive'],abs(negative)/abs(positive),places=12)
        self.assertAlmostEqual(q['zero_over_positive'],abs(zero)/abs(positive),places=12)
        for name, z in zip('ABC',phases):
            self.assertAlmostEqual(q['phase_rms'][name],abs(z)/math.sqrt(2),places=12)
        # A perfectly balanced positive sequence has no negative or zero component.
        balanced=[]
        for k in range(120):
            t=k/(120.*50.); theta=2*math.pi*50*t
            balanced.append([t]+[z.real*math.sin(theta)+z.imag*math.cos(theta)
                                  for z in (positive,positive*a*a,positive*a)])
        q=d.fundamental_sequence_metrics(balanced,2*math.pi*50.)
        self.assertLess(q['negative_over_positive'],1e-12)
        self.assertLess(q['zero_over_positive'],1e-12)

    def test_unbalanced_waveform_reports_sequence_without_imposing_threshold(self):
        with tempfile.TemporaryDirectory() as folder:
            no,load,_=self.write_fixture(Path(folder))
            for path,scale in ((no/'noload_EMF.csv',10.), (load/'Current.csv',.01)):
                with path.open(encoding='utf-8',newline='') as f: rows=list(csv.reader(f))
                for row in rows[1:]: row[2]=str(float(row[2])*scale)
                with path.open('w',encoding='utf-8',newline='') as f: csv.writer(f).writerows(rows)
            r=d.eval_case(no,load)
            self.assertAlmostEqual(r['noload_emf_fundamental_V']['negative_over_positive'],.75,places=10)
            self.assertAlmostEqual(r['noload_emf_fundamental_V']['zero_over_positive'],.75,places=10)
            self.assertAlmostEqual(r['load_current_fundamental_A']['negative_over_positive'],.99/2.01,places=10)
            self.assertTrue(any('phase-angle acceptance alone' in limit for limit in r['limits']))

    def test_self_contained_case_and_lineage(self):
        with tempfile.TemporaryDirectory() as folder:
            no,load,torque=self.write_fixture(Path(folder))
            r=d.eval_case(no,load)
            self.assertTrue(any('invariant to a common dq-axis rotation' in limit for limit in r['limits']))
            self.assertTrue(any('No-load has 1 electrical cycles and load has 2' in limit for limit in r['limits']))
            self.assertAlmostEqual(r['mean_id_peak_A'],-2.,places=9)
            self.assertAlmostEqual(r['mean_iq_peak_A'],5.,places=9)
            self.assertAlmostEqual(r['mean_torque_cross_product_Nm'],torque,places=9)
            self.assertLess(r['power_transform_max_abs_difference_W'],1e-8)
            (no/'configured_noload_EXPLORATORY.aedt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'traced'):d.eval_case(no,load)

    def test_load_shorter_than_configured_is_rejected_even_with_a_full_cycle(self):
        with tempfile.TemporaryDirectory() as folder:
            no,load,_=self.write_fixture(Path(folder))
            # Each report retains 220 intervals, i.e. more than a whole 120-step cycle.
            for name in ('Current.csv','Flux.csv','Voltage.csv','Torque.csv'):
                path=load/name; lines=path.read_text(encoding='utf-8').splitlines()
                path.write_text('\n'.join(lines[:-20])+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'load i: incomplete configured time grid'):
                d.eval_case(no,load)

    def test_noload_truncated_and_shifted_load_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            no,load,_=self.write_fixture(Path(folder))
            path=no/'noload_EMF.csv'; lines=path.read_text(encoding='utf-8').splitlines()
            path.write_text('\n'.join(lines[:-1])+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'no-load EMF: incomplete configured time grid'):
                d.eval_case(no,load)
        with tempfile.TemporaryDirectory() as folder:
            no,load,_=self.write_fixture(Path(folder))
            for name in ('Current.csv','Flux.csv','Voltage.csv','Torque.csv'):
                path=load/name
                with path.open('r',encoding='utf-8',newline='') as f: rows=list(csv.reader(f))
                for row in rows[1:]: row[0]=str(float(row[0])+1.0)
                with path.open('w',encoding='utf-8',newline='') as f: csv.writer(f).writerows(rows)
            with self.assertRaisesRegex(ValueError,'load i: configured time grid mismatch'):
                d.eval_case(no,load)

    def test_missing_or_invalid_grid_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            no,load,_=self.write_fixture(Path(folder))
            path=load/'configuration.json'; cfg=json.loads(path.read_text(encoding='utf-8'))
            del cfg['step_deg']; path.write_text(json.dumps(cfg),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'invalid or missing time configuration'):
                d.eval_case(no,load)

    def test_pole_counts_must_be_positive_even_integers_on_both_sides(self):
        for seed_poles, load_poles, label in ((4.9, 4.9, 'load'), (4.9, 4, 'no-load'),
                                               (4, 4.9, 'load'), (True, True, 'load'),
                                               (False, 4, 'no-load'), (3, 3, 'load'),
                                               (0, 0, 'load'), (-4, -4, 'load')):
            with self.subTest(seed_poles=seed_poles, load_poles=load_poles):
                with tempfile.TemporaryDirectory() as folder:
                    no,load,_=self.write_fixture(Path(folder))
                    seed_path=no/'configuration.json'; seed=json.loads(seed_path.read_text(encoding='utf-8'))
                    seed['poles']=seed_poles; seed_path.write_text(json.dumps(seed),encoding='utf-8')
                    load_path=load/'configuration.json'; cfg=json.loads(load_path.read_text(encoding='utf-8'))
                    cfg['poles']=load_poles; cfg['source_configuration_sha256']=d.sha(seed_path)
                    load_path.write_text(json.dumps(cfg),encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, label+': poles must be a positive even integer'):
                        d.eval_case(no,load)

    def test_existing_motor_waveforms_crosscheck(self):
        if ROOT is None or not (ROOT/'two_motor_simulation_20261119'/'110kW_noload').is_dir():
            self.skipTest('Real workspace data is not available; independent synthetic tests still run.')
        for name in ('110kW','75kW'):
            root=ROOT/'two_motor_simulation_20261119'
            r=d.eval_case(root/(name+'_noload'),root/(name+'_load_m62'))
            self.assertLess(r['power_transform_max_abs_difference_W'],1e-6)
            self.assertLess(r['voltage_minus_backward_flux_derivative_A_rms_V'],1e-6)
            self.assertLess(abs(r['mean_torque_cross_product_Nm']/r['mean_maxwell_torque_Nm']-1),.005)
            self.assertGreater(r['mean_iq_peak_A'],0)
            self.assertLess(r['mean_id_peak_A'],0)

if __name__=='__main__':unittest.main()
