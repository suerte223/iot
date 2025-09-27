import os
import sys
import json
import time
import math
import signal
import random
import argparse
import threading
import csv
from typing import Dict, Any

import paho.mqtt.client as mqtt

# -----------------------------
# 기본 설정 (환경변수/인자 모두 지원)
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Drone Telemetry MQTT Publisher (Simulator) with stats")
    p.add_argument("--host", default=os.environ.get("MQTT_HOST", "test.mosquitto.org"),
                   help="MQTT broker host (기본: test.mosquitto.org)")
    p.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")),
                   help="MQTT broker port (기본: 1883)")
    p.add_argument("--tls", action="store_true", default=os.environ.get("MQTT_TLS", "0") == "1",
                   help="TLS 사용(8883 권장). --port 8883와 함께 사용")
    p.add_argument("--transport", choices=["tcp", "websockets"], default=os.environ.get("MQTT_TRANSPORT", "tcp"),
                   help="전송 방식: tcp 또는 websockets")
    p.add_argument("--fleet", default=os.environ.get("DRONE_FLEET", "lab"),
                   help="플릿 이름")
    p.add_argument("--drone-id", default=os.environ.get("DRONE_ID", "2023108095"), # 드론 id를 학번으로 변경
                   help="드론 ID (학번을 여기에 입력). 기본: 2023108095")
    p.add_argument("--rate", type=float, default=float(os.environ.get("PUB_RATE_HZ", "5")),
                   help="발행 주파수(Hz). 기본 5Hz")
    p.add_argument("--qos", type=int, choices=[0, 1], default=int(os.environ.get("PUB_QOS", "0")),
                   help="QoS 수준 (0 또는 1 권장)")
    p.add_argument("--seconds", type=int, default=int(os.environ.get("SIM_SECONDS", "600")), # 시뮬레이션 지속 시간을 600초로 변경하여 10분동한 발행하고 수신 로그를 수집
                   help="시뮬레이션 지속 시간(초). 기본 600초(10분)")
    p.add_argument("--retain-battery", action="store_true", default=os.environ.get("RETAIN_BATTERY", "0") == "1",
                   help="배터리 상태를 Retained로 보낼지 여부")
    p.add_argument("--expiry", type=int, default=int(os.environ.get("MSG_EXPIRY", "0")),
                   help="MQTT v5 Message Expiry Interval(초). 0=미사용")
    p.add_argument("--client-prefix", default="drone-sim",
                   help="MQTT 클라이언트 ID 접두사")
    p.add_argument("--no-subscriber", action="store_true",
                   help="내부 subscriber를 사용하지 않음 (통계 수집 불가). 디버그 용도")
    return p.parse_args()

# -----------------------------
# 토픽 유틸
# -----------------------------
def topic_base(fleet: str, drone_id: str) -> str:
    return f"drone/{fleet}/{drone_id}"

def topics(fleet: str, drone_id: str) -> Dict[str, str]:
    base = topic_base(fleet, drone_id)
    return {
        # QoS0과 QoS1 분리 작성
        "gps_q0":      f"{base}/telemetry/gps/qos0",
        "gps_q1":      f"{base}/telemetry/gps/qos1",
        "alt_q0":      f"{base}/telemetry/alt/qos0",
        "alt_q1":      f"{base}/telemetry/alt/qos1",
        "battery":     f"{base}/status/battery",
        "online":      f"{base}/status/online",
        "mode":        f"{base}/status/mode",
    }

# -----------------------------
# 상태/시뮬레이션
# -----------------------------

def init_state() -> Dict[str, Any]:
    # 서울 시청 근방 좌표 기준
    return {
        "id": "001",
        "lat": 37.5665,
        "lon": 126.9780,
        "alt": 80.0,          # meters
        "spd": 7.5,           # m/s
        "hdg": 270,           # degrees
        "bat": 100.0,         # percent
        "fix": True,
        "ts": time.time(),
        "seq": 0,             # 메시지 순번 -> 누락/중복 판정
    }

