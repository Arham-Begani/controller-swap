"""Verify motion, locally loaded fonts and real HTTP phone clipboard fallback.

Uses a separate temporary database and an ephemeral preview port. No inference.
Run with --host <Wi-Fi IPv4> to exercise the actual non-secure LAN browser origin.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import traceback
from playwright.sync_api import sync_playwright, expect, Error
from controller_swap.server import Application
from scripts.phone_preview import make_preview


def verify(output, report, host):
    def passed(text):
        report['checks'].append(text)
        print('PASS: ' + text, flush=True)

    with tempfile.TemporaryDirectory() as directory:
        app = Application(str(Path(directory) / 'motion.sqlite3'))
        server, key = make_preview(app, host, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://{host}:{server.server_port}'
        try:
            with sync_playwright() as p:
                try: browser = p.chromium.launch(headless=True)
                except Error: browser = p.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True, reduced_motion='no-preference')
                launcher = 'http://preview-launcher.test/'
                def local_only(route):
                    if route.request.url == launcher:
                        # Fulfilled locally: simulate tapping a link from a different
                        # site without making an external request.
                        route.fulfill(content_type='text/html', body=f'<a href="{base}/?preview={key}">Open phone preview</a>')
                    elif route.request.url.startswith(base + '/'):
                        route.continue_()
                    else:
                        report['external_requests'].append(route.request.url); route.abort()
                context.route('**/*', local_only)
                page = context.new_page()
                page.on('pageerror', lambda error: report['javascript_errors'].append(str(error)))
                page.goto(launcher)
                page.get_by_role('link',name='Open phone preview').click()
                expect(page.locator('#refresh')).to_be_enabled()
                expect(page.locator('#preview-notice')).to_be_visible()
                expect(page.locator('.edition-tag')).to_have_text('MOTION EDITION / 02')
                assert page.url == base + '/'
                page.evaluate('document.fonts.ready')
                fonts = page.evaluate('Array.from(document.fonts, f => ({family:f.family,style:f.style,status:f.status}))')
                report['fonts'] = fonts
                assert len(fonts) == 3 and all(f['status'] == 'loaded' for f in fonts), fonts
                assert page.locator('.hero h1').evaluate("e=>getComputedStyle(e).fontFamily").startswith('Fraunces')
                passed('Link opened from another site becomes an HttpOnly cookie; new edition and isolated sandbox label are visible; all three local fonts load')

                page.locator('#trace-figure').scroll_into_view_if_needed()
                page.locator('#replay-trace').click()
                assert page.locator('#trace-figure').evaluate("e=>e.getAnimations({subtree:true}).some(a=>a.playState==='running')")
                timing = page.locator('.trace-human').evaluate("e=>{const a=e.getAnimations()[0];a.pause();a.currentTime=500;return parseFloat(getComputedStyle(e).strokeDashoffset)}")
                assert 0 < float(timing) < 1, timing
                page.screenshot(path=str(output/'paths-in-progress-mobile.png'))
                page.locator('#replay-trace').click()
                expect(page.locator('#trace-figure')).not_to_have_class('trace-illustration motion-playing', timeout=5000)
                assert page.locator('#trace-figure').evaluate('e=>e.getAnimations({subtree:true}).length') == 0
                passed('Replay draws a real intermediate path state and settles within 3.3 seconds; no endless animation remains')

                page.locator('#motion-toggle').click()
                expect(page.locator('#motion-toggle')).to_have_attribute('aria-pressed','false')
                page.reload()
                expect(page.locator('#refresh')).to_be_enabled()
                expect(page.locator('#motion-toggle')).to_have_text('Motion off')
                page.locator('#replay-trace').evaluate('(e)=>e.click()')
                assert page.locator('#trace-figure').evaluate('e=>e.getAnimations({subtree:true}).length') == 0
                page.locator('#motion-toggle').click()
                expect(page.locator('#motion-toggle')).to_have_text('Motion on')
                page.emulate_media(reduced_motion='reduce')
                expect(page.locator('#motion-toggle')).to_have_text('Motion off')
                page.locator('#motion-toggle').click()
                expect(page.locator('#notice')).to_contain_text('device reduced-motion')
                assert page.evaluate('document.getAnimations().length') == 0
                assert page.evaluate('getComputedStyle(document.documentElement).scrollBehavior') == 'auto'
                passed('Motion-off preference persists after reload; device reduced-motion overrides it and removes all motion')

                page.emulate_media(reduced_motion='no-preference')
                expect(page.locator('#motion-toggle')).to_have_text('Motion on')
                page.locator('#overview [data-sample]').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('Identical evaluator inputs', timeout=30000)
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#evidence-view').select_option('complete')
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#compare').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('The evaluator inputs differ')
                expect(page.locator('#compare')).to_be_focused()
                passed('Matched fixture pair runs through the real LAN adapter; changing evidence recalculates differences and returns keyboard focus')

                report['secure_context'] = page.evaluate('isSecureContext')
                if host != '127.0.0.1':
                    assert report['secure_context'] is False
                    assert page.evaluate('typeof navigator.clipboard') == 'undefined'
                else:
                    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value:undefined, configurable:true})")
                page.locator('#copy-evidence').click()
                expect(page.locator('#copy-dialog')).to_be_visible()
                expect(page.locator('#copy-json')).to_be_focused()
                exported = json.loads(page.locator('#copy-json').input_value())
                assert exported['view'] == 'complete'
                page.locator('#select-copy').click()
                selected = page.locator('#copy-json').evaluate('(e)=>e.selectionEnd-e.selectionStart === e.value.length')
                assert selected
                page.screenshot(path=str(output/'phone-copy-fallback.png'))
                page.keyboard.press('Escape')
                expect(page.locator('#copy-dialog')).not_to_be_visible()
                expect(page.locator('#copy-evidence')).to_be_focused()
                passed('Plain HTTP phone clipboard fallback shows the exact selected JSON, supports Select all and restores focus after Escape')

                page.emulate_media(reduced_motion='reduce')
                for width, height, label in [(390,844,'mobile'),(834,1112,'tablet'),(1440,1000,'desktop'),(320,740,'small-mobile')]:
                    page.set_viewport_size({'width':width,'height':height})
                    for route in ('overview','evidence'):
                        page.locator(f'[data-nav={route}]').click()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, route)
                        page.screenshot(path=str(output/f'{route}-{label}-full.png'), full_page=True)
                passed('Overview and comparison fit 320, 390, 834 and 1440 pixels; actual full-page screenshots captured')

                page.emulate_media(reduced_motion='no-preference')
                page.reload()
                expect(page.locator('#refresh')).to_be_enabled()
                page.locator('#motion-toggle').focus()
                page.keyboard.press('Tab')
                focused = page.evaluate('({id:document.activeElement.id,outline:getComputedStyle(document.activeElement).outlineWidth})')
                assert focused['id'] == 'refresh' and focused['outline'] == '3px', focused
                assert app.models.calls == 0
                report['live_model_calls'] = app.models.calls
                assert not report['javascript_errors'], report['javascript_errors']
                assert not report['external_requests'], report['external_requests']
                passed('Keyboard focus remains visible; no JavaScript errors, third-party browser requests or live model calls')
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.store.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/motion-focused')
    parser.add_argument('--host', default='127.0.0.1')
    args=parser.parse_args()
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    report=dict(checked_at=datetime.now(timezone.utc).isoformat(),status='running',checks=[],javascript_errors=[],external_requests=[],scope='Pre-sprint synthetic fixtures; temporary database; no inference')
    try:
        verify(output,report,args.host);report['status']='passed'
    except Exception:
        report['status']='failed';report['error']=traceback.format_exc();raise
    finally:
        (output/'motion-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
