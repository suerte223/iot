import os, glob
import pandas as pd

DATA_DIR = os.path.abspath("./data")
OUT_LOW = os.path.join(DATA_DIR, "low_battery.csv")

files = sorted(glob.glob(os.path.join(DATA_DIR, "telemetry_*.csv")))
if not files:
    print("분석할 CSV가 존재하지 않음 먼저 subscriber로 데이터를 수집하세요.")
    raise SystemExit(0)

dfs = []
for f in files:
    try:
        df = pd.read_csv(f)
        dfs.append(df)
    except Exception as e:
        print(f"[WARN] {f} 읽기 실패: {e}")

if not dfs:
    print("유효한 데이터가 없습니다.")
    raise SystemExit(0)

data = pd.concat(dfs, ignore_index=True)

mean_batt = data["battery"].mean()
print(f"평균 배터리: {mean_batt:.2f}%")

low = data[data["battery"] < 20].copy()
print(f"저전력(<20%) 행 수: {len(low)}")

if len(low) > 0:
    low.to_csv(OUT_LOW, index=False, encoding="utf-8")
    print(f"저전력 데이터 저장: {OUT_LOW}")
