from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text
import os
import json
import tempfile
import shutil

from config import Config
from models import db, User, Layer
from utils import get_layer_statistics, search_features_across_layers, geojson_to_shapefile_zip, allowed_upload_file, convert_shapefile_upload_to_geojson

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables and directories
with app.app_context():
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('instance', exist_ok=True)

    # Ensure the User table has a role column for role-based access control
    engine = db.get_engine()
    inspector = inspect(engine)
    if 'user' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('user')]
        if 'role' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))

# Sample initial data for RP Kigali College
def create_sample_data():
    if Layer.query.count() == 0:
        # Sample roads
        roads_geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[30.078, -1.950], [30.082, -1.948], [30.085, -1.951]]}, "properties": {"name": "Main Road", "type": "Asphalt", "length_m": 450}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[30.080, -1.952], [30.083, -1.950]]}, "properties": {"name": "Campus Drive", "type": "Concrete", "length_m": 320}}
            ]
        }
        roads_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_roads.geojson')
        with open(roads_path, 'w') as f:
            json.dump(roads_geojson, f)
        
        roads_layer = Layer(name="Campus Roads", description="Main roads and pathways", layer_type="roads",
                           geojson_path=roads_path, feature_count=2, geometry_type="LineString", user_id=1)
        
        # Sample buildings
        buildings_geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[30.079, -1.949], [30.080, -1.949], [30.080, -1.950], [30.079, -1.950], [30.079, -1.949]]]}, "properties": {"name": "Main Admin", "floors": 3, "use": "Administration"}},
                {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[30.081, -1.950], [30.082, -1.950], [30.082, -1.951], [30.081, -1.951], [30.081, -1.950]]]}, "properties": {"name": "Library", "floors": 2, "use": "Academic"}}
            ]
        }
        buildings_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_buildings.geojson')
        with open(buildings_path, 'w') as f:
            json.dump(buildings_geojson, f)
        
        buildings_layer = Layer(name="Building Footprints", description="Campus buildings", layer_type="buildings",
                               geojson_path=buildings_path, feature_count=2, geometry_type="Polygon", user_id=1)
        
        # Sample utilities
        utilities_geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0795, -1.9495]}, "properties": {"type": "Electrical Substation", "capacity": "500kVA"}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0815, -1.9505]}, "properties": {"type": "Drainage Outlet", "status": "Active"}}
            ]
        }
        utilities_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_utilities.geojson')
        with open(utilities_path, 'w') as f:
            json.dump(utilities_geojson, f)
        
        utilities_layer = Layer(name="Utilities", description="Electrical and drainage infrastructure", layer_type="utilities",
                               geojson_path=utilities_path, feature_count=2, geometry_type="Point", user_id=1)
        
        # Create default admin user if not exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@rpkigali.edu.rw', password_hash=generate_password_hash('admin123'), role='admin')
            db.session.add(admin)
            db.session.commit()
        elif admin.role != 'admin':
            admin.role = 'admin'
            db.session.commit()

        roads_layer.user_id = admin.id
        buildings_layer.user_id = admin.id
        utilities_layer.user_id = admin.id
# Routes
@app.route('/')
def index():
    return render_template('index.html')

# Authentication API Endpoints
def admin_required(func):
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        is_admin = False
        try:
            is_admin = current_user.is_admin
        except Exception:
            is_admin = current_user.username == 'admin'
        if not is_admin:
            return jsonify({'error': 'Admin permissions required'}), 403
        return func(*args, **kwargs)
    return wrapper

@app.route('/api/auth/status')
def auth_status():
    is_admin = False
    if current_user.is_authenticated:
        try:
            is_admin = current_user.is_admin
        except Exception:
            is_admin = current_user.username == 'admin'
    return jsonify({
        'authenticated': current_user.is_authenticated,
        'username': current_user.username if current_user.is_authenticated else None,
        'is_admin': is_admin
    })

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid username or password'}), 401

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    
    user = User(username=username, email=email, password_hash=generate_password_hash(password), role='user')
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Registration successful! Please login.'})

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def api_logout():
    logout_user()
    return jsonify({'success': True})

@app.route('/api/layers')
def get_layers():
    layers = Layer.query.all()
    return jsonify([layer.to_dict() for layer in layers])

@app.route('/api/layers/<int:layer_id>/geojson')
def get_layer_geojson(layer_id):
    layer = Layer.query.get_or_404(layer_id)
    
    # Check if file exists
    if not os.path.exists(layer.geojson_path):
        # Return empty FeatureCollection if file not found
        return jsonify({
            "type": "FeatureCollection",
            "features": []
        }), 404
    
    return send_file(layer.geojson_path, mimetype='application/geo+json')

