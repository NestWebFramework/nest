---
title: "Road router"
description: "Valhalla on your own server so the journey planner's cars, taxis and walks follow the streets: setting it up for Romania and Moldova, its memory and disk, keeping its maps fresh."
---

# Road router

The journey planner (the `planner` module, Încotro?) works out its car, taxi and walking
legs along the roads when it has a road router: lengths and minutes from the streets, and
the map draws them along the streets. Without one it draws a straight line, takes it as
1.3 times longer on the road, and uses an average speed.

The router is [Valhalla](https://valhalla.github.io/valhalla/) on OpenStreetMap's roads,
on your own server. It gets only two points per question, never anything about the
visitor. One Valhalla serves every site on the server (gari.ro, transport-comun.ro,
transportul.ro, aeroportul.ro).

## What it takes

| | Romania and Moldova |
|---|---|
| Download (Geofabrik extracts) | about 400 MB, once a month |
| Building the tiles | about 20–40 min, 2–3 GB of memory at its peak |
| Tiles on disk | about 2 GB |
| Serving | 200–400 MB of memory (it reads the tiles from disk as needed), tens of milliseconds a question |

## Running it

```sh
sudo mkdir -p /srv/valhalla && sudo chown $USER /srv/valhalla
docker run -d --name valhalla --restart unless-stopped \
  -p 127.0.0.1:8002:8002 \
  -v /srv/valhalla:/custom_files \
  -e tile_urls="https://download.geofabrik.de/europe/romania-latest.osm.pbf https://download.geofabrik.de/europe/moldova-latest.osm.pbf" \
  -e serve_tiles=True -e build_elevation=False -e build_transit=False \
  -e build_admins=True -e build_time_zones=True \
  -e use_tiles_ignore_pbf=True -e server_threads=2 \
  ghcr.io/valhalla/valhalla-scripted:latest
docker logs -f valhalla        # wait for the tiles: it then says it serves on 8002
```

It listens only on `127.0.0.1`: the sites ask it on the same server, it is never public.
The first start builds the tiles; later starts reuse them (`use_tiles_ignore_pbf`).

Check it:

```sh
curl -s localhost:8002/route -d '{"locations":[{"lat":46.7700,"lon":23.5900},{"lat":46.7846,"lon":23.5869}],"costing":"pedestrian","units":"kilometers","directions_type":"none"}' | head -c 300
```

## Telling the sites

Each site's admin → Settings → planner → **road_router**: `http://127.0.0.1:8002` (or
`http://host.docker.internal:8002` when the site itself runs in Docker without host
networking). Or in the workspace's `.env`:

```sh
NEST_GARI__PLANNER__ROAD_ROUTER=http://127.0.0.1:8002
```

The setting takes effect on the next search. When the router does not answer, the planner
goes back to straight lines for a minute and asks again.

## Fresh maps

Roads change slowly; once a month is plenty:

```sh
docker stop valhalla && rm -rf /srv/valhalla/valhalla_tiles* /srv/valhalla/*.pbf \
  && docker start valhalla     # downloads and builds again, then serves
```

While it rebuilds, the planner uses straight lines.

## Licence

The roads are OpenStreetMap's (ODbL): the planner credits "© OpenStreetMap contributors"
under the results whenever a leg came from the router.
