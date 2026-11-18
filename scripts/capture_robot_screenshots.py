import os
import subprocess
import time
from playwright.sync_api import sync_playwright

output_dir = os.path.abspath("docs/screenshots")
os.makedirs(output_dir, exist_ok=True)

print("Starting Next.js server for screenshot capture...")
server_process = subprocess.Popen(
    ["cmd.exe", "/c", "npm", "run", "start", "--prefix", "frontend", "--", "-p", "3000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

# Wait for server to boot
time.sleep(3)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        page = context.new_page()

        # Pre-seed authenticated customer session in localStorage
        page.goto("http://localhost:3000/login")
        page.evaluate(
            """() => {
            const mockSession = {
                user_id: "00000000-0000-0000-0000-000000000001",
                customer_id: "00000000-0000-0000-0000-000000000002",
                email: "customer@prestige.com",
                role: "customer",
                full_name: "Sarah Jenkins",
                accessToken: "mock_authenticated_jwt_token_for_ui_verification",
                refreshToken: "mock_refresh_token"
            };
            localStorage.setItem("auth_session", JSON.stringify(mockSession));
        }"""
        )

        # Navigate to customer portal
        page.goto("http://localhost:3000/customer")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Capture 1: Minimized floating robot avatar widget
        shot1 = os.path.join(output_dir, "01_customer_portal_minimized_robot.png")
        page.screenshot(path=shot1, full_page=False)
        print(f"Captured: {shot1}")

        # Click the floating robot widget to expand conversation panel
        robot_btn = page.locator('button[aria-label="Open Real Estate Voice AI Assistant"]')
        if robot_btn.count() > 0:
            robot_btn.click()
            time.sleep(1.5)

        # Capture 2: Expanded conversation panel with 3D robot avatar
        shot2 = os.path.join(output_dir, "02_expanded_robot_panel.png")
        page.screenshot(path=shot2, full_page=False)
        print(f"Captured: {shot2}")

        # Switch main view to 3D Robot mode if not already
        robot_view_btn = page.locator('button:has-text("3D Robot")')
        if robot_view_btn.count() > 0:
            robot_view_btn.click()
            time.sleep(1)

        # Capture 3: Main Customer Portal 3D Robot view
        shot3 = os.path.join(output_dir, "03_customer_portal_3d_robot_view.png")
        page.screenshot(path=shot3, full_page=False)
        print(f"Captured: {shot3}")

        browser.close()
        print("Screenshots captured successfully!")

finally:
    print("Terminating Next.js server...")
    server_process.kill()
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(server_process.pid)], capture_output=True)
    except Exception:
        pass
