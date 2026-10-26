# Fire/hot spot characterization from GOES satellites

Fire detections from the Advanced Baseline Imager (ABI) on NOAA's GOES
satellites, as virtual Zarr cubes. Each collection covers one satellite and one
scan sector. The first collection is GOES-18 CONUS. Every pixel of every scan is in the cube:
fire, clear land, cloud, water and the pixels the algorithm could not process.
The cube holds byte-range references and metadata. The pixel data stays in
NOAA's public `noaa-goes18` bucket on AWS S3.

> **Demo.** The catalog is not published yet. The collection's `extent` gives
> the time range of the cube, and the pipeline extends the cube in time.

NOAA and NESDIS produce the data and remain the authoritative source. This
catalog is a **mirror** of it.

- **Get the files**: TODO, not on Source Cooperative yet
- **Browse the metadata**: TODO, needs the published STAC root
- **Read the build**:
  [the repository on GitHub](https://github.com/mmidzik/goes-fdc-catalog)
- **The collection**: the [goes-18-fdcc README](goes-18-fdcc/README.md)

## What is here

One collection so far, `goes-18-fdcc`: NOAA's Level 2 Fire/Hot Spot Characterization
product (FDC) for the GOES-18 CONUS sector.

|            |                                                                       |
| ---------- | --------------------------------------------------------------------- |
| Satellite  | GOES-18, GOES-West, at 137.0° W                                       |
| Instrument | ABI                                                                   |
| Product    | `ABI-L2-FDCC`, Level 2 Fire/Hot Spot Characterization, CONUS sector   |
| Time range | The collection's temporal `extent`                                    |
| Scans      | About one every 5 minutes, about 288 per day                          |
| Grid       | 1500 × 2500 pixels on the ABI geostationary fixed grid, 2 km at nadir |
| Extent     | 14.6° N to 53.5° N, 175.6° E across the antimeridian to 89.6° W       |
| Variables  | `Mask`, `DQF`, `Power`, `Temp`, `Area`                                |

The FDC algorithm uses the ABI 3.89 µm and 11.19 µm bands of each scan, with
other bands for its cloud tests. For each pixel it assigns a fire mask code, and for some fire pixels it estimates the fire's radiative power,
temperature and area. NOAA writes one netCDF file per scan. The cube stacks
those files along `time` and reads them in place.

The `gsd` of 2000 m in the collection is the pixel size at nadir. Pixels are
larger toward the edges of the sector.

The GOES-18 CONUS sector is sometimes called PACUS. The extent above is NOAA's
`geospatial_lat_lon_extent` for the sector.

## Variables

Measured from the file headers. Each variable is a `time` × `y` × `x` array.

| Variable | Description          | dtype   | Units | Fill value | Scaling                                     |
| -------- | -------------------- | ------- | ----- | ---------- | ------------------------------------------- |
| `Mask`   | Fire Mask            | int16   |       | -99        |                                             |
| `DQF`    | Data quality flag    | uint8   |       | 255        |                                             |
| `Power`  | Fire Radiative Power | float32 | MW    | -9         |                                             |
| `Temp`   | Fire Temperature     | uint16  | K     | 65535      | `scale_factor` 0.05493667, `add_offset` 400 |
| `Area`   | Fire Area            | uint16  | m2    | 65535      | `scale_factor` 60.98, `add_offset` 4000     |

`Temp` and `Area` are stored as scaled integers. Most readers apply the scaling
and the fill value on read. The [collection README](goes-18-fdcc/README.md#traps)
says how to get the raw integers.

Each scan also has NOAA's own summary values, stored as variables along
`time`. They include the number of fire pixels and the outlier counts. They
also include the minimum, maximum, mean and standard deviation of fire
temperature, area and radiative power. The
collection has no statistics of its own, because they would change with every
scan the cube gains.

### Fire mask codes

`Mask` assigns each pixel one code. The codes and names come from the
`flag_values` and `flag_meanings` attributes in the file.

| Codes      | Meaning                                                                              |
| ---------- | ------------------------------------------------------------------------------------ |
| 0          | Unprocessed pixel                                                                    |
| 10         | Good fire pixel                                                                      |
| 11         | Saturated fire pixel                                                                 |
| 12         | Cloud-contaminated fire pixel                                                        |
| 13, 14, 15 | High, medium and low probability fire pixel                                          |
| 30 to 35   | The same six fire categories as 10 to 15, temporally filtered                        |
| 40         | Off-earth pixel                                                                      |
| 50         | Local zenith angle block-out zone                                                    |
| 60         | Solar zenith angle or sun glint block-out zone                                       |
| 100        | Processed pixel, no fire                                                             |
| 120 to 127 | Missing, saturated, invalid or below-threshold input radiance at 3.89 µm or 11.19 µm |
| 150 to 153 | Surface type not processed: sea water, coastline, inland water, bright desert        |
| 170 to 188 | No background value, or a conversion or fire-retrieval computation failed            |
| 200 to 245 | Cloud, detected by one of ten threshold tests                                        |

The file lists one name for each of the 45 codes. A fire pixel is a code from 10
to 15 or from 30 to 35.

### Data quality flag

| `DQF` | Meaning                                                                                     |
| ----- | ------------------------------------------------------------------------------------------- |
| 0     | Good quality fire pixel                                                                     |
| 1     | Good quality fire-free land pixel                                                           |
| 2     | Invalid, opaque cloud                                                                       |
| 3     | Invalid, surface type, sun glint, local zenith angle threshold, off earth, or missing input |
| 4     | Invalid, bad input data                                                                     |
| 5     | Invalid, algorithm failure                                                                  |

## Time

The `time` coordinate is the `t` value in each file. It falls in the middle of
the scan, between the start and end stamps in the file name. When a file's `t`
is missing or not usable, `time` is the midpoint of the file-name stamps.

NOAA's bucket can have gaps where no file exists for a scan. The cube has no
time step for a missing scan, so the spacing along `time` is not always 5
minutes.

## License

**CC0-1.0.** NOAA releases the data that its Open Data Dissemination (NODD)
program distributes, including the `noaa-goes18` bucket, under the
[Creative Commons CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).
NODD states that this license applies to each NOAA dataset it makes available
([NODD license text](https://registry.opendata.aws/noaa-ghcnh/)). The GOES
registry page says the data "can be used as desired".

NOAA also makes these requests:

- Attribute unaltered NOAA data to NOAA.
- Do not state or imply endorsement by or affiliation with NOAA.
- Do not present modified NOAA data as original, unaltered NOAA data.

## Provenance

Every scan comes from the `ABI-L2-FDCC` prefix of the `noaa-goes18` bucket,
listed in the
[AWS Registry of Open Data](https://registry.opendata.aws/noaa-goes/). Nothing
is resampled, reprojected, filtered or reclassified. The cube keeps NOAA's grid,
chunks, compression, codes, scaling and fill values. The cube includes the pixel
variables and the per-scan summary values in the files.

The methods are in the repository
[design document](https://github.com/mmidzik/goes-fdc-catalog/blob/main/docs/architecture.md).
The update workflow has not run yet.

## Access

Open the Icechunk repository with `icechunk`, `zarr` and `xarray`, and authorize
NOAA's bucket as a virtual chunk container. The tested recipe is in the
[collection README](goes-18-fdcc/README.md#access). For a worked example that
starts from this catalog, see `examples/palisades-frp.ipynb` in the
[source repository](https://github.com/mmidzik/goes-fdc-catalog).

The Zarr asset is outside the Portolan conformance surface. The Portolan
specification defers Zarr support until real Zarr datasets have been tested in
catalogs
([portolan-spec#132](https://github.com/portolan-sdi/portolan-spec/issues/132)).
This catalog is one of those test cases.

## Catalog structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here have no `self` link, so a client tracks its own location. The
data assets use absolute `https` hrefs built from the public base URL.
