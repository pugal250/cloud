"""Start the development server:  python run.py"""
import os

from sms import create_app

app = create_app()

if __name__ == "__main__":
    # Debug mode is OFF by default. Set SMS_DEBUG=1 for auto-reload while developing.
    app.run(
        host=os.environ.get("SMS_HOST", "127.0.0.1"),
        port=int(os.environ.get("SMS_PORT", "5000")),
        debug=os.environ.get("SMS_DEBUG") == "1",
    )
