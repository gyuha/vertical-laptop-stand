"""Blender offline renders. Run with blender --background --python this_file."""
from pathlib import Path
import json
import math
import sys
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence'
P=json.loads((ROOT/'cad/parameters.json').read_text())
sys.path.insert(0,str(ROOT/'cad'))
from band_geometry import band_centerline


def material(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color,1)
    m.use_nodes = True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=0.65
    return m


def reset():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 32
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 1200, 1000
    sc.render.resolution_percentage = 100
    sc.world.color = (0.7,0.7,0.7)
    sc.view_settings.view_transform = 'Standard'
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = False
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs[0].default_value=(0.82,0.84,0.85,1)
    sc.world.node_tree.nodes['Background'].inputs[1].default_value=0.65


def load(path, color, original=False):
    bpy.ops.wm.stl_import(filepath=str(path))
    obj=bpy.context.object
    if original:
        obj.rotation_euler[0] = math.pi/2
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        corners=[obj.matrix_world @ Vector(c) for c in obj.bound_box]
        lo=Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        hi=Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        obj.location -= Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z))
    obj.data.materials.append(material(path.stem,color))
    return obj


def finish(name, objects, front=False, focus=None, scale=None, direction=None):
    for obj in list(bpy.context.scene.objects):
        if obj.get('render_helper'):
            bpy.data.objects.remove(obj,do_unlink=True)
    pts=[o.matrix_world @ v.co for o in objects for v in o.data.vertices]
    lo=Vector(tuple(min(c[i] for c in pts) for i in range(3)))
    hi=Vector(tuple(max(c[i] for c in pts) for i in range(3)))
    center=Vector(focus) if focus is not None else (lo+hi)/2
    span=max(hi.x-lo.x,hi.y-lo.y,hi.z-lo.z)
    bpy.ops.object.camera_add()
    cam=bpy.context.object
    cam['render_helper']=True
    view=direction if direction is not None else ((0,-3,0.1) if front else (1.9,-2.8,1.65))
    cam.location = center + Vector(view)*span
    cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO'
    cam.data.ortho_scale=scale if scale is not None else span*(1.22 if front else 1.45)
    bpy.context.scene.camera=cam
    bpy.ops.mesh.primitive_plane_add(size=span*200,location=(0,0,lo.z-0.15))
    bpy.context.object['render_helper']=True
    bpy.context.object.data.materials.append(material('floor',(0.90,0.91,0.90)))
    for offset,energy,size in [((0,-1,3),1200,2),((2,1,2),700,2)]:
        bpy.ops.object.light_add(type='AREA',location=center+Vector(offset)*span)
        light=bpy.context.object
        light['render_helper']=True
        light.data.energy=energy*(span/10)**2
        light.data.shape='DISK'
        light.data.size=size*span
        light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.scene.render.filepath=str(OUT / f'{name}.png')
    bpy.ops.render.render(write_still=True)


def render_print_assets():
    for path,name,color in [
        (ROOT/'exports/calibration/calibration-plate.stl','print-layout',(0.35,0.44,0.54)),
        (ROOT/'exports/calibration/axle-key.stl','key-detail',(0.35,0.44,0.54))]:
        reset()
        obj=load(path,color)
        bpy.context.view_layer.update()
        finish(name,[obj])


def finish_hook_detail(objects):
    # Isolate the real left body so the opposite wall cannot hide the neck and
    # its backing in this oblique inspection view. Restore the full scene after.
    hidden=[(obj,obj.hide_render) for obj in objects[1:]]
    for obj,_ in hidden:
        obj.hide_render=True
    finish('hook-detail',objects[:1],
           focus=(-P['hook_x'][0],P['hook_band_y'],P['foot_drop']+P['hook_z']),
           scale=30,direction=(1.4,3,1))
    for obj,state in hidden:
        obj.hide_render=state


def main():
    OUT.mkdir(exist_ok=True,parents=True)
    if '--hook-only' in sys.argv:
        reset()
        objs=[load(OUT/f'assembly-open-{side}.stl',color)
              for side,color in [('left',(0.30,0.40,0.53)),('right',(0.39,0.49,0.59))]]
        bpy.context.view_layer.update()
        finish_hook_detail(objs)
        return
    if '--print-only' in sys.argv:
        render_print_assets()
        return
    if '--detail-only' in sys.argv:
        for state in ['open','loaded']:
            reset()
            objs=[load(OUT/f'assembly-{state}-{side}.stl',color)
                  for side,color in [('left',(0.30,0.40,0.53)),
                                     ('right',(0.39,0.49,0.59)),('axle',(0.83,0.53,0.17))]]
            bpy.context.view_layer.update()
            finish(f'joint-detail-{state}',objs,focus=(0,0,15),scale=48)
        return
    for file,label,color in [('body-original.stl','reference-body',(0.33,0.42,0.54)),
                             ('connector-original.stl','reference-connector',(0.85,0.35,0.06))]:
        reset()
        obj=load(ROOT/'references'/file,color,True)
        bpy.context.view_layer.update()
        finish(label,[obj])
    for state in ['open','loaded']:
        reset()
        objs=[load(OUT/f'assembly-{state}-{side}.stl',color)
              for side,color in [('left',(0.30,0.40,0.53)),('right',(0.39,0.49,0.59))]]
        objs += [load(OUT/f'assembly-{state}-{side}.stl',
                      (0.35,0.44,0.54) if side=='main-key' else (0.83,0.53,0.17))
                 for side in ['axle','main-key']]
        angle=0 if state=='open' else P['sample_loaded_angle_deg']
        points=band_centerline(P,0,angle)[:-1]
        curve=bpy.data.curves.new('Illustrative rubber band','CURVE')
        curve.dimensions='3D'
        curve.bevel_depth=P['band_wire_radius']
        curve.bevel_resolution=3
        spline=curve.splines.new('POLY')
        spline.points.add(len(points)-1)
        for pt,co in zip(spline.points,points):pt.co=(*co,1)
        spline.use_cyclic_u=True
        band=bpy.data.objects.new('Illustrative rubber band',curve)
        bpy.context.collection.objects.link(band)
        band.data.materials.append(material('band',(0.88,0.27,0.04)))
        bpy.context.view_layer.objects.active=band
        band.select_set(True)
        for o in objs:o.select_set(False)
        bpy.ops.object.convert(target='MESH')
        objs.append(bpy.context.object)
        bpy.context.view_layer.update()
        finish(f'assembly-{state}',objs)
        finish(f'front-{state}',objs,True)
        # Preserve the material-colored band object reference across camera changes.
        band=objs[-1]
        band.hide_render=True
        finish(f'joint-detail-{state}',objs[:-1],focus=(0,0,15),scale=48)
        band.hide_render=False
        band_z=sum(point[2] for point in points)/len(points)
        finish(f'inside-{state}',objs,focus=(0,P['hook_band_y'],band_z),scale=52,direction=(0,3,0))
        if state=='open':
            finish_hook_detail(objs)
            finish('retainer-installed',objs,focus=(0,P['depth']+5.7,P['foot_drop']),
                   scale=18,direction=(-0.25,3,0.18))
    render_print_assets()


if __name__=='__main__':
    main()
