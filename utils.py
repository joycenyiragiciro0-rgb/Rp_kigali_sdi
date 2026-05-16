import os
import zipfile
import json
import tempfile
import shutil
import uuid
import geopandas as gpd
from werkzeug.utils import secure_filename
import fiona
from shapely.geometry import shape
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')


def allowed_upload_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in {'shp', 'dbf', 'shx', 'prj', 'cpg', 'zip', 'geojson'}


def _find_shapefile_path(directory):
    for root, _, files in os.walk(directory):
        for fname in files:
            if fname.lower().endswith('.shp'):
                return os.path.join(root, fname)
    return None


def _safe_read_shapefile(shp_path):
    """
    Safely read shapefile by iterating features with Fiona directly,
    bypassing geopandas/numpy dtype inference entirely.
    Tries multiple encodings to handle different file formats.
    """
    print(f"[SHAPEFILE READER] Attempting safe read: {shp_path}", flush=True)

    for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'cp1250', 'macroman']:
        try:
            print(f"[SHAPEFILE READER] Trying encoding: {encoding}", flush=True)
            with fiona.open(shp_path, encoding=encoding) as src:
                crs = src.crs
                schema_props = src.schema.get('properties', {})
                print(f"[SHAPEFILE READER] Schema properties: {schema_props}", flush=True)

                # Only keep fields with non-empty names
                valid_fields = [f for f in schema_props if f and f.strip()]
                print(f"[SHAPEFILE READER] Valid fields: {valid_fields}", flush=True)

                rows = []
                geometries = []
                skipped = 0

                for feat in src:
                    try:
                        geom = shape(feat['geometry'])
                        props = feat.get('properties') or {}
                        row = {
                            k: ('' if props.get(k) is None else str(props[k]))
                            for k in valid_fields
                        }
                        rows.append(row)
                        geometries.append(geom)
                    except Exception as feat_err:
                        skipped += 1
                        print(f"[SHAPEFILE READER] Skipping feature: {feat_err}", flush=True)

                print(f"[SHAPEFILE READER] Read {len(rows)} features, skipped {skipped}", flush=True)

                if not rows:
                    raise ValueError("No valid features found in shapefile")

                # Build GeoDataFrame manually — never passes through numpy dtype inference
                df = pd.DataFrame(rows)
                gdf = gpd.GeoDataFrame(df, geometry=geometries, crs=crs)
                print(f"[SHAPEFILE READER] GeoDataFrame created successfully", flush=True)
                return gdf

        except Exception as e:
            print(f"[SHAPEFILE READER] Failed with {encoding}: {type(e).__name__}: {e}", flush=True)
            continue

    raise ValueError(
        "Could not read shapefile with any encoding. "
        "The file may be corrupted, have blank field names, or unsupported data types."
    )


def _read_shapefile_safe(shp_path):
    """
    Try geopandas first; fall back to fiona-based safe reader if it raises
    anything related to dtype interpretation (numpy '' error and friends).
    """
    DTYPE_ERRORS = (
        "cannot interpret",
        "data type",
        "dtype",
        "could not convert",
        "unsupported",
    )
    try:
        gdf = gpd.read_file(shp_path)
        print(f"[CONVERTER] Standard gpd.read_file succeeded", flush=True)
        return gdf
    except Exception as e:
        msg = str(e).lower()
        print(f"[CONVERTER] Standard read failed ({type(e).__name__}): {e}", flush=True)
        # Always fall back — don't try to guess whether it's the dtype error
        print(f"[CONVERTER] Falling back to safe Fiona reader...", flush=True)
        return _safe_read_shapefile(shp_path)


def clean_geodataframe(gdf):
    """
    Convert all non-geometry columns to plain numpy object (str) dtype.
    Pandas 2.x uses StringDtype by default which fiona cannot infer a schema
    for — explicitly casting to object fixes the 'Cannot interpret StringDtype'
    error from gdf.to_file().
    """
    cols_to_drop = []
    for col in gdf.columns:
        if col == 'geometry':
            continue
        try:
            # Step 1: convert values to plain Python strings
            cleaned = gdf[col].apply(
                lambda v: '' if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
            )
            # Step 2: force numpy object dtype — this is what fiona expects
            gdf[col] = cleaned.astype(object)
        except Exception as e:
            print(f"[CLEANER] Dropping column '{col}': {e}", flush=True)
            cols_to_drop.append(col)
    if cols_to_drop:
        gdf = gdf.drop(columns=cols_to_drop)
    return gdf


