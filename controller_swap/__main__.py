import argparse
import json
from pathlib import Path

from .core import PROTOCOL, PROTOCOL_HASH, baseline, fixture_pack, metrics
from .audit import collision_audit
from .server import Application, make_server


def main():
    parser = argparse.ArgumentParser(description="Controller Swap local research workbench")
    parser.add_argument("command", choices=["serve", "verify-fixtures"], nargs="?", default="serve")
    parser.add_argument("--db", default="data/controller-swap.sqlite3")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--allow-live-models", action="store_true", help="Explicitly enable configured model endpoints; may incur provider charges")
    parser.add_argument("--max-live-calls", type=int, default=50)
    parser.add_argument("--out", default="artifacts/fixture-verification.json")
    args = parser.parse_args()
    if args.command == "verify-fixtures":
        runs = fixture_pack()
        predictions = [baseline(r, v, m) for r in runs for v in ("actions", "messages", "complete") for m in ("evidence_checklist", "surface_heuristic", "always_abstain")]
        result = {"scope": "synthetic_software_fixtures_only", "protocol": PROTOCOL, "protocol_hash": PROTOCOL_HASH,
                  "run_count": len(runs), "prediction_count": len(predictions), "analysis": metrics(runs, predictions),
                  "collision_audit": collision_audit(runs)}
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Verified {len(runs)} synthetic fixture sessions; {len(predictions)} diagnostic predictions. Saved {output.resolve()}")
        return
    if args.max_live_calls < 1:
        parser.error("--max-live-calls must be positive")
    app = Application(args.db, args.allow_live_models, args.max_live_calls)
    server = make_server(app, args.port)
    print(f"Controller Swap: http://127.0.0.1:{server.server_port}", flush=True)
    print("Pre-sprint preparation. Fixtures are not research data. Live model calls: " + ("enabled" if args.allow_live_models else "disabled"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.store.close()


if __name__ == "__main__":
    main()
