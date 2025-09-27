#!/bin/bash

# 드론 데이터 관리 시스템 - 시연 환경 설정 스크립트
# 이 스크립트는 MQTT, Node-RED, Python 환경을 설정합니다.

echo "======================================"
echo "드론 데이터 관리 시스템 설정 시작"
echo "======================================"

# 색상 코드 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 운영체제 확인
OS="Unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="Linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="Mac"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    OS="Windows"
fi

echo -e "${GREEN}운영체제: $OS${NC}"

# 1. Python 패키지 설치
echo -e "\n${YELLOW}1. Python 패키지 설치${NC}"
pip install paho-mqtt

# 2. MQTT 브로커 설치 및 실행
echo -e "\n${YELLOW}2. MQTT 브로커 (Mosquitto) 설정${NC}"

if [[ "$OS" == "Linux" ]]; then
    # Ubuntu/Debian
    sudo apt-get update
    sudo apt-get install -y mosquitto mosquitto-clients
    sudo systemctl start mosquitto
    sudo systemctl enable mosquitto
    echo -e "${GREEN}Mosquitto가 설치되고 시작되었습니다.${NC}"
    
elif [[ "$OS" == "Mac" ]]; then
    # macOS (Homebrew 필요)
    if ! command -v brew &> /dev/null; then
        echo -e "${RED}Homebrew가 설치되어 있지 않습니다. 먼저 Homebrew를 설치하세요.${NC}"
        exit 1
    fi
    brew install mosquitto
    brew services start mosquitto
    echo -e "${GREEN}Mosquitto가 설치되고 시작되었습니다.${NC}"
    
elif [[ "$OS" == "Windows" ]]; then
    echo -e "${YELLOW}Windows에서는 수동으로 Mosquitto를 설치해야 합니다:${NC}"
    echo "1. https://mosquitto.org/download/ 에서 Windows 버전 다운로드"
    echo "2. 설치 후 서비스로 실행"
    echo "또는 Docker를 사용하세요: docker run -d -p 1883:1883 eclipse-mosquitto"
fi

# 3. Node-RED 설치 및 설정
echo -e "\n${YELLOW}3. Node-RED 설정${NC}"

# Node.js 확인
if ! command -v node &> /dev/null; then
    echo -e "${RED}Node.js가 설치되어 있지 않습니다. Node.js를 먼저 설치하세요.${NC}"
    echo "https://nodejs.org 에서 다운로드"
    exit 1
fi

# Node-RED 설치
if ! command -v node-red &> /dev/null; then
    echo "Node-RED 설치 중..."
    sudo npm install -g --unsafe-perm node-red
fi

# Node-RED 필요 모듈 설치
echo "Node-RED 대시보드 모듈 설치 중..."
cd ~/.node-red
npm install node-red-dashboard
npm install node-red-contrib-mqtt-broker

echo -e "${GREEN}Node-RED 설정 완료${NC}"

# 4. 디렉토리 구조 생성
echo -e "\n${YELLOW}4. 데이터 디렉토리 구조 생성${NC}"

mkdir -p drone_data/{raw,processed,archive,logs,backups,scripts}
mkdir -p drone_data/raw/$(date +%Y)/$(date +%m)/$(date +%d)
mkdir -p drone_data/logs/{node_red,mqtt_broker,application}
mkdir -p drone_data/backups/{daily,weekly,monthly}

echo -e "${GREEN}디렉토리 구조 생성 완료${NC}"

# 5. 실행 스크립트 생성
echo -e "\n${YELLOW}5. 실행 스크립트 생성${NC}"

# start_demo.sh 생성
cat > start_demo.sh << 'EOF'
#!/bin/bash

echo "======================================"
echo "드론 관제 시스템 시연 시작"
echo "======================================"

# Node-RED 실행 (백그라운드)
echo "1. Node-RED 시작..."
node-red &
NODE_RED_PID=$!

sleep 5

# 브라우저 열기
echo "2. 대시보드 열기..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:1880
    open http://localhost:1880/ui
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open http://localhost:1880
    xdg-open http://localhost:1880/ui
fi

echo "3. 10초 후 드론 시뮬레이터 시작..."
sleep 10

# 드론 시뮬레이터 실행
echo "4. 드론 시뮬레이터 실행 (3대)..."
python3 drone_simulator.py --drones 3

# 종료 처리
echo "시연 종료. Node-RED 종료 중..."
kill $NODE_RED_PID

EOF

chmod +x start_demo.sh

# stop_demo.sh 생성
cat > stop_demo.sh << 'EOF'
#!/bin/bash

echo "시연 환경 종료 중..."

# Node-RED 종료
pkill -f node-red

# Python 시뮬레이터 종료
pkill -f drone_simulator.py

# Mosquitto 종료 (옵션)
# sudo systemctl stop mosquitto

echo "모든 프로세스가 종료되었습니다."

EOF

chmod +x stop_demo.sh

# 6. 테스트 스크립트 생성
echo -e "\n${YELLOW}6. MQTT 테스트 스크립트 생성${NC}"

cat > test_mqtt.py << 'EOF'
import paho.mqtt.client as mqtt
import json
import time

def on_connect(client, userdata, flags, rc):
    print(f"MQTT 연결 상태: {'성공' if rc == 0 else f'실패 (코드: {rc})'}")
    if rc == 0:
        client.subscribe("drone/+/+/+")
        print("모든 드론 토픽 구독 완료")

