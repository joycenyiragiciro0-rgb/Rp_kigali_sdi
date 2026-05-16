let map;
let layers = {};
let currentLayerObjects = {};

function initMap() {
    map = L.map('map').setView([-1.9495, 30.081], 17);
    
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; CartoDB',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);
    
    // Add scale bar
    L.control.scale({metric: true, imperial: false}).addTo(map);
}

async function loadLayers() {
    const response = await fetch('/api/layers');
    const layerData = await response.json();
    
    const layerListDiv = document.getElementById('layerList');
    layerListDiv.innerHTML = '';
    
    // Clear existing layers from map
    for (let key in currentLayerObjects) {
        if (currentLayerObjects[key]) {
            map.removeLayer(currentLayerObjects[key]);
        }
    }
    currentLayerObjects = {};
    
    for (const layer of layerData) {
        // Create GeoJSON layer
        const geojsonUrl = `/api/layers/${layer.id}/geojson`;
        const layerStyle = getStyleForLayerType(layer.layer_type);
        const geoJsonLayer = L.geoJSON(null, {
            onEachFeature: (feature, fl) => {
                fl.on('click', () => {
                    showAttributes(feature.properties, fl.feature.geometry.type);
                });
                const title = feature.properties && feature.properties.name ? feature.properties.name : layer.name;
                fl.bindPopup(`<b>${title}</b><br>Type: ${layer.layer_type}`);
            },
            style: layerStyle,
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
                radius: 6,
                color: layerStyle.color,
                fillColor: layerStyle.color,
                fillOpacity: 0.8,
                weight: 2
            })
        });
        
        // Fetch and add GeoJSON data
        const geoJsonResponse = await fetch(geojsonUrl);
        const geoJsonData = await geoJsonResponse.json();
        geoJsonLayer.addData(geoJsonData);
        
        // Store for toggle
        currentLayerObjects[layer.id] = geoJsonLayer;
        
        // Create UI control
        const layerItem = document.createElement('div');
        layerItem.className = 'list-group-item list-group-item-action layer-item';
        layerItem.innerHTML = `
            <div class="layer-control">
                <div>
                    <i class="fas ${getIconForLayerType(layer.layer_type)}"></i>
                    <strong>${layer.name}</strong>
                    <span class="badge bg-secondary layer-badge">${layer.feature_count} features</span>
                </div>
                <div>
                    <button class="btn btn-sm btn-outline-danger delete-layer" data-id="${layer.id}" title="Delete Layer">
                        <i class="fas fa-trash"></i>
                    </button>
                    <div class="form-check form-switch d-inline-block ms-2">
                        <input class="form-check-input layer-toggle" type="checkbox" data-id="${layer.id}" checked>
                    </div>
                </div>
            </div>
            <small class="text-muted">${layer.layer_type} | ${layer.geometry_type}</small>
        `;
        
        const toggle = layerItem.querySelector('.layer-toggle');
        toggle.addEventListener('change', (e) => {
            if (e.target.checked) {
                currentLayerObjects[layer.id].addTo(map);
            } else {
                map.removeLayer(currentLayerObjects[layer.id]);
            }
        });
        
        const deleteBtn = layerItem.querySelector('.delete-layer');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (confirm(`Delete layer "${layer.name}"?`)) {
                    const response = await fetch(`/api/layers/${layer.id}`, { method: 'DELETE' });
                    if (response.ok) {
                        loadLayers(); // Reload all layers
                    } else {
                        alert('Failed to delete layer');
                    }
                }
            });
        }
        
        layerListDiv.appendChild(layerItem);
        
        // Add to map by default
        geoJsonLayer.addTo(map);
    }
    
    // Fit map to bounds if any layers exist
    if (Object.keys(currentLayerObjects).length > 0) {
        const allBounds = L.featureGroup(Object.values(currentLayerObjects)).getBounds();
        if (allBounds.isValid()) {
            map.fitBounds(allBounds);
        }
    }
}

function getStyleForLayerType(type) {
    switch(type) {
        case 'roads':
            return { color: '#ff7800', weight: 4, opacity: 0.8 };
        case 'buildings':
            return { color: '#3388ff', weight: 2, fillColor: '#66ccff', fillOpacity: 0.5 };
        case 'utilities':
            return { color: '#ff3333', weight: 6, radius: 6, fillColor: '#ff6666', fillOpacity: 0.8 };
        case 'drainage':
            return { color: '#33cc33', weight: 3 };
        default:
            return { color: '#888888', weight: 2, fillOpacity: 0.3 };
    }
}

