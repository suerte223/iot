import os
import json
import csv
import time
import signal
import sys
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_HOST = "broker.emqx.io"
MQTT_PORT = 1883

# 퍼블리셔에서 주로 쓰는 토픽 패턴
MQTT_TOPICS = [
    ("drone/+/+/telemetry/+", 0),
    ("drone/+/telemetry/+", 0),
    ("drone/+/status/+", 0),
]

# csv 저장 설정
SAVE_DIR = os.path.abspath("./data")   # 공백 경로 -> 안전하게 절대경로
FILE_PREFIX = "telemetry"              
MAX_FILES = 5                          # 분당 csv 파일 1개 생성, 최대 5개의 파일 생성

# 상태 변수
current_minute_key = None
current_file = None
current_writer = None
created_files = 0

os.makedirs(SAVE_DIR, exist_ok=True)

# 시간: YYYYMMDD_HHMM 형식의 문자열로 반환
def now_minute_key():
    return datetime.now().strftime("%Y%m%d_%H%M")


def is_battery_valid(bat):
    #배터리 0~100이면 T 아니면 F
    try:
        if bat is None:
            return False
        bat = float(bat)
    except Exception:
        return False
    return 0.0 <= bat <= 100.0


def parse_payload(payload: bytes) -> dict:
    try:
        p = json.loads(payload.decode("utf-8"))
    except Exception:
        return {}

    def pick(*keys):
        for k in keys:
            if k in p and p[k] is not None:
                return p[k]
        return None

    return {
        "lat": pick("lat", "latitude"),
        "lon": pick("lon", "longitude"),
        "alt": pick("alt", "altitude"),
        "spd": pick("spd", "speed"),
        "hdg": pick("hdg", "heading"),
        "fix": pick("fix", "gps_fix"),
        "battery": pick("battery", "bat", "battery_level"),
        "ts_ms": pick("ts", "timestamp") or int(time.time() * 1000),
    }

def close_file():
    global current_file, current_writer
    if current_file:
        try:
            current_file.flush()
            current_file.close()
        except Exception:
            pass
    current_file = None
    current_writer = None


def open_new_file(minute_key: str) -> bool:
    global current_file, current_writer, created_files

    if created_files >= MAX_FILES:
        print("[INFO] Max file count reached. No more new files will be created.")
        return False

    fname = f"{FILE_PREFIX}_{minute_key}.csv"
    fpath = os.path.join(SAVE_DIR, fname)
    is_new = not os.path.exists(fpath)

    current_file = open(fpath, "a", newline="", encoding="utf-8")
    current_writer = csv.writer(current_file)

    if is_new:
        current_writer.writerow(["ts_iso", "ts_ms", "lat", "lon", "alt", "spd", "hdg", "battery", "fix"])
        current_file.flush()

    created_files += 1
    print(f"[ROTATE] Opened: {fname} (#{created_files}/{MAX_FILES})")
    return True

# 분 단위로 csv 파일 회전
def rotate_if_needed():
    global current_minute_key
    mk = now_minute_key()
    if mk != current_minute_key:
        close_file()
        if open_new_file(mk):
            current_minute_key = mk
        else:
            graceful_exit()


def on_connect(client, userdata, flags, rc, properties=None):
    print("[MQTT] Connected")
    for t, qos in MQTT_TOPICS:
        client.subscribe(t, qos=qos)
        print(f"[MQTT] Subscribed: {t}")


def on_message(client, userdata, msg):
    rec = parse_payload(msg.payload)

    if not is_battery_valid(rec.get("battery")):
        print(f"[경고] 배터리 범위를 벗어남: {rec.get('battery')} | SKIP")
        return # csv에 저장X

    rotate_if_needed()

    ts_iso = datetime.now().isoformat(timespec="seconds")
    # csv에 저정할 행 구성
    row = [
        ts_iso,
        rec.get("ts_ms"),
        rec.get("lat"),
        rec.get("lon"),
        rec.get("alt"),
        rec.get("spd"),
        rec.get("hdg"),
        rec.get("battery"),
        rec.get("fix"),
    ]

    # 파일 준비X -> 회전 다시 시도
    if current_writer is None:
        rotate_if_needed()

    if current_writer is not None:
        current_writer.writerow(row)
        current_file.flush()
        print("[SAVE]", row)
    else:
        print("[WARN] Writer not ready. Row skipped.")


def on_disconnect(client, userdata, rc, properties=None):
    print(f"[MQTT] Disconnected: rc={rc}")
    close_file()


#종료
def graceful_exit(*_):
    try:
        close_file()
    finally:
        os._exit(0)


if __name__ == "__main__":
    rotate_if_needed()

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    client = mqtt.Client(protocol=mqtt.MQTTv5)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    print("[MQTT] Connecting...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

    client.loop_forever()
