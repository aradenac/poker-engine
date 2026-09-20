"""Serve site/ on :8765; run with a Python environment containing Playwright."""
import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto('http://127.0.0.1:8765/index.html')
        await page.evaluate('''() => {
          window.smokeDone=false;
          const s=window.pokerComputeScheduler;
          const snapshot={hero:[8,24],board:[41,19,25],method:'mc',trials:20000,
            opponents:[{hands:[{hand:'AA',frequency:100},{hand:'76s',frequency:100}]}]};
          window.smokeWork=Promise.all(['background','prefetch','explicit','replayer','explicit','background'].map(kind=>new Promise((resolve,reject)=>{
            const worker=createCalcWorker({kind});
            worker.onmessage=e=>{if(e.data.type==='progress')return;
              cleanupReplayWorker(worker);
              if(e.data.type==='error')reject(Error(e.data.message));else resolve(e.data.out);
            };
            worker.onerror=reject;worker.postMessage(snapshot);
          }))).then(results=>{window.smokeResults=results;window.smokeDone=true;});
        }''')
        for _ in range(10):
            await page.keyboard.press('Tab')
            await page.wait_for_timeout(25)
        await page.wait_for_function('window.smokeDone', timeout=60000)
        metrics = await page.evaluate('window.pokerComputeScheduler.snapshot()')
        assert not errors, errors
        assert metrics['maxConcurrency'] <= 2, metrics
        assert metrics['workersActive'] == 0, metrics
        assert metrics['interactionMs'], metrics
        assert max(metrics['interactionMs']) < 250, metrics
        print(json.dumps(metrics, indent=2))
        await browser.close()

asyncio.run(main())
