"""Render the real print-in-place assembly, print plate, trial and hinge section."""
from pathlib import Path
import sys
import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import render_models as render

OUT=ROOT/'docs/evidence/print-in-place'
render.OUT=OUT
LEFT,RIGHT=(0.30,0.40,0.53),(0.77,0.58,0.30)


def main():
    for state in ['open','print']:
        render.reset()
        objects=[render.load(OUT/f'{state}-body-left.stl',LEFT),
                 render.load(OUT/f'{state}-body-right.stl',RIGHT)]
        bpy.context.view_layer.update()
        render.finish(f'assembly-{state}',objects)
    for file,name in [('assembly-plate.stl','print-layout'),('hinge-trial.stl','trial-layout')]:
        render.reset()
        obj=render.load(ROOT/'exports/print-in-place'/file,(0.35,0.44,0.54))
        bpy.context.view_layer.update()
        render.finish(name,[obj])
    # Looking down onto the cut plane (Z=0) through the hinge axis.
    render.reset()
    objects=[render.load(OUT/'section-left.stl',LEFT),render.load(OUT/'section-right.stl',RIGHT)]
    bpy.context.view_layer.update()
    render.finish('hinge-section',objects,focus=(0,11,0),scale=24,direction=(0,0,-3),floor=False)


if __name__=='__main__':
    main()
