from flask import Flask, request, jsonify, render_template
from fall_detector import FallDetector
from collision_detector import load_collision_log, save_collision_log, cleanup_old_entries
from datetime import datetime

import logging
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for sensor data
sensor_data = []

fall_status = None
fall_detector = FallDetector()
start_time = time.time()

@app.route('/fall_data', methods=['POST'])
def receive_sensor_data():
    """Endpoint to receive sensor data from ESP32"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        # Process the sensor data
        result = fall_detector.process_sensor_data(data)
        
        # Return simple response to ESP32
        if result['status'] == 'success':
            return "OK", 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"❌ Error in /sensor_data endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/fall/status', methods=['GET'])
def get_status():
    stats = fall_detector.get_stats(start_time)
    return jsonify(stats)

@app.route('/fall/resolve', methods=['GET'])
def resolve_fall():
    stats = fall_detector.resolve_alert()
    return jsonify(stats)

@app.route('/fall/alerts', methods=['GET'])
def get_recent_alerts():
    limit = request.args.get('limit', 10, type=int)
    
    # Get recent fall events from file
    fall_events = fall_detector.get_fall_events(limit=limit)
    
    # Return last 10 data points for real-time analysis
    recent_data = list(fall_detector.data_buffer)[-10:]
    
    return jsonify({
        'recent_data': recent_data,
        'current_state': fall_detector.get_last_state(),
        'fall_events': fall_events,
        'total_events': len(fall_events)
    })

@app.route('/alerts/clear', methods=['POST'])
def clear_alerts():
    fall_detector.clear_fall_events()
    return jsonify({'status': 'success', 'message': 'All fall events cleared'})

@app.route('/alerts/count', methods=['GET'])
def get_alerts_count():
    events = fall_detector.get_fall_events()
    return jsonify({
        'total_events': len(events),
        'events_today': len([e for e in events if e['timestamp'].startswith(datetime.now().strftime('%Y-%m-%d'))])
    })

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('home.html')

@app.route('/temp')
def add_data():
    """Add temperature and humidity data via GET request"""
    try:
        temperature = request.args.get('temperature', type=float)
        humidity = request.args.get('humidity', type=float)
        
        if temperature is None or humidity is None:
            return jsonify({
                'error': 'Both temperature and humidity parameters are required',
                'example': '/data?temperature=25.5&humidity=60.2'
            }), 400
        
        # Validate ranges
        if not -50 <= temperature <= 100:
            return jsonify({'error': 'Temperature must be between -50°C and 100°C'}), 400
        
        if not 0 <= humidity <= 100:
            return jsonify({'error': 'Humidity must be between 0% and 100%'}), 400
        
        # Add data point
        data_point = {
            'timestamp': datetime.now().isoformat(),
            'temperature': temperature,
            'humidity': humidity
        }
        sensor_data.append(data_point)
        
        # Keep only last 100 data points to prevent memory issues
        if len(sensor_data) > 100:
            sensor_data.pop(0)
        
        return jsonify({
            'message': 'Data added successfully',
            'data': data_point,
            'total_points': len(sensor_data)
        })
        
    except ValueError:
        return jsonify({'error': 'Invalid number format for temperature or humidity'}), 400

@app.route('/collision', methods=['POST'])
def log_collision():
    """Endpoint to receive and log collision alerts from ESP32"""
    try:
        # Get JSON data from request
        collision_data_request = request.get_json()
        
        if not collision_data_request:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Add server timestamp
        collision_entry = {
            'device_id': collision_data_request.get('device_id', 'unknown'),
            'distance': collision_data_request.get('distance', 0),
            'threshold': collision_data_request.get('threshold', 0),
            'device_timestamp': collision_data_request.get('timestamp', 0),
            'server_timestamp': datetime.now().isoformat(),
            'id': len(load_collision_log()) + 1  # Simple ID generation
        }
        
        # Load existing log
        collision_log = load_collision_log()
        
        # Add new entry
        collision_log.append(collision_entry)
        
        # Cleanup old entries if needed
        collision_log = cleanup_old_entries(collision_log)
        
        # Save to file
        if save_collision_log(collision_log):
            logger.info(f"Collision logged: Device {collision_entry['device_id']}, Distance: {collision_entry['distance']}cm")
            return jsonify({
                'status': 'success',
                'message': 'Collision logged successfully',
                'entry_id': collision_entry['id']
            }), 200
        else:
            return jsonify({'error': 'Failed to save collision log'}), 500
            
    except Exception as e:
        logger.error(f"Error processing collision alert: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/collisions', methods=['GET'])
def get_collisions():
    """Endpoint to retrieve collision log"""
    try:
        # Load collision log
        collision_log = load_collision_log()
        
        # Get query parameters for filtering
        limit = request.args.get('limit', type=int)
        device_id = request.args.get('device_id', type=str)
        
        # Filter by device_id if specified
        if device_id:
            collision_log = [entry for entry in collision_log if entry.get('device_id') == device_id]
        
        # Sort by server timestamp (most recent first)
        collision_log = sorted(collision_log, key=lambda x: x.get('server_timestamp', ''), reverse=True)
        
        # Apply limit if specified
        if limit and limit > 0:
            collision_log = collision_log[:limit]
        
        return jsonify({
            'status': 'success',
            'count': len(collision_log),
            'collisions': collision_log
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving collision log: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/collisions/stats', methods=['GET'])
def get_collision_stats():
    """Endpoint to get collision statistics"""
    try:
        collision_log = load_collision_log()
        
        if not collision_log:
            return jsonify({
                'status': 'success',
                'total_collisions': 0,
                'devices': [],
                'latest_collision': None
            }), 200
        
        # Calculate statistics
        total_collisions = len(collision_log)
        devices = list(set([entry.get('device_id', 'unknown') for entry in collision_log]))
        latest_collision = max(collision_log, key=lambda x: x.get('server_timestamp', ''))
        
        # Device-specific stats
        device_stats = {}
        for device in devices:
            device_collisions = [entry for entry in collision_log if entry.get('device_id') == device]
            device_stats[device] = {
                'collision_count': len(device_collisions),
                'avg_distance': sum([entry.get('distance', 0) for entry in device_collisions]) / len(device_collisions),
                'latest_collision': max(device_collisions, key=lambda x: x.get('server_timestamp', ''))
            }
        
        return jsonify({
            'status': 'success',
            'total_collisions': total_collisions,
            'device_count': len(devices),
            'devices': devices,
            'device_stats': device_stats,
            'latest_collision': latest_collision
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving collision stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/data')
def get_data():
    """Get all stored sensor data"""
    return jsonify(sensor_data)

@app.route('/clear')
def clear_data():
    """Clear all stored data"""
    global sensor_data
    count = len(sensor_data)
    sensor_data = []
    return jsonify({
        'message': f'Cleared {count} data points',
        'remaining_points': len(sensor_data)
    })

@app.route('/api/stats')
def get_stats():
    """Get basic statistics"""
    if not sensor_data:
        return jsonify({'error': 'No data available'})
    
    temperatures = [d['temperature'] for d in sensor_data]
    humidities = [d['humidity'] for d in sensor_data]
    
    stats = {
        'temperature': {
            'current': temperatures[-1],
            'min': min(temperatures),
            'max': max(temperatures),
            'avg': sum(temperatures) / len(temperatures)
        },
        'humidity': {
            'current': humidities[-1],
            'min': min(humidities),
            'max': max(humidities),
            'avg': sum(humidities) / len(humidities)
        },
        'total_points': len(sensor_data),
        'time_range': {
            'first': sensor_data[0]['timestamp'],
            'last': sensor_data[-1]['timestamp']
        }
    }
    
    return jsonify(stats)

if __name__ == '__main__':
    print("🌡️ Temperature & Humidity Server Starting...")
    print("📊 Dashboard: http://localhost:5000")
    print("📡 Add data: http://localhost:5000/data?temperature=25.5&humidity=60.2")
    print("🔍 View data: http://localhost:5000/api/data")
    print("🗑️ Clear data: http://localhost:5000/clear")
    app.run(debug=True, host='0.0.0.0', port=5000)