@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_layer():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': 'No files uploaded'}), 400

    if not any(f.filename for f in files):
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    print(f"\n[UPLOAD] Files received: {[f.filename for f in files]}", flush=True)
    
    for f in files:
        if not allowed_upload_file(f.filename):
            return jsonify({'success': False, 'error': 'Only shapefile components, GeoJSON, or zip archives are accepted'}), 400

    name = request.form.get('name', '').strip() or 'Uploaded Layer'
    description = request.form.get('description', '').strip()
    layer_type = request.form.get('layer_type', 'general')

    temp_dir = tempfile.mkdtemp()
    print(f"[UPLOAD] Temp directory: {temp_dir}", flush=True)
    
    try:
        for f in files:
            filename = secure_filename(f.filename)
            if filename:
                path = os.path.join(temp_dir, filename)
                f.save(path)
                print(f"[UPLOAD] Saved file: {path}", flush=True)

        print(f"[UPLOAD] Converting files to GeoJSON...", flush=True)
        geojson_path, feature_count, geometry_type = convert_shapefile_upload_to_geojson(
            temp_dir, files[0].filename, app.config['UPLOAD_FOLDER']
        )
        print(f"[UPLOAD] Conversion successful: {geojson_path}, features: {feature_count}", flush=True)

        layer = Layer(
            name=name,
            description=description,
            layer_type=layer_type,
            geojson_path=geojson_path,
            feature_count=feature_count,
            geometry_type=geometry_type,
            user_id=current_user.id
        )
        db.session.add(layer)
        db.session.commit()
        print(f"[UPLOAD] Layer saved to database: {layer.id}", flush=True)
        return jsonify({'success': True, 'layer': layer.to_dict()})
    except Exception as e:
        import traceback
        print(f"\n[UPLOAD ERROR] {type(e).__name__}: {str(e)}", flush=True)
        traceback.print_exc()
        return jsonify({'success': False, 'error': f"{type(e).__name__}: {str(e)}"}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[UPLOAD] Cleaned up temp directory", flush=True)

@app.route('/api/layers/<int:layer_id>/download')
@login_required
def download_layer(layer_id):
    layer = Layer.query.get_or_404(layer_id)
    
    format_type = request.args.get('format', 'geojson')
    if format_type == 'shapefile':
        zip_path = geojson_to_shapefile_zip(layer.geojson_path)
        return send_file(zip_path, as_attachment=True, download_name=f'{layer.name}_shapefile.zip')
    else:
        return send_file(layer.geojson_path, as_attachment=True, download_name=f'{layer.name}.geojson')

@app.route('/api/layers/<int:layer_id>', methods=['DELETE'])
@admin_required
def delete_layer(layer_id):
    layer = Layer.query.get_or_404(layer_id)
    
    # Delete file
    if os.path.exists(layer.geojson_path):
        os.remove(layer.geojson_path)
    
    db.session.delete(layer)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/search')
def search():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({'features': [], 'total': 0})
    
    layers = Layer.query.all()
    results = search_features_across_layers(layers, query)
    
    # Return detailed feature data with layer info
    features = []
    for result in results:
        props = result['feature'].get('properties', {}) or {}
        feature_id = props.get('__fid') or props.get('id')
        if feature_id is None:
            feature_id = len(features)
        feature_data = {
            'feature': result['feature'],
            'layer_id': result['layer_id'],
            'layer_name': result['layer_name'],
            'feature_id': feature_id
        }
        features.append(feature_data)
    
    return jsonify({'features': features, 'total': len(features)})

@app.route('/api/feature/download', methods=['POST'])
@login_required
def download_feature():
    """Download selected feature(s) as GeoJSON"""
    data = request.json
    features = data.get('features', [])
    
    if not features:
        return jsonify({'error': 'No features selected'}), 400
    
    # Create FeatureCollection
    feature_collection = {
        'type': 'FeatureCollection',
        'features': features
    }
    
    return jsonify(feature_collection)

@app.route('/api/dashboard/stats')
def dashboard_stats():
    layers = Layer.query.all()
    stats = []
    for layer in layers:
        layer_stats = get_layer_statistics(layer.geojson_path)
        stats.append({
            'id': layer.id,
            'name': layer.name,
            'layer_type': layer.layer_type,
            'feature_count': layer_stats['feature_count'],
            'geometry_type': layer_stats['geometry_type'],
            'total_length_m': layer_stats['total_length_m'],
            'total_area_m2': layer_stats['total_area_m2']
        })
    
    # Summary statistics
    total_features = sum(s['feature_count'] for s in stats)
    total_roads_length = sum(s.get('total_length_m') or 0 for s in stats if s['layer_type'] == 'roads')
    total_buildings_area = sum(s.get('total_area_m2') or 0 for s in stats if s['layer_type'] == 'buildings')
    
    return jsonify({
        'layers': stats,
        'summary': {
            'total_layers': len(layers),
            'total_features': total_features,
            'total_roads_km': total_roads_length / 1000,
            'total_buildings_m2': total_buildings_area
        }
    })

# Initialize sample data after app context
with app.app_context():
    create_sample_data()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)