function getIconForLayerType(type) {
    switch(type) {
        case 'roads': return 'fa-road';
        case 'buildings': return 'fa-building';
        case 'utilities': return 'fa-bolt';
        case 'drainage': return 'fa-water';
        default: return 'fa-map-marker-alt';
    }
}

function showAttributes(properties, geometryType) {
    const panel = document.getElementById('infoPanel');
    const content = document.getElementById('attributesContent');
    
    let html = '<table class="attribute-table">';
    for (let [key, value] of Object.entries(properties)) {
        if (value !== null && value !== undefined) {
            html += `<tr><td><strong>${key}:</strong></td><td>${value}</td></tr>`;
        }
    }
    html += `<tr><td><strong>Geometry:</strong></td><td>${geometryType}</td></tr>`;
    html += '</table>';
    
    content.innerHTML = html;
    panel.style.display = 'block';
    
    // Auto hide after 10 seconds
    clearTimeout(window.panelTimeout);
    window.panelTimeout = setTimeout(() => {
        panel.style.display = 'none';
    }, 10000);
}

async function searchFeatures(query) {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    
    const resultsDiv = document.getElementById('searchResults');
    if (data.total === 0) {
        resultsDiv.innerHTML = '<div class="text-muted">No features found</div>';
        resultsDiv.style.display = 'block';
        return;
    }
    
    let html = `<strong>Found ${data.total} features:</strong><br>`;
    for (const [layerName, features] of Object.entries(data.results)) {
        html += `<div class="mt-1"><b>${layerName}:</b> ${features.length} features</div>`;
        features.slice(0, 3).forEach(f => {
            const name = f.properties.name || f.properties.type || 'Feature';
            html += `<div class="search-result-item" onclick="zoomToFeature(${JSON.stringify(f.geometry)})">${name}</div>`;
        });
        if (features.length > 3) html += `<div class="small text-muted">+${features.length-3} more</div>`;
    }
    resultsDiv.innerHTML = html;
    resultsDiv.style.display = 'block';
}

function zoomToFeature(geometry) {
    let latlngs = [];
    if (geometry.type === 'Point') {
        latlngs = [geometry.coordinates[1], geometry.coordinates[0]];
        map.setView(latlngs, 19);
    } else if (geometry.type === 'LineString') {
        latlngs = geometry.coordinates.map(c => [c[1], c[0]]);
        map.fitBounds(L.latLngBounds(latlngs));
    } else if (geometry.type === 'Polygon') {
        latlngs = geometry.coordinates[0].map(c => [c[1], c[0]]);
        map.fitBounds(L.latLngBounds(latlngs));
    }
}

async function loadDashboard() {
    const response = await fetch('/api/dashboard/stats');
    const data = await response.json();
    
    let html = `
        <div class="dashboard-stat-card">
            <h6>Summary</h6>
            <p>Total Layers: ${data.summary.total_layers} | Total Features: ${data.summary.total_features}</p>
            <p>Roads Length: ${data.summary.total_roads_km.toFixed(2)} km | Buildings Area: ${data.summary.total_buildings_m2.toFixed(0)} m²</p>
        </div>
        <h6>Layer Details</h6>
        <table class="table table-sm">
            <thead><tr><th>Layer</th><th>Type</th><th>Features</th><th>Length (km)</th><th>Area (m²)</th></tr></thead>
            <tbody>
    `;
    
    for (const layer of data.layers) {
        html += `<tr>
            <td>${layer.name}</td>
            <td>${layer.layer_type}</td>
            <td>${layer.feature_count}</td>
            <td>${layer.total_length_m ? (layer.total_length_m/1000).toFixed(2) : '-'}</td>
            <td>${layer.total_area_m2 ? layer.total_area_m2.toFixed(0) : '-'}</td>
        </tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('dashboardContent').innerHTML = html;
    
    // Create chart
    const ctx = document.getElementById('statsChart').getContext('2d');
    const layerNames = data.layers.map(l => l.name);
    const featureCounts = data.layers.map(l => l.feature_count);
    new Chart(ctx, {
        type: 'bar',
        data: { labels: layerNames, datasets: [{ label: 'Feature Count', data: featureCounts, backgroundColor: '#36a2eb' }] },
        options: { responsive: true, plugins: { legend: { position: 'top' }, title: { display: true, text: 'Features per Layer' } } }
    });
}