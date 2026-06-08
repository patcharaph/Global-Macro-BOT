# FlowMacro — Phase 4 Next Plan: IBKR Live Integration

**สถานะปัจจุบัน:** Phase 3 กำลังรัน (paper trading week 1, เริ่ม 2026-06-06)
**Phase 4 trigger:** Phase 3 paper pass (4–8 สัปดาห์) + ทุนถึง $10,000 USD

---

## Trigger Checklist ก่อนเริ่ม Phase 4

- [ ] Paper trading รัน ≥ 4 สัปดาห์ ไม่มี silent failure
- [ ] Paper portfolio track regime ได้สมเหตุสมผล (อยู่ใน ±20% ของ backtest projection)
- [ ] ทุน top-up ถึง $10,000 USD (จาก $3,000 ปัจจุบัน)
- [ ] IBKR Singapore KYC อนุมัติแล้ว (เริ่มยื่นได้ทันทีไม่ต้องรอ Phase 3 เสร็จ)
- [ ] Backtest Sharpe ≥ 0.7 บน out-of-sample (ผ่านแล้ว Phase 3 Branch B)

---

## Phase 4 Scope

### P4-A — IBKR Account Setup (ทำได้เลยตอนนี้)

| งาน | รายละเอียด |
|-----|------------|
| เปิดบัญชี IBKR Singapore | ibkr.com → Individual → Singapore entity |
| KYC documents | Passport + proof of address + source of funds |
| ฝากเงิน $10,000 USD | SWIFT transfer จาก ไทย → IBKR |
| ติดตั้ง TWS / IB Gateway | สำหรับ API connection (IB Gateway แนะนำ — headless) |
| เปิด paper account ใน IBKR | ทดสอบ API ก่อน live (ไม่ต้องใช้ทุนจริง) |

**หมายเหตุ:** KYC ใช้เวลา 1–2 สัปดาห์ — ยื่นเลยเพื่อไม่รอ

---

### P4-B — IBKRBroker Implementation

ขยาย abstract interface `BrokerBase` (`flowmacro/broker/base.py`) ที่วางแผนไว้ Phase 2:

```python
# flowmacro/broker/ibkr.py
class IBKRBroker(BrokerBase):
    def place_order(self, ticker, qty, side) -> OrderResult: ...
    def get_positions(self) -> dict[str, float]: ...
    def get_account_value(self) -> float: ...
    def reconcile(self, target_weights) -> list[Order]: ...
```

**งานหลัก:**
- [ ] `ibkr.py` — IBKRBroker implement ผ่าน `ib_insync` library
- [ ] Order routing: weekly rebalance weights → market orders (open Monday หลัง signal Friday)
- [ ] Fill confirmation: poll order status, log actual fill price vs target
- [ ] Position reconciliation: เทียบ actual IBKR positions vs expected weights
- [ ] Transaction cost model: bid/ask spread + $0.005/share commission IBKR

---

### P4-C — Weekly Scheduler Integration

```
weekly.py (Phase 4 flow):
  ... (regime detection เหมือนเดิม) ...
  ├── ถ้า IBKR_LIVE=true → IBKRBroker.reconcile(weights)
  ├── ถ้า IBKR_LIVE=false → PaperBroker (simulation เดิม ยังรันคู่กัน)
  └── Log actual fills + slippage ลง Supabase
```

**env var:** `IBKR_LIVE=true/false` — kill switch ปิด live ได้ทันที

---

### P4-D — Dashboard Upgrade

- [ ] หน้า Paper Trading: เพิ่มแถว "Live Portfolio" เทียบกับ simulation
- [ ] Live P&L (USD + THB equivalent) real-time จาก IBKR
- [ ] Slippage tracker: actual fill vs close price
- [ ] Drawdown Level 1-3 alert badge

---

### P4-E — ML Graduation (Dec 2026)

XGBoost shadow mode รันอยู่แล้วตั้งแต่ Phase 3 — graduation criteria:

| เกณฑ์ | Target |
|--------|--------|
| Agreement กับ rule-based | ≥ 70% |
| Walk-forward Sharpe (ML) | > rule-based Sharpe |
| ระยะเวลา shadow | ≥ 6 เดือน |

ถ้าผ่าน → `classifier.py` ใช้ ML output เป็น primary, rule-based เป็น fallback

---

## Timeline

```
ตอนนี้ (Jun 2026)
  → เปิด IBKR KYC (ทำได้เลย ไม่ต้องรอ Phase 3)
  → Paper trading สัปดาห์ที่ 1–8 (simulation รัน)

Jul–Aug 2026
  → P4-A: IBKR account ready + funded
  → P4-B: IBKRBroker code (2–3 สัปดาห์)
  → ทดสอบบน IBKR paper account (ไม่ใช่เงินจริง)

Aug–Sep 2026 (เป้าหมาย go-live)
  → Phase 3 paper pass → flip IBKR_LIVE=true
  → Live trading เริ่มด้วย ≤ 30% ของทุน ($3,000 จาก $10,000)

Dec 2026
  → ML graduation assessment
  → ถ้าผ่าน → XGBoost เป็น primary classifier
```

---

## Risk Controls ก่อน Go-Live

| Control | Implementation |
|---------|---------------|
| Kill switch | `IBKR_LIVE=false` ใน GitHub Secrets → หยุด live ทันที |
| Max position size | ≤ 25% per instrument (enforce ใน reconcile()) |
| Daily drawdown limit | ถ้า portfolio ลง > 5% ใน 1 วัน → email alert + หยุด order ใหม่ |
| Drawdown Level 1 | -10% → ลด position 50% |
| Drawdown Level 2 | -15% → ออกทุก position → cash |
| Drawdown Level 3 | -20% → หยุดระบบ → manual review |

---

## สิ่งที่ไม่ต้อง build ใน Phase 4

- Alpaca integration (skip ถาวร)
- Options / futures / leveraged ETF
- Intraday rebalancing
- Multi-account management
- Mobile app

---

## Dependencies

| Package | ใช้ทำอะไร |
|---------|----------|
| `ib_insync` | IBKR TWS/Gateway Python API |
| `ib_insync.Stock` | US ETF order routing |
| `ib_insync.Forex` | FX exposure tracking (future) |

---

*สร้าง: 2026-06-08 | อัปเดตเมื่อ Phase 3 paper pass*
