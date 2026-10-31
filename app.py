"""CourtVision AI entry point:  python app.py"""
from app.config import Config
from app.main import create_app, socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, allow_unsafe_werkzeug=True)
