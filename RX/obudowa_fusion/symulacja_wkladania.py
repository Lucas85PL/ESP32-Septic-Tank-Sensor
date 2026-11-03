"""
Czy plytke z wyswietlaczem da sie wlozyc od tylu miedzy 4 slupki w rogach (tylne mocowanie pleckow)?
Model 2D w przekroju YZ (Y = glebokosc, Z = wysokosc), ruch sztywny (obrot theta wokol osi X, przesuniecie y, z).
Dwa przekroje:
  A) przy koncach plytki (|x| > 37.4): tu stoja slupki w rogach -> plytka PCB 1,6 mm
  B) w srodku (|x| < 37.4): szyba z przodu 4 mm + elementy z tylu 5,1 mm (konserwatywnie pelne), bez slupkow
BFS po przestrzeni konfiguracji (theta, y, z) od pozycji koncowej do "wyjscia" z obudowy.
"""
import sys
from collections import deque
from shapely.geometry import box as _box, Polygon
def box(y0, y1, z0, z1):
    return _box(y0, z0, y1, z1)   # (os 'x' shapely = Y gleb., os 'y' shapely = Z wys.)
from shapely.affinity import rotate, translate
from shapely.ops import unary_union

def feasible(inner_h, post_sz, y_s, post_len, y_front_final=6.2, front_t=2.0, cover_t=2.4,
             pcb_t=1.6, glass=4.0, comps=5.1, pcb_h=50.0, dth=2, dy=1.0, dz=0.5, zmax=2.0, verbose=False):
    y_cover_in = y_s + post_len
    depth = y_cover_in + cover_t
    hz = inner_h / 2.0
    big = 500.0
    walls = [box(-big, front_t, -big, big),                 # sciana czolowa (y < front_t)
             box(-big, big, hz, big), box(-big, big, -big, -hz)]   # gora/dol
    posts = [box(y_s, y_cover_in, hz - post_sz, hz), box(y_s, y_cover_in, -hz, -hz + post_sz)]
    fposts = [box(front_t, y_front_final, 21 - 2.3, 21 + 2.3), box(front_t, y_front_final, -21 - 2.3, -21 + 2.3)]
    obsA = unary_union(walls + posts + fposts)
    obsB = unary_union(walls)

    # ciala (lokalny uklad: y_pcb_front = 0, os Y w tyl); obracane wokol srodka PCB
    bodyA = box(0, pcb_t, -pcb_h / 2, pcb_h / 2)
    bodyB = box(-glass, pcb_t + comps, -pcb_h / 2, pcb_h / 2)
    cen = (pcb_t / 2, 0)

    def pose(body, th, y, z):
        b = rotate(body, th, origin=cen, use_radians=False)
        return translate(b, y, z)

    def free(th, y, z):
        a = pose(bodyA, th, y, z)
        b = pose(bodyB, th, y, z)
        # w koncowej pozycji PCB opiera sie o slupki (stykanie dozwolone) -> maly bufor ujemny
        if a.buffer(-0.02).intersects(obsA):
            return False
        if b.buffer(-0.02).intersects(obsB):
            return False
        return True

    thetas = list(range(-90, 91, dth))
    ys = [y_front_final + i * dy for i in range(0, int((depth + 70 - y_front_final) / dy) + 1)]
    zs = [round(-zmax + i * dz, 3) for i in range(int(2 * zmax / dz) + 1)]
    start = (thetas.index(0), 0, zs.index(0.0) if 0.0 in zs else len(zs) // 2)
    if not free(0, ys[0], zs[start[2]]):
        return False, "pozycja koncowa koliduje", depth
    seen = {start}
    q = deque([start])
    while q:
        ti, yi, zi = q.popleft()
        th, y, z = thetas[ti], ys[yi], zs[zi]
        # wyjscie: cale cialo B poza obudowa (min y > depth)
        bb = pose(bodyB, th, y, z).bounds
        if bb[0] >= depth:
            return True, (th, y, z), depth
        for dti, dyi, dzi in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            n = (ti + dti, yi + dyi, zi + dzi)
            if not (0 <= n[0] < len(thetas) and 0 <= n[1] < len(ys) and 0 <= n[2] < len(zs)):
                continue
            if n in seen:
                continue
            if free(thetas[n[0]], ys[n[1]], zs[n[2]]):
                seen.add(n)
                q.append(n)
    return False, "brak drogi", depth

if __name__ == "__main__":
    inner_h = float(sys.argv[1]) if len(sys.argv) > 1 else 52.0
    post_sz = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    post_len = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    print("wnetrze Hz=%.1f, slupek %.1f x %.1f, dlugosc slupka %.1f" % (inner_h, post_sz, post_sz, post_len))
    for y_s in (8, 12, 16, 20, 24, 28, 32, 36, 40, 44):
        ok, info, depth = feasible(inner_h, post_sz, y_s, post_len)
        print("  przod slupkow y=%2d -> glebokosc obudowy %.1f mm : %s %s" % (y_s, depth, "OK" if ok else "NIE", "" if ok else info))
