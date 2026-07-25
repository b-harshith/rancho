import threading
import time
import webbrowser
from datetime import datetime
from catchmentiq.logger.server import app, broadcast

class NullLogger:
    """A no-op logger stub that mirrors LiveLogger API but only prints to console."""
    def open(self):
        pass
    def log(self, message: str, level: str = "info"):
        print(f"[{level.upper()}] {message}")
    def layer_start(self, layer_num: int, layer_name: str):
        print(f"\n>>> LAYER {layer_num}: STARTING - {layer_name}")
    def layer_end(self, layer_num: int, summary: str):
        print(f"<<< LAYER {layer_num}: ENDED - {summary}")
    def add_points(self, layer_name: str, geojson: dict, style: dict = None):
        pass
    def add_polygons(self, layer_name: str, geojson: dict, style: dict = None):
        pass
    def add_choropleth(self, layer_name: str, geojson: dict, value_field: str, color_scale: str = "YlOrRd"):
        pass
    def add_heatmap(self, layer_name: str, points: list):
        pass
    def clear_layer(self, layer_name: str):
        pass
    def snapshot(self, filename: str):
        pass
    def wait(self):
        pass

class LiveLogger:
    def __init__(self, port: int = 5050, city_center: list = [12.9716, 77.5946], zoom: int = 11):
        self.port = port
        self.city_center = city_center
        self.zoom = zoom
        self.thread = None
        self.total_layers = 7

    def _run_server(self):
        app.run(host="127.0.0.1", port=self.port, debug=False, use_reloader=False)

    def open(self):
        """Start server and open browser."""
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        time.sleep(1.0) # wait for startup
        url = f"http://127.0.0.1:{self.port}"
        print(f"Live Dashboard running at {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"Could not open browser automatically: {e}")

    def _send_payload(self, msg_type: str, payload: dict):
        timestamp = datetime.now().strftime("%H:%M:%S")
        broadcast({
            "type": msg_type,
            "timestamp": timestamp,
            "payload": payload
        })

    def log(self, message: str, level: str = "info"):
        """Send a text log message. levels: debug, info, success, warning, error"""
        print(f"[{level.upper()}] {message}")
        self._send_payload("log", {"message": message, "level": level})

    def layer_start(self, layer_num: int, layer_name: str):
        """Mark a layer as started."""
        print(f"\n>>> LAYER {layer_num}: {layer_name}")
        self._send_payload("layer_start", {
            "layer_num": layer_num,
            "layer_name": layer_name,
            "total_layers": self.total_layers
        })

    def layer_end(self, layer_num: int, summary: str):
        """Mark a layer as completed."""
        print(f"<<< LAYER {layer_num}: {summary}")
        self._send_payload("layer_end", {
            "layer_num": layer_num,
            "summary": summary
        })

    def add_points(self, layer_name: str, geojson: dict, style: dict = None):
        """Add points layer to dashboard."""
        self._send_payload("geo_add", {
            "layer_name": layer_name,
            "render_type": "points",
            "geojson": geojson,
            "style": style or {}
        })

    def add_polygons(self, layer_name: str, geojson: dict, style: dict = None):
        """Add polygon boundary layers."""
        self._send_payload("geo_add", {
            "layer_name": layer_name,
            "render_type": "polygons",
            "geojson": geojson,
            "style": style or {}
        })

    def add_choropleth(self, layer_name: str, geojson: dict, value_field: str, color_scale: str = "YlOrRd"):
        """Add dynamic graduated-color polygons."""
        self._send_payload("geo_add", {
            "layer_name": layer_name,
            "render_type": "choropleth",
            "geojson": geojson,
            "value_field": value_field,
            "color_scale": color_scale
        })

    def add_heatmap(self, layer_name: str, points: list):
        """Add heatmap layers."""
        self._send_payload("geo_add", {
            "layer_name": layer_name,
            "render_type": "heatmap",
            "points": points
        })

    def clear_layer(self, layer_name: str):
        """Clear specific layer from map."""
        self._send_payload("geo_clear", {"layer_name": layer_name})

    def snapshot(self, filename: str):
        """Optional static map capture logic."""
        pass

    def wait(self):
        """Keep server running at end of pipeline."""
        print("\nPipeline complete. Keeping Live Dashboard server alive. Press Ctrl+C to terminate.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down server.")
