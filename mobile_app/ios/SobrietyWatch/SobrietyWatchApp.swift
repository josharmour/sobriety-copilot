import SwiftUI

@main
struct SobrietyWatchApp: App {
    @StateObject private var session = WatchSessionManager.shared

    var body: some Scene {
        WindowGroup {
            TabView {
                CounterWatchView()
                    .environmentObject(session)
                    .tabItem {
                        Label("Counter", systemImage: "timer")
                    }

                DailyReadingWatchView()
                    .environmentObject(session)
                    .tabItem {
                        Label("Daily", systemImage: "book.fill")
                    }

                BreatheWatchView()
                    .tabItem {
                        Label("Breathe", systemImage: "wind")
                    }
            }
        }
    }
}

// MARK: - Counter View

struct CounterWatchView: View {
    @EnvironmentObject var session: WatchSessionManager

    var body: some View {
        ScrollView {
            VStack(spacing: 6) {
                Text(session.discreet ? "DAY" : "SOBER")
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                    .tracking(1.0)

                ZStack {
                    Circle()
                        .stroke(Color.gray.opacity(0.3), lineWidth: 6)
                        .frame(width: 84, height: 84)

                    Circle()
                        .trim(from: 0, to: CGFloat(session.daysSober % 30) / 30.0)
                        .stroke(
                            Color(red: 0.22, green: 0.74, blue: 0.97),
                            style: StrokeStyle(lineWidth: 6, lineCap: .round)
                        )
                        .rotationEffect(.degrees(-90))
                        .frame(width: 84, height: 84)

                    VStack(spacing: 0) {
                        Text("\(session.daysSober)")
                            .font(.system(size: 28, weight: .bold, design: .rounded))
                            .foregroundColor(.white)
                        Text(session.discreet ? "days" : "days")
                            .font(.system(size: 9, weight: .medium))
                            .foregroundColor(.gray)
                    }
                }
                .padding(.vertical, 4)

                if session.streakCount > 0 {
                    HStack(spacing: 3) {
                        Image(systemName: "flame.fill")
                            .font(.system(size: 10))
                            .foregroundColor(.orange)
                        Text("\(session.streakCount) day streak")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundColor(.orange)
                    }
                }
            }
            .padding()
        }
    }
}

// MARK: - Daily Reading View

struct DailyReadingWatchView: View {
    @EnvironmentObject var session: WatchSessionManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                Text(session.dailyTitle)
                    .font(.system(size: 14, weight: .bold, design: .rounded))
                    .foregroundColor(.white)

                Divider()
                    .background(Color.gray.opacity(0.4))

                Text(session.dailyBody)
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(Color(red: 0.85, green: 0.88, blue: 0.92))
                    .lineSpacing(2)

                if !session.dailySource.isEmpty {
                    Text(session.dailySource)
                        .font(.system(size: 10, weight: .medium).italic())
                        .foregroundColor(Color(red: 0.58, green: 0.64, blue: 0.72))
                        .padding(.top, 4)
                }
            }
            .padding()
        }
    }
}

// MARK: - Breathe / Urge Surf View

struct BreatheWatchView: View {
    @State private var isBreathing = false
    @State private var breathText = "Inhale"
    @State private var scale: CGFloat = 0.5

    var body: some View {
        VStack(spacing: 8) {
            Text(breathText)
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))

            ZStack {
                Circle()
                    .fill(Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.2))
                    .frame(width: 70, height: 70)
                    .scaleEffect(scale)

                Circle()
                    .stroke(Color(red: 0.22, green: 0.74, blue: 0.97), lineWidth: 3)
                    .frame(width: 50, height: 50)
                    .scaleEffect(scale)
            }
            .animation(
                isBreathing ? Animation.easeInOut(duration: 4.0).repeatForever(autoreverses: true) : .default,
                value: scale
            )

            Button(action: toggleBreathe) {
                Text(isBreathing ? "Pause" : "Start 1 Min")
                    .font(.system(size: 11, weight: .semibold))
            }
            .buttonStyle(.bordered)
            .tint(Color(red: 0.22, green: 0.74, blue: 0.97))
        }
        .padding()
    }

    private func toggleBreathe() {
        isBreathing.toggle()
        if isBreathing {
            scale = 1.2
            breathText = "Breathe in... Breathe out"
            WKInterfaceDevice.current().play(.start)
        } else {
            scale = 0.5
            breathText = "Inhale"
            WKInterfaceDevice.current().play(.stop)
        }
    }
}
