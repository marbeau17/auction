"""
Comprehensive E2E Quality Assurance Test
Tests all user flows against the live system.
"""
import sys
import requests

BASE_URL = "https://auction-ten-iota.vercel.app"
ADMIN_EMAIL = "admin@carchs.com"
ADMIN_PASS = "Admin2024!"
SALES_EMAIL = "sales@carchs.com"
SALES_PASS = "Sales2024!"

results = []

def test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not condition else ""))

def run_tests():
    session = requests.Session()

    print("=" * 60)
    print("CVLPOS E2E Quality Assurance Test")
    print("=" * 60)

    # 1. Health Check
    print("\n--- 1. Health Check ---")
    r = session.get(f"{BASE_URL}/health")
    test("Health endpoint", r.status_code == 200, f"status={r.status_code}")
    test("Health returns OK", r.json().get("status") == "ok")

    # 2. Login Flow
    print("\n--- 2. Authentication ---")
    r = session.get(f"{BASE_URL}/login")
    test("Login page loads", r.status_code == 200)

    r = session.post(f"{BASE_URL}/auth/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, allow_redirects=False)
    test("Admin login succeeds", r.status_code == 302, f"location={r.headers.get('location')}")
    test("Login sets cookies", "access_token" in session.cookies.get_dict())

    # 3. Dashboard
    print("\n--- 3. Dashboard ---")
    r = session.get(f"{BASE_URL}/dashboard")
    test("Dashboard loads", r.status_code == 200)
    test("Dashboard has KPI", "kpi-card" in r.text)
    test("Dashboard has simulations", "シミュレーション" in r.text)

    # 4. KPI API
    print("\n--- 4. KPI API ---")
    r = session.get(f"{BASE_URL}/api/v1/dashboard/kpi")
    test("KPI API returns 200", r.status_code == 200)
    test("KPI has values", "kpi-card__value" in r.text)

    # 5. Simulation Page
    print("\n--- 5. Simulation Input ---")
    r = session.get(f"{BASE_URL}/simulation/new")
    test("Simulation page loads", r.status_code == 200)
    test("Has maker dropdown", "いすゞ" in r.text or "日野" in r.text)
    test("Has body type dropdown", "ウイング" in r.text)
    test("Has equipment checkboxes", "checkbox" in r.text)

    # 6. Model Cascade
    print("\n--- 6. Model Cascade ---")
    r = session.get(f"{BASE_URL}/api/v1/masters/models-by-maker", params={"maker_name": "日野"})
    test("Model cascade works", r.status_code == 200)
    test("Returns Profia", "プロフィア" in r.text)

    # 7. Simulation Calculate
    print("\n--- 7. Simulation Calculate ---")
    calc_data = {
        "maker": "日野", "model": "プロフィア", "mileage_km": "150000",
        "acquisition_price": "15000000", "book_value": "8000000",
        "body_type": "ウイング", "target_yield_rate": "8",
        "lease_term_months": "36", "vehicle_class": "LARGE",
        "registration_year_month": "2021"
    }
    r = session.post(f"{BASE_URL}/api/v1/simulations/calculate", data=calc_data)
    test("Calculate returns 200", r.status_code == 200)
    test("Has KPI cards", "kpi-card" in r.text)
    test("Has charts", "canvas" in r.text)
    test("Has schedule table", "data-table" in r.text)
    test("Has value transfer chart", "chart-value-transfer" in r.text)
    test("Has NAV chart", "chart-nav" in r.text)
    test("Has P&L chart", "chart-pnl" in r.text)
    test("Has recommended price", "推奨買取価格" in r.text)
    test("Has assessment", "推奨" in r.text or "要検討" in r.text or "非推奨" in r.text)

    # 8. Market Data
    print("\n--- 8. Market Data ---")
    r = session.get(f"{BASE_URL}/market-data")
    test("Market data loads", r.status_code == 200)
    test("Has vehicles", "data-table" in r.text or "table" in r.text)
    test("Has maker filter", "メーカー" in r.text)
    test("Shows maker names", "日野" in r.text or "いすゞ" in r.text)

    # 9. Simulation History
    print("\n--- 9. Simulation History ---")
    r = session.get(f"{BASE_URL}/simulations")
    test("History page loads", r.status_code == 200)
    test("Has simulation list", "シミュレーション" in r.text)

    # 10. Logout
    print("\n--- 10. Logout ---")
    r = session.post(f"{BASE_URL}/auth/logout", allow_redirects=False)
    test("Logout redirects", r.status_code == 302)

    # 11. Unauth protection
    print("\n--- 11. Access Control ---")
    session2 = requests.Session()
    r = session2.get(f"{BASE_URL}/dashboard", allow_redirects=False)
    test("Unauth dashboard redirects", r.status_code == 302)
    test("Redirects to login", "/login" in r.headers.get("location", ""))

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"TOTAL: {passed} PASS / {failed} FAIL / {len(results)} tests")
    print("=" * 60)

    if failed > 0:
        print("\nFailed tests:")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"  ✗ {name}: {detail}")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_tests())