def on_message(client, userdata, msg):
    print(f"토픽: {msg.topic}")
    try:
        data = json.loads(msg.payload.decode())
        print(f"데이터: {json.dumps(data, indent=2)}")
    except:
        print(f"데이터: {msg.payload.decode()}")
    print("-" * 50)

# MQTT 클라이언트 설정
client = mqtt.Client("test_subscriber")
client.on_connect = on_connect
client.on_message = on_message

print("MQTT 브로커 연결 테스트...")
try:
    client.connect("localhost", 1883, 60)
    print("테스트 시작 (Ctrl+C로 종료)")
    client.loop_forever()
except Exception as e:
    print(f"연결 실패: {e}")
EOF

echo -e "${GREEN}테스트 스크립트 생성 완료${NC}"

# 7. README 생성
cat > README.md << 'EOF'
# 드론 데이터 관리 시스템 시연 가이드

## 시스템 요구사항
- Python 3.7+
- Node.js 14+
- MQTT Broker (Mosquitto)

## 설치된 구성 요소
- MQTT Broker (Mosquitto) - 포트 1883
- Node-RED - 포트 1880
- Node-RED Dashboard - 포트 1880/ui
- Python 드론 시뮬레이터

## 빠른 시작

### 1. 자동 실행 (추천)
```bash
./start_demo.sh
```

### 2. 수동 실행

#### Step 1: MQTT 브로커 시작
```bash
# Linux/Mac
mosquitto

# Windows
net start mosquitto
```

#### Step 2: Node-RED 시작
```bash
node-red
```
브라우저에서 http://localhost:1880 접속

#### Step 3: Node-RED 플로우 임포트
1. http://localhost:1880 접속
2. 메뉴 → Import → node_red_flows.json 선택
3. Deploy 클릭

#### Step 4: 드론 시뮬레이터 실행
```bash
# 3대 드론 시뮬레이션
python drone_simulator.py --drones 3

# 단일 드론 실행
python drone_simulator.py --single DRONE_001
```

#### Step 5: 대시보드 확인
- Node-RED Dashboard: http://localhost:1880/ui
- HTML Dashboard: dashboard.html 파일 열기

## 시연 시나리오

### 1. 다중 드론 통합 관리 (1분)
- 3대 드론 동시 실행
- MQTT 토픽 구조 확인
- 실시간 데이터 스트림 표시

### 2. 체계적 데이터 구조 (1분)
- 파일 시스템 자동 저장 확인
- 폴더 구조 탐색
- 파일명 규칙 설명

### 3. 실시간 모니터링 (1분)
- 대시보드 실시간 업데이트
- 배터리 경고 시뮬레이션
- 지도 위치 추적

### 4. 이벤트 및 알림 (1분)
- 자동 알림 생성
- 연결 끊김 감지
- 긴급 상황 대응

## 문제 해결

### MQTT 연결 실패
```bash
# MQTT 브로커 상태 확인
sudo systemctl status mosquitto

# 포트 사용 확인
netstat -an | grep 1883
```

### Node-RED 실행 오류
```bash
# Node-RED 재설치
npm install -g --unsafe-perm node-red

# 모듈 재설치
cd ~/.node-red
npm install node-red-dashboard
```

### Python 모듈 오류
```bash
pip install --upgrade paho-mqtt
```

## 종료 방법
```bash
./stop_demo.sh
```

또는 수동으로:
- Ctrl+C로 Python 시뮬레이터 종료
- Ctrl+C로 Node-RED 종료
- mosquitto 서비스 중지

## 데이터 위치
- Raw 데이터: `drone_data/raw/`
- 로그: `drone_data/logs/`
- 백업: `drone_data/backups/`

## API 엔드포인트
- GET http://localhost:1880/api/drones - 모든 드론 상태

## MQTT 토픽 구조
- `drone/{DRONE_ID}/telemetry/gps` - GPS 데이터
- `drone/{DRONE_ID}/telemetry/battery` - 배터리 상태
- `drone/{DRONE_ID}/mission/status` - 미션 상태
- `drone/{DRONE_ID}/events/{TYPE}` - 이벤트

## 주요 기능
1. **실시간 데이터 수집**: MQTT를 통한 다중 드론 데이터 수집
2. **자동 파일 저장**: 계층적 폴더 구조에 자동 저장
3. **실시간 모니터링**: 웹 대시보드로 실시간 상태 확인
4. **경고 시스템**: 배터리 부족, 연결 끊김 자동 감지
5. **데이터 시각화**: 차트와 지도로 직관적 표시

## 확장 가능성
- 클라우드 연동 (AWS IoT, Azure IoT Hub)
- AI 예측 분석 추가
- 실제 드론 MAVLink 프로토콜 연동
- 영상 스트리밍 추가
- 3D 비행 경로 시각화

EOF

echo -e "${GREEN}README.md 생성 완료${NC}"

# 8. 최종 안내
echo -e "\n${GREEN}======================================"
echo "설정 완료!"
echo "======================================${NC}"
echo
echo "시연을 시작하려면:"
echo -e "${YELLOW}./start_demo.sh${NC}"
echo
echo "수동으로 실행하려면:"
echo "1. MQTT 브로커 시작: mosquitto"
echo "2. Node-RED 시작: node-red"
echo "3. 플로우 임포트: http://localhost:1880"
echo "4. 드론 시뮬레이터: python drone_simulator.py"
echo "5. 대시보드 확인: http://localhost:1880/ui"
echo
echo -e "${GREEN}준비가 완료되었습니다!${NC}"