# ble-clock-beacon 設計メモ

## 背景

[ble-clock](https://github.com/hideosasaki/ble-clock) は ESP32 + ULP で動く単3電池1本/約2.7年動作の低電力アナログ時計。HH:00/15/30/45 に約 500ms のスキャンウィンドウだけ開いて、Pi 側から流れてくる時刻アドバタイズを受信し、針位置を補正する。

本リポジトリは Pi 側 (Raspberry Pi 4, Bookworm, BlueZ) で動く systemd デーモン。役割は単純で「NTP 同期された UTC 秒を、決められた時間帯にだけ BLE アドバタイズで撒く」だけ。

権威ある仕様はすべて ble-clock 側に存在する:

- `main/time_adv.c`, `main/time_adv.h` — パケット形式とパース
- `main/test_support.c`, `main/test_time_adv.c` — テストベクタ
- ble-clock `docs/plan.md` — システム全体設計

このリポジトリは仕様書としては副本であり、ble-clock 側と差異があれば ble-clock 側が正。

## プロトコル

AD フレーム (BLE GAP 標準、合計 23 バイト):

```
[Length=22][Type=0x21][UUID 16B, LE][Payload 5B]
```

- Service UUID (128-bit): `74F6FB5B-EF7A-4A08-8F3E-A6C2BDFF2010`
- Payload:
  - offset 0..3: UNIX 秒 (UTC), uint32 LE
  - offset 4: コマンドフラグ (現状 `0x00` 固定、将来予約)

CRC・シーケンス番号・暗号化なし。受信側は UUID と長さ (val_len==21) で判定。

Advertising パラメータ:

- Interval: 100 ms (min=max)
- Channels: 37/38/39 全て
- Non-connectable / Non-scannable

## 送信スケジュール

時計の 15 分起床に対して ±30 秒のマージンで合計 60 秒の窓を 4 回/時:

- HH:59:30 〜 HH+1:00:30
- HH:14:30 〜 HH:15:30
- HH:29:30 〜 HH:30:30
- HH:44:30 〜 HH:45:30

時計側 RTC の精度 (±20 ppm の水晶) は数日のずれを許容できるので、起動時に NTP が間に合わなくても致命的ではない。それでも安全側に倒し、起動シーケンスは:

1. `timedatectl show -p NTPSynchronized --value` が `yes` を返すまで最大 5 分待機
2. さらに 30 秒スリープ (時刻のリープ補正等の安定化)
3. メインループへ

## ペイロード更新粒度

時計側 RTC は秒単位、UNIX 秒も秒単位なので、100 ms ごとに UNIX 秒値を更新する意味はあまりない。一方 BlueZ には登録済み advertisement の payload を差し替える API がなく、`UnregisterAdvertisement` → `RegisterAdvertisement` の往復が必要。10 Hz でこれを回すと DBus・kernel への負荷が読めない。

現状の実装方針:

- 更新粒度は **1 秒** (`UPDATE_INTERVAL_S = 1.0`)
- BlueZ 側が 100 ms ごとに「同じ payload を」周囲に撒いてくれるので、時計側から見るとほぼ同じ
- もし Pi 上で計測して 1 秒粒度でも CPU/DBus が辛ければ 2〜3 秒粒度まで落としても問題ない (時計側は受信した時刻から実際の受信時刻までのオフセットを補正していないため、原理的に最大 advertising interval 分のずれは元々許容している)

## モジュール構成

| モジュール | 役割 | BLE 依存 |
|---|---|---|
| `protocol.py` | ペイロード組み立て | なし |
| `scheduler.py` | 送信窓判定・次窓計算 | なし |
| `ntp.py` | `timedatectl` の同期確認 | なし (subprocess のみ) |
| `advertiser.py` | BlueZ DBus ラッパ | あり (`dbus-next`) |
| `daemon.py` | メインループ | あり |

BLE 非依存層 (`protocol`, `scheduler`) はピュア関数で `pytest` から検証する。テストベクタは ble-clock 側 `test_time_adv.c` と一致させる (`0xDEADBEEF` ケース)。

## BlueZ への登録

`org.bluez.LEAdvertisingManager1` インターフェースに `LEAdvertisement1` 実装オブジェクトをエクスポートし、`RegisterAdvertisement` を呼ぶ。プロパティは以下:

- `Type = "broadcast"`
- `ServiceUUIDs = []` (空にする。UUID をここに含めると BlueZ が
  Complete 128-bit Service UUIDs (18 byte) + ServiceData (23 byte) +
  Flags (3 byte) で 31 byte の legacy 上限を超えたと判定して Extended
  Advertising 経路に切り替える。Realtek RTL8761BU はその経路で HCI が
  Success を返しても RF を放射しないので、独立した受信器 (Mac/iPhone/
  ESP32) のいずれからも見えなくなる)
- `ServiceData = { SERVICE_UUID: <5 byte payload> }`
- `MinInterval = MaxInterval = 100` (ms)

`ServiceData` に 128-bit UUID を指定すると BlueZ は AD type 0x21 として送出する (BlueZ ≥ 5.50)。実機投入時に `btmon` で 0x21 になっていることを必ず確認する。もし 0x16 等にされてしまう環境があれば、`Data` プロパティ (`{0x21: bytes}`) で生フレームを直指定する経路に切り替える。

## テスト

- ユニット (任意のホストで): `pytest`
  - `tests/test_protocol.py`: `0xDEADBEEF` 等の既知ベクタで `build_payload` を検証
  - `tests/test_scheduler.py`: 窓境界 (HH:59:29 vs HH:59:30, HH:00:29 vs HH:00:30) の真偽
- HIL (Pi 上):
  1. `sudo systemctl start ble-clock-beacon`
  2. `sudo btmon` で AD type 0x21 が送信窓中だけ流れることを確認
  3. 実機の時計を 1 サイクル動かし、ble-clock 側 BTHome の `0x50` (last sync UNIX 秒) が更新されることを HA で確認

## 未確定項目 (実装中に決める)

- `ServiceData` 経由で AD type 0x21 が実際に出るか実機確認
- `UPDATE_INTERVAL_S` の最終値 (1 秒で OK か、もっと下げてよいか)
- systemd unit の `User=` / `Group=` (root 回避、`bluetooth` グループ運用)
