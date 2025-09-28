import json
import time
import random
import paho.mqtt.client as mqtt

# 브로커/토픽 설정
HOST, PORT = "broker.emqx.io", 1883
TOPIC = "drone/lab/drone01/telemetry/gps"

# MQTT 연결
client = mqtt.Client(protocol=mqtt.MQTTv5)
client.connect(HOST, PORT, 60)


start = time.time()
i = 0
while time.time() - start < 120:
    msg = {
        "ts": int(time.time() * 1000),          # ms 단위 timestamp -> subscriber에서 ts_ms로 기록
        "lat": 33.50 + (i % 5) * 0.001,         # 위도
        "lon": 126.50 + (i % 5) * 0.001,        # 경도
        "alt": 100 + (i % 10),                  # 고도
        "spd": 10 + (i % 5),                    # 속도
        "hdg": (i * 15) % 360,                  # 방위각
        "battery": random.randint(-10, 120),    # 배터리 범위: 0-120 -> 100을 넘어가면 subscriber가 자동으로 저장 제외
        "fix": True                             # GPS fix 여부
    }

    client.publish(TOPIC, json.dumps(msg))
    print("[PUB]", i, msg)
    i += 1
    time.sleep(20)  #20초 간격으로 발행

client.disconnect()
print("done")
