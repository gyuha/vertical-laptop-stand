"""Render the real dual-end assembly, flat clip, six-part plate and fit sample."""
from pathlib import Path
import math
import sys
import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'cad'))
import render_models as render
from band_geometry import band_centerline

OUT=ROOT/'docs/evidence/snap-retainer'
render.OUT=OUT
COLORS={'body-left':(0.30,0.40,0.53),'body-right':(0.39,0.49,0.59),
        'pin-front':(0.77,0.58,0.30),'pin-rear':(0.77,0.58,0.30),
        'clip-front':(0.18,0.48,0.46),'clip-rear':(0.18,0.48,0.46)}


def add_band(angle):
    points=band_centerline(render.P,0,angle)[:-1]
    curve=bpy.data.curves.new('Illustrative rubber band','CURVE')
    curve.dimensions='3D'
    curve.bevel_depth=render.P['band_wire_radius']
    curve.bevel_resolution=3
    spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
    for pt,co in zip(spline.points,points):pt.co=(*co,1)
    spline.use_cyclic_u=True
    band=bpy.data.objects.new('Illustrative band',curve)
    bpy.context.collection.objects.link(band)
    band.data.materials.append(render.material('band',(0.88,0.27,0.04)))
    bpy.context.view_layer.objects.active=band
    band.select_set(True)
    bpy.ops.object.convert(target='MESH')
    return bpy.context.object


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for state,angle in [('open',0),('loaded',render.P['sample_loaded_angle_deg'])]:
        render.reset()
        objects=[render.load(OUT/f'{state}-{name}.stl',color) for name,color in COLORS.items()]
        for obj in objects:obj.select_set(False)
        objects.append(add_band(angle))
        bpy.context.view_layer.update()
        render.finish(f'assembly-{state}',objects)
        # Looking along Z reveals both short hinges and the empty middle.
        render.finish(f'underside-{state}',objects,focus=(0,60,20),scale=150,direction=(0,-0.2,-3),floor=False)
    for file,name,color in [
        ('assembly-plate.stl','print-layout',(0.35,0.44,0.54)),
        ('snap-fit-plate.stl','fit-layout',(0.35,0.44,0.54)),
        ('snap-clip.stl','clip-flat',(0.18,0.48,0.46)),
        ('short-pin.stl','short-pin',(0.77,0.58,0.30))]:
        render.reset()
        obj=render.load(ROOT/'exports/snap-retainer'/file,color)
        bpy.context.view_layer.update()
        direction=(0,-0.7,3) if file=='snap-clip.stl' else None
        render.finish(name,[obj],direction=direction)
    # Isolated actual pin + clip makes the inward end and open profile visible.
    render.reset()
    objects=[render.load(OUT/f'open-{name}.stl',COLORS[name]) for name in ['pin-front','clip-front']]
    bpy.context.view_layer.update()
    render.finish('inner-clip-detail',objects,focus=(0,20.7,22),scale=22,direction=(0,3,0.4),floor=False)


if __name__=='__main__':
    main()
