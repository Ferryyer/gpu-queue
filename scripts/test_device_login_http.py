#!/usr/bin/env python3
"""Foundation transport checks; --live only revokes a nonexistent synthetic request."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEST = r'''
import Foundation
let host = "https://inspire.markflow.work"
func rejected(_ action: () throws -> Void) {
  do { try action(); fatalError("Expected rejection") } catch {}
}
let request = try QueueDeviceHTTP.request("/auth/queue/token", ["request_id": "test"])
assert(request.url!.absoluteString == host + "/auth/queue/token")
assert(request.httpMethod == "POST")
assert(request.value(forHTTPHeaderField: "Origin") == host)
for path in ["https://other.example/", "//other.example/", "/auth/queue/token?redirect=x", "/auth/login"] {
  rejected { _ = try QueueDeviceHTTP.request(path, [:]) }
}
rejected { _ = try QueueDeviceHTTP.request("/auth/queue/token", ["x": String(repeating: "x", count: 2049)]) }
let ok = HTTPURLResponse(url: URL(string: host)!, statusCode: 200, httpVersion: nil, headerFields: nil)!
let redirect = HTTPURLResponse(url: URL(string: host)!, statusCode: 302, httpVersion: nil, headerFields: nil)!
let pending = try QueueDeviceHTTP.response(Data("{\"status\":\"pending\"}".utf8), ok)
assert(pending["status"] as? String == "pending")
rejected { _ = try QueueDeviceHTTP.response(Data("{}".utf8), redirect) }
rejected { _ = try QueueDeviceHTTP.response(Data("[]".utf8), ok) }
rejected { _ = try QueueDeviceHTTP.response(Data(repeating: 32, count: 3 * 1024 * 1024 + 1), ok) }
var blocked = false
let task = URLSession.shared.dataTask(with: URL(string: host)!)
QueueDeviceHTTP.shared.urlSession(URLSession.shared, task: task, willPerformHTTPRedirection: redirect,
  newRequest: URLRequest(url: URL(string: "https://other.example/")!)) { blocked = $0 == nil }
assert(blocked)
if CommandLine.arguments.contains("--live") {
  var done = false
  QueueDeviceHTTP.shared.post("/auth/queue/revoke", ["request_id": String(repeating: "A", count: 43),
      "code_verifier": String(repeating: "A", count: 43)]) { result in
    switch result {
    case .success(let value): assert(value["status"] as? String == "revoked")
    case .failure: fatalError("System HTTPS request did not complete")
    }
    done = true
  }
  let deadline = Date().addingTimeInterval(22)
  while !done && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
  assert(done)
}
print("Queue system HTTPS transport checks passed")
'''

with tempfile.TemporaryDirectory(prefix='queue-http-test-') as folder:
    root = Path(folder)
    (root / 'main.swift').write_text(TEST)
    executable = root / 'test'
    subprocess.run(['swiftc', str(ROOT / 'serverbox/macos/Runner/QueueDeviceHTTP.swift'),
                    str(root / 'main.swift'), '-o', str(executable)], check=True)
    subprocess.run([str(executable), *sys.argv[1:]], check=True, timeout=30)