def step_state(state: Dict[str, Any]) -> Dict[str, Any]:
    state["lat"] += (random.random() - 0.5) * 0.00008
    state["lon"] += (random.random() - 0.5) * 0.00008
    state["alt"] = max(0.0, state["alt"] + (random.random() - 0.5) * 0.7)
    state["spd"] = max(0.0, state["spd"] + (random.random() - 0.5) * 0.2)
    state["hdg"] = (state["hdg"] + random.choice([-2, -1, 0, 1, 2])) % 360
    state["bat"] = max(0.0, state["bat"] - 0.03)  # tick당 0.03% 감소
    state["ts"] = time.time()
    state["seq"] += 1
    return state

# -----------------------------
# MQTT client 생성/콜백
# -----------------------------
def build_client(client_id: str, transport: str = "tcp", use_tls: bool = False) -> mqtt.Client:
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5, transport=transport)
    if use_tls:
        client.tls_set()
    return client

def set_callbacks(client: mqtt.Client, name="client"):
    def on_connect(c, u, flags, rc, props=None):
        print(f"[{name} CONNECT] rc={rc} props={props}")
    def on_disconnect(c, u, rc, props=None):
        print(f"[{name} DISCONNECT] rc={rc} props={props}")
    def on_publish(c, u, mid):
        pass
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish

def set_lwt(client: mqtt.Client, will_topic: str):
    # LWT: 비정상 종료 시 offline 발행 (Retained)
    # 클라이언트가 갑자기 사라졌다는 사실을 알려주기 위해서 설계되었으며 평상시에는 발행되지 않음
    client.will_set(will_topic, payload="offline", qos=1, retain=True)

# -----------------------------
# 발행 헬퍼 (MQTT v5 속성: Expiry)
# -----------------------------
def make_props_for_expiry(expiry: int): # expiry 처리 코드 재사용 가능하게 분리작성
    if expiry > 0:
        from paho.mqtt.properties import Properties
        from paho.mqtt.packettypes import PacketTypes
        props = Properties(PacketTypes.PUBLISH)
        props.MessageExpiryInterval = int(expiry)
        return props
    return None

def publish_json(client: mqtt.Client, topic: str, payload_obj: Dict[str, Any],
                 qos: int, retain: bool, expiry: int = 0):
    props = make_props_for_expiry(expiry)
    payload = json.dumps(payload_obj, ensure_ascii=False)
    # retain 메시지 여부 결정
    # 함수 호출 시 retain=True를 주면 브로커가 메시지를 토픽의 마지막 상태로 저장하고 새로운 구독자가 붙으면 그 메시지를 받을 수 있음
    result = client.publish(topic, payload, qos=qos, retain=retain, properties=props)
    try:
        result.wait_for_publish()
    except Exception:
        # 네트워크 끊김, 브러커 지연 등 예외 상황을 무시하고 rc만 반환 -> 예외가 터져도 프로그램이 죽지 않고 코드가 안정하게 동작 가능
        pass
    return getattr(result, "rc", 0)

def publish_value(client: mqtt.Client, topic: str, value, qos: int, retain: bool, expiry: int = 0):
    props = make_props_for_expiry(expiry)
    result = client.publish(topic, str(value), qos=qos, retain=retain, properties=props)
    try:
        result.wait_for_publish()
    except Exception:
        pass
    return getattr(result, "rc", 0)

