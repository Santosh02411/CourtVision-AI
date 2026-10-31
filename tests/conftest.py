import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def app():
    from app.api.routes import Services
    from app.main import create_app
    from tests.fakes import FakeNBAData, TODAY
    from unittest import mock
    import datetime as _dt

    svc = Services(data=FakeNBAData())
    patcher = mock.patch("app.services.util.today_et", return_value=TODAY)
    patcher.start()
    import app.api.routes as routes
    import app.main as main
    routes.today_et = lambda: TODAY
    main.today_et = lambda: TODAY
    application = create_app(services=svc)
    application.config["TESTING"] = True
    yield application
    patcher.stop()


@pytest.fixture()
def client(app):
    return app.test_client()
