import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # Launch browser headless
        browser = await p.chromium.launch()
        
        # Emulate a mobile device (iPhone 13)
        iphone_13 = p.devices['iPhone 13']
        context = await browser.new_context(**iphone_13)
        page = await context.new_page()
        
        # Go to the live site
        await page.goto('http://10.0.0.2:8090')
        
        # Wait for the app to load
        await page.wait_for_timeout(3000)
        
        # Capture the first screenshot (main chat)
        await page.screenshot(path='/home/joshu/repos/sobriety-copilot/store_assets/phone_screenshot_main.png')
        
        # Try to find a menu button and click it to open a drawer/menu for a second screenshot
        try:
            menu_btn = await page.query_selector('button[aria-label="Menu"], .menu-icon, .hamburger, [title="Menu"]')
            if menu_btn:
                await menu_btn.click()
                await page.wait_for_timeout(1000)
                await page.screenshot(path='/home/joshu/repos/sobriety-copilot/store_assets/phone_screenshot_menu.png')
        except Exception as e:
            print("Could not take second screenshot:", e)
            
        await browser.close()
        print("Screenshots captured successfully!")

asyncio.run(main())