# -----------------------------
# 내부 Subscriber(통계용)
# -----------------------------
class StatCollector:
    def __init__(self):
        self.stats = {}
        self.lock = threading.Lock()

    def record(self, topic: str, payload: str):
        try:
            obj = json.loads(payload)
            seq = int(obj.get("seq", -1))
        except Exception:
            seq = -1
        with self.lock:
            if topic not in self.stats:
                self.stats[topic] = {"recv_total": 0, "unique_seqs": set(), "duplicates": 0, "first_seq": None, "last_seq": None}
            st = self.stats[topic]
            st["recv_total"] += 1
            if seq >= 0:
                if st["first_seq"] is None:
                    st["first_seq"] = seq
                st["last_seq"] = seq
                if seq in st["unique_seqs"]:
                    st["duplicates"] += 1
                else:
                    st["unique_seqs"].add(seq)

    def snapshot(self):
        with self.lock:
            out = {}
            for topic, st in self.stats.items():
                unique = len(st["unique_seqs"])
                total = st["recv_total"]
                dups = st["duplicates"]
                missing = 0
                if st["first_seq"] is not None and st["last_seq"] is not None and st["last_seq"] >= st["first_seq"]:
                    expected = st["last_seq"] - st["first_seq"] + 1
                    missing = max(0, expected - unique)
                out[topic] = {
                    "recv_total": total,
                    "unique": unique,
                    "duplicates": dups,
                    "missing": missing,
                    "first_seq": st["first_seq"],
                    "last_seq": st["last_seq"],
                }
            return out

