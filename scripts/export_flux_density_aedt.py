# -*- coding: utf-8 -*-
"""Native AEDT IronPython runner. Generated plan and private project copy must be beside this script."""
import csv
import json
import os
import traceback
import ScriptEnv

ScriptEnv.Initialize('Ansoft.ElectronicsDesktop')
here = os.path.dirname(os.path.abspath(__file__))
plan = json.load(open(os.path.join(here, 'plan.json')))
project = None
log = open(os.path.join(here, 'export.log'), 'w')

def note(message):
    log.write(str(message) + '\n')
    log.flush()

try:
    project_path = os.path.join(here, plan['project_file'])
    project = oDesktop.OpenProject(project_path)
    design = project.SetActiveDesign(plan['design'])
    if design.GetSolutionType() != 'Transient':
        raise ValueError('Expected a transient design')
    if plan['setup'] not in list(design.GetModule('AnalysisSetup').GetSetups()):
        raise ValueError('Setup missing')
    note('AEDT ' + oDesktop.GetVersion())
    editor = design.SetActiveEditor('3D Modeler')
    editor.SetWCS(['NAME:SetWCS Parameter', 'Working Coordinate System:=', 'Global',
                   'RegionDepCSOk:=', False])
    note('Stator material ' + str(editor.GetPropertyValue('Geometry3DAttributeTab', plan['stator'], 'Material')))
    material = editor.GetPropertyValue('Geometry3DAttributeTab', plan['stator'], 'Material')
    if str(material).strip('"').lower() != plan['steel_material'].lower():
        raise ValueError('Unexpected stator material: ' + str(material))
    for body in sorted(set(plan['air_bodies'])):
        mat = str(editor.GetPropertyValue('Geometry3DAttributeTab', body, 'Material')).strip('"').lower()
        if mat not in plan['air_materials']:
            raise ValueError('Unexpected gap-region material on '+body+': '+mat)
        note(body + ' material ' + mat)
    checked = 0
    with open(os.path.join(here, 'points.csv'), 'rb') as stream:
        for row in csv.DictReader(stream):
            bodies = set(editor.GetBodyNamesByPosition(['NAME:Parameters',
                         'XPosition:=', row['x_mm']+'mm', 'YPosition:=', row['y_mm']+'mm', 'ZPosition:=','0mm']))
            if row['region'] == 'gap':
                valid = bool(bodies) and bodies.issubset(set(plan['air_bodies']))
            else:
                valid = plan['stator'] in bodies and bodies.issubset(set([plan['stator']] + plan['air_bodies']))
            if not valid:
                raise ValueError('Wrong material region at point %s: %s' % (row['index'], sorted(bodies)))
            checked += 1
    if checked != plan['point_count']:
        raise ValueError('Point count mismatch')
    note('Geometry checked %d' % checked)
    calc = design.GetModule('FieldsReporter')
    solution = plan['setup'] + ' : Transient'
    options = ['NAME:ExportOption', 'IncludePtInOutput:=',True, 'RefCSName:=','Global',
               'PtInSI:=',True, 'FieldInRefCS:=',True]
    def export(name, when, magnitude):
        path = os.path.join(here, name)
        if os.path.exists(path):
            raise ValueError('Existing output ' + name)
        calc.CalcStack('clear')
        calc.EnterQty('B')
        if magnitude:
            calc.CalcOp('Mag')
        calc.ExportToFile(path, os.path.join(here, 'points.pts'), solution,
                          ['Time:=',when+'s'], options)
        if not os.path.isfile(path) or not os.path.getsize(path):
            raise ValueError('Missing field export: ' + name)
        note('Exported %s at %s s' % (name, when))
    for i, when in enumerate(plan['times_s']):
        export('B_%03d.fld' % i, when, False)
    export('Bmag_check.fld', plan['times_s'][-1], True)
    oDesktop.CloseProject(project.GetName())
    project = None
    note('COMPLETE')
except:
    note(traceback.format_exc())
    raise
finally:
    if project is not None:
        oDesktop.CloseProject(project.GetName())
    log.close()
