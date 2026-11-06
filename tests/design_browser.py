"""Focused redesign checks in an isolated database, using real browser/HTTP.

No external requests, model inference, production data writes or new dependencies.
Screenshots are genuine synthetic-fixture UI, not live-model results.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import time
import traceback

from playwright.sync_api import sync_playwright, expect, Error
from controller_swap.server import Application, make_server


class Checks(list):
    def append(self, message):
        super().append(message)
        print('PASS: ' + message, flush=True)


def verify(output, report):
    with tempfile.TemporaryDirectory() as directory:
        app = Application(str(Path(directory) / 'design.sqlite3'))
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Error:
                    browser = p.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                external_requests = []

                def local_only(route):
                    if route.request.url.startswith(base + '/'):
                        route.continue_()
                    else:
                        external_requests.append(route.request.url)
                        route.abort()

                context.route('**/*', local_only)
                page = context.new_page()
                page.on('pageerror', lambda error: report['javascript_errors'].append(str(error)))
                page.goto(base)
                expect(page.locator('#refresh')).to_be_enabled()
                expect(page.locator('#stats .stat')).to_have_count(4)
                page.keyboard.press('Tab')
                expect(page.locator('.skip-link')).to_be_focused()
                page.keyboard.press('Enter')
                expect(page.locator('#main')).to_be_focused()
                assert page.url == base + '/'
                report['checks'].append('Keyboard skip link focuses the workspace without changing the route')

                # Exercise the exact new-user primary action, including an empty DB.
                started = time.perf_counter()
                page.locator('#overview [data-sample]').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('Identical evaluator inputs', timeout=30000)
                expect(page.locator('#compare')).to_be_enabled()
                report['first_sample_seconds'] = round(time.perf_counter() - started, 3)
                expect(page.locator('#session-count')).to_have_text('72 stored sessions')
                expect(page.locator('#notice')).to_contain_text('No model calls')
                expect(page.locator('#evidence h1')).to_be_focused()
                left_label = page.locator('#evidence-run option:checked').inner_text()
                assert left_label.startswith('Mock file placement / Human steps / WORKER A / rep 1 /')
                assert page.locator('[data-nav=evidence]').get_attribute('aria-current') == 'page'
                page.locator('#evidence [data-sample]').click()
                expect(page.locator('#compare')).to_be_enabled()
                assert len(app.store.runs()) == 72
                report['checks'].append('One-click sample creates 72 synthetic sessions once, selects a matched pair and reuses it without duplication')

                page.locator('#evidence-view').select_option('complete')
                expect(page.locator('#comparison-result')).to_be_hidden()
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#compare').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('The evaluator inputs differ')
                expect(page.locator('#compare')).to_be_focused()
                expect(page.locator('#comparison-panels .changed').first).to_be_visible()
                page.locator('#evidence [data-sample]').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('Identical evaluator inputs')
                report['checks'].append('Complete records reveal constructed differences; sample reset restores outward-only input and recalculates')

                page.route('**/view?view=messages', lambda route: route.abort('connectionrefused'))
                page.locator('#evidence-view').select_option('messages')
                expect(page.locator('#view-warning')).to_contain_text('Evidence not loaded')
                expect(page.locator('#trace .event')).to_have_count(0)
                page.locator('#copy-evidence').click()
                expect(page.locator('#notice')).to_contain_text('Inspect a record first')
                page.unroute('**/view?view=messages')
                page.locator('#evidence [data-sample]').click()
                expect(page.locator('#comparison-result')).to_be_visible()
                expect(page.locator('#trace .event')).to_have_count(8)
                report['checks'].append('Failed evidence request clears the previous record and prevents copying stale JSON; retry restores the exact sample')

                page.locator('[data-nav=studio]').click()
                page.locator('#session-search').fill('Mock file placement')
                expect(page.locator('#runs tr')).to_have_count(12)
                expect(page.locator('#session-count')).to_have_text('12 of 72 sessions')
                page.locator('#session-search').fill('no such task 98765')
                expect(page.locator('#runs')).to_contain_text('No matching sessions')
                page.locator('#session-search').fill('')
                expect(page.locator('#runs tr')).to_have_count(72)
                report['checks'].append('Session search filters by meaningful task and shows a recoverable no-match state')

                page.locator('#open-jump').focus()
                page.keyboard.press('Control+k')
                expect(page.locator('#jump-dialog')).to_be_visible()
                expect(page.locator('#jump-search')).to_be_focused()
                page.keyboard.press('Escape')
                expect(page.locator('#open-jump')).to_be_focused()
                page.locator('#open-jump').click()
                page.locator('#jump-search').fill('protocol')
                expect(page.locator('#jump-results button')).to_have_count(1)
                page.keyboard.press('Tab')
                page.keyboard.press('Enter')
                expect(page.locator('#jump-dialog')).not_to_be_visible()
                expect(page.locator('#protocol h1')).to_be_focused()
                assert page.title() == 'Protocol & exports — Controller Swap'
                report['checks'].append('Ctrl+K, native dialog focus, Escape return, filtering and keyboard route selection work')

                # A failed GET is intentional. The actual server and DB remain intact.
                page.route('**/api/status', lambda route: route.abort('connectionrefused'))
                page.locator('#refresh').click()
                expect(page.locator('#notice.error')).to_contain_text('Cannot reach the local workspace')
                expect(page.locator('#refresh')).to_be_enabled()
                page.wait_for_timeout(9300)
                expect(page.locator('#notice.error')).to_be_visible()
                page.unroute('**/api/status')
                page.locator('#refresh').click()
                expect(page.locator('#notice')).to_contain_text('Workspace refreshed')
                expect(page.locator('#notice')).not_to_have_class('error')
                page.route('**/api/status', lambda route: route.abort('connectionrefused'))
                page.locator('#refresh').click()
                expect(page.locator('#notice.error')).to_contain_text('Cannot reach the local workspace')
                page.locator('#notice button').click()
                expect(page.locator('#notice')).to_be_empty()
                page.unroute('**/api/status')
                report['model_option_state'] = page.evaluate("({backend:document.getElementById('model-option').outerHTML,evaluator:document.querySelector('#method option[value=model_evidence]').outerHTML})")
                assert page.locator('#model-option').evaluate('(e)=>e.disabled'), report['model_option_state']
                assert page.locator('#method option[value=model_evidence]').evaluate('(e)=>e.disabled'), report['model_option_state']
                report['checks'].append('Simulated offline error persists beyond nine seconds, can be dismissed and recovers; unavailable model options stay disabled')

                # Real local deterministic diagnostic execution, not provider stubs.
                page.locator('[data-nav=analysis]').click()
                for method in ('evidence_checklist', 'surface_heuristic', 'always_abstain'):
                    for view in ('actions', 'messages', 'complete'):
                        page.locator('#method').select_option(method)
                        page.locator('#eval-view').select_option(view)
                        page.locator('#evaluate').click()
                        expect(page.locator('#notice')).to_contain_text('Evaluated 72 completed sessions')
                        expect(page.locator('#evaluate')).to_be_enabled()
                expect(page.locator('#metrics tr')).to_have_count(9)
                page.set_viewport_size({'width': 390, 'height': 844})
                first = page.locator('#metrics tr').first
                expect(first.locator('.metric-detail').first).to_be_hidden()
                expect(first.locator('td').last).to_contain_text('0 failed; 0 missing')
                first.locator('.metric-toggle').click()
                expect(first.locator('.metric-detail').first).to_be_visible()
                expect(first.locator('.metric-toggle')).to_have_attribute('aria-expanded', 'true')
                page.keyboard.press('Enter')
                expect(first.locator('.metric-detail').first).to_be_hidden()
                report['checks'].append('Mobile diagnostics retain denominators and collection gaps; secondary metrics expand and collapse by keyboard')

                # Measure real computed color pairs, including controls and focus.
                report['contrast'] = page.evaluate('''() => {
                  const root=getComputedStyle(document.documentElement);
                  const color=n=>root.getPropertyValue(n).trim();
                  const luminance=hex=>{
                    const rgb=hex.replace('#','').match(/.{2}/g).map(v=>parseInt(v,16)/255)
                      .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
                    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
                  };
                  const pairs=[['Body text',color('--ink'),color('--paper'),4.5],
                    ['Secondary text',color('--muted'),color('--paper'),4.5],
                    ['Accent text',color('--accent'),color('--paper'),4.5],
                    ['Primary button','#ffffff',color('--accent'),4.5],
                    ['Matching evidence',color('--teal'),color('--soft'),4.5],
                    ['Focus ring',color('--focus'),color('--paper'),3],
                    ['Control boundary',color('--control-border'),color('--surface'),3]];
                  return pairs.map(([label,fg,bg,minimum])=>{
                    const a=luminance(fg),b=luminance(bg);
                    return {label,fg,bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),minimum};
                  });
                }''')
                assert all(item['ratio'] >= item['minimum'] for item in report['contrast'])
                report['checks'].append('Seven measured contrast pairs meet text, focus and control-boundary thresholds; this is not a full WCAG audit')

                # Clear the timed success notification before screenshots.
                expect(page.locator('#notice')).to_be_empty(timeout=10000)
                for width, height, name in ((390, 844, 'mobile'), (834, 1112, 'tablet'), (1440, 1000, 'desktop')):
                    page.set_viewport_size({'width': width, 'height': height})
                    for section in ('overview', 'studio', 'evidence', 'analysis', 'protocol'):
                        page.locator(f'[data-nav={section}]').click()
                        expect(page.locator(f'#{section} h1')).to_be_focused()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, section)
                        for nav in page.locator('[data-nav]').all():
                            bounds = nav.bounding_box()
                            assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1
                        if section == 'evidence':
                            page.locator('#compare').click()
                            expect(page.locator('#comparison-verdict')).to_contain_text('Identical evaluator inputs')
                            expect(page.locator('#comparison-result')).to_be_visible()
                            expect(page.locator('#compare')).to_be_enabled()
                            page.locator('#comparison-result').screenshot(path=str(output / f'comparison-{name}.png'))
                        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                        page.screenshot(path=str(output / f'{section}-{name}.png'), full_page=True)
                        if section == 'overview':
                            page.screenshot(path=str(output / f'first-impression-{name}.png'))
                    report['checks'].append(f'All five pages fit {width}px with all navigation choices visible; full-page screenshots captured')

                page.set_viewport_size({'width': 320, 'height': 800})
                for section in ('overview', 'studio', 'evidence', 'analysis', 'protocol'):
                    page.locator(f'[data-nav={section}]').click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), section
                assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == 'auto'
                page.locator('[data-nav=overview]').focus()
                page.keyboard.press('Tab')
                expect(page.locator('[data-nav=studio]')).to_be_focused()
                assert page.locator('[data-nav=studio]').evaluate("e=>getComputedStyle(e).outlineStyle") != 'none'
                page.screenshot(path=str(output / 'keyboard-focus-320.png'))
                report['checks'].append('320px reflow has no document overflow; reduced-motion disables smooth scrolling and keyboard focus is visible')
                page.locator('[data-nav=studio]').click()
                region = page.locator('[aria-label="Stored sessions table"]')
                region.focus()
                page.keyboard.press('ArrowRight')
                page.wait_for_function("document.querySelector('[aria-label=\"Stored sessions table\"]').scrollLeft > 0")
                report['checks'].append('Wide session table is named, focusable and horizontally scrollable with the keyboard')
                assert not external_requests, external_requests
                assert not report['javascript_errors'], report['javascript_errors']
                assert app.models.calls == 0
                report['fixture_sessions'] = len(app.store.runs())
                report['external_requests'] = external_requests
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            app.store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'checks': Checks(), 'javascript_errors': [], 'live_model_calls': 0,
              'scope': 'Isolated synthetic fixtures; deliberate offline failure; no new inference'}
    try:
        verify(output, report)
        report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        report['traceback'] = traceback.format_exc()
        raise
    finally:
        (output / 'design-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
