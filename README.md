# doknowdocare

The same projected grid, on different datums. Zoom in until they disagree.

Live: https://hypertidy.github.io/doknowdocare/

A projected grid line like "MGA zone 55, E = 527000" is only a place on the
ground once you say which datum it is realised on. This site draws the same
set of easting/northing labels on each of several datums and lets you zoom
in and out. At low zoom the copies fuse into one grid and the datum does not
matter. Zoom in and they come apart: by 200 m for AGD66 vs GDA94, by 1 to 2 m
for GDA94 vs GDA2020 or NAD83(2011) vs NATRF2022. The panel reports each
offset in metres and in screen pixels at the current zoom, so the answer to
"do I care?" is always just "at this zoom, N pixels".

## Scenes

- **Sydney, MGA zone 56**: AGD66 (AMG), GDA94 (MGA94), GDA2020 (MGA2020), centred on Sydney Harbour where the author learned that longlat is not longlat.
- **Melbourne, VicGrid**: VicGrid66, VicGrid94, VicGrid2020. VicGrid94 moved the
  false northing by 2,000,000 m so it could never be confused with VicGrid66;
  the same label is 2,000 km away. VicGrid2020 kept the VicGrid94 origin.
- **Paris, UTM zone 31N**: ED50 vs ETRS89, about 230 m.
- **Seattle, UTM zone 10N**: NAD83(2011) at epoch 2010.0 vs NATRF2022.

Append `?howard` to the URL for the alternative sub-pixel verdict.

## How the data is made

`scripts/make_grids.py` uses pyproj to generate grid lines in each datum's
projected CRS, inverse-projects them to that datum's geographic CRS, then
transforms them into the scene's modern frame (GDA2020 for Australia,
NATRF2022 for the US). The web map treats that frame as WGS84, which is wrong
by a few decimetres, but every datum in a scene is wrong by the same few
decimetres, so the differences between them are right.

The datum steps:

- AGD66 to GDA94 and GDA94 to GDA2020 come from PROJ's EPSG database. The
  script picks the most accurate operation that is actually available for
  the scene bounding box rather than PROJ's default ranking (which for
  AGD66 is a 3 m offshore Helmert). With `PROJ_NETWORK=ON` and
  cdn.proj.org reachable it uses the ICSM NTv2 grid; otherwise the best
  regional 7-parameter Helmert, which is accurate to about a metre and is
  fine for a 200 m effect.
- NAD83(2011) to NATRF2022 does not exist in EPSG yet and PROJ falls through
  to a no-op via WGS84, which is precisely the mistake this site is about.
  The script composes it: EPSG's time-dependent Helmert
  "ITRF2020 to NAD83(2011) (1)" inverted at epoch 2010.0, then ten years of
  rigid North America plate motion (ITRF2014 PMM Euler vector) to carry the
  point to 2020.0. NATRF2022 is defined so that its coordinates equal
  ITRF2020 at epoch 2020.0, so that is the answer. The plate step is about
  0.15 m; the frame step is 1 to 2 m.

Regenerate with:

    pip install pyproj
    python3 scripts/make_grids.py
    # or, to use grid-shift files where they exist:
    PROJ_NETWORK=ON python3 scripts/make_grids.py

The generated GeoJSON in `data/` is committed so the site is purely static.

## Ideas not done yet

- NAD27 vs NAD83 (about 100 m in CONUS) needs the NADCON5 grid, so it
  wants `PROJ_NETWORK=ON` at build time.
- Dynamic datums: an epoch slider for ATRF / ITRF so the grid visibly walks.
- The raster version: one orthophoto warped to web mercator twice, once with
  its true CRS and once with the wrong datum declared, so the coastline
  ghosts at high zoom and fuses at low zoom.
- More scenes: anywhere with a crisp cadastre and a well-known datum story.

## Name

Do you know? Do you care? Zoom in and find out.
