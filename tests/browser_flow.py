"""Real browser verification against an isolated local database; no live models."""
import argparse
import json
import os
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, Error

from controller_swap.server import Application, make_server
from controller_swap.models import ModelRequestError


def verify(artifacts):
    errors, network_errors = [], []
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        app = Application(os.path.join(directory, 'browser.sqlite3'))
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
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('requestfailed', lambda request: network_errors.append({'url': request.url, 'error': request.failure}))
                page.goto(base)
                expect(page.locator('#stats .stat')).to_have_count(4)
                page.screenshot(path=str(artifacts / 'overview-desktop.png'), full_page=True)
                checks.append('Dashboard renders with status from the API')

                page.locator('#seed').click()
                expect(page.locator('#session-count')).to_have_text('72 stored sessions')
                page.locator('#seed').click()
                expect(page.locator('#notice')).to_contain_text('nothing duplicated')
                checks.append('Fixture generation creates exactly 72 sessions and is idempotent')

                page.locator('[data-nav=studio]').click()
                page.locator('#task').select_option('issues')
                page.locator('#mode').select_option('human_steps')
                page.locator('#new-run button[type=submit]').click()
                for record, value in [('I1', 'ready'), ('I2', 'hold'), ('I3', 'hold'), ('I4', 'ready')]:
                    expect(page.locator('#decision-record')).to_be_visible()
                    page.locator('#decision-record').select_option(record)
                    page.locator('#decision-value').select_option(value)
                    page.locator('#advance').click()
                    if record != 'I4':
                        expect(page.locator('#session .record.done')).to_have_count(int(record[-1]))
                expect(page.locator('.session-result')).to_contain_text('Session complete')
                expect(page.locator('#session-count')).to_have_text('73 stored sessions')
                page.screenshot(path=str(artifacts / 'studio-desktop.png'), full_page=True)
                checks.append('Interactive choices persist through four API steps and complete the mock task')

                for mode in ('standing_instruction', 'ai_steps'):
                    page.locator('#mode').select_option(mode)
                    page.locator('#new-run button[type=submit]').click()
                    for index in range(4):
                        expect(page.locator('#advance')).to_be_visible()
                        page.locator('#advance').click()
                        expect(page.locator('#session .record.done')).to_have_count(index + 1)
                    expect(page.locator('.session-result')).to_contain_text('Session complete')
                checks.append('Standing and simulated-AI fixture workflows complete through the UI')

                page.locator('[data-nav=evidence]').click()
                page.locator('#inspect').click()
                expect(page.locator('#trace .event')).to_have_count(8)
                expect(page.locator('.event-source')).to_have_count(0)
                page.locator('#evidence-view').select_option('messages')
                expect(page.locator('#trace .event')).to_have_count(13)
                page.locator('#evidence-view').select_option('complete')
                expect(page.locator('.event-source').first).to_be_visible()
                page.screenshot(path=str(artifacts / 'evidence-desktop.png'), full_page=True)
                checks.append('Evidence selector changes exact records and shows origins only in complete view')

                fixtures = app.store.runs()
                def fixture(mode, worker='worker_a'):
                    return next(r['id'] for r in fixtures if r['task'] == 'files' and r['mode'] == mode
                                and r['worker'] == worker and r['repetition'] == 1 and r['scope'] == 'synthetic_fixture')
                page.locator('#evidence-run').select_option(fixture('human_steps'))
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#comparison-run').select_option(fixture('ai_steps'))
                for view in ('actions', 'messages'):
                    page.locator('#evidence-view').select_option(view)
                    expect(page.locator('#compare')).to_be_enabled()
                    page.locator('#compare').click()
                    expect(page.locator('#comparison-verdict')).to_contain_text('Identical evaluator inputs')
                    expect(page.locator('.comparison-panel')).to_have_count(2)
                    expect(page.locator('#comparison-panels .changed')).to_have_count(0)
                    expect(page.locator('.comparison-heading').first).to_contain_text('synthetic fixture')
                expect(page.locator('#notice')).to_have_text('', timeout=10000)
                page.locator('#comparison-result').scroll_into_view_if_needed()
                page.locator('#comparison-result').screenshot(path=str(artifacts / 'comparison-desktop.png'))
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
                page.locator('#comparison-result').scroll_into_view_if_needed()
                page.locator('#comparison-result').screenshot(path=str(artifacts / 'comparison-mobile.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                checks.append('Different fixture control arrangements have identical public inputs; comparison fits desktop and mobile')
                page.locator('#evidence-view').select_option('complete')
                expect(page.locator('#comparison-result')).to_be_hidden()
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#compare').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('The evaluator inputs differ')
                expect(page.locator('#comparison-panels .changed').first).to_be_visible()
                page.locator('#comparison-run').select_option(fixture('ai_steps', 'worker_b'))
                expect(page.locator('#comparison-result')).to_be_hidden()
                page.locator('#evidence-view').select_option('actions')
                expect(page.locator('#compare')).to_be_enabled()
                page.locator('#compare').click()
                expect(page.locator('#comparison-verdict')).to_contain_text('The evaluator inputs differ')
                checks.append('Complete-origin and worker-style differences are highlighted; changing a selector clears stale comparison')
                def delay_evidence(route):
                    page.wait_for_timeout(150)
                    route.continue_()
                page.route('**/view?view=*', delay_evidence)
                page.locator('#compare').click()
                expect(page.locator('#evidence-view')).to_be_disabled()
                expect(page.locator('#comparison-run')).to_be_disabled()
                expect(page.locator('#compare')).to_be_enabled()
                page.unroute('**/view?view=*', delay_evidence)
                expect(page.locator('#evidence-view')).to_be_enabled()
                page.locator('.comparison-events').first.focus()
                expect(page.locator('.comparison-events').first).to_be_focused()
                page.keyboard.press('End')
                assert page.locator('.comparison-events').first.evaluate('(el) => el.scrollTop > 0')
                checks.append('Pending comparisons lock selectors against stale results and evidence regions support keyboard scrolling')

                page.locator('[data-nav=analysis]').click()
                for method in ('evidence_checklist', 'surface_heuristic', 'always_abstain'):
                    for view in ('actions', 'messages', 'complete'):
                        page.locator('#method').select_option(method)
                        page.locator('#eval-view').select_option(view)
                        page.locator('#evaluate').click()
                        expect(page.locator('#notice')).to_contain_text('Evaluated 75 completed sessions')
                expect(page.locator('#metrics tr')).to_have_count(9)
                expect(page.locator('#metrics')).to_contain_text('—')
                expect(page.locator('#collisions tr')).to_have_count(3)
                expect(page.locator('#collisions')).to_contain_text('33.3%')
                expect(page.locator('#collisions')).to_contain_text('66.7%')
                with page.expect_download() as audit_download:
                    page.locator('#audit-download').click()
                audit_path = artifacts / 'collision-audit.json'
                audit_download.value.save_as(str(audit_path))
                audit = json.loads(audit_path.read_text(encoding='utf-8'))
                assert len(audit['summaries']) == 3
                assert all(row['n'] == 48 for row in audit['summaries'])
                checks.append('Collision audit renders exact finite-sample ceilings and downloads matching 48-session evidence groups')
                page.screenshot(path=str(artifacts / 'analysis-desktop.png'), full_page=True)
                checks.append('All nine local diagnostic method/view combinations render held-out results and undefined answered-error')

                example = {'predictions': [{'run_id': app.store.runs()[0]['id'], 'view': 'actions', 'label': 'unresolved', 'compatible': ['human_steps', 'standing_instruction', 'ai_steps'], 'evidence': [], 'reason': 'Browser test import'}]}
                with page.expect_response(lambda response: response.url == base + '/api/predictions/import', timeout=30000) as imported:
                    page.locator('#import').set_input_files({'name': 'predictions.json', 'mimeType': 'application/json', 'buffer': json.dumps(example).encode()})
                assert imported.value.status == 200
                assert imported.value.json()['imported'] == 1
                expect(page.locator('#notice')).to_contain_text('Imported 1 validated predictions', timeout=15000)
                expect(page.locator('#import')).to_be_enabled()
                checks.append('File input imports validated predictions through API and database')

                # Real UI -> HTTP -> store with an explicitly simulated provider failure/success.
                config = {'CS_MODEL_BASE_URL': 'http://127.0.0.1:12345/v1', 'CS_WORKER_A': 'browser-test-stub', 'CS_WORKER_B': 'browser-test-stub'}
                with patch.dict(os.environ, config), patch.object(app.models, 'enabled', True):
                    page.locator('#refresh').click(); expect(page.locator('#method')).to_be_enabled()
                    page.locator('#method').select_option('model_evidence')
                    page.locator('#eval-scope').select_option('synthetic_fixture')
                    page.locator('#eval-view').select_option('actions')
                    def failed_provider(*args, **kwargs):
                        time.sleep(2)
                        raise ModelRequestError('Model request failed: timed out after 45 seconds', 'timeout')
                    with patch.object(app.models, 'ask', side_effect=failed_provider):
                        page.locator('#evaluate').click()
                        expect(page.locator('#evaluation-state')).to_have_text('Waiting for the model')
                        expect(page.locator('#eval-scope')).to_be_disabled()
                        expect(page.locator('#evaluation-elapsed')).not_to_have_text('0s')
                        expect(page.locator('#evaluation-state')).to_have_text('Evaluation finished with failures')
                        expect(page.locator('#evaluation-attempts')).to_contain_text('Review the endpoint and time limit')
                    failed_id = app.store.attempts()[-1]['run_id']
                    answer = {'label':'unresolved', 'compatible':['human_steps','standing_instruction','ai_steps'], 'evidence':[], 'reason':'Simulated browser test response.'}
                    page.locator('#retry-failed').check()
                    with patch.object(app.models, 'ask', return_value=answer):
                        page.locator('#evaluate').click()
                        expect(page.locator('#evaluation-state')).to_have_text('Evaluation finished')
                        expect(page.locator('#evaluation-detail')).to_contain_text('1 saved / 1 attempted; 0 failed.')
                        expect(page.locator('#evaluation-attempts .attempt-card')).to_have_count(2)
                    assert app.store.attempts()[-1]['run_id'] == failed_id
                    expect(page.locator('#notice')).to_have_text('', timeout=10000)
                    page.locator('#evaluation-attempts').screenshot(path=str(artifacts / 'evaluation-attempts-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
                    page.locator('#evaluation-attempts').screenshot(path=str(artifacts / 'evaluation-attempts-mobile.png'))
                    page.set_viewport_size({'width':1440,'height':1000})
                    checks.append('Evaluator UI shows real elapsed time, retains a simulated timeout, and saves only after explicit retry; history fits mobile')

                page.locator('[data-nav=protocol]').click()
                with page.expect_download() as download:
                    page.locator('a[href="/api/export"]').click()
                export_path = artifacts / 'browser-export.json'
                download.value.save_as(str(export_path))
                exported = json.loads(export_path.read_text(encoding='utf-8'))
                assert len(exported['runs']) == 75
                assert all(not run['research_eligible'] for run in exported['runs'])
                assert 'collision_audit' in exported
                checks.append('Bundle download contains all persisted sessions and no falsely verified research data')

                page.set_viewport_size({'width': 390, 'height': 844})
                for section in ('overview', 'studio', 'evidence', 'analysis', 'protocol'):
                    page.goto(base + '/#' + section)
                    expect(page.locator('#stats .stat')).to_have_count(4)
                    expect(page.locator('#seed')).to_be_enabled()
                    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), section
                    if section == 'analysis':
                        page.screenshot(path=str(artifacts / 'analysis-mobile.png'), full_page=True)
                page.goto(base + '/#overview')
                page.screenshot(path=str(artifacts / 'overview-mobile.png'), full_page=True)
                checks.append('All five sections fit a 390px viewport without page-level horizontal overflow')
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            app.store.close()
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed' if not errors and not network_errors else 'failed', 'checks': checks, 'javascript_errors': errors, 'failed_requests': network_errors, 'live_model_calls': 0}
    (artifacts / 'browser-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert not errors, errors
    assert not network_errors, network_errors
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', help='New evidence directory; an existing directory is never overwritten')
    args = parser.parse_args()
    artifacts = Path(args.output or 'artifacts')
    artifacts.mkdir(parents=True, exist_ok=not bool(args.output))
    try:
        verify(artifacts)
    except Exception:
        (artifacts / 'browser-failure.json').write_text(json.dumps({
            'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
            'traceback': traceback.format_exc(), 'live_model_calls': 0,
        }, indent=2), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
