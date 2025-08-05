import math
import time
import json
import os
from collections import deque
from datetime import datetime

import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FallDetector:
    def __init__(self, events_file="fall_events.json"):
        # Fall detection parameters
        self.FALL_THRESHOLD_LOW = 0.5      # Low acceleration threshold (g)
        self.FALL_THRESHOLD_HIGH = 2.5     # High acceleration threshold (g) 
        self.IMPACT_THRESHOLD = 3.0        # Impact detection threshold (g)
        self.ORIENTATION_THRESHOLD = 60    # Orientation change threshold (degrees)
        self.FREEFALL_TIME_MIN = 200       # Minimum freefall time (ms)
        self.IMPACT_TIME_MAX = 1000        # Max time between freefall and impact (ms)
        self.STILL_TIME_THRESHOLD = 2000   # Time to be still after impact (ms)
        
        # State variables
        self.state = "NORMAL"
        self.freefall_start_time = 0
        self.impact_time = 0
        self.pre_freefall_orientation = [0, 0, 0]
        
        # Data buffers for analysis
        self.data_buffer = deque(maxlen=100)  # Last 5 seconds at 20Hz
        self.filter_buffer = deque(maxlen=5)  # Moving average filter
        
        # File storage for fall events
        self.events_file = events_file
        self.fall_events = []  # In-memory cache
        self.load_fall_events()  # Load existing events from file
        
        # Statistics
        self.total_packets = 0
        self.fall_events_count = len(self.fall_events)  # Count from loaded events
        self.last_packet_time = time.time()
        
        logger.info("🚀 Fall Detection System Initialized")
        logger.info(f"📁 Events file: {self.events_file}")
        logger.info(f"📊 Loaded {len(self.fall_events)} existing fall events")
        logger.info(f"Thresholds: Low={self.FALL_THRESHOLD_LOW}g, High={self.FALL_THRESHOLD_HIGH}g, Impact={self.IMPACT_THRESHOLD}g")
    
    def load_fall_events(self):
        """Load fall events from file"""
        try:
            if os.path.exists(self.events_file):
                with open(self.events_file, 'r') as f:
                    self.fall_events = json.load(f)
                    logger.info(f"✅ Loaded {len(self.fall_events)} fall events from file")
            else:
                self.fall_events = []
                logger.info("📝 No existing events file found, starting fresh")
        except Exception as e:
            logger.error(f"❌ Error loading fall events: {e}")
            self.fall_events = []
    
    def save_fall_event(self, event_data):
        """Save a new fall event to file"""
        try:
            if len(self.fall_events) > 0:
                self.fall_events[-1]['is_expired'] = True

            # Add to in-memory cache
            self.fall_events.append(event_data)
            
            # Keep only last 1000 events to prevent file from growing too large
            if len(self.fall_events) > 1000:
                self.fall_events = self.fall_events[-1000:]
            
            # Save to file
            with open(self.events_file, 'w') as f:
                json.dump(self.fall_events, f, indent=2)
            
            logger.info(f"💾 Fall event saved to {self.events_file}")
            
        except Exception as e:
            logger.error(f"❌ Error saving fall event: {e}")
    
    def get_fall_events(self, limit=None):
        """Get fall events from file (most recent first)"""
        try:
            # Reload from file to get latest events
            self.load_fall_events()
            
            # Sort by timestamp (most recent first)
            sorted_events = sorted(self.fall_events, 
                                 key=lambda x: x.get('timestamp', ''), 
                                 reverse=True)
            
            if limit:
                return sorted_events[:limit]
            
            return sorted_events
            
        except Exception as e:
            logger.error(f"❌ Error getting fall events: {e}")
            return []
    
    def clear_fall_events(self):
        """Clear all fall events (for testing/maintenance)"""
        try:
            self.fall_events = []
            with open(self.events_file, 'w') as f:
                json.dump([], f)
            logger.info("🗑️ All fall events cleared")
        except Exception as e:
            logger.error(f"❌ Error clearing fall events: {e}")
    
    def process_sensor_data(self, data):
        """Process incoming sensor data and detect falls"""
        try:
            timestamp = data.get('timestamp', 0)
            accel = data['accelerometer']
            gyro = data['gyroscope']
            temperature = data.get('temperature', 0)
            device_id = data.get('device_id', 'unknown')
            
            # Apply moving average filter
            filtered_accel = self.apply_filter(accel)
            
            # Calculate total acceleration magnitude
            total_accel = math.sqrt(sum(a*a for a in filtered_accel))
            
            # Calculate orientation (tilt angles)
            roll = math.atan2(filtered_accel[1], filtered_accel[2]) * 180.0 / math.pi
            pitch = math.atan2(-filtered_accel[0], 
                             math.sqrt(filtered_accel[1]**2 + filtered_accel[2]**2)) * 180.0 / math.pi
            total_rotation = math.sqrt(sum(g*g for g in gyro))
            
            current_orientation = [roll, pitch, total_rotation]
            
            # Store data for analysis
            data_point = {
                'timestamp': timestamp,
                'accel': filtered_accel,
                'gyro': gyro,
                'total_accel': total_accel,
                'orientation': current_orientation,
                'temperature': temperature,
                'device_id': device_id
            }
            self.data_buffer.append(data_point)
            
            # Fall detection state machine
            fall_status = self.detect_fall(timestamp, total_accel, current_orientation, gyro)
            
            # Update statistics
            self.total_packets += 1
            self.last_packet_time = time.time()
            
            # Log significant events
            if self.total_packets % 200 == 0:  # Every 10 seconds at 20Hz
                logger.info(f"📊 Stats: {self.total_packets} packets, {len(self.fall_events)} fall events")
                logger.info(f"📊 Current: {total_accel:.2f}g, {temperature:.1f}°C, State: {self.state}")
            
            return {
                'status': 'success',
                'fall_detected': fall_status,
                'state': self.state,
                'total_acceleration': round(total_accel, 3),
                'orientation': {
                    'roll': round(roll, 1),
                    'pitch': round(pitch, 1),
                    'rotation_rate': round(total_rotation, 1)
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing data: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def apply_filter(self, accel):
        """Apply moving average filter to reduce noise"""
        self.filter_buffer.append(accel)
        
        if len(self.filter_buffer) < 3:
            return accel
        
        # Calculate moving average
        filtered = [0, 0, 0]
        for axis in range(3):
            filtered[axis] = sum(data[axis] for data in self.filter_buffer) / len(self.filter_buffer)
        
        return filtered
    
    def detect_fall(self, timestamp, total_accel, orientation, gyro):
        """Main fall detection logic"""
        current_time = timestamp
        fall_detected = False
        
        if self.state == "NORMAL":
            # Look for sudden drop in acceleration (freefall)
            if total_accel < self.FALL_THRESHOLD_LOW:
                self.state = "POSSIBLE_FREEFALL"
                self.freefall_start_time = current_time
                self.pre_freefall_orientation = orientation.copy()
                logger.info("⚠️  POSSIBLE FREEFALL DETECTED")
                self.send_fall_alert(orientation, total_accel, current_time)
        
        elif self.state == "POSSIBLE_FREEFALL":
            if total_accel > self.FALL_THRESHOLD_LOW:
                # False alarm
                self.state = "NORMAL"
                logger.info("✅ False alarm - returning to normal")
            elif current_time - self.freefall_start_time > self.FREEFALL_TIME_MIN:
                self.state = "CONFIRMED_FREEFALL"
                logger.info("🚨 FREEFALL CONFIRMED - Looking for impact...")
        
        elif self.state == "CONFIRMED_FREEFALL":
            if total_accel > self.IMPACT_THRESHOLD:
                self.state = "IMPACT_DETECTED"
                self.impact_time = current_time
                logger.info("💥 IMPACT DETECTED!")
                
                # Calculate orientation change
                roll_change = abs(orientation[0] - self.pre_freefall_orientation[0])
                pitch_change = abs(orientation[1] - self.pre_freefall_orientation[1])
                max_orientation_change = max(roll_change, pitch_change)
                
                logger.info(f"📐 Orientation change: {max_orientation_change:.1f}°")
                
                if max_orientation_change > self.ORIENTATION_THRESHOLD:
                    logger.info("🆘 SIGNIFICANT ORIENTATION CHANGE - LIKELY FALL!")
                    fall_detected = True
                    self.fall_events_count += 1
                    self.send_fall_alert(orientation, total_accel, current_time)
                
            elif current_time - self.freefall_start_time > self.IMPACT_TIME_MAX:
                self.state = "NORMAL"
                logger.info("⏰ No impact detected - timeout")
        
        elif self.state == "IMPACT_DETECTED":
            # Check if person remains still
            if total_accel < 1.5 and orientation[2] < 50:  # Low movement
                if current_time - self.impact_time > self.STILL_TIME_THRESHOLD:
                    logger.info("🚨🚨🚨 FALL DETECTED WITH PROLONGED STILLNESS!")
                    logger.info("🚨🚨🚨 EMERGENCY RESPONSE RECOMMENDED!")
                    self.state = "POST_FALL_STILL"
                    fall_detected = True
                    if not hasattr(self, '_stillness_alert_sent'):
                        self.fall_events_count += 1
                        self.send_fall_alert(orientation, total_accel, current_time, alert_type="PROLONGED_STILLNESS")
                        self._stillness_alert_sent = True
            else:
                # Person is moving - likely recovered
                self.state = "NORMAL"
                self._stillness_alert_sent = False  # Reset flag
                logger.info("✅ Person is moving - recovery detected")
        
        elif self.state == "POST_FALL_STILL":
            # Check for movement indicating recovery
            if total_accel > 1.5 or orientation[2] > 100:
                self.state = "NORMAL"
                self._stillness_alert_sent = False  # Reset flag
                logger.info("✅ Movement detected - person may have recovered")
        
        return fall_detected
    
    def send_fall_alert(self, orientation, total_accel, timestamp, alert_type="FALL_DETECTED"):
        """Send fall alert and save to file"""
        # Calculate confidence score based on multiple factors
        orientation_change = max(abs(orientation[0] - self.pre_freefall_orientation[0]),
                               abs(orientation[1] - self.pre_freefall_orientation[1]))
        
        impact_force = total_accel
        confidence = min(1.0, (impact_force / self.IMPACT_THRESHOLD + 
                             orientation_change / self.ORIENTATION_THRESHOLD) / 2)
        
        alert_data = {
            'timestamp': datetime.now().isoformat(),
            'event_type': alert_type,
            'severity': 'CRITICAL' if confidence > 0.8 else 'HIGH',
            'confidence': round(confidence, 3),
            'impact_force': round(impact_force, 2),
            'orientation_change': round(orientation_change, 1),
            'pre_fall_orientation': {
                'roll': round(self.pre_freefall_orientation[0], 1),
                'pitch': round(self.pre_freefall_orientation[1], 1),
                'rotation': round(self.pre_freefall_orientation[2], 1)
            },
            'current_orientation': {
                'roll': round(orientation[0], 1),
                'pitch': round(orientation[1], 1),
                'rotation': round(orientation[2], 1)
            },
            'freefall_duration': timestamp - self.freefall_start_time if self.freefall_start_time else 0,
            'location': 'Room 204B',  # Could be dynamic based on device location
            'device_id': getattr(self, 'current_device_id', 'SENSOR_001'),
            'patient_id': 'PAT-2024-1157',  # Could be configurable
            'is_resolved': False,
            'is_expired': False
        }
        
        logger.info(f"🚨 FALL ALERT: {json.dumps(alert_data, indent=2)}")
        
        # Save to file
        self.save_fall_event(alert_data)
        
        # Here you can add additional notification methods:
        # - Send email notification
        # - Send SMS via Twilio
        # - Call emergency contacts
        # - Send push notification
        # - Log to database
        # - Trigger IoT devices (lights, alarms)
    
    def get_last_state(self):
        current_state = self.state

        if len(self.fall_events) > 0:
            last_state = self.fall_events[-1]
            current_state = "NORMAL" if last_state['is_resolved'] or last_state['is_expired'] else last_state['event_type']
        
        return current_state

    def get_stats(self, start_time):
        current_state = self.get_last_state()

        """Get system statistics"""
        return {
            'total_packets': self.total_packets,
            'fall_events': len(self.fall_events),
            'total_falls': self.fall_events_count,  # Total count including current session
            'current_state': current_state,
            'buffer_size': len(self.data_buffer),
            'last_packet_age': time.time() - self.last_packet_time,
            'uptime_seconds': time.time() - start_time,
            'active_alerts': 1 if current_state in ['IMPACT_DETECTED', 'POST_FALL_STILL'] else 0,
            'latest_sensor_value': self.data_buffer[-1]['total_accel'] if self.data_buffer else 0
        }
    
    def resolve_alert(self):
        """Save a new fall event to file"""
        try:
            self.fall_events[-1]['is_resolved'] = True
            
            # Save to file
            with open(self.events_file, 'w') as f:
                json.dump(self.fall_events, f, indent=2)
            
            logger.info(f"💾 Fall event resolved")
            
        except Exception as e:
            logger.error(f"❌ Error saving fall event: {e}")