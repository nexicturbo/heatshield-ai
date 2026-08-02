# Data sources and provenance

HeatShield preserves source boundaries. Official forecasts are not relabeled as
model output, demographic context is not used as a medical prediction, and
facility listings are not treated as live operating status.

## NOAA/NCEI Global Hourly

- Stations: O'Hare `72530094846`, Midway `72534014819`
- Warm season: May 1 through September 30, 2015–2025
- Fields: `DATE`, `STATION`, `TMP`, `DEW`, `WND`
- API documentation:
  <https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation>
- Heat-index method and limitations:
  <https://www.weather.gov/tbw/heatindex>
- NOAA use policy: <https://sos.noaa.gov/copyright/>

The pipeline rejects missing sentinels and invalid quality flags, computes
relative humidity from temperature and dew point, and retains the validity
limits of the NWS Rothfusz heat-index procedure.

## National Weather Service API

- Point metadata: <https://api.weather.gov/points/41.8781,-87.6298>
- Documentation: <https://www.weather.gov/documentation/services-web-api>
- Active point alerts:
  <https://api.weather.gov/alerts/active?point=41.8781,-87.6298>

The runtime re-resolves the point/grid mapping as needed, sends an identifying
User-Agent, caches successful responses for up to 15 minutes (and failures only
briefly), and shows when the current request was checked.

## CDC/ATSDR Social Vulnerability Index 2022

- Layer documentation:
  <https://onemap.cdc.gov/OneMapServices/rest/services/SVI/CDC_ATSDR_Social_Vulnerability_Index_2022_USA/MapServer/2>
- Scope: Cook County (`STCNTY = 17031`), 1,331 tract records
- Vintage: 2018–2022 ACS estimates
- Documentation:
  <https://atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html>
- Material policy: <https://www.cdc.gov/other/agencymaterials.html>

Three tracts contain the documented `-999` unavailable sentinel across
percentage and percentile fields. HeatShield excludes those values rather than
coercing them to zero.

## Census TIGER/Line 2022 tracts

- Illinois tract geometry:
  <https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_17_tract.zip>
- Citation policy: <https://www.census.gov/about/policies/citation.html>

Cook County tracts are filtered with `COUNTYFP = 031` and joined from `GEOID` to
SVI `FIPS`.

## City of Chicago community-area boundaries

- Dataset ID: `igwz-8jzy`
- GeoJSON endpoint:
  <https://data.cityofchicago.org/resource/igwz-8jzy.geojson?$limit=100>
- Metadata: <https://data.cityofchicago.org/api/views/igwz-8jzy>

The snapshot contains the 77 official community-area geometries used to group
the tract-intersection access estimates shown in the interface.

## City of Chicago cooling resources

- Dataset ID: `msrk-w9ih`
- Dataset page: <https://data.cityofchicago.org/d/msrk-w9ih>
- Official map and operating caveat:
  <https://data.cityofchicago.org/Health-Human-Services/Cooling-Centers-Map/cj7n-sh49>
- Data Portal FAQ and terms:
  <https://data.cityofchicago.org/stories/s/Data-Portal-FAQ/iy9c-7e89/>

The snapshot retrieved 287 unique records on 2026-08-02. All 287 points parsed
inside Chicago-area coordinate bounds. Hours were absent for 132 records; ZIP
and phone were absent for 110 records. These nulls are retained in the audit
artifact. The interface labels availability as unverified, warns that hours and
activation can change, and directs users to call 311.

## Snapshot controls

Together, the geospatial and NOAA manifests, geospatial validation report, and
model evaluation record, as available for each source:

- request URL and, for the geospatial downloads, final URL;
- retrieval timestamp in UTC;
- selected HTTP metadata (`ETag`, `Last-Modified`, `Content-Length` where
  available);
- byte size and SHA-256;
- row counts and source-specific schema or season metadata; and
- validation evidence for sentinels, coordinates, duplicates, key integrity,
  joins, and model data quality where applicable.

Both manifests set a per-file download cap of 104,857,600 bytes. Source
documentation, attribution, and terms links are listed above. The committed
audit artifacts are the [geospatial manifest](public/data/geo_manifest.json),
[geospatial validation report](public/data/validation_report.json), [NOAA data
manifest](model/data-manifest.json), and [model evaluation
JSON](model/artifacts/heatshield-model-evaluation.json).

## Redistribution and license boundary

The MIT license applies to HeatShield's original source code and documentation.
It does not replace the terms that apply to source records embedded in, or
represented by, committed data snapshots and derived artifacts.

- NOAA-origin data is generally not copyrighted, but NOAA requests attribution
  and prohibits implying agency endorsement. HeatShield identifies NOAA as the
  source and makes no endorsement claim.
- Most CDC/ATSDR material is public domain unless marked otherwise. The SVI
  source is available from CDC/ATSDR at no charge. HeatShield attributes
  CDC/ATSDR, does not imply endorsement, and clearly labels its joins,
  calculations, and conclusions as project-derived.
- Census TIGER/Line geometry is attributed to the U.S. Census Bureau. Any
  estimates produced from it are HeatShield's responsibility.
- The City of Chicago dataset metadata for `msrk-w9ih` and `igwz-8jzy` says
  `SEE_TERMS_OF_USE`. HeatShield selects fields, normalizes missing values,
  deduplicates cooling-resource records, validates and rounds coordinates,
  assigns deterministic project IDs, joins resources to community areas, and
  uses community geometry in derived coverage estimates. Those modifications
  are recorded in the geospatial manifest and validation report.

The City of Chicago requires the following notice for applications using
modified City data:

> This site provides applications using data that has been modified for use
> from its original source, www.cityofchicago.org, the official website of the
> City of Chicago. The City of Chicago makes no claims as to the content,
> accuracy, timeliness, or completeness of any of the data provided at this
> site. The data provided at this site is subject to change at any time. It is
> understood that the data provided at this site is being used at one's own
> risk.
