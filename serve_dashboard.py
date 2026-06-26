import os
import sys
import json
import sqlite3
import webbrowser
from http.server import SimpleHTTPRequestHandler, HTTPServer
import socket

PORT = 8080

class DashboardHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence verbose request logs to keep terminal clear
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(302)
            self.send_header("Location", "/test_dashboard.html")
            self.end_headers()
            return
            
        elif self.path == "/api/results":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            results_path = os.path.join(os.path.dirname(__file__), "test_results.json")
            data = None
            if os.path.exists(results_path):
                # Try reading and parsing multiple times to avoid half-written race condition errors
                for _ in range(3):
                    try:
                        with open(results_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        data = json.loads(content)
                        break
                    except (json.JSONDecodeError, OSError):
                        import time
                        time.sleep(0.05)
            
            if data is not None:
                self.wfile.write(json.dumps(data).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({
                    "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "duration": 0, "status": "running"},
                    "tests": []
                }).encode("utf-8"))
                
        elif self.path == "/api/db-stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            db_path = os.path.join(os.path.dirname(__file__), "backend", "test_bizassist.db")
            if not os.path.exists(db_path):
                db_path = os.path.join(os.path.dirname(__file__), "backend", "bizassist.db")
            stats = {"tables": {}, "sync_queue_pending": 0, "sync_logs": [], "conflict_logs": []}
            
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    
                    # 1. Get counts for synced tables
                    tables_to_count = [
                        "customers", "vendors", "products", "invoices", "invoice_line_items",
                        "inventory", "payments", "stock_ledger", "product_barcodes",
                        "business_settings", "invoice_payments", "shared_ledgers",
                        "expenses", "godowns", "stock_transfers", "purchase_invoices",
                        "purchase_orders"
                    ]
                    for table in tables_to_count:
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table}")
                            stats["tables"][table] = cursor.fetchone()[0]
                        except Exception:
                            stats["tables"][table] = 0
                            
                    # 2. Get sync queue pending count
                    try:
                        cursor.execute("SELECT COUNT(*) FROM sync_queue WHERE synced_at IS NULL")
                        stats["sync_queue_pending"] = cursor.fetchone()[0]
                    except Exception:
                        pass
                        
                    # 3. Get recent sync logs
                    try:
                        cursor.execute("SELECT id, status, synced_at, error FROM sync_logs ORDER BY id DESC LIMIT 10")
                        stats["sync_logs"] = [
                            {"id": r[0], "status": r[1], "synced_at": r[2], "error": r[3]}
                            for r in cursor.fetchall()
                        ]
                    except Exception:
                        pass
                        
                    # 4. Get recent conflicts
                    try:
                        cursor.execute("SELECT id, entity, entity_id, resolution, resolved_at FROM conflict_logs ORDER BY id DESC LIMIT 10")
                        stats["conflict_logs"] = [
                            {"id": r[0], "entity": r[1], "entity_id": r[2], "resolution": r[3], "resolved_at": r[4]}
                            for r in cursor.fetchall()
                        ]
                    except Exception:
                        pass
                        
                    conn.close()
                except Exception as e:
                    stats["error"] = str(e)
            else:
                stats["error"] = f"DB not found at {db_path}"
                
            self.wfile.write(json.dumps(stats).encode("utf-8"))
        else:
            super().do_GET()

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def start_server():
    global PORT
    while is_port_in_use(PORT):
        PORT += 1
        
    server = HTTPServer(('localhost', PORT), DashboardHandler)
    url = f"http://localhost:{PORT}/test_dashboard.html"
    
    # Write URL to a temporary handshake file so the background PowerShell process can find it
    try:
        url_file = os.path.join(os.path.dirname(__file__), "dashboard_url.txt")
        with open(url_file, "w", encoding="utf-8") as f:
            f.write(url)
    except Exception:
        pass

    print(f"\n\033[92m=== BIZASSIST TEST REPORT READY ===\033[0m")
    print(f"\033[94mURL: {url}\033[0m")
    print(f"\033[90m(Press Ctrl+C to stop the dashboard server)\033[0m\n")
    
    # Automatically open the browser
    webbrowser.open(url)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        sys.exit(0)

if __name__ == "__main__":
    start_server()
