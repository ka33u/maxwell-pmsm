import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flux_density import add_mean_squares, cycle_results, cycle_weights, field_values, make_points, metrics
from audit_case import read_csv


class FieldChecks(unittest.TestCase):
    def setUp(self):
        self.spec=dict(rotor_tip_mm=49,bore_mm=50,slot_bottom_mm=65,outer_mm=80,slots=12,
                       poles=4,angles=120,slot1_deg=90,gap_fraction=.6,tooth_offset_pitch=.08)
        self.points=make_points(self.spec)

    def test_known_radial_fundamental_and_yoke_tangential_field(self):
        vectors=[]
        for p in self.points:
            a=math.radians(p['theta_deg'])
            br,bt=(1.2*math.cos(2*a+.37),0.) if p['region']=='gap' else ((1.6,0.) if p['region']=='tooth' else (0.,-1.35))
            vectors.append((br*math.cos(a)-bt*math.sin(a),br*math.sin(a)+bt*math.cos(a),0.))
        result=metrics(self.points,vectors,4)
        self.assertAlmostEqual(result['gap']['spatial_fundamental_Br_peak_T'],1.2)
        self.assertAlmostEqual(result['gap']['spatial_rms_component_T'],1.2/math.sqrt(2))
        self.assertAlmostEqual(result['gap']['spatial_fundamental_Br_rms_T'],1.2/math.sqrt(2))
        self.assertAlmostEqual(result['tooth']['peak_abs_component_T'],1.6)
        self.assertAlmostEqual(result['yoke']['mean_abs_component_T'],1.35)
        self.assertEqual(result['yoke']['component'],'Bt')

    def test_full_wave_spatial_rms_includes_harmonics_and_dc(self):
        vectors=[]
        for p in self.points:
            a=math.radians(p['theta_deg'])
            br=.4+1.2*math.cos(2*a)+.5*math.cos(6*a)
            vectors.append((br*math.cos(a),br*math.sin(a),.3))
        gap=metrics(self.points,vectors,4)['gap']
        expected=.4**2+(1.2**2+.5**2)/2
        self.assertAlmostEqual(gap['spatial_rms_component_T'],math.sqrt(expected))
        self.assertAlmostEqual(gap['spatial_rms_Bmag_T'],math.sqrt(expected+.3**2))
        self.assertAlmostEqual(gap['spatial_fundamental_Br_rms_T'],1.2/math.sqrt(2))

    def test_nonuniform_time_rms_and_fixed_point_max(self):
        weights=cycle_weights([0.,.25,1.],1.)
        self.assertEqual(weights,[.125,.5,.375])
        self.assertIsNone(cycle_weights([0.],1.))
        self.assertIsNone(cycle_weights([.25,.5,1.],1.))
        self.assertIsNone(cycle_weights([0.,1.],1.))
        with self.assertRaises(ValueError):
            cycle_weights([0.,.25,.25,1.],1.)
        pts=[dict(index=i,region=r,theta_deg=i*4,r_mm=5.) for i,r in enumerate(('gap','tooth','tooth','yoke'))]
        sums=[[0.,0.,0.] for _ in pts]
        for weight,a,b in zip(weights,(4.,0.,4.),(0.,2.,0.)):
            values=[(1.,0.),(a,0.),(b,0.),(0.,-3.)]
            frame=[(p,x,y,math.hypot(x,y)) for p,(x,y) in zip(pts,values)]
            add_mean_squares(sums,frame,weight)
        rows,regions=cycle_results(pts,sums,.5)
        self.assertAlmostEqual(rows[3]['Bt_rms_T'],3.)
        self.assertAlmostEqual(regions['tooth']['Bmag_space_time_rms_T'],math.sqrt(5.))
        self.assertAlmostEqual(regions['tooth']['max_point_cycle_Bmag_rms_T'],math.sqrt(8.))
        self.assertEqual(regions['tooth']['point_index'],1)

    def test_point_units_and_missing_field_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'B.fld'
            header='Vector data "<Bx,By,0>"\n'
            p.write_text(header+'49.6 0 0 1 0 0\n')
            with self.assertRaisesRegex(ValueError,'units'):
                field_values(p,self.points[:1])
            p.write_text(header+'0.0496 0 0 nan 0 0\n')
            with self.assertRaisesRegex(ValueError,'Invalid'):
                field_values(p,self.points[:1])
            p.write_text(header)
            with self.assertRaisesRegex(ValueError,'count'):
                field_values(p,self.points[:1])

    def test_refinement_keeps_coarse_points(self):
        fine=make_points(dict(self.spec,angles=240,depth_fractions=[.2,.35,.5,.65,.8],tooth_side_subdivisions=2))
        keys=lambda pts:{(p['region'],p['theta_deg'],p['r_mm']) for p in pts}
        self.assertTrue(keys(self.points).issubset(keys(fine)))
        with self.assertRaisesRegex(ValueError,'radii'):
            make_points(dict(self.spec,slot_bottom_mm=85.))

    def test_loaded_engineering_prefixes_are_scaled_per_phase(self):
        with TemporaryDirectory() as tmp:
            for name,quantity,unit in [('Current.csv','InputCurrent','A'),('Voltage.csv','InducedVoltage','V')]:
                p=Path(tmp)/name
                header='Time [ms],'+','.join('%s(Phase_%s) [%s%s]'%(quantity,phase,prefix,unit)
                                             for phase,prefix in zip('ABC',('m','','k')))
                p.write_text(header+'\n'+'\n'.join('%d,1000,2,0.003'%ms for ms in (0,5,10,15,20)))
                result=read_csv(p,quantity,4,dict(frequency_Hz=50,cycles=1,step_deg=90))
                self.assertEqual(result['value_units'],unit)
                self.assertEqual(result['last_cycle_rms'],[1.,2.,3.])
