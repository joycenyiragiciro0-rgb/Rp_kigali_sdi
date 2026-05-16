import os
import zipfile
import json
import tempfile
import shutil
import uuid
from werkzeug.utils import secure_filename


def allowed_upload_file(filename):
    """Only allow GeoJSON files for simplified deployment"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in {'geojson', 'json'}


def convert_shapefile_upload_to_geojson(upload_dir, original_filename, upload_folder):
    """
    Simplified: Only handle GeoJSON files. For shapefiles, users should convert them offline.
    """
    geojson_file = None
    for fname in os.listdir(upload_dir):
        if fname.lower().endswith(('.geojson', '.json')):
            geojson_file = fname
            break
    
    if not geojson_file:
        raise Exception("Please upload a GeoJSON file directly. Shapefile conversion is not supported on this deployment.")
    
    geojson_path = os.path.join(upload_dir, geojson_file)
    
    # Validate GeoJSON
    try:
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
    except Exception as e:
        raise Exception(f"Invalid GeoJSON: {str(e)}")
    
    # Save to uploads folder
    filename = secure_filename(f"{uuid.uuid4()}_{geojson_file}")
    dest_path = os.path.join(upload_folder, filename)
    shutil.copy(geojson_path, dest_path)
    
    # Count features
    feature_count = len(geojson_data.get('features', []))
    geometry_type = 'Unknown'
    if feature_count > 0:
        first_feature = geojson_data['features'][0]
        geometry_type = first_feature.get('geometry', {}).get('type', 'Unknown')
    
    return dest_path, feature_count, geometry_type


def get_layer_statistics(geojson_path):
    """Get basic statistics from GeoJSON file"""
    stats = {
        'feature_count': 0,
        'geometry_type': 'Unknown',
        'total_length_m': 0,
        'total_area_m2': 0
    }
    
    try:
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
        
        features = geojson_data.get('features', [])
        stats['feature_count'] = len(features)
        
        if features:
            stats['geometry_type'] = features[0].get('geometry', {}).get('type', 'Unknown')
    
    except Exception as e:
        print(f"[STATS] Error reading {geojson_path}: {e}", flush=True)
    
    return stats


def geojson_to_shapefile_zip(geojson_path):
    """
    Simplified: Not supported on this deployment.
    Users should download GeoJSON directly instead.
    """
    raise NotImplementedError("Shapefile export is not available. Please download GeoJSON format instead.")


def search_features_across_layers(layers, query_text):
    """Search for features by property values"""
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
