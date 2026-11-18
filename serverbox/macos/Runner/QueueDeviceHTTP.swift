import Foundation

// Use the Mac's system networking and proxy handling without sharing browser cookies.
final class QueueDeviceHTTP: NSObject, URLSessionTaskDelegate {
  static let shared = QueueDeviceHTTP()
  enum Failure: Error { case request, response }
  private lazy var session: URLSession = {
    let config = URLSessionConfiguration.ephemeral
    config.timeoutIntervalForRequest = 18
    config.timeoutIntervalForResource = 18
    config.httpCookieStorage = nil
    config.urlCredentialStorage = nil
    config.httpShouldSetCookies = false
    return URLSession(configuration: config, delegate: self, delegateQueue: nil)
  }()

  static func request(_ path: String, _ body: [String: Any]) throws -> URLRequest {
    guard ["/auth/queue/device", "/auth/queue/token", "/auth/queue/revoke"].contains(path),
          JSONSerialization.isValidJSONObject(body) else { throw Failure.request }
    let data = try JSONSerialization.data(withJSONObject: body)
    guard data.count <= 2048 else { throw Failure.request }
    var request = URLRequest(url: URL(string: "https://inspire.markflow.work" + path)!)
    request.httpMethod = "POST"
    request.setValue("https://inspire.markflow.work", forHTTPHeaderField: "Origin")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = data
    return request
  }

  static func response(_ data: Data?, _ response: URLResponse?) throws -> [String: Any] {
    guard (response as? HTTPURLResponse)?.statusCode == 200, let data = data,
          data.count <= 3 * 1024 * 1024,
          let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
    else { throw Failure.response }
    return json
  }

  func post(_ path: String, _ body: [String: Any], completion: @escaping (Result<[String: Any], Error>) -> Void) {
    do {
      let request = try Self.request(path, body)
      session.dataTask(with: request) { data, response, error in
        let result = Result { () throws -> [String: Any] in
          guard error == nil else { throw Failure.response }
          return try Self.response(data, response)
        }
        DispatchQueue.main.async { completion(result) }
      }.resume()
    } catch { completion(.failure(Failure.request)) }
  }

  func urlSession(_ session: URLSession, task: URLSessionTask,
                  willPerformHTTPRedirection response: HTTPURLResponse,
                  newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
    completionHandler(nil)
  }
}
