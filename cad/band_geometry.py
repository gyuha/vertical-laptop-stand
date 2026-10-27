"""Shared rubber centerline for CAD clearance checks and the Blender illustration."""
import math


def band_centerline(p,index,theta):
    t=math.radians(theta)
    co,si=math.cos(t),math.sin(t)
    h=p['foot_drop']*co-(p['foot_x']-12)*si
    x,y=p['hook_x'][index],p['hook_band_y']
    radius=p['band_wrap_radius']
    points=[]
    for left in [False,True]:
        for i in range(33):
            a=(-math.pi/2 if not left else math.pi/2)+math.pi*i/32
            local_x=(-x if left else x)+radius*math.cos(a)
            local_y=y
            z=p['hook_z']+radius*math.sin(a)
            sign=1 if left else -1
            points.append((local_x*co+sign*z*si,local_y,
                           -sign*local_x*si+z*co+h))
    return points+[points[0]]
