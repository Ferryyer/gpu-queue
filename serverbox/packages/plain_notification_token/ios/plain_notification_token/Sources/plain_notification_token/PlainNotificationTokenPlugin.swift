import Flutter
import UIKit
import UserNotifications

@objc(PlainNotificationTokenPlugin)
public class PlainNotificationTokenPlugin: NSObject, FlutterPlugin, UIApplicationDelegate {
  private let channel: FlutterMethodChannel
  private var lastToken: String?

  public static func register(with registrar: FlutterPluginRegistrar) {
    let channel = FlutterMethodChannel(
      name: "plain_notification_token",
      binaryMessenger: registrar.messenger()
    )
    let instance = PlainNotificationTokenPlugin(channel: channel)
    registrar.addApplicationDelegate(instance)
    registrar.addMethodCallDelegate(instance, channel: channel)
  }

  init(channel: FlutterMethodChannel) {
    self.channel = channel
    super.init()

    DispatchQueue.main.async {
      UIApplication.shared.registerForRemoteNotifications()
    }

    UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in
      let settingsDictionary: [String: Bool] = [
        "sound": settings.soundSetting == .enabled,
        "badge": settings.badgeSetting == .enabled,
        "alert": settings.alertSetting == .enabled,
      ]
      DispatchQueue.main.async {
        self?.channel.invokeMethod("onIosSettingsRegistered", arguments: settingsDictionary)
      }
    }
  }

  public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "getToken":
      result(lastToken)
    case "requestPermission":
      requestPermission(with: call.arguments as? [String: NSNumber] ?? [:])
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func requestPermission(with settings: [String: NSNumber]) {
    var options: UNAuthorizationOptions = []
    if settings["sound"]?.boolValue == true {
      options.insert(.sound)
    }
    if settings["badge"]?.boolValue == true {
      options.insert(.badge)
    }
    if settings["alert"]?.boolValue == true {
      options.insert(.alert)
    }

    UNUserNotificationCenter.current().requestAuthorization(options: options) {
      [weak self] granted, error in
      if let error {
        NSLog("Error during requesting notification permission: %@", error.localizedDescription)
      }

      DispatchQueue.main.async {
        guard let self else {
          return
        }

        if granted {
          UIApplication.shared.registerForRemoteNotifications()
          let settingsDictionary: [String: Bool] = [
            "alert": settings["alert"]?.boolValue == true,
            "badge": settings["badge"]?.boolValue == true,
            "sound": settings["sound"]?.boolValue == true,
          ]
          self.channel.invokeMethod("onIosSettingsRegistered", arguments: settingsDictionary)
        } else {
          self.channel.invokeMethod(
            "onIosSettingsRegistered",
            arguments: ["badge": false, "alert": false, "sound": false]
          )
        }
      }
    }
  }

  public func application(
    _ application: UIApplication,
    didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
  ) {
    lastToken = deviceToken.map { String(format: "%02.2hhx", $0) }.joined()
    channel.invokeMethod("onToken", arguments: lastToken)
  }
}
