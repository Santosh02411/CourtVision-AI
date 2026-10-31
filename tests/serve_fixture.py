"""Run the UI against deterministic TEST fixtures (never real data):  python -m tests.serve_fixture"""
import os
os.environ.setdefault("COURTVISION_DISK_CACHE", "false")
import app.api.routes as routes
import app.main as main
from tests.fakes import FakeNBAData, TODAY

routes.today_et = lambda: TODAY
main.today_et = lambda: TODAY
application = main.create_app(services=routes.Services(data=FakeNBAData()))
if __name__ == "__main__":
    main.socketio.run(application, host="127.0.0.1", port=5057, allow_unsafe_werkzeug=True)