# -----------------------------
# 메인 루프
# -----------------------------
def main():
    args = parse_args()
    drone_id = args.drone_id
    t = topics(args.fleet, drone_id)

    # 발행 클라이언트 생성 및 콜백&LWT 설정
    pub_client_id = f"{args.client_prefix}-pub-{drone_id}-{int(time.time())}"
    client_pub = build_client(client_id=pub_client_id, transport=args.transport, use_tls=args.tls)
    set_callbacks(client_pub, name="PUB") # 연결, 끊김, 발행 콜백 등록
    set_lwt(client_pub, t["online"]) # 비정상 종료 시 online 토픽에 offline 메시지를 Retained로 보내도록 설정

    stat = StatCollector()
    client_sub = None
    if not args.no_subscriber:
        sub_client_id = f"{args.client_prefix}-sub-{drone_id}-{int(time.time())}"
        client_sub = build_client(client_id=sub_client_id, transport=args.transport, use_tls=args.tls)
        set_callbacks(client_sub, name="SUB")

        def on_message_sub(c, u, msg):
            payload = msg.payload.decode("utf-8", errors="replace")
            stat.record(msg.topic, payload)

        client_sub.on_message = on_message_sub

    # 브로커 연결 후 백그라운드 루프 시작 -> 메시지 발행/수신이 비동기로 이루어짐
    client_pub.connect(args.host, args.port, keepalive=60)
    client_pub.loop_start()
    if client_sub:
        client_sub.connect(args.host, args.port, keepalive=60)
        client_sub.loop_start()

    # 초기 상태 메시지 발행 후 Retained 메시지로 브로커에 기록 -> 새로 구독하는 클라이언트도 즉시 확인 가능
    publish_value(client_pub, t["online"], "online", qos=1, retain=True, expiry=0)
    publish_value(client_pub, t["mode"], "CRUISE", qos=1, retain=True, expiry=0)

    if client_sub:
        client_sub.subscribe([
            (t["gps_q0"], 0),
            (t["gps_q1"], 1),
            (t["alt_q0"], 0),
            (t["alt_q1"], 1),
            (t["battery"], 1),
        ])

    stop_event = threading.Event()
    normal_exit = {"flag": False}

    def handle_sig(signum, frame):
        print("\n[Signal] 정상 종료 요청 수신")
        normal_exit["flag"] = True
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    state = init_state()
    state["id"] = drone_id
    dt = 1.0 / max(0.1, args.rate)

    if args.qos == 0:
        gps_topic = t["gps_q0"]
        alt_topic = t["alt_q0"]
    else:
        gps_topic = t["gps_q1"]
        alt_topic = t["alt_q1"]

    print(f"[RUN] host={args.host} port={args.port} tls={args.tls} transport={args.transport}")
    print(f"[RUN] topics={t}")
    print(f"[RUN] using gps_topic={gps_topic} alt_topic={alt_topic}")
    print(f"[RUN] rate={args.rate}Hz qos={args.qos} seconds={args.seconds} expiry={args.expiry}")

    start = time.time()
    count = 0
    try:
        while not stop_event.is_set() and (time.time() - start) < args.seconds:
            state = step_state(state) # 시뮬레이터 상태 업데이트
            ts = state["ts"]

            # gps 데이터
            gps_payload = {
                "id": state["id"], "lat": state["lat"], "lon": state["lon"],
                "spd": state["spd"], "hdg": state["hdg"], "fix": state["fix"], "ts": ts,
                "seq": state["seq"],
            }
            publish_json(client_pub, gps_topic, gps_payload, qos=args.qos, retain=False, expiry=args.expiry)

            # 고도 데이터
            alt_payload = {"id": state["id"], "alt": state["alt"], "ts": ts, "seq": state["seq"]}
            publish_json(client_pub, alt_topic, alt_payload, qos=args.qos, retain=False, expiry=args.expiry)

            # 배터리 데이터
            bat_payload = {"id": state["id"], "bat": state["bat"], "ts": ts, "seq": state["seq"]}
            bat_qos = 1 if args.qos == 0 else args.qos
            publish_json(client_pub, t["battery"], bat_payload, qos=bat_qos,
                         retain=args.retain_battery, expiry=args.expiry)

            # 5초마다 한 번씩 현재 발행 상태 로그 출력 -> 디버깅 + 진행 상황 확인
            count += 1
            if count % int(max(1, args.rate*5)) == 0:
                print(f"[PUB] {count} msgs  lat={state['lat']:.6f} lon={state['lon']:.6f} "
                      f"alt={state['alt']:.1f} bat={state['bat']:.1f}% seq={state['seq']}")

            time.sleep(dt)

    except Exception as e:
        print("예외 발생:", e)
        raise

    finally:
        try:
            if normal_exit["flag"]:
                publish_value(client_pub, t["online"], "offline", qos=1, retain=True, expiry=0) # 드론 종료
                publish_value(client_pub, t["mode"], "IDLE", qos=1, retain=True, expiry=0) # 대기 모드 전환
        except Exception as e:
            print("종료 시 상태 변경 중 예외:", e)

        if client_sub:
            time.sleep(0.5)
            stats = stat.snapshot()
            print("\n=== QoS/수신 통계 ===")
            print("topic, recv_total, unique_seqs, duplicates, missing, first_seq, last_seq") 
            # mqtt 토픽 이름, 전체 메시지 수(중복 포함), 고유 번호 수, 중복 수신 메시지 수, 누락 메시지 수, 수신 메시지 중 첫 번째 시퀍스 번호, 수신한 메시지 중 마지막 시퀀스 번호

            for topic, s in stats.items():
                print(f"{topic}, {s['recv_total']}, {s['unique']}, {s['duplicates']}, {s['missing']}, {s['first_seq']}, {s['last_seq']}")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_fname = os.path.join(script_dir, f"mqtt_stats_{args.fleet}_{drone_id}.csv")

            try:
                with open(csv_fname, "w", newline='', encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["topic", "recv_total", "unique_seqs", "duplicates", "missing", "first_seq", "last_seq"])
                    for topic, s in stats.items():
                        writer.writerow([topic, s['recv_total'], s['unique'], s['duplicates'], s['missing'], s['first_seq'], s['last_seq']])
                print(f"[STATS] CSV 저장: {csv_fname}")
            except Exception as e:
                print("CSV 저장 실패:", e)

        client_pub.loop_stop()
        client_pub.disconnect()
        if client_sub:
            client_sub.loop_stop()
            client_sub.disconnect()
        print("[DONE] published messages:", count)

if __name__ == "__main__":
    main()

# 1. 드론 ID를 학번으로 변경하고 10분간 발행되도록 설정 완료

# 2. QoS0과 QoS1의 수신 통계 결과 비교 완료 -> 결과는 터미널에도 나오고 csv에 표로 저장됨
# 3. LWT와 Retained 메시지를 명확히 분리 설계하여 LWT는 클라이언트의 비정상 종료 알림을 전달하고
###  Retained는 현재 상태를 저장하고 전달하는 역할을 나눔