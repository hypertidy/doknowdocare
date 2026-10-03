#!/usr/bin/env python3
"""
Precompute projected-grid lines for each scene and datum, written as GeoJSON
in the display frame that the web map treats as WGS84.

The point of the exercise: the SAME easting/northing labels (e.g. the MGA zone
55 line E=525000) sit at different places on the ground depending on which
datum the projected CRS is realised on. We draw each datum's copy of the grid
and let the viewer zoom in until the copies separate.

Usage:
    python3 scripts/make_grids.py            # writes data/
    PROJ_NETWORK=ON python3 scripts/make_grids.py   # use NTv2 / NADCON grids if reachable

Requires pyproj >= 3.6 (PROJ >= 9).
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pyproj
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.transformer import TransformerGroup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"

if os.environ.get("PROJ_NETWORK", "").upper() == "ON":
    pyproj.network.set_network_enabled(True)


# --------------------------------------------------------------------------
# Transform plumbing
# --------------------------------------------------------------------------

def best_transformer(src: str, dst: str, bbox: tuple[float, float, float, float]) -> Transformer:
    """Pick the most accurate *available* operation for the area, not the
    first one PROJ happens to rank (which for AGD66->GDA94 is a 3 m offshore
    Helmert). With PROJ_NETWORK=ON and cdn.proj.org reachable this picks the
    NTv2 / NADCON grids; otherwise the best Helmert that covers the bbox."""
    aoi = AreaOfInterest(*bbox)
    tg = TransformerGroup(src, dst, always_xy=True, area_of_interest=aoi)
    cands = [t for t in tg.transformers if t.accuracy is not None and t.accuracy >= 0]
    if not cands:
        raise RuntimeError(f"no usable operation {src} -> {dst}")
    cands.sort(key=lambda t: t.accuracy)
    t = cands[0]
    print(f"  {src} -> {dst}: {t.description.split(' (with')[0]}  [{t.accuracy} m]", file=sys.stderr)
    if tg.unavailable_operations:
        names = ", ".join(u.name for u in tg.unavailable_operations)
        print(f"    (unavailable, needs grid download: {names})", file=sys.stderr)
    return t


def nad83_2011_to_natrf2022_pipeline() -> str:
    """NAD83(2011) epoch 2010.0 -> NATRF2022.

    EPSG has no NAD83(2011)->NATRF2022 operation yet (PROJ falls through to a
    no-op via WGS84, which is exactly the mistake this site is about). So we
    compose it:

      1. NAD83(2011) -> ITRF2020 at epoch 2010.0, the inverse of EPSG's
         time-dependent 14-parameter Helmert 'ITRF2020 to NAD83(2011) (1)'.
         With no time coordinate supplied PROJ evaluates it at t_epoch=2010,
         which is what we want: NAD83(2011) coordinates ARE epoch 2010.0.
      2. Carry the point on the rigid North America plate from 2010.0 to
         2020.0 with the ITRF2014 plate-motion-model Euler vector for NOAM
         (Altamimi et al. 2017: 0.024, -0.694, -0.063 mas/yr).
      3. NATRF2022 is defined so that its coordinates equal ITRF2020 at
         epoch 2020.0, so step 2's output is NATRF2022.

    Step 1 is ~1-2 m across CONUS; step 2 is ~0.1-0.2 m. Swap the Euler
    vector for the ITRF2020 PMM when you have it to hand; it changes mm.
    """
    itrf2020_to_nad83 = Transformer.from_crs("EPSG:9990", "EPSG:6318", always_xy=True).definition
    # pull the helmert step out of PROJ's own pipeline so the numbers stay EPSG's
    steps = itrf2020_to_nad83.split(" step ")
    helmert = next(s for s in steps if s.startswith("proj=helmert"))
    dt = 10.0  # years, 2010.0 -> 2020.0
    mas_to_arcsec = 1e-3
    wx, wy, wz = 0.024, -0.694, -0.063  # mas/yr, ITRF2014 PMM NOAM
    plate = (
        f"proj=helmert rx={wx * dt * mas_to_arcsec} ry={wy * dt * mas_to_arcsec} "
        f"rz={wz * dt * mas_to_arcsec} convention=position_vector"
    )
    return (
        "proj=pipeline "
        "step proj=unitconvert xy_in=deg xy_out=rad "
        "step proj=cart ellps=GRS80 "
        f"step inv {helmert} "
        f"step {plate} "
        "step inv proj=cart ellps=GRS80 "
        "step proj=unitconvert xy_in=rad xy_out=deg"
    )


# --------------------------------------------------------------------------
# Scenes
# --------------------------------------------------------------------------

@dataclass
class Datum:
    key: str
    label: str
    note: str
    projected: str              # the projected CRS whose E/N labels we draw
    geographic: str | None      # its geographic base (None = derive from projected)
    to_display: Transformer | None = None   # geographic -> display frame
    color: str = "#000000"
    dash: list = field(default_factory=lambda: [1, 0])   # line-dasharray, in line widths


@dataclass
class Scene:
    key: str
    title: str
    blurb: str
    display_frame: str          # what the web map treats as WGS84
    centre_en: tuple[float, float]  # scene centre in grid E/N (shared labels)
    half_km: float              # half-width of the drawn grid, km
    spacings_m: tuple[int, ...] # grid spacings to draw
    datums: list[Datum] = field(default_factory=list)
    bbox_ll: tuple[float, float, float, float] = (0, 0, 0, 0)


def sydney() -> Scene:
    # -33.8769221, 151.2434361: Sydney Harbour, where the author learned that
    # longlat ain't longlat.
    bbox = (150.9, -34.1, 151.5, -33.6)
    s = Scene(
        key="sydney",
        title="Sydney, MGA zone 56",
        blurb=(
            "The same zone-56 grid realised on three datums. AGD66 to GDA94 is "
            "about 200 m north-east; GDA94 to GDA2020 is about 1.8 m of plate "
            "motion. Zoom out and the first disappears around z12; the second "
            "was never visible above z18."
        ),
        display_frame="EPSG:7844",
        centre_en=(337_542, 6_250_102),
        half_km=6,
        spacings_m=(1000, 100),
        bbox_ll=bbox,
    )
    s.datums = [
        Datum("agd66", "AGD66 (AMG zone 56)", "EPSG:20256", "EPSG:20256", "EPSG:4202", color="#D55E00", dash=[1, 0]),
        Datum("gda94", "GDA94 (MGA94 zone 56)", "EPSG:28356", "EPSG:28356", "EPSG:4283", color="#0072B2", dash=[4, 3]),
        Datum("gda2020", "GDA2020 (MGA2020 zone 56)", "EPSG:7856", "EPSG:7856", "EPSG:7844", color="#CC79A7", dash=[1, 2]),
    ]
    print("sydney", file=sys.stderr)
    for d in s.datums:
        if d.geographic == s.display_frame:
            d.to_display = None
        else:
            d.to_display = best_transformer(d.geographic, s.display_frame, bbox)
    return s


def seattle() -> Scene:
    bbox = (-122.6, 47.4, -122.1, 47.8)
    s = Scene(
        key="seattle",
        title="Seattle, UTM zone 10N",
        blurb=(
            "NAD83(2011) versus NATRF2022 on the UTM zone 10N grid. The shift "
            "is 1 to 2 m, mostly the NAD83-vs-ITRF frame offset plus a decade "
            "of plate motion. Invisible until about z18, then suddenly a "
            "parcel-boundary problem."
        ),
        display_frame="NATRF2022",
        centre_en=(550_000, 5_273_000),
        half_km=6,
        spacings_m=(1000, 100),
        bbox_ll=bbox,
    )
    s.datums = [
        Datum("nad83_2011", "NAD83(2011) epoch 2010.0", "EPSG:6339", "EPSG:6339", "EPSG:6318", color="#D55E00", dash=[1, 0]),
        Datum("natrf2022", "NATRF2022 (ITRF2020 @ 2020.0)", "NATRF2022 / UTM 10N (no EPSG code yet)",
              "+proj=utm +zone=10 +ellps=GRS80 +units=m +no_defs", None, color="#CC79A7", dash=[1, 2]),
    ]
    print("seattle", file=sys.stderr)
    pipe = nad83_2011_to_natrf2022_pipeline()
    print(f"  NAD83(2011) -> NATRF2022: composed pipeline (EPSG Helmert + NOAM plate motion)", file=sys.stderr)
    s.datums[0].to_display = Transformer.from_pipeline(pipe)
    s.datums[1].to_display = None
    return s


# --------------------------------------------------------------------------
# Grid generation
# --------------------------------------------------------------------------

def grid_lines(centre: tuple[float, float], half_km: float, spacing: int, step_m: float = 1000.0):
    """Yield (axis, value, [(E,N),...]) for grid lines in projected coords.
    Lines are densified so curvature after reprojection is honest."""
    e0, n0 = centre
    half = half_km * 1000.0
    emin, emax = math.floor((e0 - half) / spacing) * spacing, math.ceil((e0 + half) / spacing) * spacing
    nmin, nmax = math.floor((n0 - half) / spacing) * spacing, math.ceil((n0 + half) / spacing) * spacing
    nd = max(2, int((emax - emin) / step_m) + 1)
    for e in range(int(emin), int(emax) + 1, spacing):
        pts = [(e, nmin + (nmax - nmin) * i / (nd - 1)) for i in range(nd)]
        yield "E", e, pts
    for n in range(int(nmin), int(nmax) + 1, spacing):
        pts = [(emin + (emax - emin) * i / (nd - 1), n) for i in range(nd)]
        yield "N", n, pts


def project_to_display(d: Datum, pts):
    proj_crs = CRS.from_user_input(d.projected)
    geog_crs = CRS.from_user_input(d.geographic) if d.geographic else proj_crs.geodetic_crs
    inv = Transformer.from_crs(proj_crs, geog_crs, always_xy=True)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    lon, lat = inv.transform(xs, ys)
    if d.to_display is not None:
        lon, lat = d.to_display.transform(lon, lat)
    return list(zip(lon, lat))


def write_scene(s: Scene):
    scene_dir = OUT / s.key
    scene_dir.mkdir(parents=True, exist_ok=True)
    # scene centre in each datum, for the offset readout
    centre_ll = {}
    for d in s.datums:
        (lon, lat), = project_to_display(d, [s.centre_en])
        centre_ll[d.key] = [round(lon, 9), round(lat, 9)]
        feats = []
        for spacing in s.spacings_m:
            for axis, val, pts in grid_lines(s.centre_en, s.half_km, spacing):
                if spacing != s.spacings_m[0] and val % s.spacings_m[0] == 0:
                    continue  # don't double-draw the coarse lines
                coords = [[round(x, 7), round(y, 7)] for x, y in project_to_display(d, pts)]
                feats.append({
                    "type": "Feature",
                    "properties": {"axis": axis, "value": val, "spacing": spacing, "datum": d.key},
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
        fc = {"type": "FeatureCollection", "features": feats}
        with open(scene_dir / f"{d.key}.geojson", "w") as f:
            json.dump(fc, f, separators=(",", ":"))
        print(f"  wrote {s.key}/{d.key}.geojson ({len(feats)} lines)", file=sys.stderr)

    # pairwise offsets at the centre, metres and bearing
    geod = pyproj.Geod(ellps="GRS80")
    offsets = []
    keys = [d.key for d in s.datums]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = centre_ll[keys[i]], centre_ll[keys[j]]
            az, _, dist = geod.inv(a[0], a[1], b[0], b[1])
            offsets.append({"from": keys[i], "to": keys[j], "metres": round(dist, 3), "bearing": round(az % 360, 1)})
            print(f"  {keys[i]} -> {keys[j]}: {dist:.3f} m at {az % 360:.1f} deg", file=sys.stderr)

    return {
        "key": s.key,
        "title": s.title,
        "blurb": s.blurb,
        "display_frame": s.display_frame,
        "centre": centre_ll[s.datums[-1].key],
        "centre_en": list(s.centre_en),
        "spacings_m": list(s.spacings_m),
        "datums": [{"key": d.key, "label": d.label, "crs": d.note, "color": d.color, "dash": d.dash,
                    "file": f"data/{s.key}/{d.key}.geojson"} for d in s.datums],
        "offsets": offsets,
    }


def main():
    OUT.mkdir(exist_ok=True)
    scenes = [write_scene(s) for s in (sydney(), seattle())]
    meta = {"proj_version": pyproj.proj_version_str, "scenes": scenes}
    with open(OUT / "scenes.json", "w") as f:
        json.dump(meta, f, indent=1)
    print(f"wrote data/scenes.json (PROJ {pyproj.proj_version_str})", file=sys.stderr)


if __name__ == "__main__":
    main()
