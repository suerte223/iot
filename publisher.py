#!/usr/bin/env python3
"""
드론 데이터 관리 시스템 - 드론 시뮬레이터
여러 대의 드론이 MQTT로 데이터를 전송하는 것을 시뮬레이션
"""
from paho.mqtt import client as mqtt
import paho.mqtt.client as mqtt
import json
import time
import random
import math
from datetime import datetime
import threading
import argparse

class DroneSimulator:
    def __init__(self, drone_id, mqtt_broker="localhost", mqtt_port=1883):
        self.drone_id = drone_id
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.client = mqtt.Client(
            client_id=f"drone_{drone_id}",
            protocol=mqtt.MQTTv311,
        )
        
        # 드론 초기 상태
        self.latitude = 37.5665 + random.uniform(-0.01, 0.01)
        self.longitude = 126.9780 + random.uniform(-0.01, 0.01)
        self.altitude = 0.0
        self.battery = 100.0
        self.speed = 0.0
        self.heading = random.randint(0, 360)
        self.status = "IDLE"
        self.is_connected = True
        self.mission_progress = 0
        
        # 시뮬레이션 파라미터
        self.time_elapsed = 0
        self.flight_pattern = random.choice(["circle", "square", "patrol"])
        
    def connect_mqtt(self):
        """MQTT 브로커 연결"""
        try:
            self.client.on_connect = self.on_connect
            self.client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.client.loop_start()
            print(f"[{self.drone_id}] MQTT 브로커 연결 성공")
            return True
        except Exception as e:
            print(f"[{self.drone_id}] MQTT 연결 실패: {e}")
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT 연결 콜백"""
        if rc == 0:
            print(f"[{self.drone_id}] MQTT 연결 완료")
            # 연결 상태 메시지 발행
            self.publish_event("CONNECTED", "드론이 시스템에 연결되었습니다")
        else:
            print(f"[{self.drone_id}] 연결 실패 코드: {rc}")
    
    def simulate_movement(self):
        """드론 움직임 시뮬레이션"""
        if self.status == "FLYING":
            # 비행 패턴에 따른 이동
            if self.flight_pattern == "circle":
                angle = math.radians(self.time_elapsed * 6)  # 60초에 한 바퀴
                self.latitude += math.cos(angle) * 0.0001
                self.longitude += math.sin(angle) * 0.0001
            elif self.flight_pattern == "square":
                side = (self.time_elapsed // 15) % 4
                if side == 0:
                    self.longitude += 0.0001
                elif side == 1:
                    self.latitude += 0.0001
                elif side == 2:
                    self.longitude -= 0.0001
                else:
                    self.latitude -= 0.0001
            else:  # patrol
                self.longitude += math.sin(self.time_elapsed * 0.1) * 0.0001
                
            # 고도 변화
            self.altitude = 50 + math.sin(self.time_elapsed * 0.05) * 20
            
            # 속도 변화
            self.speed = 10 + random.uniform(-2, 2)
            
            # 배터리 소모
            self.battery -= random.uniform(0.1, 0.3)
            
            # 미션 진행
            self.mission_progress = min(100, self.mission_progress + random.uniform(0.5, 1.5))
            
    def update_status(self):
        """드론 상태 업데이트"""
        if self.battery < 15:
            self.status = "LOW_BATTERY"
            self.publish_event("WARNING", f"배터리 부족: {self.battery:.1f}%")
        elif self.battery < 5:
            self.status = "EMERGENCY"
            self.publish_event("CRITICAL", "긴급 착륙 필요")
        elif self.mission_progress >= 100:
            self.status = "RETURNING"
        elif self.time_elapsed > 10 and self.status == "IDLE":
            self.status = "FLYING"
            self.publish_event("STATUS_CHANGE", "이륙 완료")
            
    def publish_telemetry(self):
        """텔레메트리 데이터 발행"""
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "drone_id": self.drone_id,
            "gps": {
                "latitude": round(self.latitude, 6),
                "longitude": round(self.longitude, 6),
                "altitude": round(self.altitude, 2)
            },
            "battery": round(self.battery, 1),
            "speed": round(self.speed, 1),
            "heading": self.heading,
            "status": self.status
        }
        
        # GPS 데이터
        topic_gps = f"drone/{self.drone_id}/telemetry/gps"
        self.client.publish(topic_gps, json.dumps(telemetry["gps"]))
        
        # 배터리 데이터
        topic_battery = f"drone/{self.drone_id}/telemetry/battery"
        self.client.publish(topic_battery, json.dumps({
            "level": telemetry["battery"],
            "voltage": 12.4 + (telemetry["battery"] / 100) * 2,
            "temperature": 25 + random.uniform(-5, 5)
        }))
        
        # 전체 텔레메트리
        topic_all = f"drone/{self.drone_id}/telemetry/all"
        self.client.publish(topic_all, json.dumps(telemetry))
        
    def publish_mission(self):
        """미션 데이터 발행"""
        mission = {
            "timestamp": datetime.utcnow().isoformat(),
            "drone_id": self.drone_id,
            "mission_id": f"MISSION_{self.drone_id}_{datetime.now().strftime('%Y%m%d')}",
            "progress": round(self.mission_progress, 1),
            "waypoints_completed": int(self.mission_progress / 10),
            "waypoints_total": 10,
            "estimated_time_remaining": max(0, 120 - self.time_elapsed)
        }
        
        topic = f"drone/{self.drone_id}/mission/status"
        self.client.publish(topic, json.dumps(mission))
        
    def publish_event(self, event_type, message):
        """이벤트 발행"""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "drone_id": self.drone_id,
            "event_type": event_type,
            "message": message,
            "severity": self.get_severity(event_type)
        }
        
        topic = f"drone/{self.drone_id}/events/{event_type.lower()}"
        self.client.publish(topic, json.dumps(event))
        
    def get_severity(self, event_type):
        """이벤트 심각도 결정"""
        severity_map = {
            "CRITICAL": 5,
            "WARNING": 3,
            "STATUS_CHANGE": 2,
            "INFO": 1,
            "CONNECTED": 1
        }
        return severity_map.get(event_type, 1)
    
    def simulate_random_events(self):
        """랜덤 이벤트 시뮬레이션"""
        if random.random() < 0.05:  # 5% 확률로 이벤트 발생
            events = [
                ("INFO", "웨이포인트 도달"),
                ("WARNING", "강풍 감지"),
                ("INFO", "카메라 촬영 완료"),
                ("WARNING", "GPS 신호 약함")
            ]
            event_type, message = random.choice(events)
            self.publish_event(event_type, message)
            
    def run(self):
        """시뮬레이터 실행"""
        if not self.connect_mqtt():
            return
            
        print(f"[{self.drone_id}] 시뮬레이션 시작 - 패턴: {self.flight_pattern}")
        
        try:
            while self.battery > 0 and self.is_connected:
                # 상태 업데이트
                self.simulate_movement()
                self.update_status()
                
                # 데이터 발행
                self.publish_telemetry()
                
                if self.time_elapsed % 5 == 0:  # 5초마다
                    self.publish_mission()
                    
                self.simulate_random_events()
                
                # 시간 증가
                self.time_elapsed += 1
                time.sleep(1)
                
                # 상태 출력
                if self.time_elapsed % 10 == 0:
                    print(f"[{self.drone_id}] 상태: {self.status}, 배터리: {self.battery:.1f}%, "
                          f"위치: ({self.latitude:.4f}, {self.longitude:.4f}), 고도: {self.altitude:.1f}m")
                    
        except KeyboardInterrupt:
            print(f"\n[{self.drone_id}] 시뮬레이션 중단")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            print(f"[{self.drone_id}] 연결 종료")

def run_multiple_drones(num_drones=3, broker="localhost"):
    """여러 드론 동시 실행"""
    drones = []
    threads = []
    
    for i in range(1, num_drones + 1):
        drone_id = f"DRONE_{i:03d}"
        drone = DroneSimulator(drone_id, broker)
        drones.append(drone)
        
        thread = threading.Thread(target=drone.run)
        threads.append(thread)
        thread.start()
        
        time.sleep(2)  # 드론 시작 시간 간격
    
    # 모든 스레드 종료 대기
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="드론 데이터 관리 시스템 시뮬레이터")
    parser.add_argument("--drones", type=int, default=3, help="시뮬레이션할 드론 수")
    parser.add_argument("--broker", type=str, default="localhost", help="MQTT 브로커 주소")
    parser.add_argument("--single", type=str, help="단일 드론 ID (예: DRONE_001)")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("드론 데이터 관리 시스템 - 시뮬레이터")
    print("=" * 50)
    
    if args.single:
        # 단일 드론 실행
        drone = DroneSimulator(args.single, args.broker)
        drone.run()
    else:
        # 다중 드론 실행
        print(f"시뮬레이션 드론 수: {args.drones}")
        print(f"MQTT 브로커: {args.broker}")
        print("시뮬레이션을 시작합니다...\n")
        
        try:
            run_multiple_drones(args.drones, args.broker)
        except KeyboardInterrupt:
            print("\n시뮬레이션 종료")