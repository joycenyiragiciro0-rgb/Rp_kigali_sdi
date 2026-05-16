from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    layers = db.relationship('Layer', backref='owner', lazy=True)

    @property
    def is_admin(self):
        return (getattr(self, 'role', None) == 'admin') or (self.username == 'admin')

class Layer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    layer_type = db.Column(db.String(50))  # roads, buildings, utilities, etc.
    geojson_path = db.Column(db.String(300), nullable=False)
    feature_count = db.Column(db.Integer, default=0)
    geometry_type = db.Column(db.String(50))  # Point, LineString, Polygon
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'layer_type': self.layer_type,
            'feature_count': self.feature_count,
            'geometry_type': self.geometry_type,
            'created_at': self.created_at.isoformat(),
            'geojson_url': f'/api/layers/{self.id}/geojson'
        }