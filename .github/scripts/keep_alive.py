import os
import sys
from playwright.sync_api import sync_playwright

url = os.environ.get("STREAMLIT_APP_URL")
if not url:
    print("Error: STREAMLIT_APP_URL environment variable is missing.")
    print("Please set STREAMLIT_APP_URL in your GitHub Repository Secrets.")
    sys.exit(1)

def run():
    print(f"Target URL: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # Search for Streamlit's wake up button
            button = page.locator("button", has_text="get this app back up")
            if button.count() > 0 and button.first.is_visible():
                print("App is sleeping! Clicking 'Yes, get this app back up!' button...")
                button.first.click()
                page.wait_for_timeout(10000)
                print("Wake-up request submitted successfully.")
            else:
                print("App is already awake!")
        except Exception as e:
            print(f"Error during keep-alive execution: {e}")
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    run()
