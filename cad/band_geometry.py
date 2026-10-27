"""Shared rubber centerline for CAD clearance checks and the Blender illustration."""
import math


def convex_hull(points):
    """Counter-clockwise hull in the X/Z plane, removing collinear vertices."""
    def cross(o,a,b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    points=sorted(set(points))
    lower,upper=[],[]
    for sequence,half in [(points,lower),(list(reversed(points)),upper)]:
        for point in sequence:
            while len(half)>=2 and cross(half[-2],half[-1],point)<=1e-10:
                half.pop()
            half.append(point)
    return lower[:-1]+upper[:-1]


def band_centerline(p,index,theta):
    """Taut loop around the convex hull of both rotating capsule necks.

    An obround is a segment swept by a disk. Offset the hull of all segment
    endpoints by the wrap radius, including the tangent lines and end arcs.
    """
    t=math.radians(theta)
    co,si=math.cos(t),math.sin(t)
    h=p['foot_drop']*co-(p['foot_x']-12)*si
    x,y=p['hook_x'][index],p['hook_band_y']
    radius=p['band_wrap_radius']
    centers=[]
    span=p['hook_capsule_half_span']
    for left in [False,True]:
        sign=1 if left else -1
        for offset in [-span,span]:
            local_x=(-x if left else x)+offset
            z=p['hook_z']
            centers.append((local_x*co+sign*z*si,-sign*local_x*si+z*co+h))
    hull=convex_hull(centers)
    assert len(hull)>=2
    points=[]
    for i,(cx,cz) in enumerate(hull):
        before,after=hull[i-1],hull[(i+1)%len(hull)]
        a0=math.atan2(-(cx-before[0]),cz-before[1])
        a1=math.atan2(-(after[0]-cx),after[1]-cz)
        sweep=(a1-a0)%(2*math.pi)
        steps=max(1,math.ceil(sweep/(math.pi/32)))
        for step in range(steps+1):
            angle=a0+sweep*step/steps
            points.append((cx+radius*math.cos(angle),y,cz+radius*math.sin(angle)))
    return points+[points[0]]
