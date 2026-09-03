import Foundation
import WatchConnectivity
import Combine

class WatchSessionManager: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchSessionManager()

    @Published var daysSober: Int = 0
    @Published var discreet: Bool = false
    @Published var streakCount: Int = 0
    @Published var dailyTitle: String = "Daily Reflection"
    @Published var dailyBody: String = "One day at a time."
    @Published var dailySource: String = "Recovery Literature"

    private let userDefaults = UserDefaults.standard

    override init() {
        super.init()
        loadLocalCache()
        if WCSession.isSupported() {
            let session = WCSession.default
            session.delegate = self
            session.activate()
        }
    }

    private func loadLocalCache() {
        let dateIso = userDefaults.string(forKey: "sobriety_date")
        discreet = userDefaults.bool(forKey: "sobriety_discreet")
        streakCount = userDefaults.integer(forKey: "sobriety_streak")
        dailyTitle = userDefaults.string(forKey: "daily_title") ?? "Daily Reflection"
        dailyBody = userDefaults.string(forKey: "daily_body") ?? "One day at a time."
        dailySource = userDefaults.string(forKey: "daily_source") ?? "Recovery Literature"
        daysSober = calculateDaysSince(dateIso: dateIso)
    }

    func calculateDaysSince(dateIso: String?) -> Int {
        guard let dateIso = dateIso, !dateIso.isEmpty else { return 0 }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone.current
        guard let startDate = formatter.date(from: dateIso) else { return 0 }

        let calendar = Calendar.current
        let start = calendar.startOfDay(for: startDate)
        let today = calendar.startOfDay(for: Date())
        let components = calendar.dateComponents([.day], from: start, to: today)
        return max(0, components.day ?? 0)
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String : Any]) {
        DispatchQueue.main.async {
            if let dateIso = applicationContext["sobriety_date"] as? String {
                self.userDefaults.set(dateIso, forKey: "sobriety_date")
                self.daysSober = self.calculateDaysSince(dateIso: dateIso)
            }
            if let discreet = applicationContext["sobriety_discreet"] as? Bool {
                self.userDefaults.set(discreet, forKey: "sobriety_discreet")
                self.discreet = discreet
            }
            if let streak = applicationContext["sobriety_streak"] as? Int {
                self.userDefaults.set(streak, forKey: "sobriety_streak")
                self.streakCount = streak
            }
            if let title = applicationContext["daily_title"] as? String {
                self.userDefaults.set(title, forKey: "daily_title")
                self.dailyTitle = title
            }
            if let body = applicationContext["daily_body"] as? String {
                self.userDefaults.set(body, forKey: "daily_body")
                self.dailyBody = body
            }
            if let source = applicationContext["daily_source"] as? String {
                self.userDefaults.set(source, forKey: "daily_source")
                self.dailySource = source
            }
        }
    }
}