def convert_shapefile_upload_to_geojson(upload_dir, original_filename, upload_folder):
    """
    Handle shapefile (bare components, ZIP) and GeoJSON uploads.
    Returns (dest_path, feature_count, geometry_type).
    """
    print(f"\n[CONVERTER] Processing: {original_filename}", flush=True)
    print(f"[CONVERTER] Files in upload dir: {os.listdir(upload_dir)}", flush=True)

    # ── GeoJSON upload ────────────────────────────────────────────────────
    if original_filename.lower().endswith('.geojson'):
        print(f"[CONVERTER] Detected GeoJSON", flush=True)

        geojson_file = next(
            (os.path.join(upload_dir, f) for f in os.listdir(upload_dir) if f.lower().endswith('.geojson')),
            None
        )
        if not geojson_file:
            raise ValueError('No .geojson file found in upload directory')

        try:
            with open(geojson_file, 'r') as f:
                geojson_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f'Invalid GeoJSON: {e}')

        if not isinstance(geojson_data, dict) or 'features' not in geojson_data:
            raise ValueError('GeoJSON must be a FeatureCollection')
        if not geojson_data.get('features'):
            raise ValueError('GeoJSON contains no features')

        try:
            gdf = gpd.read_file(geojson_file)
        except Exception as e:
            raise ValueError(f'Could not read GeoJSON: {e}')

        if gdf.empty:
            raise ValueError('GeoJSON file has no valid features')

        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326')
        else:
            gdf = gdf.to_crs('EPSG:4326')
        gdf = clean_geodataframe(gdf)

        base_name = secure_filename(os.path.splitext(original_filename)[0]) or f'upload_{uuid.uuid4().hex}'
        dest_path = os.path.join(upload_folder, f'{uuid.uuid4().hex}_{base_name}.geojson')
        gdf.to_file(dest_path, driver='GeoJSON')
        print(f"[CONVERTER] Saved to: {dest_path}", flush=True)

        feature_count = len(gdf)
        geometry_type = gdf.geom_type.iloc[0] if feature_count > 0 else 'Unknown'
        return dest_path, feature_count, geometry_type

    # ── Shapefile / ZIP upload ────────────────────────────────────────────
    print(f"[CONVERTER] Detected shapefile", flush=True)

    # Extract any ZIP archives first
    for fname in os.listdir(upload_dir):
        if fname.lower().endswith('.zip'):
            print(f"[CONVERTER] Extracting ZIP: {fname}", flush=True)
            with zipfile.ZipFile(os.path.join(upload_dir, fname), 'r') as zf:
                zf.extractall(upload_dir)
            print(f"[CONVERTER] After extract: {os.listdir(upload_dir)}", flush=True)

    shp_path = _find_shapefile_path(upload_dir)
    if not shp_path:
        raise ValueError('No .shp file found in uploaded package')

    print(f"[CONVERTER] Found shapefile: {shp_path}", flush=True)

    gdf = _read_shapefile_safe(shp_path)

    if gdf.empty:
        raise ValueError('Uploaded shapefile contains no features')

    print(f"[CONVERTER] {len(gdf)} features loaded", flush=True)

    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:4326')
    else:
        gdf = gdf.to_crs('EPSG:4326')

    gdf = clean_geodataframe(gdf)

    base_name = secure_filename(os.path.splitext(original_filename)[0]) or f'upload_{uuid.uuid4().hex}'
    dest_path = os.path.join(upload_folder, f'{uuid.uuid4().hex}_{base_name}.geojson')
    gdf.to_file(dest_path, driver='GeoJSON')
    print(f"[CONVERTER] Saved to: {dest_path}", flush=True)

    feature_count = len(gdf)
    geometry_type = gdf.geom_type.iloc[0] if feature_count > 0 else 'Unknown'
    print(f"[CONVERTER] Done: {feature_count} features, type: {geometry_type}", flush=True)
    return dest_path, feature_count, geometry_type


def get_layer_statistics(geojson_path):
    """Read a saved GeoJSON and return basic stats. Never crashes on bad dtypes."""
    try:
        gdf = gpd.read_file(geojson_path)
    except Exception as e:
        print(f"[STATS] Could not read {geojson_path}: {e}", flush=True)
        return {'feature_count': 0, 'geometry_type': 'Unknown',
                'total_length_m': None, 'total_area_m2': None}

    stats = {
        'feature_count': len(gdf),
        'geometry_type': gdf.geom_type.iloc[0] if len(gdf) > 0 else 'Unknown',
        'total_length_m': None,
        'total_area_m2': None,
    }

    if len(gdf) > 0:
        geom_type = stats['geometry_type']
        try:
            if geom_type in ('LineString', 'MultiLineString'):
                gdf_proj = gdf.to_crs('EPSG:32736')
                stats['total_length_m'] = float(gdf_proj.geometry.length.sum())
            elif geom_type in ('Polygon', 'MultiPolygon'):
                gdf_proj = gdf.to_crs('EPSG:32736')
                stats['total_area_m2'] = float(gdf_proj.geometry.area.sum())
        except Exception as e:
            print(f"[STATS] Projection error: {e}", flush=True)

    return stats


def search_features_across_layers(layers, query_text):
    results = []
    for layer in layers:
        try:
            with open(layer.geojson_path, 'r') as f:
                data = json.load(f)
            for feature in data.get('features', []):
                props = feature.get('properties') or {}
                for value in props.values():
                    if isinstance(value, str) and query_text.lower() in value.lower():
                        results.append({
                            'layer_name': layer.name,
                            'layer_id': layer.id,
                            'feature': feature,
                        })
                        break
        except Exception as e:
            print(f"[SEARCH] Error searching layer {layer.id}: {e}", flush=True)
    return results


def geojson_to_shapefile_zip(geojson_path):
    gdf = gpd.read_file(geojson_path)
    temp_dir = tempfile.mkdtemp()
    shp_path = os.path.join(temp_dir, 'output.shp')
    gdf.to_file(shp_path, driver='ESRI Shapefile')

    zip_path = os.path.join(temp_dir, 'shapefile_export.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
            candidate = shp_path.replace('.shp', ext)
            if os.path.exists(candidate):
                zf.write(candidate, f'campus_data{ext}')
    return zip_path